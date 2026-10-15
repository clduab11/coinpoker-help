//! Deterministic runtime coverage with explicit clock, capture state, and inference completions.
use std::cell::RefCell;
use std::rc::Rc;

use ingest::capture::{CaptureError, CaptureSource, Frame, WindowInfo};
use ingest::discovery::{ApplicationInfo, DiscoveryConfig, DiscoverySnapshot};
use ingest::runtime::{
    Analysis, Clock, Completion, InferenceFailure, InferenceJob, InferencePort, LiveEvent,
    LiveRuntime, RuntimeConfig, Ticket, DECISION_DEADLINE_CODE,
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
    frame: Option<Frame>,
    ready: Option<Result<Analysis<&'static str>, InferenceFailure>>,
    started: Vec<u64>,
    probes: Vec<bool>,
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
        worker.probes.push(job.activity_probe);
        worker.ticket = Some(job.ticket);
        worker.frame = Some(job.frame);
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
        partial: None,
        diagnostics: None,
        recommendation: Some("check"),
    }));
}
fn finish_without_advice(worker: &Worker, observation: ScreenObservation) {
    worker.0.borrow_mut().ready = Some(Ok(Analysis {
        observation,
        partial: None,
        diagnostics: None,
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

fn partial_rig() -> (Runtime, Source, Worker) {
    let (runtime, source, worker) = rig(RuntimeConfig::default());
    let mut state = source.0.borrow_mut();
    state.snapshot.windows[0].width = 800;
    state.snapshot.windows[0].height = 613;
    state.frame = partial_source_frame();
    drop(state);
    (runtime, source, worker)
}

fn partial(pot: u32, changed_stack: Option<u32>) -> ingest::partial::PartialObservation {
    let mut value = partial_score_candidate(pot, changed_stack);
    value.bind_source_frame(&partial_source_frame()).unwrap();
    value
}

fn partial_source_frame() -> Frame {
    let mut pixels = vec![64; 800 * 613 * 4];
    pixels[0] = 255;
    Frame::new(800, 613, pixels).unwrap()
}

fn partial_score_candidate(
    pot: u32,
    changed_stack: Option<u32>,
) -> ingest::partial::PartialObservation {
    use ingest::laya::client::{Answer, PassAnswers, Segments};
    let (value, _, _) = ingest::laya::partial::assemble_partial(
        ingest::laya::question_set(),
        (800, 613),
        None,
        None,
        &mut |pass| {
            let mut result = PassAnswers {
                acceptance_floor: Some(if pass.id == "p0_full" {
                    0.995
                } else if pass.id == "p2_board" {
                    1.0
                } else {
                    0.8
                }),
                ..PassAnswers::default()
            };
            if pass.id == "p0_full" {
                for id in ["ev_table_layout", "ev_readable", "ev_board_area", "ev_pot"] {
                    result.answers.insert(
                        id.into(),
                        Answer {
                            choice: None,
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
                result.answers.insert(
                    "screen_kind".into(),
                    Answer {
                        choice: Some("poker_table".into()),
                        p: 1.0,
                        truncated: false,
                    },
                );
                // Role and phase intentionally unknown, no GameState/card gate.
            } else if pass.id != "p2_board" {
                let amount = if pass.id == "p3_pot" {
                    pot
                } else if pass.id == "p5_seat_1_stack" {
                    changed_stack.unwrap_or(10)
                } else {
                    10
                };
                let text = amount.to_string();
                result.segments = Some(Segments {
                    n: text.len() as u32,
                    overflow: false,
                });
                for (i, glyph) in text.chars().enumerate() {
                    result.answers.insert(
                        format!("g{}", i + 1),
                        Answer {
                            choice: Some(glyph.to_string()),
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
            }
            Ok(result)
        },
    )
    .unwrap();
    value.unwrap()
}

fn finish_partial(worker: &Worker, value: ingest::partial::PartialObservation) {
    let mut observation = unseated();
    observation.state = None;
    observation.evidence.readable = false; // Strict state failed, core partial remains independent.
    worker.0.borrow_mut().ready = Some(Ok(Analysis {
        observation,
        partial: Some(value),
        diagnostics: Some(ingest::partial::PerceptionDiagnostics::default()),
        recommendation: Some("must-not-publish"),
    }));
}

fn finish_experimental(
    worker: &Worker,
    wager: bool,
) -> ingest::laya::experimental::ExperimentalDiagnostics {
    use ingest::laya::experimental::{
        ExperimentalDescriptor, ExperimentalDiagnostics, ExperimentalProvenance,
    };
    use ingest::partial::{
        DiagnosticReason, EvidenceStatus, FieldEvidence, FieldName, PassDiagnostic,
        PerceptionDiagnostics, QuestionDiagnostic, SafeAnswer, SegmentDiagnostic,
    };
    let descriptor = if wager {
        ExperimentalDescriptor::wager(1)
    } else {
        ExperimentalDescriptor::scene(1)
    }
    .unwrap();
    let pass = descriptor.pass_descriptor().unwrap();
    let provenance: ExperimentalProvenance = serde_json::from_value(json!({
        "diagnostic_only":true,"training":"unvalidated","geometry_status":"DRAFT","human_review":"PENDING",
        "donor_pass":wager.then_some("p5_seat_1_stack"), "inherited_cutoff":wager.then_some(0.8)
    })).unwrap();
    let source = worker.0.borrow().frame.clone().unwrap();
    let proof = ExperimentalDiagnostics::bind(descriptor, provenance, &source, true).unwrap();
    let questions = pass
        .questions
        .iter()
        .map(|q| {
            let label = if wager {
                (q.id == "g1").then_some("7")
            } else if q.id == "badge" {
                Some("call")
            } else {
                q.criteria.as_ref().unwrap().as_array().unwrap()[0].as_str()
            };
            assert!(label.is_none_or(|label| q.has_option(label)));
            QuestionDiagnostic {
                question: q.id.clone(),
                answer: label.map(|label| SafeAnswer::Choice(label.into())),
                score: label.map(|_| 1.0),
                effective_floor: None,
                status: EvidenceStatus::Unknown,
                reason: if label.is_some() {
                    DiagnosticReason::UnapprovedCapability
                } else {
                    DiagnosticReason::MissingAnswer
                },
                truncated: false,
            }
        })
        .collect();
    let fields = if wager {
        vec![FieldName::VisibleWager]
    } else {
        ingest::laya::scene::SCENE_QUESTIONS
            .iter()
            .map(|(field, _, _, _)| *field)
            .collect()
    }
    .into_iter()
    .map(|field| FieldEvidence {
        field,
        seat: Some(1),
        board_slot: None,
        status: EvidenceStatus::Unknown,
        reason: DiagnosticReason::UnapprovedCapability,
        admission_status: EvidenceStatus::Unknown,
        admission_reason: DiagnosticReason::AwaitingConsensus,
    })
    .collect();
    let diagnostics = PerceptionDiagnostics {
        frame_width: source.width,
        frame_height: source.height,
        passes: vec![PassDiagnostic {
            pass: pass.id,
            crop_bounds: vec![proof.crop_bounds],
            crop_dimensions: vec![proof.crop_dimensions],
            questions,
            segments: wager.then_some(SegmentDiagnostic {
                n: 1,
                overflow: false,
            }),
            total_ms: None,
        }],
        fields,
        experimental: Some(proof.clone()),
        ..Default::default()
    };
    let observation = parse_screen_output(&VlmOutput {
        text: json!({"screen_kind":"poker_table",
        "evidence":{"table_layout":false,"hero_cards":false,"board_area":false,"pot":false,
            "action_controls":false,"readable":false},"state":null})
        .to_string(),
    })
    .unwrap();
    worker.0.borrow_mut().ready = Some(Ok(Analysis {
        observation,
        partial: None,
        diagnostics: Some(diagnostics),
        recommendation: Some("must-not-publish"),
    }));
    proof
}

#[test]
fn experimental_completions_do_not_clear_or_renew_independently_admitted_numeric_fields() {
    use ingest::partial::{DiagnosticAdmission, EvidenceStatus};
    let (mut runtime, _, worker) = partial_rig();
    runtime.enable_activity_probe();
    start(&mut runtime);
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    finish_partial(&worker, partial(10, None));
    let events = runtime.tick(&Time(600));
    let numeric_ticket =
        events
            .iter()
            .find_map(|event| match event {
                LiveEvent::PartialObservation {
                    ticket,
                    value,
                    valid_for_ms,
                } => {
                    assert_eq!(value.pot_size, Some(1000));
                    assert!(value
                        .seats
                        .iter()
                        .all(|seat| seat.displayed_stack == Some(1000)
                            && seat.visible_wager.is_none()));
                    assert!(!value.quality_approved);
                    assert_eq!(*valid_for_ms, ticket.captured_at_ms + 5_000 - 600);
                    Some(ticket.clone())
                }
                _ => None,
            })
            .unwrap();
    for (index, wager) in [true, false].into_iter().enumerate() {
        assert_eq!(runtime.active_count(), 1);
        let ticket = worker.0.borrow().ticket.clone().unwrap();
        assert!(ticket.generation > numeric_ticket.generation);
        assert_eq!(ticket.epoch, numeric_ticket.epoch);
        let proof = finish_experimental(&worker, wager);
        let now = 700 + index as u64 * 100;
        let events = runtime.tick(&Time(now));
        let (current, value, valid_for_ms) = events
            .iter()
            .find_map(|event| match event {
                LiveEvent::PerceptionDiagnostics {
                    ticket,
                    value,
                    valid_for_ms,
                } => Some((ticket, value, *valid_for_ms)),
                _ => None,
            })
            .unwrap();
        assert_eq!(current, &ticket);
        assert_eq!(value.experimental.as_ref(), Some(&proof));
        assert!(value.source_current && value.admission == DiagnosticAdmission::SourceCurrent);
        assert_eq!(valid_for_ms, ticket.captured_at_ms + 5_000 - now);
        assert!(value
            .fields
            .iter()
            .all(|field| field.status == EvidenceStatus::Unknown
                && field.admission_status != EvidenceStatus::Accepted));
        assert!(value
            .passes
            .iter()
            .flat_map(|pass| &pass.questions)
            .all(|q| q.effective_floor.is_none() && q.status == EvidenceStatus::Unknown));
        assert!(!events.iter().any(|event| matches!(
            event,
            LiveEvent::ObservationInvalidated { .. }
                | LiveEvent::PartialObservationInvalidated { .. }
                | LiveEvent::PartialObservation { .. }
                | LiveEvent::Observation { .. }
                | LiveEvent::Table { .. }
                | LiveEvent::Recommendation { .. }
        )));
        assert!(runtime.active_count() <= 1 && runtime.queued_count() <= 1);
    }
    let original_expiry = numeric_ticket.captured_at_ms + 5_000;
    let before_expiry = runtime.tick(&Time(original_expiry - 1));
    assert!(!before_expiry.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated { .. }
            | LiveEvent::PartialObservationInvalidated { .. }
            | LiveEvent::PartialObservation { .. }
    )));
    let expired = runtime.tick(&Time(original_expiry));
    assert!(expired.iter().any(|event| matches!(
        event,
        LiveEvent::PartialObservationInvalidated {
            reason: "observation-expired",
            fields: None,
            ..
        }
    )));
    assert!(!expired.iter().any(is_decision));
}

#[test]
fn experimental_candidates_reject_changed_roi_and_original_deadline_without_rebinding() {
    use ingest::partial::{DiagnosticAdmission, EvidenceStatus};
    for wager in [true, false] {
        for cause in ["none", "outside", "roi", "deadline"] {
            let (mut runtime, source, worker) = partial_rig();
            runtime.enable_activity_probe();
            start(&mut runtime);
            let ticket = worker.0.borrow().ticket.clone().unwrap();
            let original = worker.0.borrow().frame.clone().unwrap();
            let proof = finish_experimental(&worker, wager);
            assert!(proof.source_matches(&original));
            if cause == "roi" {
                let [x, y, _, _] = proof.crop_bounds;
                let mut source = source.0.borrow_mut();
                let offset = ((y * source.frame.width + x) * 4) as usize;
                source.frame.rgba[offset] += 1;
            } else if cause == "outside" {
                source.0.borrow_mut().frame.rgba[4] += 1;
            }
            let now = if cause == "deadline" {
                ticket.captured_at_ms + 5_000
            } else {
                400
            };
            let events = runtime.tick(&Time(now));
            let (returned, value, lease) = events
                .iter()
                .find_map(|event| match event {
                    LiveEvent::PerceptionDiagnostics {
                        ticket,
                        value,
                        valid_for_ms,
                    } => Some((ticket, value, *valid_for_ms)),
                    _ => None,
                })
                .unwrap();
            assert_eq!(returned, &ticket, "wager={wager}/{cause}");
            assert_eq!(value.experimental.as_ref(), Some(&proof));
            assert_eq!(value.source_current, matches!(cause, "none" | "outside"));
            assert_eq!(
                value.admission,
                match cause {
                    "roi" => DiagnosticAdmission::ObsoleteObservation,
                    "deadline" => DiagnosticAdmission::DecisionBudgetExpired,
                    _ => DiagnosticAdmission::SourceCurrent,
                }
            );
            assert_eq!(
                lease,
                if cause == "deadline" {
                    0
                } else {
                    ticket.captured_at_ms + 5_000 - now
                }
            );
            assert_eq!(
                proof.source_matches(&source.0.borrow().frame),
                cause != "roi"
            );
            assert!(
                proof.source_matches(&original),
                "comparison must not replace original source witness"
            );
            assert!(value
                .fields
                .iter()
                .all(|field| field.status == EvidenceStatus::Unknown
                    && field.admission_status != EvidenceStatus::Accepted));
            assert!(value
                .passes
                .iter()
                .flat_map(|pass| &pass.questions)
                .all(|q| q.effective_floor.is_none() && q.status == EvidenceStatus::Unknown));
            assert!(!events.iter().any(|event| matches!(
                event,
                LiveEvent::PartialObservation { .. }
                    | LiveEvent::Observation { .. }
                    | LiveEvent::Table { .. }
                    | LiveEvent::Recommendation { .. }
            )));
        }
    }
}

fn registered_wager_partial(wager: u32, candidate: &str) -> ingest::partial::PartialObservation {
    use ingest::laya::client::{Answer, PassAnswers, Segments};
    let registry: ingest::laya::wager::WagerPassRegistry = serde_json::from_value(json!({
        "version":1,"model_alias":"coinpoker-laya-vision","passes":(1..=6).map(|seat|
            json!({"seat":seat,"pass":format!("p6_seat_{seat}_wager"),
                "region":{"id":format!("seat_{seat}_wager"),"reference_dimensions":[800,613],"bounds":[seat*80,100,seat*80+60,130]},
                "fitted_floor":0.99,"trained_candidate":true,"held_out_approved":true,"human_verified":true,
                "candidate_sha256":if seat == 1 { candidate.repeat(64) } else { "1".repeat(64) },
                "model_sha256":"2".repeat(64),"capability_evidence_sha256":"3".repeat(64),
                "provenance":"observation-only-calibrated-pass"})).collect::<Vec<_>>()
    })).unwrap();
    let (partial, _, _) = ingest::laya::partial::assemble_partial_with_wagers(
        ingest::laya::question_set(),
        (800, 613),
        None,
        None,
        &registry,
        &mut |pass| {
            let mut answers = PassAnswers {
                acceptance_floor: Some(if pass.id == "p0_full" {
                    0.995
                } else if pass.id == "p2_board" {
                    1.0
                } else if pass.id.starts_with("p6_") {
                    0.99
                } else {
                    0.8
                }),
                ..PassAnswers::default()
            };
            if pass.id == "p0_full" {
                for id in ["ev_table_layout", "ev_readable", "ev_pot"] {
                    answers.answers.insert(
                        id.into(),
                        Answer {
                            choice: None,
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
                answers.answers.insert(
                    "screen_kind".into(),
                    Answer {
                        choice: Some("poker_table".into()),
                        p: 1.0,
                        truncated: false,
                    },
                );
            } else if pass.id != "p2_board" {
                let text = if pass.id == "p6_seat_1_wager" {
                    wager.to_string()
                } else if pass.id.starts_with("p6_") {
                    "7".into()
                } else {
                    "10".into()
                };
                answers.segments = Some(Segments {
                    n: text.len() as u32,
                    overflow: false,
                });
                for (i, glyph) in text.chars().enumerate() {
                    answers.answers.insert(
                        format!("g{}", i + 1),
                        Answer {
                            choice: Some(glyph.to_string()),
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
            }
            Ok(answers)
        },
    )
    .unwrap();
    let mut partial = partial.unwrap();
    partial.bind_source_frame(&partial_source_frame()).unwrap();
    partial
}

#[test]
fn registered_wagers_need_independent_current_consensus_and_exact_candidate_identity() {
    for change in ["none", "amount", "candidate"] {
        let (mut runtime, _, worker) = partial_rig();
        start(&mut runtime);
        finish_partial(&worker, registered_wager_partial(7, "1"));
        runtime.tick(&Time(400));
        runtime.tick(&Time(500));
        finish_partial(
            &worker,
            registered_wager_partial(
                if change == "amount" { 8 } else { 7 },
                if change == "candidate" { "4" } else { "1" },
            ),
        );
        let events = runtime.tick(&Time(600));
        let view = events
            .iter()
            .find_map(|e| match e {
                LiveEvent::PartialObservation {
                    value,
                    valid_for_ms: 4900,
                    ..
                } => Some(value),
                _ => None,
            })
            .unwrap();
        assert_eq!(
            view.seats[0].visible_wager,
            (change == "none").then_some(700)
        );
        assert_eq!(view.seats[1].visible_wager, Some(700));
        assert_eq!(view.seats[0].displayed_stack, Some(1000));
        assert!(view.seats.iter().all(|s| s.street_contribution.is_none()));
        assert!(!view.quality_approved && !events.iter().any(is_decision));
        assert!(view
            .verified_fields
            .contains(&ingest::partial::VerifiedField::Wager2));
        assert_eq!(
            view.verified_fields
                .contains(&ingest::partial::VerifiedField::Wager1),
            change == "none"
        );
    }
    for bad in ["identity", "deadline"] {
        let (mut runtime, _, worker) = partial_rig();
        start(&mut runtime);
        finish_partial(&worker, registered_wager_partial(7, "1"));
        if bad == "identity" {
            worker.0.borrow_mut().ticket.as_mut().unwrap().identity.hwnd += 1;
        }
        let events = runtime.tick(&Time(if bad == "deadline" { 5300 } else { 400 }));
        assert!(!events
            .iter()
            .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
        assert!(!events.iter().any(is_decision));
    }
}

#[test]
fn automatic_field_invalidation_targets_old_publication_not_new_current_completion() {
    let (mut runtime, source, worker) = partial_rig();
    runtime.enable_activity_probe();
    start(&mut runtime);
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    finish_partial(&worker, partial(10, None));
    let first = runtime.tick(&Time(600));
    let published = first
        .iter()
        .find_map(|event| match event {
            LiveEvent::PartialObservation { ticket, .. } => Some(ticket.clone()),
            _ => None,
        })
        .unwrap();
    runtime.finish_activity_probe();
    // An unpublished region changes, starting another job while the Pot/stack
    // publication stays valid. The full original frame must reach the worker.
    let (x, y, _, _) = ingest::laya::geometry::region_px("board_slot_1", 800, 613).unwrap();
    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] = 255;
    runtime.tick(&Time(700));
    let new_ticket = worker.0.borrow().ticket.clone().unwrap();
    assert!(new_ticket.generation > published.generation);
    assert_eq!(new_ticket.epoch, published.epoch);
    let mut answer = partial_score_candidate(10, None);
    answer
        .bind_source_frame(worker.0.borrow().frame.as_ref().unwrap())
        .unwrap();
    let (x, y, _, _) = ingest::laya::geometry::region_px("pot", 800, 613).unwrap();
    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] += 1;
    finish_partial(&worker, answer);
    let events = runtime.tick(&Time(800));
    assert!(events.iter().any(|event| matches!(event,
        LiveEvent::PartialObservationInvalidated { ticket, reason: "source-region-changed", fields: Some(fields) }
        if ticket == &published && fields == &[ingest::partial::VerifiedField::PotSize])));
    assert!(!events
        .iter()
        .any(|event| matches!(event, LiveEvent::ObservationInvalidated { .. })));
    let view = events
        .iter()
        .find_map(|event| match event {
            LiveEvent::PartialObservation {
                ticket,
                value,
                valid_for_ms,
            } => {
                assert_eq!(ticket, &new_ticket);
                assert_eq!(*valid_for_ms, new_ticket.captured_at_ms + 5000 - 800);
                Some(value)
            }
            _ => None,
        })
        .unwrap();
    assert!(view.pot_size.is_none());
    assert_eq!(view.seats[1].displayed_stack, Some(1000));
    assert!(!events.iter().any(is_decision));
    // Reversing pixels cannot restore the old, already-pruned Pot candidate.
    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] -= 1;
    let reverse = runtime.tick(&Time(900));
    assert!(!reverse
        .iter()
        .any(|event| matches!(event, LiveEvent::PartialObservation { .. })));
}

#[test]
fn field_invalidation_without_replacement_keeps_pot_on_original_lease() {
    use ingest::partial::VerifiedField;
    let (mut runtime, source, worker) = partial_rig();
    runtime.enable_activity_probe();
    start(&mut runtime);
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    finish_partial(&worker, partial(10, None));
    let first = runtime.tick(&Time(600));
    let published = first
        .iter()
        .find_map(|event| match event {
            LiveEvent::PartialObservation {
                ticket,
                value,
                valid_for_ms,
            } => {
                assert_eq!(value.pot_size, Some(1000));
                assert_eq!(value.role, None);
                assert_eq!(*valid_for_ms, ticket.captured_at_ms + 5000 - 600);
                Some(ticket.clone())
            }
            _ => None,
        })
        .unwrap();
    // No new completion: the current packet must survive independently of the worker.
    for (now, seat, field) in [
        (700, 1, VerifiedField::Stack1),
        (900, 2, VerifiedField::Stack2),
    ] {
        let (x, y, _, _) =
            ingest::laya::geometry::region_px(&format!("seat_{seat}_stack"), 800, 613).unwrap();
        let offset = (y * 800 + x) as usize * 4;
        source.0.borrow_mut().frame.rgba[offset] += 1;
        let events = runtime.tick(&Time(now));
        assert!(events.iter().any(|event| matches!(event,
            LiveEvent::PartialObservationInvalidated { ticket, fields: Some(fields), .. }
            if ticket == &published && fields == &[field])));
        assert!(!events.iter().any(|event| matches!(
            event,
            LiveEvent::PartialObservation { .. } | LiveEvent::ObservationInvalidated { .. }
        )));
        assert!(!events.iter().any(is_decision));
        // Restoring pixels cannot restore a pruned value or restart its lease.
        source.0.borrow_mut().frame.rgba[offset] -= 1;
        let reversed = runtime.tick(&Time(now + 100));
        assert!(!reversed.iter().any(|event| matches!(
            event,
            LiveEvent::PartialObservation { .. }
                | LiveEvent::PartialObservationInvalidated { .. }
                | LiveEvent::ObservationInvalidated { .. }
        )));
    }
    change(&source, 65); // Whole-frame role proof changes, but role was already unknown.
    assert!(!runtime.tick(&Time(1100)).iter().any(|event| matches!(
        event,
        LiveEvent::PartialObservation { .. }
            | LiveEvent::PartialObservationInvalidated { .. }
            | LiveEvent::ObservationInvalidated { .. }
    )));
    let expires = published.captured_at_ms + 5000;
    assert!(!runtime
        .tick(&Time(expires - 1))
        .iter()
        .any(|event| matches!(
            event,
            LiveEvent::PartialObservation { .. }
                | LiveEvent::PartialObservationInvalidated { .. }
                | LiveEvent::ObservationInvalidated { .. }
        )));
    assert!(runtime.tick(&Time(expires)).iter().any(|event| matches!(event,
        LiveEvent::PartialObservationInvalidated { ticket, reason: "observation-expired", fields: None }
        if ticket == &published)));
}

#[test]
fn field_invalidation_clears_confirmed_empty_board_and_role_not_unchanged_numbers() {
    use ingest::partial::VerifiedField;
    use ingest::runtime::ObservationRole;
    let (mut runtime, source, worker) = partial_rig();
    runtime.enable_activity_probe();
    start(&mut runtime);
    let mut empty_board = partial(10, None);
    empty_board.view.board_count = Some(0);
    empty_board.view.game_phase = Some(ingest::parser::GamePhase::Preflop);
    empty_board.view.role = Some(ObservationRole::Observing);
    empty_board.view.hero_seated = Some(false);
    finish_partial(&worker, empty_board.clone());
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    finish_partial(&worker, empty_board);
    let first = runtime.tick(&Time(600));
    let published = first
        .iter()
        .find_map(|event| match event {
            LiveEvent::PartialObservation { ticket, value, .. } => {
                assert_eq!(value.board_count, Some(0));
                assert!(value.board_slots.iter().all(Option::is_none));
                Some(ticket.clone())
            }
            _ => None,
        })
        .unwrap();
    let (x, y, _, _) = ingest::laya::geometry::region_px("board_slot_5", 800, 613).unwrap();
    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] += 1;
    let events = runtime.tick(&Time(700));
    assert!(events.iter().any(|event| matches!(event,
        LiveEvent::PartialObservationInvalidated { ticket, fields: Some(fields), .. }
        if ticket == &published && fields == &[VerifiedField::Role, VerifiedField::HeroSeated,
            VerifiedField::GamePhase, VerifiedField::BoardCount])));
    assert!(!events.iter().any(|event| matches!(
        event,
        LiveEvent::PartialObservation { .. } | LiveEvent::ObservationInvalidated { .. }
    )));
    // The remaining Pot is still watched against its original source.
    let (x, y, _, _) = ingest::laya::geometry::region_px("pot", 800, 613).unwrap();
    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] += 1;
    assert!(runtime.tick(&Time(800)).iter().any(|event| matches!(event,
        LiveEvent::PartialObservationInvalidated { ticket, fields: Some(fields), .. }
        if ticket == &published && fields == &[VerifiedField::PotSize])));
}

#[test]
fn field_invalidation_no_survivors_or_core_source_loss_still_clears_whole_packet() {
    for cause in ["no-survivors", "core", "capture"] {
        let (mut runtime, source, worker) = partial_rig();
        runtime.enable_activity_probe();
        start(&mut runtime);
        let mut pot_only = partial(10, None);
        for seat in &mut pot_only.view.seats {
            seat.displayed_stack = None;
        }
        finish_partial(&worker, pot_only.clone());
        runtime.tick(&Time(400));
        runtime.tick(&Time(500));
        finish_partial(&worker, pot_only);
        let first = runtime.tick(&Time(600));
        let published = first
            .iter()
            .find_map(|event| match event {
                LiveEvent::PartialObservation { ticket, value, .. } => {
                    assert_eq!(
                        value.verified_fields,
                        vec![ingest::partial::VerifiedField::PotSize]
                    );
                    Some(ticket.clone())
                }
                _ => None,
            })
            .unwrap();
        match cause {
            "no-survivors" => {
                let (x, y, _, _) = ingest::laya::geometry::region_px("pot", 800, 613).unwrap();
                source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] += 1;
            }
            "core" => finish(&worker, lobby()),
            _ => source.0.borrow_mut().permission = false,
        }
        let events = runtime.tick(&Time(700));
        if cause == "no-survivors" {
            assert!(events.iter().any(|event| matches!(event,
                LiveEvent::PartialObservationInvalidated { ticket, fields: None, .. } if ticket == &published)));
            source.0.borrow_mut().frame = partial_source_frame();
            assert!(!runtime.tick(&Time(800)).iter().any(|event| matches!(
                event,
                LiveEvent::PartialObservation { .. }
                    | LiveEvent::PartialObservationInvalidated { .. }
            )));
        } else {
            assert!(events
                .iter()
                .any(|event| matches!(event, LiveEvent::ObservationInvalidated { .. })));
        }
        assert!(!events
            .iter()
            .any(|event| matches!(event, LiveEvent::PartialObservation { .. })));
        assert!(!events.iter().any(is_decision));
    }
}

#[test]
fn published_partial_expiry_preserves_only_independently_fresh_source_current_seed() {
    use ingest::partial::VerifiedField;
    for cause in ["current", "stale-seed", "changed-roi"] {
        let (mut runtime, source, worker) = partial_rig();
        runtime.enable_activity_probe();
        start(&mut runtime);
        let mut pot_only = partial(10, None);
        for seat in &mut pot_only.view.seats {
            seat.displayed_stack = None;
        }
        finish_partial(&worker, pot_only.clone());
        runtime.tick(&Time(400));
        runtime.tick(&Time(500));
        finish_partial(&worker, pot_only.clone());
        let first = runtime.tick(&Time(600));
        let published = first
            .iter()
            .find_map(|event| match event {
                LiveEvent::PartialObservation { ticket, .. } => Some(ticket.clone()),
                _ => None,
            })
            .unwrap();
        let seed_ticket = worker.0.borrow().ticket.clone().unwrap();
        let mut board_only = pot_only;
        board_only.view.pot_size = None;
        board_only.view.board_count = Some(0);
        finish_partial(&worker, board_only.clone());
        assert!(!runtime
            .tick(&Time(4000))
            .iter()
            .any(|event| matches!(event, LiveEvent::PartialObservation { .. })));
        let current_ticket = worker.0.borrow().ticket.clone().unwrap();
        let expiry = runtime.tick(&Time(published.captured_at_ms + 5000));
        assert!(expiry.iter().any(|event| matches!(event,
            LiveEvent::PartialObservationInvalidated { ticket, reason: "observation-expired", fields: None }
            if ticket == &published)));
        assert!(!expiry
            .iter()
            .any(|event| matches!(event, LiveEvent::ObservationInvalidated { .. })));
        if cause == "changed-roi" {
            let (x, y, _, _) = ingest::laya::geometry::region_px("board_slot_1", 800, 613).unwrap();
            source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] += 1;
        }
        let now = seed_ticket.captured_at_ms + if cause == "stale-seed" { 5000 } else { 4900 };
        finish_partial(&worker, board_only);
        let events = runtime.tick(&Time(now));
        let admitted = events.iter().find_map(|event| match event {
            LiveEvent::PartialObservation {
                ticket,
                value,
                valid_for_ms,
            } => {
                assert_eq!(ticket, &current_ticket);
                assert_eq!(*valid_for_ms, ticket.captured_at_ms + 5000 - now);
                assert_eq!(value.verified_fields, vec![VerifiedField::BoardCount]);
                assert_eq!(value.board_count, Some(0));
                assert_eq!(value.pot_size, None);
                Some(())
            }
            _ => None,
        });
        assert_eq!(admitted.is_some(), cause == "current", "{cause}");
        assert!(!events.iter().any(is_decision));
    }
}

#[test]
fn automatic_observation_never_promotes_even_a_valid_full_state_or_recommendation() {
    let (mut runtime, _, worker) = partial_rig();
    runtime.enable_activity_probe();
    for now in (0..=4000).step_by(100) {
        if runtime.active_count() == 1 {
            finish(&worker, table());
        }
        let events = runtime.tick(&Time(now));
        assert!(!events.iter().any(|event| matches!(
            event,
            LiveEvent::Observation { .. }
                | LiveEvent::Recommendation { .. }
                | LiveEvent::Table { .. }
        )));
    }
}

#[test]
fn automatic_independent_stability_dispatches_unchanged_pot_despite_staggered_stack_motion() {
    for automatic in [false, true] {
        let (mut runtime, source, worker) = partial_rig();
        if automatic {
            runtime.enable_activity_probe();
        }
        let mut observed_pot = false;
        for now in (0..=2200_u64).step_by(100) {
            let seat = (now / 100) % 6 + 1;
            let (left, top, right, bottom) =
                ingest::laya::geometry::region_px(&format!("seat_{seat}_stack"), 800, 613).unwrap();
            let color = if (now / 600).is_multiple_of(2) {
                220
            } else {
                64
            };
            for y in top..bottom {
                for x in left..right {
                    source.0.borrow_mut().frame.rgba[(y * 800 + x) as usize * 4] = color;
                }
            }
            if runtime.active_count() == 1 {
                let mut answer = partial_score_candidate(10, None);
                answer
                    .bind_source_frame(worker.0.borrow().frame.as_ref().unwrap())
                    .unwrap();
                finish_partial(&worker, answer);
            }
            let events = runtime.tick(&Time(now));
            observed_pot |= events.iter().any(|event| {
                matches!(event,
                LiveEvent::PartialObservation { value, .. } if value.pot_size == Some(1000))
            });
            assert!(!events.iter().any(is_decision));
            assert!(runtime.active_count() <= 1 && runtime.queued_count() <= 1);
        }
        assert_eq!(
            observed_pot, automatic,
            "scoped stability must not change manual scheduling"
        );
    }
}

#[test]
fn source_region_witnesses_withhold_masked_amount_changes_without_erasing_other_fields() {
    use ingest::partial::{DiagnosticReason, EvidenceStatus, FieldName};
    for changed in [
        FieldName::PotSize,
        FieldName::DisplayedStack,
        FieldName::VisibleWager,
    ] {
        let (mut runtime, source, worker) = partial_rig();
        start(&mut runtime);
        finish_partial(&worker, registered_wager_partial(7, "1"));
        runtime.tick(&Time(400));
        runtime.tick(&Time(500));
        let ticket = worker.0.borrow().ticket.clone().unwrap();
        let bounds = match changed {
            FieldName::PotSize => ingest::laya::geometry::region_px("pot", 800, 613).unwrap(),
            FieldName::DisplayedStack => {
                ingest::laya::geometry::region_px("seat_1_stack", 800, 613).unwrap()
            }
            _ => (80, 100, 140, 130),
        };
        // A sub-delta pixel change remains globally stable, but exact ROI provenance changes.
        let offset = ((bounds.1 + 1) * 800 + bounds.0 + 1) as usize * 4;
        source.0.borrow_mut().frame.rgba[offset] += 1;
        finish_partial(&worker, registered_wager_partial(7, "1"));
        let events = runtime.tick(&Time(600));
        let (current, view) = events
            .iter()
            .find_map(|event| match event {
                LiveEvent::PartialObservation {
                    ticket,
                    value,
                    valid_for_ms: 4900,
                } => Some((ticket, value)),
                _ => None,
            })
            .unwrap();
        assert_eq!(
            current, &ticket,
            "whole source/generation/epoch must stay exact"
        );
        assert!(!events
            .iter()
            .any(|e| matches!(e, LiveEvent::Discarded { .. })));
        assert_eq!(
            view.pot_size,
            (changed != FieldName::PotSize).then_some(1000)
        );
        assert_eq!(
            view.seats[0].displayed_stack,
            (changed != FieldName::DisplayedStack).then_some(1000)
        );
        assert_eq!(
            view.seats[0].visible_wager,
            (changed != FieldName::VisibleWager).then_some(700)
        );
        assert!(view.seats[1..]
            .iter()
            .all(|s| s.displayed_stack == Some(1000) && s.visible_wager == Some(700)));
        assert!(events.iter().any(|event| matches!(event, LiveEvent::PerceptionDiagnostics { value, .. }
            if value.source_current && value.fields.iter().any(|f| f.field == changed
                && f.status == EvidenceStatus::Accepted && f.admission_status == EvidenceStatus::Rejected
                && f.admission_reason == DiagnosticReason::SourceRegionChanged))));
        assert!(!events.iter().any(is_decision));
        assert!(!view.quality_approved);
        assert!(runtime.tick(&Time(5500)).iter().any(|e| matches!(
            e,
            LiveEvent::ObservationInvalidated {
                reason: "observation-expired",
                ..
            }
        )));
    }
}

#[test]
fn score_only_candidates_without_source_witness_never_seed_or_publish_partial_consensus() {
    let (mut runtime, _, worker) = partial_rig();
    start(&mut runtime);
    for (finish, next) in [(400, 2400), (2500, 4500)] {
        finish_partial(&worker, partial_score_candidate(10, None));
        let events = runtime.tick(&Time(finish));
        assert!(!events
            .iter()
            .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
        assert!(events.iter().any(|e| matches!(e, LiveEvent::PerceptionDiagnostics { value, .. }
            if value.fields.iter().any(|f| f.admission_status == ingest::partial::EvidenceStatus::Rejected
                && f.admission_reason == ingest::partial::DiagnosticReason::MissingSourceWitness))));
        assert!(!events.iter().any(is_decision));
        runtime.tick(&Time(next));
    }
}

#[test]
fn time_spent_checking_source_witnesses_cannot_extend_or_cross_the_original_expiry() {
    struct AfterProof(std::cell::Cell<usize>);
    impl Clock for AfterProof {
        fn now_ms(&self) -> u64 {
            let calls = self.0.get();
            self.0.set(calls + 1);
            // For this already-selected tick the sixth clock read follows ROI verification.
            if calls >= 5 {
                5500
            } else {
                600
            }
        }
    }
    let (mut runtime, _, worker) = partial_rig();
    start(&mut runtime);
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    finish_partial(&worker, partial(10, None));
    let events = runtime.tick(&AfterProof(std::cell::Cell::new(0)));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            reason: DECISION_DEADLINE_CODE,
            ..
        }
    )));
    assert!(!events.iter().any(|e| matches!(
        e,
        LiveEvent::PartialObservation { .. } | LiveEvent::Observation { .. }
    )));
    assert!(events.iter().any(|e| matches!(e, LiveEvent::PerceptionDiagnostics { value, valid_for_ms: 0, .. }
        if !value.source_current && value.admission == ingest::partial::DiagnosticAdmission::DecisionBudgetExpired)));
    assert!(!events.iter().any(is_decision));
}

#[test]
fn known_negative_pixel_proof_vetoes_strict_sibling_and_advice_without_clearing_valid_partial_fields(
) {
    for changed in [false, true] {
        let (mut runtime, source, worker) = partial_rig();
        start(&mut runtime);
        for (finish_at, next) in [(400, 500), (600, 700)] {
            if changed && finish_at == 600 {
                let (a, b, _, _) = ingest::laya::geometry::region_px("pot", 800, 613).unwrap();
                source.0.borrow_mut().frame.rgba[(b * 800 + a) as usize * 4] += 1;
            }
            finish(&worker, table());
            {
                let mut state = worker.0.borrow_mut();
                let analysis = state.ready.as_mut().unwrap().as_mut().unwrap();
                analysis.partial = Some(partial(10, None));
                analysis.diagnostics = Some(ingest::partial::PerceptionDiagnostics::default());
            }
            let events = runtime.tick(&Time(finish_at));
            if finish_at == 600 {
                assert_eq!(
                    events
                        .iter()
                        .any(|e| matches!(e, LiveEvent::Observation { .. })),
                    !changed
                );
                assert_eq!(events.iter().any(is_decision), !changed);
                let view = events
                    .iter()
                    .find_map(|e| match e {
                        LiveEvent::PartialObservation { value, .. } => Some(value),
                        _ => None,
                    })
                    .unwrap();
                assert!(view.seats.iter().all(|s| s.displayed_stack == Some(1000)));
                assert_eq!(view.pot_size, (!changed).then_some(1000));
                assert!(!events.iter().any(|e| matches!(e, LiveEvent::ObservationInvalidated { .. })),
                    "negative strict-source proof must not clear independently current partial fields");
            }
            runtime.tick(&Time(next));
        }
    }
}

#[test]
fn partial_consensus_is_fieldwise_even_when_role_cards_and_strict_state_fail() {
    let (mut runtime, _, worker) = partial_rig();
    start(&mut runtime);
    finish_partial(&worker, partial(10, None));
    assert!(!runtime
        .tick(&Time(400))
        .iter()
        .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
    runtime.tick(&Time(500));
    finish_partial(&worker, partial(11, Some(12)));
    let events = runtime.tick(&Time(600));
    let (ticket, value, lease) = events
        .iter()
        .find_map(|e| match e {
            LiveEvent::PartialObservation {
                ticket,
                value,
                valid_for_ms,
            } => Some((ticket, value, valid_for_ms)),
            _ => None,
        })
        .unwrap();
    assert_eq!(ticket.captured_at_ms, 500);
    assert_eq!(*lease, 4900);
    assert_eq!(
        value.pot_size, None,
        "pot disagreement must not erase independent stacks"
    );
    assert_eq!(value.seats[0].displayed_stack, None);
    assert_eq!(value.seats[1].displayed_stack, Some(1000));
    assert!(value.role.is_none() && value.game_phase.is_none() && value.board_count.is_none());
    assert!(value.seats.iter().all(|seat| seat.visible_wager.is_none()));
    assert!(!value.quality_approved);
    assert!(!events.iter().any(is_decision));
    assert!(!events
        .iter()
        .any(|e| matches!(e, LiveEvent::Observation { .. })));
    for now in [700, 800, 900] {
        assert!(!runtime
            .tick(&Time(now))
            .iter()
            .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
    }
    assert!(runtime.tick(&Time(5500)).iter().any(|e| matches!(
        e,
        LiveEvent::ObservationInvalidated {
            reason: "observation-expired",
            ..
        }
    )));
}

#[test]
fn partial_obsolete_wrong_identity_out_of_order_and_deadline_results_cannot_seed_consensus() {
    for cause in [
        "frame",
        "identity",
        "generation",
        "epoch",
        "deadline",
        "worker-deadline",
    ] {
        let (mut runtime, source, worker) = partial_rig();
        start(&mut runtime);
        finish_partial(&worker, partial(10, None));
        match cause {
            "frame" => change(&source, 255),
            "identity" => worker.0.borrow_mut().ticket.as_mut().unwrap().identity.hwnd += 1,
            "generation" => worker.0.borrow_mut().ticket.as_mut().unwrap().generation -= 1,
            "epoch" => worker.0.borrow_mut().ticket.as_mut().unwrap().epoch += 1,
            "worker-deadline" => {
                worker
                    .0
                    .borrow_mut()
                    .ready
                    .as_mut()
                    .unwrap()
                    .as_mut()
                    .unwrap()
                    .diagnostics
                    .as_mut()
                    .unwrap()
                    .admission = ingest::partial::DiagnosticAdmission::DecisionBudgetExpired;
            }
            _ => {}
        }
        let now = if cause == "deadline" { 5300 } else { 400 };
        let events = runtime.tick(&Time(now));
        assert!(
            events
                .iter()
                .any(|e| matches!(e, LiveEvent::Discarded { .. })),
            "{cause}"
        );
        assert!(
            !events
                .iter()
                .any(|e| matches!(e, LiveEvent::PartialObservation { .. })),
            "{cause}"
        );
        assert!(
            events
                .iter()
                .any(|e| matches!(e, LiveEvent::PerceptionDiagnostics {
            value, valid_for_ms: 0, .. } if !value.source_current)),
            "{cause}"
        );
        assert!(!events.iter().any(is_decision));
    }
}

#[test]
fn partial_lobby_or_unidentified_metadata_and_wrong_kind_never_publish() {
    for cause in ["lobby", "metadata", "kind"] {
        let (mut runtime, source, worker) = partial_rig();
        if cause == "lobby" {
            source.0.borrow_mut().snapshot.windows[0].title = Some("Synthetic lobby".into());
        }
        if cause == "metadata" {
            runtime = LiveRuntime::new(
                source.clone(),
                worker.clone(),
                DiscoveryConfig {
                    exe_name: Some("test.synthetic".into()),
                    window_hwnd: Some(7),
                    table_title: None,
                    ..DiscoveryConfig::default()
                },
                RuntimeConfig::default(),
            )
            .unwrap();
        }
        start(&mut runtime);
        for now in [400, 2500] {
            finish_partial(&worker, partial(10, None));
            if cause == "kind" {
                worker
                    .0
                    .borrow_mut()
                    .ready
                    .as_mut()
                    .unwrap()
                    .as_mut()
                    .unwrap()
                    .observation = lobby();
            }
            let events = runtime.tick(&Time(now));
            assert!(!events
                .iter()
                .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
            assert!(!events.iter().any(is_decision));
            runtime.tick(&Time(now + 2000));
        }
    }
}

#[test]
fn metadata_suffix_change_keeps_identity_but_resize_invalidates_old_geometry_work() {
    let (mut runtime, source, worker) = partial_rig();
    start(&mut runtime);
    let first = worker.0.borrow().ticket.clone().unwrap();
    source.0.borrow_mut().snapshot.windows[0].title = Some("Synthetic table renamed".into());
    let events = runtime.tick(&Time(1000));
    assert!(!events.iter().any(|e| matches!(
        e,
        LiveEvent::ObservationInvalidated {
            reason: "window-changed",
            ..
        }
    )));
    assert_eq!(
        worker.0.borrow().ticket.as_ref().unwrap().epoch,
        first.epoch
    );
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(1100));
    runtime.tick(&Time(1200));
    let before_resize = worker.0.borrow().ticket.clone().unwrap();
    {
        let mut state = source.0.borrow_mut();
        state.snapshot.windows[0].width = 879;
        state.snapshot.windows[0].height = 670;
        let mut pixels = vec![64; 879 * 670 * 4];
        pixels[0] = 255;
        state.frame = Frame::new(879, 670, pixels).unwrap();
    }
    finish_partial(&worker, partial(10, None));
    let events = runtime.tick(&Time(2000));
    assert!(events.iter().any(|e| matches!(e, LiveEvent::ObservationInvalidated { reason: "geometry-changed", identity: Some(id), .. }
        if *id == before_resize.identity)));
    assert!(events.iter().any(|e| matches!(
        e,
        LiveEvent::Discarded {
            reason: "obsolete-observation",
            ..
        }
    )));
    assert!(!events
        .iter()
        .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
    assert!(!events.iter().any(|e| matches!(
        e,
        LiveEvent::ObservationInvalidated {
            reason: "window-changed",
            ..
        }
    )));
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
fn explicit_owner_stop_invalidates_all_and_never_rearms_or_consumes_late_results() {
    let (mut runtime, source, worker) = rig(RuntimeConfig::default());
    start(&mut runtime);
    assert_eq!(runtime.active_count(), 1);
    let captures = source.0.borrow().captures;
    let starts = worker.0.borrow().started.len();
    let events = runtime.stop("operator-stop");
    assert!(events.iter().any(|event| matches!(
        event,
        LiveEvent::ObservationInvalidated {
            reason: "operator-stop",
            ..
        }
    )));
    assert_eq!(runtime.queued_count(), 0);
    finish(&worker, table());
    for now in [500, 10_000, 600_000] {
        assert!(runtime.tick(&Time(now)).is_empty());
    }
    assert!(runtime.stop("operator-stop").is_empty());
    assert_eq!(source.0.borrow().captures, captures);
    assert_eq!(worker.0.borrow().started.len(), starts);
    assert!(
        worker.0.borrow().ready.is_some(),
        "stop cannot publish a late completion"
    );
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
fn jobs_carry_probe_state_only_until_activity_is_qualified() {
    let (mut runtime, _, worker) = partial_rig();
    runtime.enable_activity_probe();
    start(&mut runtime);
    assert_eq!(worker.0.borrow().probes, [true]);
    assert_eq!(
        worker.0.borrow().ticket.as_ref().unwrap().captured_at_ms,
        300
    );
    runtime.finish_activity_probe();
    finish_partial(&worker, partial(10, None));
    runtime.tick(&Time(400));
    runtime.tick(&Time(500));
    assert_eq!(worker.0.borrow().probes, [true, false]);
    assert_eq!(
        worker.0.borrow().ticket.as_ref().unwrap().captured_at_ms,
        400
    );

    let (mut manual, _, worker) = rig(RuntimeConfig::default());
    start(&mut manual);
    assert_eq!(worker.0.borrow().probes, [false]);
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
