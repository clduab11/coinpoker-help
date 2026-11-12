//! Approved same-source capture with bounded evidence and one live inference worker.

use std::cell::Cell;
use std::collections::hash_map::RandomState;
use std::collections::VecDeque;
use std::hash::BuildHasher;
use std::path::Path;
use std::rc::Rc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use ingest::capture::{
    CaptureError, CaptureSource, CaptureTiming, DiscoverySnapshot, Frame, PlatformCapture,
    WindowInfo,
};
use ingest::discovery::DiscoveryConfig;
use ingest::laya::{LayaBackend, ObservationPass};
use ingest::partial::TableContentWitness;
use ingest::recorder::{
    CaptureStamp, LiveFrameReceipt, PrivateRecorder, RecorderConfig, RecorderStatus,
};
use ingest::runtime::{
    Clock, InferenceFailure, InferencePort, LiveEvent, LiveRuntime, MonotonicClock, RuntimeConfig,
    ThreadWorker, Ticket,
};
use ingest::vlm::VlmConfig;
use serde_json::{json, Value};

use crate::manual_capture::{
    budget_reason, capture_failure, effective_recording_end_reason, find_approved_window,
    recording_end_reason, Approval, CaptureFailure, SourcePolicy,
};
use crate::{Pipeline, RunError};

const ACTIVITY_REGIONS: usize = ingest::laya::geometry::TABLE_READOUT_REGIONS.len();

/// A baseline is honoured while the probe keeps observing the region; it is dropped only after
/// this many consecutive samples in which the region could not be observed. Counting observations
/// instead of milliseconds is what stops the qualifier depending on inference latency.
const BASELINE_ABSENT_BUDGET: u8 = 8;

struct ActivityGate {
    active: bool,
    last: Option<Ticket>,
    baseline: [Option<TableContentWitness>; ACTIVITY_REGIONS],
    absent: [u8; ACTIVITY_REGIONS],
    candidate: Option<TableContentWitness>,
    repeats: [u8; ACTIVITY_REGIONS],
}

impl ActivityGate {
    fn new(policy: SourcePolicy) -> Self {
        Self {
            active: policy == SourcePolicy::Manual,
            last: None,
            baseline: std::array::from_fn(|_| None),
            absent: [0; ACTIVITY_REGIONS],
            candidate: None,
            repeats: [0; ACTIVITY_REGIONS],
        }
    }

    fn observe(&mut self, ticket: Ticket, witness: Option<TableContentWitness>, now: u64) {
        if self.active {
            return;
        }
        if self.last.as_ref().is_some_and(|last| {
            last.identity == ticket.identity
                && (ticket.epoch < last.epoch
                    || ticket.captured_at_ms <= last.captured_at_ms
                    || ticket.generation <= last.generation)
        }) {
            return;
        }
        if now
            .checked_sub(ticket.captured_at_ms)
            .is_none_or(|age| age >= 5_000)
            || witness.is_none()
            || self.last.as_ref().is_some_and(|last| {
                last.identity != ticket.identity
                    || last.epoch != ticket.epoch
                    || now.saturating_sub(last.captured_at_ms) >= 5_000
            })
            || self
                .candidate
                .as_ref()
                .zip(witness.as_ref())
                .is_some_and(|(a, b)| !a.same_geometry(b))
        {
            self.baseline.fill(None);
            self.absent.fill(0);
            self.candidate = None;
            self.repeats.fill(0);
        }
        self.last = Some(ticket.clone());
        if now
            .checked_sub(ticket.captured_at_ms)
            .is_none_or(|age| age >= 5_000)
        {
            return;
        }
        let Some(witness) = witness else {
            return;
        };
        for index in 0..ACTIVITY_REGIONS {
            if !witness.has_current_region(index) {
                // A readout may change during inference: it cannot count toward either pair, and
                // absence is the only thing that ages a baseline. Not a source break.
                self.repeats[index] = 0;
                self.absent[index] = self.absent[index].saturating_add(1);
                if self.absent[index] >= BASELINE_ABSENT_BUDGET {
                    self.baseline[index] = None;
                }
                continue;
            }
            self.absent[index] = 0;
            self.repeats[index] = if self
                .candidate
                .as_ref()
                .is_some_and(|previous| previous.same_region(&witness, index))
            {
                self.repeats[index].saturating_add(1).min(2)
            } else {
                1
            };
            if self.repeats[index] == 2 {
                match &self.baseline[index] {
                    Some(baseline) => {
                        if !baseline.same_region(&witness, index) {
                            self.active = true;
                        }
                    }
                    None => self.baseline[index] = Some(witness.clone()),
                }
            }
        }
        self.candidate = Some(witness);
    }
}

struct ManualWorker<W> {
    inner: W,
    failed: Rc<Cell<bool>>,
    stop_on_result_error: bool,
}

impl<W: InferencePort<crate::ui::widgets::DecisionView>>
    InferencePort<crate::ui::widgets::DecisionView> for ManualWorker<W>
{
    fn start(&mut self, job: ingest::runtime::InferenceJob) -> Result<(), InferenceFailure> {
        if self.failed.get() {
            return Err(InferenceFailure {
                code: "inference-failed",
            });
        }
        let result = self.inner.start(job);
        self.failed.set(result.as_ref().err().is_some_and(|error| {
            self.stop_on_result_error || error.code != "inference-worker-busy"
        }));
        result
    }

    fn try_complete(
        &mut self,
    ) -> Result<
        Option<ingest::runtime::Completion<crate::ui::widgets::DecisionView>>,
        InferenceFailure,
    > {
        let result = self.inner.try_complete();
        if result.as_ref().is_err()
            || self.stop_on_result_error
                && matches!(&result, Ok(Some(completion)) if completion.result.is_err())
        {
            self.failed.set(true);
        }
        result
    }
}

struct ManualSource<'a, S, C> {
    inner: S,
    approval: &'a Approval,
    stop: &'a Path,
    clock: &'a C,
    utc: &'a dyn Fn() -> SystemTime,
    recorder: PrivateRecorder,
    selected: Option<WindowInfo>,
    timing: Option<CaptureTiming>,
    last_live_clocks: Option<(u64, u64)>,
    last_check_ms: u64,
    terminal: Option<&'static str>,
    capture_failures: u64,
    capture_failure: Option<CaptureFailure>,
    source_id: u64,
    activity: ActivityGate,
    live_frame_index: u64,
    live_frame: Option<LiveFrameReceipt>,
}

impl<'a, S: CaptureSource, C: Clock> ManualSource<'a, S, C> {
    fn new(
        inner: S,
        approval: &'a Approval,
        root: &Path,
        stop: &'a Path,
        clock: &'a C,
        utc: &'a dyn Fn() -> SystemTime,
    ) -> Result<Self, RunError> {
        let recorder = PrivateRecorder::new(
            root,
            RecorderConfig {
                max_frames: approval.max_frames,
                ..RecorderConfig::default()
            },
            SystemTime::now(),
        )?;
        Ok(Self::with_recorder(
            inner, approval, stop, clock, utc, recorder,
        ))
    }

    fn with_recorder(
        inner: S,
        approval: &'a Approval,
        stop: &'a Path,
        clock: &'a C,
        utc: &'a dyn Fn() -> SystemTime,
        recorder: PrivateRecorder,
    ) -> Self {
        Self {
            inner,
            approval,
            stop,
            clock,
            utc,
            recorder,
            selected: None,
            timing: None,
            last_live_clocks: None,
            last_check_ms: clock.now_ms(),
            terminal: None,
            capture_failures: 0,
            capture_failure: None,
            source_id: RandomState::new()
                .hash_one((approval.source.process_id, approval.source.hwnd)),
            activity: ActivityGate::new(approval.source_policy),
            live_frame_index: 0,
            live_frame: None,
        }
    }

    fn fail(&mut self, reason: &'static str) -> CaptureError {
        self.terminal.get_or_insert(reason);
        CaptureError::Backend("manual-session-stopped".into())
    }

    fn check(&mut self) -> Result<(), CaptureError> {
        if self.terminal.is_some() {
            return Err(self.fail("manual-session-stopped"));
        }
        if self.stop.exists() {
            return Err(self.fail("operator-stop"));
        }
        let now = self.clock.now_ms();
        if self.approval.source_policy.is_sustained() {
            if now < self.last_check_ms {
                return Err(self.fail("capture-failed"));
            }
            self.last_check_ms = now;
            if now >= self.approval.max_seconds * 1_000 {
                self.recorder.end_duration();
            }
            return match self.recorder.handle().snapshot().recording_status {
                RecorderStatus::Active
                | RecorderStatus::DurationLimit
                | RecorderStatus::CountLimit
                | RecorderStatus::DiskLimit => Ok(()),
                _ => Err(self.fail("recorder-failure")),
            };
        }
        if let Some(reason) = budget_reason(
            now,
            self.approval.max_seconds * 1_000,
            self.recorder.handle().snapshot().recording_status,
        ) {
            return Err(self.fail(reason));
        }
        Ok(())
    }

    fn current_window(&mut self) -> Result<WindowInfo, CaptureError> {
        self.check()?;
        let listing = self
            .inner
            .discover()
            .map_err(|_| self.fail("source-unavailable"))?;
        let Some(current) = find_approved_window(&listing.windows, &self.approval.source).cloned()
        else {
            eprintln!(
                "{}",
                json!({"event":"source-validation-rejected", "approved":self.approval.source,
                "current":listing.windows.iter().filter(|window| window.process_id == self.approval.source.process_id
                    || window.hwnd == self.approval.source.hwnd).collect::<Vec<_>>(), "captured_at_ms":self.clock.now_ms()})
            );
            return Err(self.fail("source-changed"));
        };
        self.check()?;
        Ok(current)
    }

    fn progress(&self, reason: Option<&str>) -> Value {
        let snapshot = self.recorder.handle().snapshot();
        json!({"event":"manual_capture", "version":self.approval.source_policy.approval_version(), "mode":self.approval.mode,
            "source_policy":self.approval.source_policy,
            "experimental_bet_action":self.approval.experimental_bet_action,
            "activity_state":if self.activity.active { "active" } else { "verifying" },
            "activity_reason":self.activity_reason(),
            "service_instance_id":self.approval.service_instance_id,
            "elapsed_ms":self.clock.now_ms(), "stop_reason":reason,
            "recording_end_reason":effective_recording_end_reason(reason, snapshot.recording_status),
            "recording":snapshot, "capture_failures":self.capture_failures,
            "capture_failure":self.capture_failure,
            "capture_directory":self.recorder.session_path(), "latest_frame":self.recorder.last_receipt(),
            "live_frame":self.live_frame,
            "updated_at_unix_ms":self.now_unix_ms()})
    }

    fn activity_reason(&self) -> &'static str {
        if !self.activity.active {
            "activity-verifying"
        } else if self.approval.source_policy.is_automatic() {
            "visible-table-content-change"
        } else {
            "manual-approval"
        }
    }

    fn activity_status(&self) -> Value {
        json!({"schema_version":2,"event":"status",
            "state":if self.activity.active { "capturing_table" } else { "verifying" },
            "reason":self.activity_reason(),
            "generation":self.activity.last.as_ref().map_or(0, |ticket| ticket.generation),
            "epoch":self.activity.last.as_ref().map_or(0, |ticket| ticket.epoch),
            "identity":self.approval.source.identity(),"emitted_at_unix_ms":self.now_unix_ms()})
    }

    fn now_unix_ms(&self) -> u64 {
        (self.utc)()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |time| time.as_millis().min(u128::from(u64::MAX)) as u64)
    }
}

impl<S: CaptureSource, C: Clock> CaptureSource for ManualSource<'_, S, C> {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        Ok(DiscoverySnapshot {
            windows: vec![self.current_window()?],
            ..Default::default()
        })
    }

    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError> {
        let current = self.current_window()?;
        if &current != window {
            // Identity is still approved, but geometry must be rediscovered.
            return Err(CaptureError::StaleWindow { hwnd: window.hwnd });
        }
        self.inner
            .select(&current)
            .map_err(|_| self.fail("source-unavailable"))?;
        self.selected = Some(current);
        Ok(())
    }

    fn capture(&mut self) -> Result<Frame, CaptureError> {
        self.timing = None;
        let current = self.current_window()?;
        if self.selected.as_ref() != Some(&current) {
            return Err(CaptureError::StaleWindow { hwnd: current.hwnd });
        }
        self.check()?;
        // These clocks describe this exact acquisition, not discovery or PNG encoding.
        let started = Instant::now();
        let monotonic_ms = self.clock.now_ms();
        let source_utc = (self.utc)();
        let utc_unix_ms = source_utc
            .duration_since(UNIX_EPOCH)
            .ok()
            .and_then(|time| u64::try_from(time.as_millis()).ok())
            .ok_or_else(|| self.fail("capture-failed"))?;
        if self.approval.source_policy.is_sustained()
            && self
                .last_live_clocks
                .is_some_and(|(mono, utc)| monotonic_ms <= mono || utc_unix_ms <= utc)
        {
            return Err(self.fail("capture-failed"));
        }
        let mut frame = match self.inner.capture() {
            Ok(frame) => frame,
            Err(error) => {
                let failure = capture_failure(&error);
                eprintln!("approved source capture failed: {}", failure.detail);
                self.capture_failure = Some(failure);
                self.capture_failures += 1;
                if matches!(error, CaptureError::StaleWindow { .. }) {
                    let resized = self.current_window()?;
                    if (resized.width, resized.height) != (current.width, current.height) {
                        return Err(error);
                    }
                }
                return Err(self.fail("capture-failed"));
            }
        };
        let after = self.current_window()?;
        if after != current {
            return Err(CaptureError::StaleWindow { hwnd: current.hwnd });
        }
        self.check()?;
        if self.approval.source_policy.is_sustained()
            && (frame.validate().is_err()
                || frame.width == 0
                || frame.height == 0
                || frame.rgba.len() > 64 * 1024 * 1024)
        {
            return Err(self.fail("capture-failed"));
        }
        let before = self.recorder.handle().snapshot().recorded_frames;
        let stamp = CaptureStamp {
            source_utc,
            captured_at_monotonic_ms: monotonic_ms,
            generation: None,
            source_id: Some(self.source_id),
        };
        self.recorder.record(&frame, stamp);
        if self.approval.source_policy.is_sustained() {
            self.live_frame_index += 1;
            self.live_frame = self
                .recorder
                .live_frame_with_popups(&frame, stamp, self.live_frame_index, started)
                .ok();
        }
        // Only sustained observation may use new live pixels after an expected cap.
        // All other skipped/unacknowledged frames and unexpected I/O remain terminal.
        self.check()?;
        let recorded = self.recorder.handle().snapshot();
        if recorded.recorded_frames != before + 1
            && !(self.approval.source_policy.is_sustained()
                && recording_end_reason(recorded.recording_status).is_some())
        {
            return Err(self.fail("recorder-failure"));
        }
        // This receipt was produced from these exact pixels in this call. Never
        // borrow last_receipt after a cap or associate an old completion by time.
        frame.original_capture = self
            .live_frame
            .as_ref()
            .map(|receipt| {
                receipt.original_capture(
                    self.recorder
                        .session_path()
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("")
                        .to_owned(),
                )
            })
            .or_else(|| {
                (recorded.recorded_frames == before + 1)
                    .then(|| self.recorder.original_capture())
                    .flatten()
            });
        if let Some(original) = &mut frame.original_capture {
            original.capture_session_id = self
                .stop
                .parent()
                .and_then(Path::file_name)
                .and_then(|name| name.to_str())
                .map(str::to_owned);
        }
        self.last_live_clocks = Some((monotonic_ms, utc_unix_ms));
        self.timing = Some(CaptureTiming {
            monotonic_ms,
            utc_unix_ms,
            started,
        });
        Ok(frame)
    }

    fn reset(&mut self) {
        self.inner.reset();
        self.selected = None;
        self.timing = None;
    }

    fn last_capture_timing(&self) -> Option<CaptureTiming> {
        self.timing
    }
}

fn poll_delay(policy: SourcePolicy, period: u64, started: u64, now: u64) -> u64 {
    if policy.is_automatic() {
        period.saturating_sub(now.saturating_sub(started))
    } else {
        period
    }
}

fn inference_loop<
    S: CaptureSource,
    W: InferencePort<crate::ui::widgets::DecisionView>,
    C: Clock,
>(
    source: ManualSource<'_, S, C>,
    worker: W,
    mut wait: impl FnMut(u64),
    mut sink: impl FnMut(&Value) -> Result<(), RunError>,
) -> Result<(), RunError> {
    let (approval, clock, utc) = (source.approval, source.clock, source.utc);
    let recording = source.recorder.handle();
    let mut config = RuntimeConfig {
        poll_ms: 500,
        ..RuntimeConfig::default()
    };
    if approval.source_policy.is_automatic() {
        // Two independent live acquisitions at this cadence already span the
        // unchanged 300 ms settling interval.
        config.stability.stable_captures = 2;
    }
    let discovery = DiscoveryConfig {
        exe_name: Some(approval.source.exe_name.clone()),
        process_id: Some(approval.source.process_id),
        window_hwnd: Some(approval.source.hwnd),
        table_title: approval.source.title.clone(),
        ..DiscoveryConfig::default()
    };
    let worker_failed = Rc::new(Cell::new(false));
    let worker = ManualWorker {
        inner: worker,
        failed: worker_failed.clone(),
        stop_on_result_error: !approval.source_policy.is_sustained(),
    };
    let mut runtime = LiveRuntime::new(source, worker, discovery, config.clone())
        .map_err(|error| RunError::Message(error.into()))?;
    if approval.source_policy.is_automatic() {
        runtime.enable_activity_probe();
    }
    let mut history = crate::live::AdmittedHistory::new()?;
    let activity_active = Cell::new(runtime.source().activity.active);
    let mut emit = |record: &Value| {
        let mut record = record.clone();
        record["mode"] = json!(approval.mode);
        record["service_instance_id"] = json!(approval.service_instance_id);
        record["source_policy"] = json!(approval.source_policy);
        record["experimental_bet_action"] = json!(approval.experimental_bet_action);
        record["activity_state"] = json!(if activity_active.get() {
            "active"
        } else {
            "verifying"
        });
        if record["event"] == "history" {
            record["emitted_at_unix_ms"] = json!(utc()
                .duration_since(UNIX_EPOCH)
                .map_or(0, |time| time.as_millis().min(u128::from(u64::MAX)) as u64));
        }
        if serde_json::to_vec(&record)
            .map_err(|_| RunError::Message("publication-failed".into()))?
            .len()
            > 256 * 1024
        {
            return Err(RunError::Message("publication-failed".into()));
        }
        sink(&record)
    };
    let mut pending_events = VecDeque::new();
    let mut visual_sequence = None;
    let result = (|| -> Result<&'static str, RunError> {
        emit(&runtime.source().progress(None))?;
        if !runtime.source().activity.active {
            emit(&runtime.source().activity_status())?;
        }
        loop {
            let iteration_started = clock.now_ms();
            if runtime.source_mut().check().is_err() {
                return Ok(runtime.source().terminal.unwrap());
            }
            pending_events = runtime.tick(clock).into();
            if let Some(reason) = runtime.source().terminal {
                return Ok(reason);
            }
            if worker_failed.get() {
                return Ok("inference-failed");
            }
            if runtime.source_mut().check().is_err() {
                return Ok(runtime.source().terminal.unwrap());
            }
            if let Some((ticket, witness)) = runtime.take_activity_sample() {
                let was_active = runtime.source().activity.active;
                runtime
                    .source_mut()
                    .activity
                    .observe(ticket, witness, clock.now_ms());
                activity_active.set(runtime.source().activity.active);
                if !was_active && runtime.source().activity.active {
                    runtime.finish_activity_probe();
                    // Activity qualifies history, not independently admitted readouts.
                    emit(&runtime.source().progress(None))?;
                    emit(&runtime.source().activity_status())?;
                }
            }
            if pending_events.iter().any(|event| {
                matches!(event, LiveEvent::Status { state: "recovering", reason, .. }
                if *reason != "stale-window-filter" && !(approval.source_policy.is_automatic()
                    && *reason == "source-region-changed"))
            }) {
                for event in &pending_events {
                    if let LiveEvent::Status {
                        state: "recovering",
                        reason,
                        ..
                    } = event
                    {
                        eprintln!(
                            "{}",
                            json!({"event":"inference-recovery", "reason":reason,"runtime_now_ms":clock.now_ms()})
                        );
                    }
                }
                if !approval.source_policy.is_sustained() {
                    return Ok("inference-failed");
                }
            }
            while !pending_events.is_empty() {
                if runtime.source_mut().check().is_err() {
                    return Ok(runtime.source().terminal.unwrap());
                }
                let event = pending_events.pop_front().unwrap();
                if !runtime.source().activity.active
                    && matches!(
                        event,
                        LiveEvent::Observation { .. } | LiveEvent::Status { .. }
                    )
                {
                    continue;
                }
                let partial = match &event {
                    LiveEvent::PartialObservation { value, .. } => Some(value.clone()),
                    _ => None,
                };
                let ticket = match &event {
                    LiveEvent::Observation { ticket, .. }
                    | LiveEvent::PartialObservation { ticket, .. }
                    | LiveEvent::PerceptionDiagnostics { ticket, .. }
                    | LiveEvent::Recommendation { ticket, .. } => Some(ticket.clone()),
                    LiveEvent::CaptureHealth {
                        generation,
                        epoch,
                        captured_at_ms: Some(captured_at_ms),
                        identity: Some(identity),
                        fresh_capture: true,
                        ..
                    } => Some(ingest::runtime::Ticket {
                        identity: identity.clone(),
                        generation: *generation,
                        epoch: *epoch,
                        captured_at_ms: *captured_at_ms,
                        captured_at_unix_ms: runtime
                            .source()
                            .last_capture_timing()
                            .map(|timing| timing.utc_unix_ms),
                    }),
                    _ => None,
                };
                let emitted_at = utc()
                    .duration_since(UNIX_EPOCH)
                    .map_err(|_| RunError::Message("publication-failed".into()))?
                    .as_millis() as u64;
                if let Some(mut record) = crate::live::event_record(
                    event,
                    clock.now_ms(),
                    emitted_at,
                    &config,
                    recording.snapshot(),
                )? {
                    if record["event"] == "capture_health" {
                        if let Some(timing) = runtime.source().last_capture_timing() {
                            record["captured_at_unix_ms"] = json!(timing.utc_unix_ms);
                        }
                    }
                    if !runtime.source().activity.active {
                        emit(&record)?;
                        continue;
                    }
                    crate::live::emit_with_history(
                        &record,
                        ticket.as_ref(),
                        partial.as_deref(),
                        &mut history,
                        clock,
                        &config,
                        &mut emit,
                    )?;
                } else {
                    runtime.publication_dropped();
                    let ticket = ticket.expect("only leased readings expire at publication");
                    crate::live::emit_with_history(
                        &json!({"schema_version":2,"event":"observation_invalidated",
                        "generation":ticket.generation,"epoch":ticket.epoch,"identity":ticket.identity,
                        "reason":"publication-expired","emitted_at_unix_ms":emitted_at}),
                        None,
                        None,
                        &mut history,
                        clock,
                        &config,
                        &mut emit,
                    )?;
                }
            }
            if approval.source_policy.is_sustained() {
                if let Some(frame) = runtime.source().live_frame.as_ref() {
                    if visual_sequence != Some(frame.frame_index) {
                        emit(&json!({"schema_version":2,"event":"visual_frame",
                            "identity":approval.source.identity(),
                            "capture_directory":runtime.source().recorder.session_path(),"frame":frame}))?;
                        visual_sequence = Some(frame.frame_index);
                    }
                }
            }
            emit(&runtime.source().progress(None))?;
            // Anchor to the last acknowledged source call, not loop entry: initial
            // selection/setup can be slow before that call. The next frame must
            // still satisfy the recorder's source-clock sampling interval.
            let capture_started = runtime
                .source()
                .last_capture_timing()
                .map_or(iteration_started, |timing| timing.monotonic_ms);
            wait(poll_delay(
                approval.source_policy,
                config.poll_ms,
                capture_started,
                clock.now_ms(),
            ));
        }
    })();
    let reason = result.as_ref().copied().unwrap_or("publication-failed");
    // A terminal tick may already have cleared runtime leases. Preserve its
    // queued invalidations, but never publish queued readings after a stop/error.
    let invalidations = pending_events
        .into_iter()
        .filter(|event| {
            matches!(
                event,
                LiveEvent::Clear { .. }
                    | LiveEvent::ObservationInvalidated { .. }
                    | LiveEvent::PartialObservationInvalidated { .. }
            )
        })
        .chain(runtime.stop(reason));
    // Publish termination before dropping the worker; never wait for GPU work.
    let final_status = emit(&runtime.source().progress(Some(reason)));
    for event in invalidations {
        if let Ok(Some(record)) = crate::live::event_record(
            event,
            clock.now_ms(),
            runtime.source().now_unix_ms(),
            &config,
            recording.snapshot(),
        ) {
            let _ = emit(&record);
        }
    }
    result?;
    final_status
}

fn next_automatic_pass(step: &mut u8, experimental: bool) -> ObservationPass {
    // Three fresh jobs per field allow two-read consensus inside the original
    // five-second budget. Experiments have separate lanes, never numeric pairs/batches.
    let period = if experimental { 60 } else { 24 };
    let pass = if *step >= period - 3 {
        ObservationPass::Board
    } else if *step < 3 {
        ObservationPass::Pot
    } else if experimental {
        let lane = (*step - 3) / 3;
        let seat = lane / 3 + 1;
        match lane % 3 {
            0 => ObservationPass::Stack(seat),
            1 => ObservationPass::Wager(seat),
            _ => ObservationPass::Scene(seat),
        }
    } else {
        ObservationPass::Stack((*step - 3) / 3 + 1)
    };
    *step = (*step + 1) % period;
    pass
}

#[derive(Default)]
struct AutomaticSchedule {
    step: u8,
    cpu_visual_board: bool,
}

impl AutomaticSchedule {
    fn new(cpu_visual_board: bool) -> Self {
        Self {
            cpu_visual_board,
            ..Self::default()
        }
    }

    fn next(&mut self, policy: SourcePolicy, experimental: bool) -> ObservationPass {
        if !policy.is_sustained() {
            return next_automatic_pass(&mut self.step, experimental);
        }
        // One mixed request reads Pot and every seat, so one repeated pair refreshes the
        // whole seat row instead of three separate pairs. A separately running CPU board
        // lane removes only GPU Board jobs; it never supplies qualified native Board or
        // GameState inputs.
        let period = if self.cpu_visual_board && !experimental {
            2
        } else {
            4
        };
        let pass = if self.step < 2 {
            ObservationPass::ReadoutAll
        } else {
            ObservationPass::BoardReadout
        };
        self.step = (self.step + 1) % period;
        pass
    }
}

pub(crate) fn validate_experimental_opt_in(
    approval: &Approval,
    enabled: bool,
) -> Result<(), RunError> {
    if approval.experimental_bet_action != enabled
        || enabled
            && (approval.mode != "inference-enabled"
                || !approval.source_policy.is_automatic()
                || approval.source_policy.is_sustained()
                || !(1..=600).contains(&approval.max_seconds)
                || !(1..=1_200).contains(&approval.max_frames)
                || !approval.service_instance_id.as_deref().is_some_and(|id| {
                    id.len() == 32
                        && id
                            .bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                }))
    {
        return Err(RunError::Message("experimental-approval-mismatch".into()));
    }
    Ok(())
}

pub(crate) fn run(
    approval: Approval,
    root: &Path,
    stop: &Path,
    experimental_bet_action: bool,
) -> Result<(), RunError> {
    validate_experimental_opt_in(&approval, experimental_bet_action)?;
    // Pinned defaults only: no ambient model, thresholds, or readiness calls.
    // The supervisor waits for installed-it1 readiness before fresh confirmation.
    let session = stop
        .parent()
        .and_then(Path::file_name)
        .and_then(|name| name.to_str())
        .ok_or_else(|| RunError::Message("invalid-manual-session-binding".into()))?;
    let backend = LayaBackend::new(VlmConfig::default(), None)
        .and_then(|backend| {
            backend.with_manual_session(
                session,
                approval.service_instance_id.as_deref().unwrap_or(""),
            )
        })
        .and_then(|backend| backend.with_experimental_bet_action(experimental_bet_action))
        .map_err(|_| RunError::Message("inference-unavailable".into()))?;
    let policy = approval.source_policy;
    let mut schedule = AutomaticSchedule::new(approval.cpu_visual_board);
    let pipeline = Pipeline::new();
    let worker = ThreadWorker::new(move |job| {
        let output = if policy.is_automatic() {
            backend.analyze_partial_with_deadline(
                &job.frame,
                job.deadline,
                schedule.next(policy, experimental_bet_action),
            )
        } else {
            backend.analyze_observation_with_deadline(&job.frame, job.deadline)
        }
        .map_err(|error| {
            eprintln!("{}", json!({"event":"inference-error", "code":error.code(),"error":error.to_string(),
                "generation":job.ticket.generation,"epoch":job.ticket.epoch,
                "captured_at_ms":job.ticket.captured_at_ms,"captured_at_unix_ms":job.ticket.captured_at_unix_ms}));
            InferenceFailure { code: error.code() }
        })?;
        crate::live::finish_laya_analysis(output, Some(&pipeline), job.deadline)
    });
    let clock = MonotonicClock::default();
    let source = if policy.is_automatic() {
        eprintln!("automatic capture backend: current visible desktop rectangle; verified selected-owned transient regional masks; original capture-call clocks; no compositing or archived/WGC frame reuse");
        PlatformCapture::visible_desktop_pixels()
    } else {
        PlatformCapture::default()
    };
    inference_loop(
        ManualSource::new(source, &approval, root, stop, &clock, &SystemTime::now)?,
        worker,
        |delay| std::thread::sleep(Duration::from_millis(delay)),
        crate::live::emit,
    )
}

#[cfg(test)]
#[path = "manual_inference_tests.rs"]
mod tests;
