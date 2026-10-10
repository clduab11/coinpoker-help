//! Deterministic runtime coverage with explicit clock, capture state, and inference completions.
use std::cell::RefCell;
use std::rc::Rc;

use ingest::capture::{CaptureError, CaptureSource, Frame, WindowInfo};
use ingest::discovery::{ApplicationInfo, DiscoveryConfig, DiscoverySnapshot};
use ingest::runtime::{
    Analysis, Clock, Completion, InferenceFailure, InferenceJob, InferencePort, LiveEvent,
    LiveRuntime, RuntimeConfig, Ticket,
};
use ingest::screen::{parse_screen_output, ScreenObservation};
use ingest::vlm::VlmOutput;
use serde_json::json;

struct Time(u64);
impl Clock for Time {
    fn now_ms(&self) -> u64 {
        self.0
    }
}
struct SourceState {
    snapshot: DiscoverySnapshot,
    frame: Frame,
    permission: bool,
    captures: usize,
    filters: usize,
}
#[derive(Clone)]
struct Source(Rc<RefCell<SourceState>>);
impl CaptureSource for Source {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        let state = self.0.borrow();
        if !state.permission {
            Err(CaptureError::PermissionDenied)
        } else {
            Ok(state.snapshot.clone())
        }
    }
    fn select(&mut self, _: &WindowInfo) -> Result<(), CaptureError> {
        self.0.borrow_mut().filters += 1;
        Ok(())
    }
    fn capture(&mut self) -> Result<Frame, CaptureError> {
        let mut state = self.0.borrow_mut();
        state.captures += 1;
        if state.permission {
            Ok(state.frame.clone())
        } else {
            Err(CaptureError::PermissionDenied)
        }
    }
    fn reset(&mut self) {}
}
#[derive(Default)]
struct WorkerState {
    ticket: Option<Ticket>,
    ready: Option<Result<Analysis<&'static str>, InferenceFailure>>,
    started: Vec<u64>,
    fail_start: Option<InferenceFailure>,
    disconnected: bool,
}
#[derive(Clone, Default)]
struct Worker(Rc<RefCell<WorkerState>>);
impl InferencePort<&'static str> for Worker {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
        let mut worker = self.0.borrow_mut();
        if let Some(failure) = worker.fail_start.take() {
            return Err(failure);
        }
        assert!(worker.ticket.is_none(), "only one active inference");
        worker.started.push(job.ticket.generation);
        worker.ticket = Some(job.ticket);
        Ok(())
    }
    fn try_complete(&mut self) -> Result<Option<Completion<&'static str>>, InferenceFailure> {
        let mut worker = self.0.borrow_mut();
        if worker.disconnected {
            return Err(InferenceFailure {
                code: "inference-worker-stopped",
            });
        }
        Ok(worker.ready.take().map(|result| Completion {
            ticket: worker.ticket.take().unwrap(),
            result,
        }))
    }
}
type Runtime = LiveRuntime<Source, Worker, &'static str>;
fn table() -> ScreenObservation {
    parse_screen_output(&VlmOutput { text: json!({
        "screen_kind":"poker_table", "evidence":{"table_layout":true,"hero_cards":true,"board_area":true,"pot":true,"action_controls":true,"readable":true},
        "state":{"game_phase":"preflop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],"board":[],"pot_size":100,"to_call":0,"hero_chips":1000,"min_raise_to":null,"max_raise_to":null,"players":[{"name":"Hero","chips":1000,"last_action":null,"bet_amount":50},{"name":"Seat1","chips":1000,"last_action":null,"bet_amount":50}],"action_required":true,"available_actions":["check"]}
    }).to_string() }).unwrap()
}
fn lobby() -> ScreenObservation {
    parse_screen_output(&VlmOutput {
        text: json!({
            "screen_kind":"lobby",
            "evidence":{"table_layout":false,"hero_cards":false,"board_area":false,"pot":false,"action_controls":false,"readable":true},
            "state":null
        })
        .to_string(),
    })
    .unwrap()
}
fn unseated() -> ScreenObservation {
    let mut observation = table();
    observation.evidence.hero_cards = false;
    observation.evidence.action_controls = false;
    let state = observation.state.as_mut().unwrap();
    state.hero_cards.clear();
    state.players.clear();
    state.hero_chips = 0;
    state.action_required = false;
    state.available_actions.clear();
    observation
}
fn rig(config: RuntimeConfig) -> (Runtime, Source, Worker) {
    let window = WindowInfo {
        hwnd: 7,
        process_id: 42,
        exe_name: "test.synthetic".into(),
        title: Some("Synthetic table".into()),
        on_screen: true,
        width: 160,
        height: 120,
    };
    let snapshot = DiscoverySnapshot {
        applications: vec![ApplicationInfo {
            exe_name: window.exe_name.clone(),
            process_id: window.process_id,
        }],
        windows: vec![window],
    };
    let mut rgba = vec![64; 160 * 120 * 4];
    rgba[0] = 255;
    let source = Source(Rc::new(RefCell::new(SourceState {
        snapshot,
        frame: Frame::new(160, 120, rgba).unwrap(),
        permission: true,
        captures: 0,
        filters: 0,
    })));
    let worker = Worker::default();
    let runtime = LiveRuntime::new(
        source.clone(),
        worker.clone(),
        DiscoveryConfig {
            exe_name: Some("test.synthetic".into()),
            table_title: Some("table".into()),
            lobby_title: Some("lobby".into()),
            ..DiscoveryConfig::default()
        },
        config,
    )
    .unwrap();
    (runtime, source, worker)
}
fn finish(worker: &Worker, observation: ScreenObservation) {
    worker.0.borrow_mut().ready = Some(Ok(Analysis {
        observation,
        recommendation: Some("check"),
    }));
}
fn finish_without_advice(worker: &Worker, observation: ScreenObservation) {
    worker.0.borrow_mut().ready = Some(Ok(Analysis {
        observation,
        recommendation: None,
    }));
}
fn activate_observation(runtime: &mut Runtime, worker: &Worker) -> Vec<LiveEvent<&'static str>> {
    start(runtime);
    finish_without_advice(worker, unseated());
    assert!(!runtime
        .tick(&Time(400))
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
    runtime.tick(&Time(500));
    finish_without_advice(worker, unseated());
    let events = runtime.tick(&Time(600));
    assert!(events
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
    assert!(!events.iter().any(is_decision));
    events
}
fn rig_with_discovery(
    discovery: DiscoveryConfig,
    config: RuntimeConfig,
) -> (Runtime, Source, Worker) {
    let window = WindowInfo {
        hwnd: 7,
        process_id: 42,
        exe_name: "test.synthetic".into(),
        title: Some("Synthetic table".into()),
        on_screen: true,
        width: 160,
        height: 120,
    };
    let snapshot = DiscoverySnapshot {
        applications: vec![ApplicationInfo {
            exe_name: window.exe_name.clone(),
            process_id: window.process_id,
        }],
        windows: vec![window],
    };
    let mut rgba = vec![64; 160 * 120 * 4];
    rgba[0] = 255;
    let source = Source(Rc::new(RefCell::new(SourceState {
        snapshot,
        frame: Frame::new(160, 120, rgba).unwrap(),
        permission: true,
        captures: 0,
        filters: 0,
    })));
    let worker = Worker::default();
    let runtime = LiveRuntime::new(source.clone(), worker.clone(), discovery, config).unwrap();
    (runtime, source, worker)
}
/// Ticks until the accepted completion has been consumed (idle worker).
fn drive_completion_consumed(runtime: &mut Runtime, start_ms: u64, limit_ms: u64) -> u64 {
    let mut now = start_ms;
    while (runtime.active_count() != 0 || runtime.queued_count() != 0) && now <= limit_ms {
        runtime.tick(&Time(now));
        now += 100;
    }
    assert_eq!(runtime.active_count(), 0, "completion was consumed");
    assert_eq!(runtime.queued_count(), 0, "no job is queued while idle");
    now
}
fn start(runtime: &mut Runtime) {
    for now in [0, 100, 200, 300] {
        runtime.tick(&Time(now));
    }
    assert_eq!(runtime.active_count(), 1);
}
fn activate(runtime: &mut Runtime, worker: &Worker) {
    start(runtime);
    finish(worker, table());
    assert!(!runtime.tick(&Time(400)).iter().any(is_decision));
    runtime.tick(&Time(500));
    finish(worker, table());
    assert!(runtime.tick(&Time(600)).iter().any(is_decision));
}
fn is_decision(event: &LiveEvent<&str>) -> bool {
    matches!(event, LiveEvent::Recommendation { .. })
}
fn clears(events: &[LiveEvent<&str>]) -> usize {
    events
        .iter()
        .filter(|e| matches!(e, LiveEvent::Clear { .. }))
        .count()
}
fn change(source: &Source, value: u8) {
    source.0.borrow_mut().frame.rgba[40] = value;
}
/// Ticks until exactly one inference is active, returning the next unused timestamp.
fn drive_until_active(runtime: &mut Runtime, start_ms: u64, limit_ms: u64) -> u64 {
    let mut now = start_ms;
    while runtime.active_count() == 0 && now <= limit_ms {
        runtime.tick(&Time(now));
        now += 100;
    }
    assert_eq!(runtime.active_count(), 1, "expected an active inference");
    now
}

#[test]
fn immediately_clears_before_changed_frame_inference_and_never_floods() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    activate(&mut runtime, &worker);
    change(&source, 255);
    let events = runtime.tick(&Time(700));
    assert_eq!(clears(&events), 1);
    assert!(matches!(
        events.first(),
        Some(LiveEvent::Clear {
            reason: "frame-changed",
            ..
        })
    ));
    for now in [800, 900, 1000, 1100] {
        assert_eq!(clears(&runtime.tick(&Time(now))), 0);
    }
}

#[test]
fn captures_continue_and_latest_queue_is_bounded_while_inference_is_slow() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    change(&source, 255);
    for now in [400, 500, 600, 700] {
        runtime.tick(&Time(now));
    }
    assert_eq!(runtime.queued_count(), 1);
    change(&source, 0);
    for now in [800, 900, 1000, 1100] {
        runtime.tick(&Time(now));
        assert!(runtime.queued_count() <= 1);
    }
    assert_eq!(runtime.active_count(), 1);
    assert_eq!(source.0.borrow().captures, 12);
    assert_eq!(worker.0.borrow().started, vec![1]);
    finish(&worker, table());
    let events = runtime.tick(&Time(1200));
    assert!(events
        .iter()
        .any(|e| matches!(e, LiveEvent::Discarded { generation: 1, .. })));
    assert!(!events.iter().any(is_decision));
    assert_eq!(worker.0.borrow().started, vec![1, 3]);
    assert_eq!(runtime.queued_count(), 0);
    assert_eq!(runtime.active_count(), 1);
}

#[test]
fn stale_completion_cannot_cross_pid_or_hwnd_identity() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    source.0.borrow_mut().snapshot.windows[0].process_id = 99;
    runtime.tick(&Time(1000));
    finish(&worker, table());
    assert!(!runtime.tick(&Time(1100)).iter().any(is_decision));
    for now in [1200, 1300] {
        runtime.tick(&Time(now));
    }
    finish(&worker, table());
    assert!(
        !runtime.tick(&Time(1400)).iter().any(is_decision),
        "new window still needs its own consensus"
    );
}

#[test]
fn close_reopen_and_application_restart_clear_once_and_reconstruct_filters() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    activate(&mut runtime, &worker);
    let original = source.0.borrow().snapshot.clone();
    source.0.borrow_mut().snapshot = DiscoverySnapshot::default();
    let events = runtime.tick(&Time(1000));
    assert_eq!(clears(&events), 1);
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Status {
            state: "waiting_for_coin_poker",
            ..
        }
    )));
    assert_eq!(clears(&runtime.tick(&Time(2000))), 0);
    source.0.borrow_mut().snapshot = original;
    runtime.tick(&Time(3000));
    for now in [3100, 3200, 3300] {
        runtime.tick(&Time(now));
    }
    finish(&worker, table());
    runtime.tick(&Time(3400));
    runtime.tick(&Time(3500));
    finish(&worker, table());
    assert!(runtime.tick(&Time(3600)).iter().any(is_decision));
    assert!(source.0.borrow().filters >= 2);
}

#[test]
fn ambiguous_windows_and_permission_loss_invalidate_without_duplicate_clears() {
    for permission in [true, false] {
        let (mut runtime, source, worker) = rig(RuntimeConfig::default());
        activate(&mut runtime, &worker);
        if permission {
            let mut extra = source.0.borrow().snapshot.windows[0].clone();
            extra.hwnd = 8;
            source.0.borrow_mut().snapshot.windows.push(extra);
        } else {
            source.0.borrow_mut().permission = false;
        }
        let events = runtime.tick(&Time(1000));
        assert_eq!(clears(&events), 1);
        assert!(events.iter().any(|e| matches!(
            e,
            LiveEvent::Status {
                state: "ambiguous_multiple_tables" | "permission_required",
                ..
            }
        )));
        assert_eq!(clears(&runtime.tick(&Time(2000))), 0);
    }
}

#[test]
fn lobby_metadata_vetoes_repeated_hallucinated_table_states() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    source.0.borrow_mut().snapshot.windows[0].title = Some("Synthetic lobby".into());
    start(&mut runtime);
    finish(&worker, table());
    assert!(!runtime.tick(&Time(400)).iter().any(is_decision));
    runtime.tick(&Time(2400));
    finish(&worker, table());
    let events = runtime.tick(&Time(2500));
    assert!(!events.iter().any(is_decision));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Status {
            state: "lobby_detected",
            ..
        }
    )));
}

#[test]
fn over_age_response_and_periodic_refresh_are_fail_closed() {
    let (mut runtime, _, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 1_000,
        force_refresh_ms: 2_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    finish(&worker, table());
    let events = runtime.tick(&Time(1500));
    assert!(events
        .iter()
        .any(|e| matches!(e, LiveEvent::Discarded { .. })));
    assert!(!events.iter().any(is_decision));
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    activate(&mut runtime, &worker);
    let events = runtime.tick(&Time(5500));
    assert_eq!(clears(&events), 1);
    assert_eq!(
        runtime.active_count(),
        1,
        "periodic refresh analyzes even unchanged pixels"
    );
}

#[test]
fn expired_result_discards_without_classifying_the_stale_screen() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 5_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    finish(&worker, lobby());
    let events = runtime.tick(&Time(5_400));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            generation: 1,
            reason: "observation-expired"
        }
    )));
    assert!(
        !events.iter().any(|e| matches!(
            e,
            LiveEvent::Status {
                state: "lobby_detected",
                ..
            }
        )),
        "an expired result must not call the screen a lobby"
    );
    assert!(
        !events.iter().any(|e| matches!(e, LiveEvent::Table { .. })),
        "an expired result must not publish cards"
    );
}

#[test]
fn expired_result_must_not_poison_consensus_for_the_next_fresh_read() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 5_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    finish(&worker, table());
    let events = runtime.tick(&Time(5_400));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            reason: "observation-expired",
            ..
        }
    )));
    assert!(!events.iter().any(is_decision));
    assert_eq!(runtime.active_count(), 1);
    finish(&worker, table());
    let events = runtime.tick(&Time(5_500));
    assert!(
        !events.iter().any(is_decision),
        "one fresh observation must not pair with an expired observation"
    );
    runtime.tick(&Time(5_600));
    finish(&worker, table());
    let events = runtime.tick(&Time(5_700));
    assert!(events.iter().any(is_decision));
}

#[test]
fn expired_worker_failure_does_not_throttle_the_next_read() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 5_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    worker.0.borrow_mut().ready = Some(Err(InferenceFailure {
        code: "invalid-observation",
    }));
    let events = runtime.tick(&Time(5_400));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            generation: 1,
            reason: "observation-expired"
        }
    )));
    assert!(
        !events.iter().any(|e| matches!(
            e,
            LiveEvent::Status {
                state: "recovering",
                ..
            }
        )),
        "an expired failure must not be reported as a fresh worker error"
    );
    assert_eq!(
        runtime.active_count(),
        1,
        "an expired failure must not delay re-analysis by retry_ms"
    );
    assert_eq!(worker.0.borrow().started, vec![1, 2]);
}

#[test]
fn server_error_retries_are_bounded_and_do_not_create_new_workers() {
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    worker.0.borrow_mut().ready = Some(Err(InferenceFailure {
        code: "vlm-unavailable",
    }));
    let events = runtime.tick(&Time(400));
    assert!(!events.iter().any(is_decision));
    for now in [500, 1000, 1500, 2000, 2300] {
        runtime.tick(&Time(now));
    }
    assert_eq!(worker.0.borrow().started.len(), 1);
    runtime.tick(&Time(2400));
    assert_eq!(worker.0.borrow().started.len(), 2);
}

#[test]
fn transient_worker_send_failure_recovers_without_restart() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig::default());
    worker.0.borrow_mut().fail_start = Some(InferenceFailure {
        code: "inference-worker-busy",
    });
    let now = drive_until_active(&mut runtime, 0, 2_000);
    assert!(
        !worker.0.borrow().started.is_empty(),
        "transient backpressure must not permanently latch submission off"
    );
    assert!(
        worker.0.borrow().started.len() == 1,
        "only the retried generation may be submitted"
    );
    // Consume the recovered completion, then drive to the next active inference.
    finish(&worker, table());
    let now = drive_completion_consumed(&mut runtime, now, 3_000);
    let now = drive_until_active(&mut runtime, now, 3_000);
    finish(&worker, table());
    let mut now = now;
    let mut decided = false;
    while now <= 4_000 && !decided {
        decided = runtime.tick(&Time(now)).iter().any(is_decision);
        now += 100;
    }
    assert!(decided, "recovered worker must still publish a decision");
}

#[test]
fn disconnected_worker_stops_submission_permanently() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    assert_eq!(worker.0.borrow().started, vec![1]);
    worker.0.borrow_mut().disconnected = true;
    for step in 0..300 {
        let events = runtime.tick(&Time(400 + step * 100));
        assert!(
            !events.iter().any(is_decision),
            "a disconnected worker must never publish after disconnecting"
        );
    }
    assert_eq!(
        worker.0.borrow().started,
        vec![1],
        "submission must stop permanently once the worker disconnects"
    );
}

#[test]
fn publication_dropped_clears_lease_silently_then_reanalyzes() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig::default());
    activate(&mut runtime, &worker);
    let submitted_before = worker.0.borrow().started.len();
    runtime.publication_dropped();
    let events = runtime.tick(&Time(700));
    assert_eq!(
        clears(&events),
        0,
        "a silently dropped publication must not emit a clear"
    );
    let mut now = 800;
    while worker.0.borrow().started.len() == submitted_before && now <= 4_000 {
        runtime.tick(&Time(now));
        now += 100;
    }
    assert!(
        worker.0.borrow().started.len() > submitted_before,
        "analysis must resume after a silently dropped publication"
    );
}

#[test]
fn lease_expiry_emits_clear_exactly_once() {
    let (mut runtime, _source, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 5_000,
        ..RuntimeConfig::default()
    });
    activate(&mut runtime, &worker);
    let events = runtime.tick(&Time(5_500));
    assert_eq!(clears(&events), 1, "expiry must emit exactly one clear");
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Clear {
            reason: "recommendation-expired",
            ..
        }
    )));
    for now in [5_600, 5_700, 5_800] {
        assert_eq!(clears(&runtime.tick(&Time(now))), 0);
    }
}

#[test]
fn hwnd_pin_without_table_title_is_not_actionable() {
    let (mut runtime, _source, worker) = rig_with_discovery(
        DiscoveryConfig {
            exe_name: Some("test.synthetic".into()),
            window_hwnd: Some(7),
            table_title: None,
            lobby_title: None,
            ..DiscoveryConfig::default()
        },
        RuntimeConfig::default(),
    );
    assert!(
        !(0..6)
            .map(|step| runtime.tick(&Time(step * 100)))
            .any(|events| events.iter().any(is_decision)),
        "a pinned window with no table title is not an actionable table"
    );
    for now in 600..=1_000 {
        if now % 100 == 0 && runtime.active_count() == 1 {
            finish(&worker, table());
        }
    }
    let mut now = 1_100;
    let mut decided = false;
    while now <= 3_000 && !decided {
        decided = runtime.tick(&Time(now)).iter().any(is_decision);
        now += 100;
    }
    assert!(
        !decided,
        "repeated fresh table observations cannot bypass table-title calibration"
    );
}

#[test]
fn waiting_for_application_has_bounded_discovery_and_recovers_without_restart() {
    let (mut runtime, source, _) = rig(RuntimeConfig::default());
    let saved = source.0.borrow().snapshot.clone();
    source.0.borrow_mut().snapshot = DiscoverySnapshot::default();
    let events = runtime.tick(&Time(0));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Status {
            state: "waiting_for_coin_poker",
            ..
        }
    )));
    source.0.borrow_mut().snapshot = saved;
    runtime.tick(&Time(500));
    assert_eq!(source.0.borrow().captures, 0);
    runtime.tick(&Time(1000));
    assert_eq!(source.0.borrow().captures, 1);
}

/// Alternate one 16x16 tile between two values, like an animated seat avatar.
fn toggle_tile(source: &Source, step: u64) {
    let value = if step.is_multiple_of(2) { 64 } else { 200 };
    let mut state = source.0.borrow_mut();
    let width = state.frame.width as usize;
    for y in 48..64 {
        for x in 32..48 {
            let start = (y * width + x) * 4;
            state.frame.rgba[start..start + 4].copy_from_slice(&[value; 4]);
        }
    }
}

#[test]
fn persistently_animated_tile_does_not_starve_inference() {
    // Live finding 20261009T061624Z: seat avatars change every capture, so
    // every completion was discarded as obsolete. With the animated tile
    // suppressed, inference that takes several captures still completes fresh.
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    let latency_ms = 1_000;
    let mut decisions = 0;
    let mut discards = Vec::new();
    let mut now = 0;
    while now <= 8_000 {
        toggle_tile(&source, now / 100);
        let due = worker
            .0
            .borrow()
            .ticket
            .as_ref()
            .map(|ticket| ticket.captured_at_ms + latency_ms);
        if due.is_some_and(|due| now >= due) {
            finish(&worker, table());
        }
        for event in runtime.tick(&Time(now)) {
            match event {
                LiveEvent::Recommendation { .. } => decisions += 1,
                LiveEvent::Discarded { reason, .. } => discards.push(reason),
                _ => {}
            }
        }
        now += 100;
    }
    assert!(discards.is_empty(), "{discards:?}");
    assert!(
        decisions >= 1,
        "the animated seat tile must not block advice"
    );

    // A change outside the animated tile still invalidates in-flight work.
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    let mut now = 0;
    while runtime.active_count() == 0 && now <= 3_000 {
        toggle_tile(&source, now / 100);
        runtime.tick(&Time(now));
        now += 100;
    }
    assert_eq!(runtime.active_count(), 1);
    toggle_tile(&source, now / 100);
    change(&source, 255);
    runtime.tick(&Time(now));
    finish(&worker, table());
    let events = runtime.tick(&Time(now + 100));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            reason: "obsolete-observation",
            ..
        }
    )));
}

#[test]
fn admitted_unseated_observation_has_a_source_lease_and_no_placeholder_controls() {
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    let events = activate_observation(&mut runtime, &worker);
    let (ticket, value, valid_for_ms) = events
        .iter()
        .find_map(|event| match event {
            LiveEvent::Observation {
                ticket,
                value,
                valid_for_ms,
            } => Some((ticket, value, valid_for_ms)),
            _ => None,
        })
        .unwrap();
    assert_eq!(ticket.generation, 2);
    assert_eq!(ticket.captured_at_ms, 500);
    assert_eq!(*valid_for_ms, 4_900);
    assert_eq!(value.pot_size, Some(100));
    assert_eq!(value.to_call, None);
    assert_eq!(value.hero_chips, None);
    assert_eq!(value.available_actions, None);
    assert_eq!(value.role, ingest::runtime::ObservationRole::Uncertain);
    assert_eq!(
        value.hero_seated, None,
        "this generic worker has no seating evidence"
    );
    assert_eq!(value.action_required, None);
    assert_eq!(value.acting_seat, None);
    assert_eq!(value.acting_to_call, None);
    assert!(value.wagers.is_empty());
    assert_eq!(
        value.metrics,
        ingest::runtime::ObservationMetrics::default()
    );
    assert!(!value.quality_approved);
    assert_eq!(clears(&events), 0);
}

#[test]
fn observations_invalidate_on_change_target_loss_and_capture_loss_without_any_advice() {
    for cause in ["frame-changed", "window-changed", "capture-access-required"] {
        let (mut runtime, source, worker) = rig(RuntimeConfig::default());
        activate_observation(&mut runtime, &worker);
        let now = match cause {
            "frame-changed" => {
                change(&source, 255);
                700
            }
            "window-changed" => {
                source.0.borrow_mut().snapshot = DiscoverySnapshot::default();
                1_000
            }
            _ => {
                source.0.borrow_mut().permission = false;
                700
            }
        };
        let events = runtime.tick(&Time(now));
        assert!(events.iter().any(|event| matches!(event, LiveEvent::ObservationInvalidated { reason, .. } if *reason == cause)), "{cause}");
        assert_eq!(clears(&events), 0, "no recommendation was ever active");
        assert!(!events
            .iter()
            .any(|event| matches!(event, LiveEvent::Observation { .. })));
    }
}

#[test]
fn observation_expiry_invalidates_without_a_recommendation() {
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    activate_observation(&mut runtime, &worker);
    let events = runtime.tick(&Time(5_500));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated {
            reason: "observation-expired",
            ..
        }
    )));
    assert_eq!(clears(&events), 0);
    assert!(
        runtime.active_count() == 1,
        "expired controls require fresh re-analysis"
    );
}

#[test]
fn inference_error_invalidates_even_before_any_advice_or_observation() {
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    worker.0.borrow_mut().ready = Some(Err(InferenceFailure {
        code: "invalid-vlm-schema",
    }));
    let events = runtime.tick(&Time(400));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated {
            reason: "invalid-vlm-schema",
            ..
        }
    )));
    assert_eq!(clears(&events), 0);
}

#[test]
fn weak_card_agreement_does_not_publish_an_admitted_observation() {
    let (mut runtime, _, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    finish_without_advice(&worker, unseated());
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    let mut changed_pot = unseated();
    changed_pot.state.as_mut().unwrap().pot_size += 1;
    finish_without_advice(&worker, changed_pot);
    let events = runtime.tick(&Time(600));
    assert!(events
        .iter()
        .any(|event| matches!(event, LiveEvent::Table { .. })));
    assert!(!events
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
    assert!(events
        .iter()
        .any(|event| matches!(event, LiveEvent::ObservationInvalidated { .. })));
}

#[test]
fn obsolete_same_window_completion_cannot_seed_observation_consensus() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    change(&source, 255);
    runtime.tick(&Time(400));
    finish_without_advice(&worker, unseated());
    let events = runtime.tick(&Time(500));
    assert!(!events.iter().any(|event| matches!(
        event,
        LiveEvent::Observation { .. } | LiveEvent::Table { .. }
    )));
    runtime.tick(&Time(600));
    runtime.tick(&Time(700));
    finish_without_advice(&worker, unseated());
    let events = runtime.tick(&Time(800));
    assert!(
        !events.iter().any(|event| matches!(
            event,
            LiveEvent::Observation { .. } | LiveEvent::Table { .. }
        )),
        "first new-epoch read cannot pair with obsolete work"
    );
    runtime.tick(&Time(900));
    finish_without_advice(&worker, unseated());
    assert!(runtime
        .tick(&Time(1_000))
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
}

#[test]
fn over_age_unseated_result_emits_neither_controls_nor_table() {
    let (mut runtime, _, worker) = rig(RuntimeConfig {
        max_frame_age_ms: 1_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    finish_without_advice(&worker, unseated());
    let events = runtime.tick(&Time(1_300));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::Discarded {
            reason: "observation-expired",
            ..
        }
    )));
    assert!(!events.iter().any(|event| matches!(
        event,
        LiveEvent::Observation { .. } | LiveEvent::Table { .. }
    )));
}

#[test]
fn total_decision_deadline_discards_before_the_independent_eight_second_frame_age() {
    let (mut runtime, _, worker) = rig(RuntimeConfig {
        force_refresh_ms: 10_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    finish_without_advice(&worker, unseated());
    let events = runtime.tick(&Time(5_300));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::Discarded {
            reason: "decision-deadline-exceeded",
            ..
        }
    )));
    assert!(!events.iter().any(|event| matches!(
        event,
        LiveEvent::Observation { .. } | LiveEvent::Table { .. }
    )));
    finish_without_advice(&worker, unseated());
    assert!(!runtime
        .tick(&Time(5_400))
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
    runtime.tick(&Time(5_500));
    finish_without_advice(&worker, unseated());
    assert!(runtime
        .tick(&Time(5_600))
        .iter()
        .any(|event| matches!(event, LiveEvent::Observation { .. })));
}

#[test]
fn total_deadline_reports_without_releasing_or_restarting_a_blocked_worker() {
    let (mut runtime, _, worker) = rig(RuntimeConfig {
        decision_budget_ms: 1_000,
        force_refresh_ms: 10_000,
        ..RuntimeConfig::default()
    });
    start(&mut runtime);
    let events = runtime.tick(&Time(1_300));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated {
            reason: "decision-deadline-exceeded",
            ..
        }
    )));
    assert_eq!(runtime.active_count(), 1);
    assert_eq!(worker.0.borrow().started, vec![1]);
    let events = runtime.tick(&Time(1_400));
    assert!(!events.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated {
            reason: "decision-deadline-exceeded",
            ..
        }
    )));
    assert_eq!(worker.0.borrow().started, vec![1]);
}

#[test]
fn heartbeat_is_throttled_counts_fresh_frames_and_reports_loss_and_no_frames() {
    let (mut runtime, source, _) = rig(RuntimeConfig::default());
    let first = runtime.tick(&Time(0));
    assert!(first.iter().any(|event| matches!(
        event,
        LiveEvent::CaptureHealth {
            frame_count: 1,
            frame_width: Some(160),
            frame_height: Some(120),
            fresh_capture: true,
            ..
        }
    )));
    for now in [100, 200, 300, 400, 500, 600, 700, 800, 900] {
        assert!(!runtime
            .tick(&Time(now))
            .iter()
            .any(|event| matches!(event, LiveEvent::CaptureHealth { .. })));
    }
    let events = runtime.tick(&Time(1_000));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::CaptureHealth {
            frame_count: 11,
            captured_at_ms: Some(1_000),
            fresh_capture: true,
            ..
        }
    )));
    source.0.borrow_mut().permission = false;
    runtime.tick(&Time(1_100));
    let events = runtime.tick(&Time(2_000));
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::CaptureHealth {
            frame_count: 11,
            frame_width: None,
            frame_height: None,
            fresh_capture: false,
            identity: None,
            ..
        }
    )));

    let (mut runtime, source, _) = rig(RuntimeConfig::default());
    source.0.borrow_mut().snapshot = DiscoverySnapshot::default();
    for now in [0, 1_000, 2_000] {
        assert!(runtime.tick(&Time(now)).iter().any(|event| matches!(
            event,
            LiveEvent::CaptureHealth {
                frame_count: 0,
                fresh_capture: false,
                identity: None,
                ..
            }
        )));
    }
}
