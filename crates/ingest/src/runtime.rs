//! Bounded live orchestration. Only this owner can publish or invalidate advice.
//!
//! Capture/discovery run on the caller; blocking inference (and optional decision
//! computation) runs on one worker. There is one active ticket and one replaceable
//! latest stable frame. A result is never trusted without a fresh capture in the
//! same tick, matching identity/epoch/generation, and an unexpired capture lease.
//! An over-age completion is discarded whole: it never classifies the screen.

use std::sync::mpsc::{self, Receiver, SyncSender, TryRecvError, TrySendError};
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::capture::{CaptureError, CaptureSource, Frame, WindowInfo};
use crate::change_detect::{ChangeDetectorConfig, FrameTracker, StabilityConfig};
use crate::discovery::{CaptureManager, DiscoveryConfig, DiscoveryState, TableIdentity};
use crate::parser::{Card, GamePhase, GameState};
use crate::screen::{
    inspect_frame, MetadataEvidence, ScreenKind, ScreenObservation, TableGate, VisualEvidence,
};

/// Bounded transient worker retries before submission pauses until the next refresh.
const MAX_WORKER_FAILURES: u32 = 3;
/// A disconnected worker is terminal: it is never restarted in-process.
const TERMINAL_WORKER_CODE: &str = "inference-worker-stopped";
pub const CAPTURE_HEALTH_INTERVAL_MS: u64 = 1_000;
/// Leave one browser poll plus transport/render margin inside the total budget.
pub const PUBLICATION_RESERVE_MS: u64 = 300;
pub const DECISION_DEADLINE_CODE: &str = "decision-deadline-exceeded";

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
    pub decision_budget_ms: u64,
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
            decision_budget_ms: 5_000,
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
            || !(500..=5_000).contains(&self.decision_budget_ms)
        {
            return Err("invalid timing: poll 50..1000, discovery 500..5000, retry 500..30000, refresh 1000..10000, frame age 500..10000, decision budget 500..5000 ms");
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
    /// Source-anchored worker deadline, including time already spent capturing/queuing.
    pub deadline: Instant,
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
        mut analyze: impl FnMut(&InferenceJob) -> Result<Analysis<T>, InferenceFailure> + Send + 'static,
    ) -> Self {
        let (jobs, input) = mpsc::sync_channel::<InferenceJob>(1);
        let (output, results) = mpsc::sync_channel(1);
        std::thread::spawn(move || {
            while let Ok(job) = input.recv() {
                let result = if Instant::now() >= job.deadline {
                    Err(InferenceFailure {
                        code: DECISION_DEADLINE_CODE,
                    })
                } else {
                    let result = analyze(&job);
                    if Instant::now() >= job.deadline {
                        Err(InferenceFailure {
                            code: DECISION_DEADLINE_CODE,
                        })
                    } else {
                        result
                    }
                };
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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationRole {
    Observing,
    SeatedWaiting,
    YourTurn,
    Uncertain,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ControlView {
    pub action: &'static str,
    pub presence: &'static str,
    pub enabled: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WagerView {
    /// Physical six-max label, never a player-vector index.
    pub seat: u8,
    pub amount: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PotOddsView {
    pub seat: Option<u8>,
    pub required_equity_pct: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DrawView {
    pub outs: u32,
    pub next_card_pct: f64,
    pub by_river_pct: f64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ObservationMetrics {
    pub hand_rank: Option<String>,
    pub pot_odds: Option<PotOddsView>,
    pub draw: Option<DrawView>,
    pub equity_pct: Option<f64>,
}

/// Dashboard allowlist. Never serialize a GameState or its player names.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ObservationView {
    pub game_phase: GamePhase,
    pub hero_cards: Vec<Card>,
    pub board: Vec<Card>,
    pub role: ObservationRole,
    pub hero_seated: Option<bool>,
    pub acting_seat: Option<u8>,
    pub pot_size: Option<u32>,
    pub to_call: Option<u32>,
    pub acting_to_call: Option<u32>,
    pub hero_chips: Option<u32>,
    pub min_raise_to: Option<u32>,
    pub max_raise_to: Option<u32>,
    pub available_actions: Option<Vec<String>>,
    pub controls: Vec<ControlView>,
    pub action_required: Option<bool>,
    pub wagers: Vec<WagerView>,
    pub metrics: ObservationMetrics,
    /// Shape/semantic validation of individual readings, not perception quality.
    pub verified_fields: Vec<&'static str>,
    pub quality_approved: bool,
}
impl ObservationView {
    pub fn from_accepted_state(state: &GameState) -> Self {
        // Non-actionable legacy zeros/empty actions carry no control/amount evidence.
        let validated = crate::parser::validate_game_state(state).is_ok()
            && state.game_phase != GamePhase::Lobby;
        let seated = validated && state.players.iter().any(|player| player.name == "Hero");
        let actionable = seated
            && state.action_required
            && state.hero_cards.len() == 2
            && !state.available_actions.is_empty();
        let mut verified_fields = Vec::new();
        if validated {
            verified_fields.push("pot_size");
        }
        if seated {
            verified_fields.extend(["hero_seated", "action_required", "hero_chips"]);
        }
        if actionable {
            verified_fields.extend(["controls", "to_call"]);
            if state.min_raise_to.is_some() {
                verified_fields.push("min_raise_to");
            }
            if state.max_raise_to.is_some() {
                verified_fields.push("max_raise_to");
            }
        }
        let controls = ["fold", "check", "call", "bet", "raise", "all_in"]
            .into_iter()
            .map(|action| {
                let offered = actionable
                    && state.available_actions.iter().any(|offered| {
                        offered == if action == "all_in" { "allin" } else { action }
                    });
                ControlView {
                    action,
                    presence: if offered { "present" } else { "unknown" },
                    enabled: if offered { "enabled" } else { "unknown" },
                }
            })
            .collect();
        Self {
            game_phase: state.game_phase,
            hero_cards: state.hero_cards.clone(),
            board: state.board.clone(),
            role: if actionable {
                ObservationRole::YourTurn
            } else if seated && !state.action_required {
                ObservationRole::SeatedWaiting
            } else {
                ObservationRole::Uncertain
            },
            hero_seated: seated.then_some(true),
            acting_seat: None,
            pot_size: validated.then_some(state.pot_size),
            to_call: actionable.then_some(state.to_call),
            acting_to_call: None,
            hero_chips: seated.then_some(state.hero_chips),
            min_raise_to: actionable.then_some(state.min_raise_to).flatten(),
            max_raise_to: actionable.then_some(state.max_raise_to).flatten(),
            available_actions: actionable.then(|| state.available_actions.clone()),
            controls,
            action_required: seated.then_some(state.action_required),
            // GameState has no physical acting-seat/wager evidence. Metrics remain
            // unavailable until a separate capability approval, even for valid cards.
            wagers: Vec::new(),
            metrics: ObservationMetrics::default(),
            verified_fields,
            quality_approved: false,
        }
    }

    /// Only a caller with independent unseated admission evidence may call this.
    /// Empty cards, no Hero row, or a legacy false action flag are NOT that evidence.
    pub fn with_confirmed_unseated_admission(mut self) -> Self {
        if self.role == ObservationRole::Uncertain
            && self.hero_seated.is_none()
            && self.hero_cards.is_empty()
            && self.pot_size.is_some()
            && self.available_actions.is_none()
            && self
                .controls
                .iter()
                .all(|control| control.presence == "unknown")
        {
            self.role = ObservationRole::Observing;
            self.hero_seated = Some(false);
            self.action_required = Some(false);
            self.verified_fields
                .extend(["hero_seated", "action_required"]);
        }
        self
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
    /// Full consensus plus source-current admission, separate from weak Table.
    Observation {
        ticket: Ticket,
        value: ObservationView,
        valid_for_ms: u64,
    },
    ObservationInvalidated {
        reason: &'static str,
        generation: u64,
        epoch: u64,
        identity: Option<TableIdentity>,
    },
    CaptureHealth {
        frame_count: u64,
        frame_width: Option<u32>,
        frame_height: Option<u32>,
        captured_at_ms: Option<u64>,
        generation: u64,
        epoch: u64,
        fresh_capture: bool,
        identity: Option<TableIdentity>,
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
    active_deadline_reported: bool,
    queued: Option<InferenceJob>,
    recommendation_deadline: Option<u64>,
    observation_deadline: Option<u64>,
    next_health: u64,
    frame_count: u64,
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
            active_deadline_reported: false,
            queued: None,
            recommendation_deadline: None,
            observation_deadline: None,
            next_health: 0,
            frame_count: 0,
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
        if self
            .observation_deadline
            .is_some_and(|deadline| now >= deadline)
        {
            self.invalidate_observation("observation-expired", &mut events);
            self.needs_analysis = true;
            self.gate.break_consensus();
        }
        if now >= self.next_discovery {
            match self.capture.refresh() {
                Ok(selection) => {
                    self.worker_failures = 0;
                    let selection_changed = self.selected != selection.window;
                    if selection_changed {
                        self.selected = selection.window;
                        self.invalidate("window-changed", true, &mut events);
                        self.last_table = None;
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
        let mut dimensions = None;
        let mut captured_at = None;
        let mut fresh_capture = false;
        if self.selected.is_some() {
            let captured_at_ms = clock.now_ms();
            let capture_started = Instant::now();
            match self.capture.capture() {
                Ok(frame) => {
                    now = clock.now_ms();
                    self.frame_count = self.frame_count.saturating_add(1);
                    dimensions = Some((frame.width, frame.height));
                    captured_at = Some(captured_at_ms);
                    fresh_capture = frame.validate().is_ok();
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
                            current = Some((frame, captured_at_ms, capture_started));
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

        now = clock.now_ms();
        if !self.active_deadline_reported
            && self.active.as_ref().is_some_and(|ticket| {
                now.saturating_sub(ticket.captured_at_ms) >= self.config.decision_budget_ms
            })
        {
            // Do not free the worker slot or pretend that timed-out GPU work was cancelled.
            self.active_deadline_reported = true;
            self.clear(DECISION_DEADLINE_CODE, &mut events);
            self.invalidate_observation(DECISION_DEADLINE_CODE, &mut events);
        }
        match self.worker.try_complete() {
            Ok(Some(completion)) => {
                now = clock.now_ms();
                self.worker_failures = 0;
                let expected = self.active.take();
                self.active_deadline_reported = false;
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
                let expired = now.saturating_sub(completion.ticket.captured_at_ms)
                    >= self.config.max_frame_age_ms;
                let over_budget = now.saturating_sub(completion.ticket.captured_at_ms)
                    >= self.config.decision_budget_ms;
                if fresh && !over_budget {
                    self.complete(completion, now, &mut events);
                } else {
                    let reason = if expired {
                        "observation-expired"
                    } else if over_budget {
                        DECISION_DEADLINE_CODE
                    } else {
                        "obsolete-observation"
                    };
                    events.push(LiveEvent::Discarded {
                        generation: completion.ticket.generation,
                        reason,
                    });
                    // Obsolete results cannot seed even weak-card consensus.
                    self.clear(reason, &mut events);
                    self.invalidate_observation(reason, &mut events);
                    self.needs_analysis = true;
                    self.gate.break_consensus();
                }
            }
            Ok(None) => {
                self.worker_failures = 0;
            }
            Err(error) => self.record_worker_failure(error, &mut events),
        }

        now = clock.now_ms();
        if let Some((frame, captured_at_ms, capture_started)) = current {
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
                    queued.ticket.captured_at_ms = captured_at_ms;
                    queued.deadline = capture_started
                        + Duration::from_millis(
                            self.config.decision_budget_ms - PUBLICATION_RESERVE_MS,
                        );
                } else if let Some(window) = self.selected.as_ref() {
                    self.generation += 1;
                    self.queued = Some(InferenceJob {
                        ticket: Ticket {
                            identity: window.identity(),
                            generation: self.generation,
                            epoch: self.epoch,
                            captured_at_ms,
                        },
                        frame,
                        deadline: capture_started
                            + Duration::from_millis(
                                self.config.decision_budget_ms - PUBLICATION_RESERVE_MS,
                            ),
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
                        self.active_deadline_reported = false;
                        self.status("analyzing", "stable-frame-submitted", &mut events);
                    }
                    Err(error) => self.record_worker_failure(error, &mut events),
                }
            }
        }
        now = clock.now_ms();
        if now >= self.next_health {
            self.next_health = now.saturating_add(CAPTURE_HEALTH_INTERVAL_MS);
            events.push(LiveEvent::CaptureHealth {
                frame_count: self.frame_count,
                frame_width: dimensions.map(|(width, _)| width),
                frame_height: dimensions.map(|(_, height)| height),
                captured_at_ms: captured_at,
                generation: self.generation,
                epoch: self.epoch,
                fresh_capture,
                identity: self.selected.as_ref().map(WindowInfo::identity),
            });
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

    fn complete(&mut self, completion: Completion<T>, now: u64, events: &mut Vec<LiveEvent<T>>) {
        match completion.result {
            Err(error) => {
                self.clear(error.code, events);
                self.invalidate_observation(error.code, events);
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
                    Some(state) => {
                        self.needs_analysis = false;
                        self.status("capturing_table", outcome.reason, events);
                        let deadline = completion.ticket.captured_at_ms.saturating_add(
                            self.config
                                .max_frame_age_ms
                                .min(self.config.decision_budget_ms),
                        );
                        self.observation_deadline = Some(deadline);
                        events.push(LiveEvent::Observation {
                            ticket: completion.ticket.clone(),
                            value: ObservationView::from_accepted_state(&state),
                            valid_for_ms: deadline.saturating_sub(now),
                        });
                        if state.action_required {
                            if let Some(value) = analysis.recommendation {
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
                    None => {
                        self.clear("screen-not-accepted", events);
                        self.invalidate_observation("screen-not-accepted", events);
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
        self.selected = None;
        self.invalidate(reason, true, events);
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
        self.invalidate_observation(reason, events);
    }
    fn clear(&mut self, reason: &'static str, events: &mut Vec<LiveEvent<T>>) {
        if self.recommendation_deadline.take().is_some() {
            events.push(LiveEvent::Clear {
                reason,
                generation: self.generation,
            });
        }
    }
    fn invalidate_observation(&mut self, reason: &'static str, events: &mut Vec<LiveEvent<T>>) {
        self.observation_deadline = None;
        events.push(LiveEvent::ObservationInvalidated {
            reason,
            generation: self.generation,
            epoch: self.epoch,
            identity: self.selected.as_ref().map(WindowInfo::identity),
        });
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
        self.observation_deadline = None;
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
    use serde_json::json;
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

    fn view_state() -> GameState {
        serde_json::from_value(json!({
            "game_phase":"preflop","hero_cards":[
                {"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],
            "board":[],"pot_size":100,"to_call":0,"hero_chips":1000,
            "min_raise_to":null,"max_raise_to":null,"players":[
                {"name":"Hero","chips":1000,"last_action":null,"bet_amount":50},
                {"name":"PRIVATE-PLAYER","chips":1000,"last_action":null,"bet_amount":50}],
            "action_required":true,"available_actions":["check"]
        }))
        .unwrap()
    }

    #[test]
    fn observation_view_seated_roles_are_validated_without_metrics_or_seat_guesses() {
        let mut state = view_state();
        let turn = ObservationView::from_accepted_state(&state);
        assert_eq!(turn.role, ObservationRole::YourTurn);
        assert_eq!(turn.hero_seated, Some(true));
        assert_eq!(turn.action_required, Some(true));
        assert_eq!(turn.to_call, Some(0));
        assert_eq!(turn.hero_chips, Some(1000));
        assert_eq!(turn.controls[1].presence, "present");
        assert_eq!(turn.controls[1].enabled, "enabled");
        assert_eq!(turn.controls[0].presence, "unknown");
        assert!(turn.verified_fields.contains(&"controls"));
        assert_eq!(turn.acting_seat, None);
        assert_eq!(turn.acting_to_call, None);
        assert!(turn.wagers.is_empty());
        assert_eq!(turn.metrics, ObservationMetrics::default());
        assert!(!turn.quality_approved);
        assert!(!serde_json::to_string(&turn).unwrap().contains("PRIVATE"));

        state.action_required = false;
        state.available_actions.clear();
        state.hero_cards.clear(); // A seated/folded player is not an observer.
        let waiting = ObservationView::from_accepted_state(&state);
        assert_eq!(waiting.role, ObservationRole::SeatedWaiting);
        assert_eq!(waiting.hero_seated, Some(true));
        assert_eq!(waiting.action_required, Some(false));
        assert_eq!(waiting.to_call, None);
        assert_eq!(waiting.hero_chips, Some(1000));
        assert!(waiting.verified_fields.contains(&"hero_chips"));
        assert_eq!(waiting.available_actions, None);
        assert_eq!(
            waiting.with_confirmed_unseated_admission().role,
            ObservationRole::SeatedWaiting
        );
        state.hero_chips = 0;
        state.players[0].chips = 0;
        assert_eq!(
            ObservationView::from_accepted_state(&state).hero_chips,
            Some(0)
        );
    }

    #[test]
    fn observation_view_empty_cards_need_independent_unseated_admission() {
        let mut state = view_state();
        state.action_required = false;
        state.available_actions.clear();
        state.hero_cards.clear();
        state.players.clear();
        state.hero_chips = 0;
        let unknown = ObservationView::from_accepted_state(&state);
        assert_eq!(unknown.role, ObservationRole::Uncertain);
        assert_eq!(unknown.hero_seated, None);
        assert_eq!(unknown.action_required, None);
        assert_eq!(unknown.verified_fields, ["pot_size"]);
        let observing = unknown.with_confirmed_unseated_admission();
        assert_eq!(observing.role, ObservationRole::Observing);
        assert_eq!(observing.hero_seated, Some(false));
        assert_eq!(observing.action_required, Some(false));
        assert_eq!(observing.to_call, None);
        assert_eq!(observing.hero_chips, None);
        assert_eq!(observing.acting_to_call, None);
        assert_eq!(observing.metrics, ObservationMetrics::default());
        assert!(!observing.quality_approved);
    }

    #[test]
    fn observation_view_contradictory_cards_or_actions_cannot_establish_a_role() {
        for fault in ["cards", "controls", "call"] {
            let mut state = view_state();
            match fault {
                "cards" => state.hero_cards.clear(),
                "controls" => state.available_actions = vec!["call".into()],
                "call" => state.to_call = 50,
                _ => unreachable!(),
            }
            let view =
                ObservationView::from_accepted_state(&state).with_confirmed_unseated_admission();
            assert_eq!(view.role, ObservationRole::Uncertain);
            assert_eq!(view.hero_seated, None);
            assert_eq!(view.action_required, None);
            assert_eq!(view.pot_size, None);
            assert_eq!(view.to_call, None);
            assert_eq!(view.available_actions, None);
            assert!(view.verified_fields.is_empty());
            assert!(view
                .controls
                .iter()
                .all(|control| control.presence == "unknown"));
            assert!(!view.quality_approved);
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
                    deadline: Instant::now() + Duration::from_secs(5),
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

    #[test]
    fn expired_worker_job_never_runs_analysis() {
        let mut worker = ThreadWorker::new(|_| -> Result<Analysis<()>, InferenceFailure> {
            panic!("expired source must not reach analysis")
        });
        worker
            .start(InferenceJob {
                ticket: ticket(1),
                frame: Frame::new(1, 1, vec![0; 4]).unwrap(),
                deadline: Instant::now(),
            })
            .unwrap();
        let result = worker.results.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(result.result.err().unwrap().code, DECISION_DEADLINE_CODE);
    }

    #[test]
    fn freshness_requires_each_identity_component_epoch_generation_and_fresh_pixels() {
        let ticket = ticket(1);
        for mismatch in 0..6 {
            let mut identity = ticket.identity.clone();
            let mut generation = 1;
            let mut epoch = 1;
            let mut fresh_capture = true;
            match mismatch {
                0 => identity.exe_name.push_str(".other"),
                1 => identity.process_id += 1,
                2 => identity.hwnd += 1,
                3 => generation += 1,
                4 => epoch += 1,
                5 => fresh_capture = false,
                _ => unreachable!(),
            }
            assert!(!observation_is_current(
                &ticket,
                Freshness {
                    identity: Some(&identity),
                    generation,
                    epoch,
                    now_ms: 20,
                    fresh_capture,
                    max_frame_age_ms: 8_000,
                }
            ));
        }
    }
}
