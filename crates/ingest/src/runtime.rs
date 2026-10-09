//! Bounded live orchestration. Only this owner can publish or invalidate advice.
//!
//! Capture/discovery run on the caller; blocking inference (and optional decision
//! computation) runs on one worker. There is one active ticket and one replaceable
//! latest stable frame. A result is never trusted without a fresh capture in the
//! same tick, matching identity/epoch/generation, and an unexpired capture lease.
//! An over-age completion is discarded whole: it never classifies the screen.

use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError, TrySendError};
use std::time::Instant;

use serde::Serialize;

use crate::capture::{CaptureError, CaptureSource, Frame, WindowInfo};
use crate::change_detect::{ChangeDetectorConfig, FrameTracker, StabilityConfig};
use crate::discovery::{CaptureManager, DiscoveryConfig, DiscoveryState, TableIdentity};
use crate::parser::{Card, GamePhase};
use crate::screen::{
    inspect_frame, MetadataEvidence, ScreenKind, ScreenObservation, TableGate, VisualEvidence,
};

/// Bounded transient worker retries before submission pauses until the next refresh.
const MAX_WORKER_FAILURES: u32 = 3;
/// A disconnected worker is terminal: it is never restarted in-process.
const TERMINAL_WORKER_CODE: &str = "inference-worker-stopped";

pub trait Clock {
    fn now_ms(&self) -> u64;
}

pub struct MonotonicClock(Instant);
impl Default for MonotonicClock {
    fn default() -> Self {
        Self(Instant::now())
    }
}
impl Clock for MonotonicClock {
    fn now_ms(&self) -> u64 {
        self.0.elapsed().as_millis().min(u128::from(u64::MAX)) as u64
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RuntimeConfig {
    pub poll_ms: u64,
    pub discovery_ms: u64,
    pub retry_ms: u64,
    pub force_refresh_ms: u64,
    pub max_frame_age_ms: u64,
    pub change: ChangeDetectorConfig,
    pub stability: StabilityConfig,
}
impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            poll_ms: 100,
            discovery_ms: 1_000,
            retry_ms: 2_000,
            force_refresh_ms: 5_000,
            max_frame_age_ms: 8_000,
            change: ChangeDetectorConfig::default(),
            stability: StabilityConfig::default(),
        }
    }
}
impl RuntimeConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        self.change.validate()?;
        self.stability.validate()?;
        if !(50..=1_000).contains(&self.poll_ms)
            || !(500..=5_000).contains(&self.discovery_ms)
            || !(500..=30_000).contains(&self.retry_ms)
            || !(1_000..=10_000).contains(&self.force_refresh_ms)
            || !(500..=10_000).contains(&self.max_frame_age_ms)
        {
            return Err("invalid timing: poll 50..1000, discovery 500..5000, retry 500..30000, refresh 1000..10000, frame age 500..10000 ms");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Ticket {
    pub identity: TableIdentity,
    pub generation: u64,
    pub epoch: u64,
    pub captured_at_ms: u64,
}

/// Shared admission predicate for live capture and local sequence evaluation.
pub struct Freshness<'a> {
    pub identity: Option<&'a TableIdentity>,
    pub generation: u64,
    pub epoch: u64,
    pub now_ms: u64,
    pub fresh_capture: bool,
    pub max_frame_age_ms: u64,
}

pub fn observation_is_current(ticket: &Ticket, current: Freshness<'_>) -> bool {
    current.fresh_capture
        && current.identity == Some(&ticket.identity)
        && ticket.generation == current.generation
        && ticket.epoch == current.epoch
        && current.now_ms >= ticket.captured_at_ms
        && current.now_ms - ticket.captured_at_ms < current.max_frame_age_ms
}

pub struct InferenceJob {
    pub ticket: Ticket,
    pub frame: Frame,
}
pub struct Analysis<T> {
    pub observation: ScreenObservation,
    pub recommendation: Option<T>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InferenceFailure {
    pub code: &'static str,
}
pub struct Completion<T> {
    pub ticket: Ticket,
    pub result: Result<Analysis<T>, InferenceFailure>,
}

/// Injection boundary: tests can deliver a slow/obsolete completion explicitly.
pub trait InferencePort<T> {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure>;
    fn try_complete(&mut self) -> Result<Option<Completion<T>>, InferenceFailure>;
}

pub struct ThreadWorker<T> {
    jobs: SyncSender<InferenceJob>,
    results: Receiver<Completion<T>>,
}
impl<T: Send + 'static> ThreadWorker<T> {
    pub fn new(
        mut analyze: impl FnMut(&Frame) -> Result<Analysis<T>, InferenceFailure> + Send + 'static,
    ) -> Self {
        let (jobs, input) = mpsc::sync_channel::<InferenceJob>(1);
        let (output, results) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            while let Ok(job) = input.recv() {
                let result = analyze(&job.frame);
                if output
                    .send(Completion {
                        ticket: job.ticket,
                        result,
                    })
                    .is_err()
                {
                    break;
                }
            }
        });
        Self { jobs, results }
    }
}
impl<T> InferencePort<T> for ThreadWorker<T> {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
        match self.jobs.try_send(job) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err(InferenceFailure {
                code: "inference-worker-busy",
            }),
            Err(TrySendError::Disconnected(_)) => Err(InferenceFailure {
                code: TERMINAL_WORKER_CODE,
            }),
        }
    }
    fn try_complete(&mut self) -> Result<Option<Completion<T>>, InferenceFailure> {
        match self.results.try_recv() {
            Ok(result) => Ok(Some(result)),
            Err(TryRecvError::Empty) => Ok(None),
            Err(TryRecvError::Disconnected) => Err(InferenceFailure {
                code: TERMINAL_WORKER_CODE,
            }),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum LiveEvent<T> {
    Status {
        state: &'static str,
        reason: &'static str,
        identity: Option<TableIdentity>,
    },
    Clear {
        reason: &'static str,
        generation: u64,
    },
    Recommendation {
        ticket: Ticket,
        value: T,
        valid_for_ms: u64,
    },
    Discarded {
        generation: u64,
        reason: &'static str,
    },
    /// Visible table cards. This is not advice and carries no action.
    Table {
        game_phase: GamePhase,
        hero_cards: Vec<Card>,
        board: Vec<Card>,
        action_required: bool,
    },
}

pub struct LiveRuntime<S: CaptureSource, W, T> {
    capture: CaptureManager<S>,
    worker: W,
    config: RuntimeConfig,
    discovery: DiscoveryConfig,
    selected: Option<WindowInfo>,
    tracker: FrameTracker,
    gate: TableGate,
    epoch: u64,
    generation: u64,
    active: Option<Ticket>,
    queued: Option<InferenceJob>,
    recommendation_deadline: Option<u64>,
    next_discovery: u64,
    next_analysis: u64,
    last_analysis: Option<u64>,
    needs_analysis: bool,
    worker_dead: bool,
    worker_failures: u32,
    last_status: Option<(&'static str, &'static str, Option<TableIdentity>)>,
    last_table: Option<(GamePhase, Vec<Card>, Vec<Card>, bool)>,
    marker: std::marker::PhantomData<T>,
}

impl<S: CaptureSource, W: InferencePort<T>, T> LiveRuntime<S, W, T> {
    pub fn new(
        source: S,
        worker: W,
        discovery: DiscoveryConfig,
        config: RuntimeConfig,
    ) -> Result<Self, &'static str> {
        config.validate()?;
        Ok(Self {
            capture: CaptureManager::new(source, discovery.clone()),
            worker,
            tracker: FrameTracker::new(config.change.clone(), config.stability.clone()),
            discovery,
            config,
            selected: None,
            gate: TableGate::new(),
            epoch: 0,
            generation: 0,
            active: None,
            queued: None,
            recommendation_deadline: None,
            next_discovery: 0,
            next_analysis: 0,
            last_analysis: None,
            needs_analysis: true,
            worker_dead: false,
            worker_failures: 0,
            last_status: None,
            last_table: None,
            marker: std::marker::PhantomData,
        })
    }

    /// A caller must tick at the configured poll interval, not on inference completion.
    pub fn tick(&mut self, clock: &impl Clock) -> Vec<LiveEvent<T>> {
        let mut events = Vec::new();
        let mut now = clock.now_ms();
        if self
            .recommendation_deadline
            .is_some_and(|deadline| now >= deadline)
        {
            self.clear("recommendation-expired", &mut events);
        }
        if now >= self.next_discovery {
            match self.capture.refresh() {
                Ok(selection) => {
                    self.worker_failures = 0;
                    let selection_changed = self.selected != selection.window;
                    if selection_changed {
                        self.invalidate("window-changed", true, &mut events);
                        self.last_table = None;
                        self.selected = selection.window;
                        self.tracker.reset();
                        self.last_analysis = None;
                        self.next_analysis = 0;
                    }
                    if selection_changed || self.selected.is_none() || self.last_status.is_none() {
                        self.status(
                            discovery_code(selection.state),
                            selection.reason,
                            &mut events,
                        );
                    }
                }
                Err(error) => self.capture_failure(&error, &mut events),
            }
            now = clock.now_ms();
            self.next_discovery = now.saturating_add(self.config.discovery_ms);
        }

        // Always observe current pixels BEFORE looking at any completed inference.
        let mut current = None;
        if self.selected.is_some() {
            match self.capture.capture() {
                Ok(frame) => {
                    now = clock.now_ms();
                    let progress = self.tracker.observe(&frame, now);
                    if progress.changed {
                        self.invalidate("frame-changed", false, &mut events);
                        self.next_analysis = now;
                        self.last_analysis = None;
                        self.status("candidate_table", "stabilizing-changed-frame", &mut events);
                    }
                    if inspect_frame(&frame) == VisualEvidence::Unreadable {
                        self.invalidate("unreadable-frame", false, &mut events);
                        self.status("unknown", "unreadable-frame", &mut events);
                    } else {
                        // Periodic invalidation bounds the lifetime of changes below thresholds.
                        if self.last_analysis.is_some_and(|last| {
                            now.saturating_sub(last) >= self.config.force_refresh_ms
                        }) {
                            self.invalidate("forced-refresh", false, &mut events);
                            self.last_analysis = None;
                            self.next_analysis = now;
                        }
                        if progress.stable {
                            current = Some(frame);
                        }
                    }
                }
                Err(error) => {
                    self.capture_failure(&error, &mut events);
                    now = clock.now_ms();
                    self.next_discovery = now.saturating_add(self.config.discovery_ms);
                }
            }
        }

        match self.worker.try_complete() {
            Ok(Some(completion)) => {
                self.worker_failures = 0;
                let expected = self.active.take();
                let identity = self.selected.as_ref().map(WindowInfo::identity);
                let fresh = expected.as_ref() == Some(&completion.ticket)
                    && observation_is_current(
                        &completion.ticket,
                        Freshness {
                            identity: identity.as_ref(),
                            generation: self.generation,
                            epoch: self.epoch,
                            now_ms: now,
                            fresh_capture: current.is_some(),
                            max_frame_age_ms: self.config.max_frame_age_ms,
                        },
                    );
                let same_window = expected.as_ref() == Some(&completion.ticket)
                    && identity.as_ref() == Some(&completion.ticket.identity);
                if fresh {
                    self.complete(completion, now, true, &mut events);
                } else if same_window {
                    // A young result from a moved frame is stale advice, but its
                    // board reading can still be published; a newer capture is
                    // already queued. An over-age result is also too old to
                    // classify: it must not label the screen a lobby or unreadable,
                    // enter consensus, or delay the next read by retry_ms.
                    let expired = now.saturating_sub(completion.ticket.captured_at_ms)
                        >= self.config.max_frame_age_ms;
                    events.push(LiveEvent::Discarded {
                        generation: completion.ticket.generation,
                        reason: if expired {
                            "observation-expired"
                        } else {
                            "obsolete-observation"
                        },
                    });
                    self.needs_analysis = true;
                    if !expired {
                        self.complete(completion, now, false, &mut events);
                    }
                } else {
                    events.push(LiveEvent::Discarded {
                        generation: completion.ticket.generation,
                        reason: "obsolete-observation",
                    });
                    // Even unchanged pixels cannot make an over-age request current again.
                    self.needs_analysis = true;
                    self.gate.break_consensus();
                }
            }
            Ok(None) => {
                self.worker_failures = 0;
            }
            Err(error) => self.record_worker_failure(error, &mut events),
        }

        if let Some(frame) = current {
            let active_current = self
                .active
                .as_ref()
                .is_some_and(|ticket| ticket.epoch == self.epoch);
            if self.needs_analysis
                && !active_current
                && now >= self.next_analysis
                && !self.worker_dead
                && self.worker_failures < MAX_WORKER_FAILURES
            {
                if let Some(queued) = self.queued.as_mut() {
                    queued.frame = frame;
                    queued.ticket.captured_at_ms = now;
                } else if let Some(window) = self.selected.as_ref() {
                    self.generation += 1;
                    self.queued = Some(InferenceJob {
                        ticket: Ticket {
                            identity: window.identity(),
                            generation: self.generation,
                            epoch: self.epoch,
                            captured_at_ms: now,
                        },
                        frame,
                    });
                }
            }
        }
        if self.active.is_none() && !self.worker_dead && self.worker_failures < MAX_WORKER_FAILURES
        {
            if let Some(job) = self.queued.take() {
                let ticket = job.ticket.clone();
                match self.worker.start(job) {
                    Ok(()) => {
                        self.worker_failures = 0;
                        self.last_analysis = Some(ticket.captured_at_ms);
                        self.active = Some(ticket);
                        self.status("analyzing", "stable-frame-submitted", &mut events);
                    }
                    Err(error) => self.record_worker_failure(error, &mut events),
                }
            }
        }
        events
    }

    /// Only a disconnected worker latches `worker_dead`; transient backpressure is
    /// counted and retried, and is bounded by `MAX_WORKER_FAILURES` between refreshes.
    fn record_worker_failure(&mut self, error: InferenceFailure, events: &mut Vec<LiveEvent<T>>) {
        self.invalidate(error.code, false, events);
        if error.code == TERMINAL_WORKER_CODE {
            self.worker_dead = true;
        } else {
            self.worker_failures = self.worker_failures.saturating_add(1);
        }
        self.status("recovering", error.code, events);
    }

    fn complete(
        &mut self,
        completion: Completion<T>,
        now: u64,
        allow_advice: bool,
        events: &mut Vec<LiveEvent<T>>,
    ) {
        match completion.result {
            Err(error) => {
                self.clear(error.code, events);
                self.gate.break_consensus();
                self.needs_analysis = true;
                self.next_analysis = now.saturating_add(self.config.retry_ms);
                self.status("recovering", error.code, events);
            }
            Ok(analysis) => {
                let metadata = self.metadata();
                let outcome = self.gate.observe(
                    &completion.ticket.identity,
                    &analysis.observation,
                    metadata,
                    VisualEvidence::Plausible,
                );
                if let Some(state) = outcome.visible_cards.as_ref() {
                    let reading = (
                        state.game_phase,
                        state.hero_cards.clone(),
                        state.board.clone(),
                        state.action_required,
                    );
                    if self.last_table.as_ref() != Some(&reading) {
                        self.last_table = Some(reading.clone());
                        events.push(LiveEvent::Table {
                            game_phase: reading.0,
                            hero_cards: reading.1,
                            board: reading.2,
                            action_required: reading.3,
                        });
                    }
                }
                match outcome.accepted_state {
                    Some(state) if allow_advice => {
                        self.needs_analysis = false;
                        self.status("capturing_table", outcome.reason, events);
                        if state.action_required {
                            if let Some(value) = analysis.recommendation {
                                let deadline = completion
                                    .ticket
                                    .captured_at_ms
                                    .saturating_add(self.config.max_frame_age_ms);
                                self.recommendation_deadline = Some(deadline);
                                events.push(LiveEvent::Recommendation {
                                    ticket: completion.ticket,
                                    value,
                                    valid_for_ms: deadline.saturating_sub(now),
                                });
                            } else {
                                self.clear("decision-suppressed", events);
                                self.status("capturing_table", "decision-suppressed", events);
                            }
                        } else {
                            self.clear("action-not-required", events);
                        }
                    }
                    Some(_) => {
                        self.needs_analysis = true;
                        self.status("capturing_table", "advice-withheld-frame-changed", events);
                    }
                    None => {
                        self.clear("screen-not-accepted", events);
                        let state = match outcome.kind {
                            ScreenKind::Lobby => "lobby_detected",
                            ScreenKind::PokerTable => "candidate_table",
                            ScreenKind::OtherCoinPokerWindow => "other_coin_poker_window",
                            ScreenKind::Unknown => "unknown",
                        };
                        self.status(state, outcome.reason, events);
                        self.needs_analysis = true;
                        self.next_analysis = now.saturating_add(
                            if outcome.reason == "waiting for a second matching observation" {
                                self.config.poll_ms
                            } else {
                                self.config.retry_ms
                            },
                        );
                    }
                }
            }
        }
    }

    fn metadata(&self) -> MetadataEvidence {
        let Some(window) = self.selected.as_ref() else {
            return MetadataEvidence::Candidate;
        };
        if self.discovery.is_calibrated_lobby(window) {
            MetadataEvidence::LobbyTitle
        } else if self.discovery.is_calibrated_table(window) {
            MetadataEvidence::TableTitle
        } else {
            MetadataEvidence::Candidate
        }
    }

    fn capture_failure(&mut self, error: &CaptureError, events: &mut Vec<LiveEvent<T>>) {
        let (state, reason) = match error {
            CaptureError::PermissionDenied => ("permission_required", "capture-access-required"),
            CaptureError::UnsupportedPlatform => ("unsupported_platform", "windows-only"),
            CaptureError::UnsupportedWindowsVersion => {
                ("unsupported_platform", "windows-1903-required")
            }
            CaptureError::StaleWindow { .. } => ("recovering", "stale-window-filter"),
            _ => ("recovering", "capture-unavailable"),
        };
        self.invalidate(reason, true, events);
        self.selected = None;
        self.tracker.reset();
        self.status(state, reason, events);
    }

    fn invalidate(
        &mut self,
        reason: &'static str,
        reset_gate: bool,
        events: &mut Vec<LiveEvent<T>>,
    ) {
        self.epoch += 1;
        self.queued = None;
        self.needs_analysis = true;
        if reset_gate {
            self.gate.reset();
        } else {
            self.gate.break_consensus();
        }
        self.clear(reason, events);
    }
    fn clear(&mut self, reason: &'static str, events: &mut Vec<LiveEvent<T>>) {
        if self.recommendation_deadline.take().is_some() {
            events.push(LiveEvent::Clear {
                reason,
                generation: self.generation,
            });
        }
    }
    fn status(
        &mut self,
        state: &'static str,
        reason: &'static str,
        events: &mut Vec<LiveEvent<T>>,
    ) {
        let identity = self.selected.as_ref().map(WindowInfo::identity);
        let status = (state, reason, identity.clone());
        if self.last_status.as_ref() != Some(&status) {
            self.last_status = Some(status);
            events.push(LiveEvent::Status {
                state,
                reason,
                identity,
            });
        }
    }
    /// The caller must not publish a decision whose lease expired while stdout
    /// was backpressured. It was never active for the consumer, so no clear is owed.
    pub fn publication_dropped(&mut self) {
        self.recommendation_deadline = None;
        self.needs_analysis = true;
        self.gate.break_consensus();
    }

    pub fn queued_count(&self) -> usize {
        usize::from(self.queued.is_some())
    }
    pub fn active_count(&self) -> usize {
        usize::from(self.active.is_some())
    }
}

pub fn discovery_code(state: DiscoveryState) -> &'static str {
    match state {
        DiscoveryState::ConfigurationRequired => "configuration_required",
        DiscoveryState::WaitingForCoinPoker => "waiting_for_coin_poker",
        DiscoveryState::WaitingForTable => "waiting_for_table",
        DiscoveryState::LobbyDetected => "lobby_detected",
        DiscoveryState::CandidateTable => "candidate_table",
        DiscoveryState::CapturingTable => "capturing_table",
        DiscoveryState::AmbiguousMultipleTables => "ambiguous_multiple_tables",
        DiscoveryState::PermissionRequired => "permission_required",
        DiscoveryState::Recovering => "recovering",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn ticket(generation: u64) -> Ticket {
        Ticket {
            identity: TableIdentity {
                exe_name: "test.synthetic".into(),
                process_id: 1,
                hwnd: 2,
            },
            generation,
            epoch: 1,
            captured_at_ms: 10,
        }
    }

    #[test]
    fn worker_runs_off_thread_with_channel_synchronization() {
        let (started, started_rx) = mpsc::sync_channel(1);
        let (release, release_rx) = mpsc::sync_channel(1);
        let main_thread = std::thread::current().id();
        let mut worker = ThreadWorker::new(move |_| {
            started.send(std::thread::current().id()).unwrap();
            release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            Ok(Analysis {
                observation: ScreenObservation {
                    screen_kind: ScreenKind::Unknown,
                    evidence: crate::screen::ScreenEvidence {
                        table_layout: false,
                        hero_cards: false,
                        board_area: false,
                        pot: false,
                        action_controls: false,
                        readable: false,
                    },
                    state: None,
                },
                recommendation: None::<()>,
            })
        });
        let mut worker_id = None;
        for generation in [1, 2] {
            worker
                .start(InferenceJob {
                    ticket: ticket(generation),
                    frame: Frame::new(1, 1, vec![0; 4]).unwrap(),
                })
                .unwrap();
            let id = started_rx.recv_timeout(Duration::from_secs(5)).unwrap();
            assert_ne!(id, main_thread);
            if let Some(previous) = worker_id {
                assert_eq!(id, previous);
            }
            worker_id = Some(id);
            assert!(worker.try_complete().unwrap().is_none());
            release.send(()).unwrap();
            let result = worker.results.recv_timeout(Duration::from_secs(5)).unwrap();
            assert_eq!(result.ticket.generation, generation);
            assert!(result.result.is_ok());
        }
    }

    #[test]
    fn freshness_rejects_future_and_expired_captures_without_clock_sleeps() {
        let ticket = ticket(1);
        for now in [0, 9, 5010, 10000] {
            assert!(!observation_is_current(
                &ticket,
                Freshness {
                    identity: Some(&ticket.identity),
                    generation: 1,
                    epoch: 1,
                    now_ms: now,
                    fresh_capture: true,
                    max_frame_age_ms: 5000
                }
            ));
        }
        assert!(observation_is_current(
            &ticket,
            Freshness {
                identity: Some(&ticket.identity),
                generation: 1,
                epoch: 1,
                now_ms: 5009,
                fresh_capture: true,
                max_frame_age_ms: 5000
            }
        ));
    }
}
