use super::*;
use ingest::runtime::{Analysis, Completion, InferenceJob, Ticket};
use std::cell::{Cell, RefCell};
use std::fs;
use std::path::PathBuf;
use std::rc::Rc;

struct FailedResultPort {
    completion: Option<Completion<ui::widgets::DecisionView>>,
    disconnected: bool,
    started: usize,
}

impl InferencePort<ui::widgets::DecisionView> for FailedResultPort {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
        self.started += 1;
        self.completion = Some(Completion {
            ticket: job.ticket,
            result: Err(InferenceFailure {
                code: "synthetic-transient",
            }),
        });
        Ok(())
    }
    fn try_complete(
        &mut self,
    ) -> Result<Option<Completion<ui::widgets::DecisionView>>, InferenceFailure> {
        if self.disconnected {
            Err(InferenceFailure {
                code: "synthetic-worker-disconnected",
            })
        } else {
            Ok(self.completion.take())
        }
    }
}

fn recovery_job() -> InferenceJob {
    InferenceJob {
        ticket: Ticket {
            generation: 1,
            epoch: 1,
            captured_at_ms: 100,
            captured_at_unix_ms: Some(1_000),
            identity: ingest::discovery::TableIdentity {
                process_id: 123,
                hwnd: 456,
                exe_name: "synthetic.exe".into(),
            },
        },
        frame: Frame::new(2, 2, [0, 0, 0, 255].repeat(4)).unwrap(),
        activity_probe: false,
        deadline: Instant::now() + std::time::Duration::from_secs(1),
    }
}

#[test]
fn sustained_failed_result_is_returned_unchanged_without_killing_fresh_capture_work() {
    let failed = Rc::new(Cell::new(false));
    let mut worker = ManualWorker {
        inner: FailedResultPort {
            completion: None,
            disconnected: false,
            started: 0,
        },
        failed: failed.clone(),
        stop_on_result_error: false,
    };
    worker.start(recovery_job()).unwrap();
    let completion = worker.try_complete().unwrap().unwrap();
    assert_eq!(completion.ticket.captured_at_ms, 100);
    assert_eq!(completion.ticket.captured_at_unix_ms, Some(1_000));
    assert!(completion.result.is_err());
    assert!(!failed.get());
    worker.start(recovery_job()).unwrap();
    assert_eq!(worker.inner.started, 2);
}

#[test]
fn legacy_result_error_and_disconnected_worker_remain_terminal() {
    for (stop_on_result_error, disconnected) in [(true, false), (false, true)] {
        let failed = Rc::new(Cell::new(false));
        let mut worker = ManualWorker {
            inner: FailedResultPort {
                completion: None,
                disconnected,
                started: 0,
            },
            failed: failed.clone(),
            stop_on_result_error,
        };
        worker.start(recovery_job()).unwrap();
        let result: Result<Option<Completion<ui::widgets::DecisionView>>, InferenceFailure> =
            worker.try_complete();
        assert!(disconnected == result.is_err());
        assert!(failed.get());
        assert!(worker.start(recovery_job()).is_err());
    }
}

const SOURCE_UTC: u64 = 1_800_000_000_000;

fn temp_root() -> tempfile::TempDir {
    tempfile::Builder::new()
        .prefix("coinpoker-inference-test-")
        .tempdir()
        .unwrap()
}

#[test]
fn inference_temp_root_is_external_and_cleans_up_on_return_and_panic() {
    let checkout = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .canonicalize()
        .unwrap();
    for panic in [false, true] {
        let mut path = PathBuf::new();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let root = temp_root();
            path = root.path().canonicalize().unwrap();
            assert!(!path.starts_with(&checkout));
            assert!(path.starts_with(std::env::temp_dir().canonicalize().unwrap()));
            fs::write(path.join("synthetic.txt"), b"test").unwrap();
            assert_eq!(fs::read(path.join("synthetic.txt")).unwrap(), b"test");
            if panic {
                panic!("synthetic fixture failure");
            }
        }));
        assert_eq!(result.is_err(), panic);
        assert!(!path.exists());
    }
}

#[test]
fn inference_temp_roots_are_unique_and_independently_owned_in_parallel() {
    let threads: Vec<_> = (0..4).map(|_| std::thread::spawn(temp_root)).collect();
    let roots: Vec<_> = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect();
    let paths: std::collections::HashSet<_> =
        roots.iter().map(|root| root.path().to_path_buf()).collect();
    assert_eq!(paths.len(), roots.len());
    let mut roots = roots.into_iter();
    let first = roots.next().unwrap();
    let first_path = first.path().to_path_buf();
    drop(first);
    assert!(!first_path.exists());
    assert!(roots.all(|root| root.path().is_dir()));
    assert!(paths.iter().all(|path| !path.exists()));
}

#[test]
fn automatic_poll_period_includes_capture_and_publication_work_without_catch_up() {
    for (elapsed, expected) in [(0, 500), (150, 350), (499, 1), (500, 0), (1500, 0)] {
        for policy in [
            SourcePolicy::AutomaticBounded,
            SourcePolicy::AutomaticSustained,
        ] {
            assert_eq!(poll_delay(policy, 500, 100, 100 + elapsed), expected);
        }
        assert_eq!(
            poll_delay(SourcePolicy::Manual, 500, 100, 100 + elapsed),
            500
        );
    }
}

#[test]
fn automatic_pass_schedule_has_separate_repeated_lanes_and_never_batches() {
    for experimental in [false, true] {
        let mut step = 0;
        for _ in 0..2 {
            for _ in 0..3 {
                assert_eq!(
                    next_automatic_pass(&mut step, experimental),
                    ObservationPass::Pot
                );
            }
            for seat in 1..=6 {
                let lanes = if experimental {
                    vec![
                        ObservationPass::Stack(seat),
                        ObservationPass::Wager(seat),
                        ObservationPass::Scene(seat),
                    ]
                } else {
                    vec![ObservationPass::Stack(seat)]
                };
                for lane in lanes {
                    for _ in 0..3 {
                        assert_eq!(next_automatic_pass(&mut step, experimental), lane);
                    }
                }
            }
            for _ in 0..3 {
                assert_eq!(
                    next_automatic_pass(&mut step, experimental),
                    ObservationPass::Board
                );
            }
            assert_eq!(step, 0);
        }
    }
}

#[test]
fn sustained_readout_schedule_repeats_each_seat_pair_and_bounds_board_pair() {
    let mut schedule = AutomaticSchedule::default();
    for _ in 0..2 {
        for seat in [1, 3, 5] {
            for _ in 0..2 {
                assert_eq!(
                    schedule.next(SourcePolicy::AutomaticSustained, false),
                    ObservationPass::ReadoutPair(seat)
                );
            }
        }
        for _ in 0..2 {
            assert_eq!(
                schedule.next(SourcePolicy::AutomaticSustained, false),
                ObservationPass::BoardReadout
            );
        }
        assert_eq!(schedule.step, 0);
    }
}

#[test]
fn sustained_cpu_board_schedule_keeps_six_distinct_numeric_jobs_and_no_gpu_board() {
    let mut schedule = AutomaticSchedule::new(true);
    let mut attempts = [Vec::new(), Vec::new(), Vec::new()];
    for cycle in 0..3 {
        for step in 0..6 {
            let seat = (step / 2) * 2 + 1;
            assert_eq!(
                schedule.next(SourcePolicy::AutomaticSustained, false),
                ObservationPass::ReadoutPair(seat)
            );
            attempts[(seat / 2) as usize].push(cycle * 6 + step);
        }
        assert_eq!(schedule.step, 0);
    }
    for pair in attempts {
        assert_eq!(pair.len(), 6);
        assert_eq!(pair.windows(2).map(|p| p[1] - p[0]).max(), Some(5));
    }
}

#[test]
fn cpu_board_readiness_cannot_change_manual_bounded_or_experimental_schedules() {
    for policy in [SourcePolicy::Manual, SourcePolicy::AutomaticBounded] {
        for experimental in [false, true] {
            let mut original = AutomaticSchedule::default();
            let mut cpu_board = AutomaticSchedule::new(true);
            for _ in 0..120 {
                assert_eq!(
                    cpu_board.next(policy, experimental),
                    original.next(policy, experimental)
                );
            }
        }
    }
    let mut original = AutomaticSchedule::default();
    let mut cpu_board = AutomaticSchedule::new(true);
    for _ in 0..24 {
        assert_eq!(
            cpu_board.next(SourcePolicy::AutomaticSustained, true),
            original.next(SourcePolicy::AutomaticSustained, true)
        );
    }
}

#[test]
fn experimental_opt_in_requires_exact_bool_bounded_automatic_and_service() {
    let mut value = approval_json();
    value.as_object_mut().unwrap().remove("operator_assertion");
    value["source_policy"] = json!("automatic-bounded");
    value["automatic_assertion"] = json!("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION");
    let default: Approval = serde_json::from_value(value.clone()).unwrap();
    assert!(!default.experimental_bet_action);
    assert!(validate_experimental_opt_in(&default, false).is_ok());
    assert!(validate_experimental_opt_in(&default, true).is_err());
    value["experimental_bet_action"] = json!(true);
    let valid: Approval = serde_json::from_value(value.clone()).unwrap();
    assert!(validate_experimental_opt_in(&valid, true).is_ok());
    assert!(validate_experimental_opt_in(&valid, false).is_err());
    for (key, bad) in [
        ("mode", json!("capture-only")),
        ("source_policy", json!("manual")),
        ("source_policy", json!("automatic-sustained")),
        ("service_instance_id", Value::Null),
        ("service_instance_id", json!("A".repeat(32))),
        ("max_frames", json!(0)),
        ("max_frames", json!(1_201)),
        ("max_seconds", json!(0)),
        ("max_seconds", json!(601)),
    ] {
        let mut bad_value = value.clone();
        bad_value[key] = bad;
        let bad: Approval = serde_json::from_value(bad_value).unwrap();
        assert!(validate_experimental_opt_in(&bad, true).is_err(), "{key}");
    }
    for bad in [json!(1), json!("true"), Value::Null] {
        value["experimental_bet_action"] = bad;
        assert!(serde_json::from_value::<Approval>(value.clone()).is_err());
    }
}

#[test]
fn experimental_diagnostics_cannot_create_actions_admission_or_historical_ledger_entries() {
    use ingest::laya::experimental::{
        ExperimentalDescriptor, ExperimentalDiagnostics, ExperimentalProvenance,
    };
    use ingest::partial::{DiagnosticAdmission, PerceptionDiagnostics};
    let frame = Frame::new(900, 686, vec![64; 900 * 686 * 4]).unwrap();
    let descriptor = ExperimentalDescriptor::scene(1).unwrap();
    let provenance: ExperimentalProvenance = serde_json::from_value(json!({
        "diagnostic_only":true,"training":"unvalidated","geometry_status":"DRAFT", "human_review":"PENDING",
        "donor_pass":null,"inherited_cutoff":null
    })).unwrap();
    let diagnostics = PerceptionDiagnostics {
        experimental: Some(
            ExperimentalDiagnostics::bind(descriptor, provenance, &frame, true).unwrap(),
        ),
        frame_width: 900,
        frame_height: 686,
        source_current: true,
        admission: DiagnosticAdmission::SourceCurrent,
        ..Default::default()
    };
    let analysis = crate::live::finish_laya_analysis(
        ingest::laya::LayaAnalysis {
            output: ingest::vlm::VlmOutput {
                text: json!({"screen_kind":"poker_table",
            "evidence":{"table_layout":false,"hero_cards":false,"board_area":false,"pot":false,
                "action_controls":false,"readable":false},"state":null})
                .to_string(),
            },
            partial: None,
            diagnostics,
        },
        Some(&crate::Pipeline::new()),
        Instant::now() + Duration::from_secs(5),
    )
    .unwrap();
    assert!(
        analysis.partial.is_none()
            && analysis.observation.state.is_none()
            && analysis.recommendation.is_none()
    );
    let ticket = Ticket {
        identity: approval().source.identity(),
        generation: 4,
        epoch: 3,
        captured_at_ms: 100,
        captured_at_unix_ms: Some(SOURCE_UTC + 100),
    };
    let config = RuntimeConfig::default();
    let record = crate::live::event_record(
        LiveEvent::PerceptionDiagnostics {
            ticket: ticket.clone(),
            value: analysis.diagnostics.unwrap(),
            valid_for_ms: 4_000,
        },
        1_100,
        SOURCE_UTC + 1_100,
        &config,
        Default::default(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(record["event"], "perception_diagnostics");
    assert_eq!(record["captured_at_unix_ms"], SOURCE_UTC + 100);
    assert_eq!(record["expires_at_unix_ms"], SOURCE_UTC + 5_100);
    assert_eq!(record["experimental"]["inherited_cutoff"], Value::Null);
    let mut history = crate::live::AdmittedHistory::new().unwrap();
    let clock = Time::default();
    clock.0.set(1_100);
    let mut events = Vec::new();
    crate::live::emit_with_history(
        &record,
        Some(&ticket),
        None,
        &mut history,
        &clock,
        &config,
        &mut |event: &Value| {
            events.push(event.clone());
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(events, [record]);
    assert!(events.iter().all(|event| !matches!(
        event["event"].as_str(),
        Some("history" | "observation" | "partial_observation" | "table" | "decision")
    )));
}

#[derive(Default)]
struct Time(Cell<u64>);
impl Clock for Time {
    fn now_ms(&self) -> u64 {
        self.0.get()
    }
}

struct SourceState {
    window: WindowInfo,
    captures: usize,
    case: &'static str,
    reset: usize,
}
struct Source {
    state: Rc<RefCell<SourceState>>,
    time: Rc<Time>,
    stop: PathBuf,
}
impl CaptureSource for Source {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        let state = self.state.borrow();
        if state.case == "discovery-failure" && state.captures > 0 {
            return Err(CaptureError::PermissionDenied);
        }
        Ok(DiscoverySnapshot {
            windows: if state.case == "ambiguous" {
                vec![state.window.clone(), state.window.clone()]
            } else if state.case == "closed" {
                vec![]
            } else {
                vec![state.window.clone()]
            },
            ..Default::default()
        })
    }
    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError> {
        assert_eq!(window, &self.state.borrow().window);
        if self.state.borrow().case == "auto-slow-selection" && self.state.borrow().captures == 0 {
            self.time.0.set(self.time.now_ms() + 1200);
        }
        Ok(())
    }
    fn capture(&mut self) -> Result<Frame, CaptureError> {
        let mut state = self.state.borrow_mut();
        state.captures += 1;
        match state.case {
            "replacement" => state.window.hwnd += 1,
            "pid" => state.window.process_id += 1,
            "title" => state.window.title = Some("replacement".into()),
            "minimized" => state.window.on_screen = false,
            "capture-failure" => return Err(CaptureError::PermissionDenied),
            "capture-overlap" => return Err(CaptureError::Backend("selected window surface is obscured or ambiguous: cause=foreign-overlap offender=(hwnd=0x1) reference=(hwnd=0x2)".into())),
            "capture-overlap-inflight" if state.captures == 4 => return Err(CaptureError::Backend("selected window surface is obscured or ambiguous: cause=popup-overlap offender=(hwnd=0x1) reference=(hwnd=0x2)".into())),
            "capture-backend" => return Err(CaptureError::Backend("unrecognized backend\nprivate".into())),
            "stop-during-capture" => fs::write(&self.stop, "synthetic stop").unwrap(),
            "duration-during-capture" => self.time.0.set(600_000),
            "slow-capture" | "auto-slow-selection" => self.time.0.set(self.time.now_ms() + 200),
            "stale-resize" if state.captures == 1 => {
                state.window.width = 900;
                return Err(CaptureError::StaleWindow {
                    hwnd: state.window.hwnd,
                });
            }
            _ => {}
        }
        let mut rgba =
            [64, 64, 64, 255].repeat((state.window.width * state.window.height) as usize);
        rgba[0] = 255;
        if state.case == "sustained-provenance" {
            rgba[1] = (state.captures % 251) as u8;
        }
        if (matches!(state.case, "auto-active" | "auto-ambiguous")
            || state.case.starts_with("auto-partial") && state.case != "auto-partial-idle")
            && self.time.now_ms() >= 3_000
            || state.case == "auto-transient" && self.time.now_ms() == 3_000
        {
            let (left, top, right, bottom) =
                ingest::laya::geometry::region_px("pot", state.window.width, state.window.height)
                    .unwrap();
            for y in top..bottom {
                for x in left..right {
                    rgba[((y * state.window.width + x) * 4) as usize] = 180;
                }
            }
        }
        if state.case == "auto-outside" && self.time.now_ms() >= 3_000 {
            rgba[0] = 120;
        }
        if state.case == "auto-partial-cosmetic" {
            // Timer churn is not model input substitution; the recorder/worker
            // assertions below still compare every original byte.
            for y in 40..64 {
                for x in 32..160 {
                    rgba[((y * state.window.width + x) * 4) as usize] =
                        if (self.time.now_ms() / 500).is_multiple_of(2) {
                            32
                        } else {
                            220
                        };
                }
            }
            let (x, y, _, _) = ingest::laya::geometry::region_px(
                "seat_1_stack",
                state.window.width,
                state.window.height,
            )
            .unwrap();
            rgba[((y * state.window.width + x) * 4) as usize] =
                if (self.time.now_ms() / 500).is_multiple_of(2) {
                    64
                } else {
                    65
                };
        }
        if state.case == "invalid-frame" {
            rgba.clear();
        }
        Ok(Frame {
            width: state.window.width,
            height: state.window.height,
            rgba,
            ..Frame::default()
        })
    }
    fn reset(&mut self) {
        self.state.borrow_mut().reset += 1;
    }
}

#[derive(Default)]
struct WorkerState {
    job: Option<InferenceJob>,
    job_ms: u64,
    starts: Vec<Ticket>,
    pass_step: u8,
    interrupted: bool,
    sustained_schedule: AutomaticSchedule,
    passes: Vec<(Ticket, ObservationPass)>,
    unsaved_starts: usize,
    recommendations: Vec<(Ticket, ui::widgets::DecisionView)>,
}
struct Worker {
    state: Rc<RefCell<WorkerState>>,
    time: Rc<Time>,
    root: PathBuf,
    case: &'static str,
}

fn session(root: &Path) -> PathBuf {
    fs::read_dir(root.join(".local/captures"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path()
}
fn rows(root: &Path) -> Vec<Value> {
    fs::read_to_string(session(root).join("manifest.jsonl"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

impl InferencePort<ui::widgets::DecisionView> for Worker {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
        let mut state = self.state.borrow_mut();
        assert!(state.job.is_none(), "one active worker only");
        // This assertion executes at submission, before any simulated analysis.
        let receipts = rows(&self.root);
        assert_eq!(
            job.ticket.captured_at_unix_ms,
            Some(SOURCE_UTC + job.ticket.captured_at_ms)
        );
        let row = receipts
            .iter()
            .find(|row| row["captured_at_monotonic_ms"] == job.ticket.captured_at_ms);
        if let Some(row) = row {
            assert_eq!(
                row["source_utc_unix_ms"].as_u64(),
                job.ticket.captured_at_unix_ms
            );
            assert_eq!(row["timestamp_basis"], "capture_call_start");
            let image = image::open(session(&self.root).join(format!(
                "frame-{:010}.png",
                row["frame_index"].as_u64().unwrap()
            )))
            .unwrap()
            .to_rgba8();
            assert_eq!(image.as_raw(), &job.frame.rgba);
            assert_eq!(
                (image.width(), image.height()),
                (job.frame.width, job.frame.height)
            );
        } else {
            assert!(
                self.case.starts_with("sustained-"),
                "only sustained may infer unsaved pixels"
            );
            assert!(
                job.ticket.captured_at_ms
                    > receipts.last().unwrap()["captured_at_monotonic_ms"]
                        .as_u64()
                        .unwrap()
            );
            state.unsaved_starts += 1;
        }
        state.starts.push(job.ticket.clone());
        state.job = Some(job);
        Ok(())
    }
    fn try_complete(
        &mut self,
    ) -> Result<Option<Completion<ui::widgets::DecisionView>>, InferenceFailure> {
        if self.case == "slow-worker"
            || self.case == "capture-overlap-inflight" && self.time.now_ms() < 1500
            || self.case == "late-worker" && self.time.now_ms() < 6_000
            || self.state.borrow().job.as_ref().is_some_and(|job| {
                self.time.now_ms() < job.ticket.captured_at_ms + self.state.borrow().job_ms
            })
        {
            return Ok(None);
        }
        let Some(job) = self.state.borrow_mut().job.take() else {
            return Ok(None);
        };
        let scheduled = if self.case.starts_with("auto-partial") {
            Some(next_automatic_pass(
                &mut self.state.borrow_mut().pass_step,
                false,
            ))
        } else if self.case.starts_with("sustained-") {
            Some(
                self.state
                    .borrow_mut()
                    .sustained_schedule
                    .next(SourcePolicy::AutomaticSustained, false),
            )
        } else {
            None
        };
        if let Some(pass) = scheduled {
            self.state
                .borrow_mut()
                .passes
                .push((job.ticket.clone(), pass));
        }
        let mut ticket = job.ticket.clone();
        if self.case == "decision-wrong-source" {
            ticket.identity.hwnd += 1;
        } else if self.case == "decision-obsolete" {
            ticket.epoch += 1;
        }
        let result = if matches!(self.case, "worker-failure" | "obsolete-worker-failure") {
            Err(InferenceFailure {
                code: "vlm-unavailable",
            })
        } else if self.case.starts_with("decision-") {
            // Use an existing synthetic full-state fixture, not invented
            // partial-to-GameState fields or a canned recommendation.
            let manifest: Value =
                serde_json::from_str(include_str!("../fixtures/synthetic/manifest.json")).unwrap();
            let mut response = manifest["cases"]
                .as_array()
                .unwrap()
                .iter()
                .find(|case| case["id"] == "preflop-hero2")
                .unwrap()["response"]
                .clone();
            if self.case == "decision-untrusted" {
                response["evidence"]["action_controls"] = json!(false);
            }
            crate::live::finish_laya_analysis(
                ingest::laya::LayaAnalysis {
                    output: ingest::vlm::VlmOutput {
                        text: response.to_string(),
                    },
                    partial: None,
                    diagnostics: Default::default(),
                },
                Some(&Pipeline::new()),
                job.deadline,
            )
        } else {
            let variant = if self.case == "auto-ambiguous" && job.ticket.generation % 2 == 0 {
                "auto-lobby"
            } else if self.case == "auto-jitter" && job.ticket.generation % 2 == 1 {
                "auto-jitter-odd"
            } else {
                self.case
            };
            let mut analysis = synthetic_analysis(&job.frame, job.deadline, variant, scheduled);
            if matches!(
                scheduled,
                Some(ObservationPass::Pot | ObservationPass::Stack(_))
            ) && !self.state.borrow().interrupted
                && (self.case != "auto-partial-middle" || self.state.borrow().pass_step == 2)
            {
                self.state.borrow_mut().interrupted = true;
                if matches!(self.case, "auto-partial-obsolete" | "auto-partial-middle") {
                    ticket.epoch += 1;
                } else if self.case == "auto-partial-late" {
                    analysis.diagnostics.as_mut().unwrap().admission =
                        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired;
                    analysis.partial = None;
                }
            }
            Ok(analysis)
        };
        if let Ok(analysis) = &result {
            if let Some(view) = &analysis.recommendation {
                self.state
                    .borrow_mut()
                    .recommendations
                    .push((ticket.clone(), view.clone()));
            }
        }
        Ok(Some(Completion { ticket, result }))
    }
}

fn synthetic_analysis(
    frame: &Frame,
    deadline: Instant,
    variant: &str,
    selected: Option<ObservationPass>,
) -> Analysis<ui::widgets::DecisionView> {
    use ingest::laya::client::{Answer, PassAnswers, Segments};
    let (mut partial, diagnostics, cache) = ingest::laya::partial::assemble_partial(
        ingest::laya::question_set(),
        (frame.width, frame.height),
        None,
        None,
        &mut |pass| {
            assert!(!pass.id.starts_with("p6_") && !pass.id.starts_with("p7_"));
            let requested = match selected {
                None => true,
                Some(ObservationPass::Table) => pass.id == "p0_full",
                Some(ObservationPass::Pot) => pass.id == "p0_full" || pass.id == "p3_pot",
                Some(ObservationPass::Board | ObservationPass::BoardReadout) => {
                    pass.id == "p0_full" || pass.id == "p2_board"
                }
                Some(ObservationPass::Stack(seat)) => {
                    pass.id == "p0_full" || pass.id == format!("p5_seat_{seat}_stack")
                }
                Some(ObservationPass::Numbers(seat)) => {
                    pass.id == "p0_full"
                        || pass.id == "p3_pot"
                        || pass.id == format!("p5_seat_{seat}_stack")
                }
                Some(ObservationPass::ReadoutPair(seat)) => {
                    pass.id == "p0_full"
                        || pass.id == "p3_pot"
                        || pass.id == format!("p5_seat_{seat}_stack")
                        || pass.id == format!("p5_seat_{}_stack", seat + 1)
                }
                Some(ObservationPass::Wager(_) | ObservationPass::Scene(_)) => false,
            };
            if !requested {
                return Err(ingest::vlm::VlmError::Unavailable(
                    "synthetic-unscheduled-pass".into(),
                ));
            }
            let mut answers = PassAnswers {
                acceptance_floor: Some(if pass.id == "p0_full" {
                    0.995
                } else if pass.id == "p2_board" {
                    1.0
                } else {
                    0.8
                }),
                ..Default::default()
            };
            if pass.id == "p0_full" {
                if variant.starts_with("sustained-") {
                    answers.answers.insert(
                        "game_phase".into(),
                        Answer {
                            choice: Some("flop".into()),
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
                if selected.is_some() && variant != "sustained-unknown-role" {
                    for (id, p) in [
                        ("ev_seat_controls", 1.0),
                        ("ev_hero_cards", 0.0),
                        ("ev_action_controls", 0.0),
                        ("action_on_hero", 0.0),
                    ] {
                        answers.answers.insert(
                            id.into(),
                            Answer {
                                choice: None,
                                p,
                                truncated: false,
                            },
                        );
                    }
                    answers.answers.insert(
                        "hero_seat_index".into(),
                        Answer {
                            choice: Some("not_seated".into()),
                            p: 1.0,
                            truncated: false,
                        },
                    );
                }
                for id in ["ev_table_layout", "ev_readable", "ev_board_area", "ev_pot"] {
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
                        choice: Some(
                            if matches!(variant, "auto-lobby" | "sustained-core-rejected") {
                                "lobby"
                            } else {
                                "poker_table"
                            }
                            .into(),
                        ),
                        p: 1.0,
                        truncated: false,
                    },
                );
            } else if pass.id == "p2_board" {
                for slot in 1..=5 {
                    let (rank, suit) = if variant.starts_with("sustained-") {
                        match slot {
                            1 => ("A", "spades"),
                            2 => ("K", "hearts"),
                            3 => ("Q", "diamonds"),
                            _ => ("no_card", "no_card"),
                        }
                    } else {
                        ("A", "spades")
                    };
                    for (kind, choice) in [("rank", rank), ("suit", suit)] {
                        answers.answers.insert(
                            format!("board_{slot}_{kind}"),
                            Answer {
                                choice: Some(choice.into()),
                                p: if variant.starts_with("sustained-") {
                                    1.0
                                } else {
                                    0.99999999
                                },
                                truncated: false,
                            },
                        );
                    }
                }
            } else {
                let text = if pass.id == "p3_pot" {
                    if variant == "auto-jitter-odd" {
                        "11.50"
                    } else {
                        "10.50"
                    }
                } else {
                    "0"
                };
                answers.segments = Some(Segments {
                    n: text.len() as u32,
                    overflow: false,
                });
                for (i, c) in text.chars().enumerate() {
                    answers.answers.insert(
                        format!("g{}", i + 1),
                        Answer {
                            choice: Some(c.to_string()),
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
    if let Some(partial) = partial.as_mut() {
        partial.bind_source_frame(frame).unwrap();
    }
    let strict = ingest::laya::assemble(
        ingest::laya::question_set(),
        (frame.width, frame.height),
        None,
        None,
        &mut |pass| Ok(cache.get(&pass.id).cloned().unwrap_or_default()),
    )
    .unwrap_or_else(|_| {
        assert!(
            selected.is_some(),
            "only deliberately omitted passes may fail strict assembly"
        );
        json!({"screen_kind":"poker_table","evidence":{"table_layout":false,
            "hero_cards":false,"board_area":false,"pot":false,"action_controls":false,
            "readable":false},"state":null})
        .to_string()
    });
    crate::live::finish_laya_analysis(
        ingest::laya::LayaAnalysis {
            output: ingest::vlm::VlmOutput { text: strict },
            partial,
            diagnostics,
        },
        Some(&Pipeline::new()),
        deadline,
    )
    .unwrap()
}

fn approval_json() -> Value {
    json!({"version":1,"mode":"inference-enabled",
        "operator_assertion":"I am seated and ready","inference_assertion":"USE INSTALLED IT1 FOR THIS SESSION",
        "service_instance_id":"a1b2c3d4e5f60718293a4b5c6d7e8f90", "confirmed_at_unix_ms":SOURCE_UTC,
        "max_seconds":600,"max_frames":9,"source":{"hwnd":"0xb","process_id":22,
        "exe_name":"CoinPoker.exe","title":"SYNTHETIC PRIVATE TITLE","on_screen":true,"width":800,"height":613}})
}

fn approval() -> Approval {
    serde_json::from_value(approval_json()).unwrap()
}

fn sustained_approval() -> Approval {
    let mut value = approval_json();
    value.as_object_mut().unwrap().remove("operator_assertion");
    value["version"] = json!(2);
    value["source_policy"] = json!("automatic-sustained");
    value["automatic_assertion"] = json!("AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION");
    value["max_frames"] = json!(1_200);
    serde_json::from_value(value).unwrap()
}

#[test]
fn sustained_capture_passes_600_seconds_and_1200_acquisitions_with_frozen_evidence() {
    for (case, expected) in [
        ("count", RecorderStatus::CountLimit),
        ("duration", RecorderStatus::DurationLimit),
        ("disk", RecorderStatus::DiskLimit),
    ] {
        let root = temp_root();
        let stop = root.path().join("STOP");
        let time = Rc::new(Time::default());
        let utc = || UNIX_EPOCH + Duration::from_millis(SOURCE_UTC + time.now_ms());
        let mut approval = sustained_approval();
        approval.source.width = 2;
        approval.source.height = 2;
        let state = Rc::new(RefCell::new(SourceState {
            window: approval.source.clone(),
            captures: 0,
            case: "sustained-provenance",
            reset: 0,
        }));
        // One tiny PNG plus the source/readability metadata fits, two do not.
        let max_bytes = if case == "disk" { 768 } else { 1_073_741_824 };
        let recorder = PrivateRecorder::new(
            root.path(),
            RecorderConfig {
                max_frames: approval.max_frames,
                max_bytes,
                ..RecorderConfig::default()
            },
            SystemTime::now(),
        )
        .unwrap();
        let mut source = ManualSource::with_recorder(
            Source {
                state: state.clone(),
                time: time.clone(),
                stop: stop.clone(),
            },
            &approval,
            &stop,
            time.as_ref(),
            &utc,
            recorder,
        );
        source.select(&approval.source).unwrap();
        let mut ended = None;
        for index in 0..1_210 {
            let captured_at_ms = if case == "duration" && index > 0 {
                599_500 + (index - 1) * 500
            } else {
                index * 500
            };
            time.0.set(captured_at_ms);
            let pixels = source.capture().unwrap();
            assert_eq!(pixels.rgba[1], (state.borrow().captures % 251) as u8);
            let timing = source.last_capture_timing().unwrap();
            assert_eq!(timing.monotonic_ms, captured_at_ms);
            assert_eq!(timing.utc_unix_ms, SOURCE_UTC + captured_at_ms);
            let snapshot = source.recorder.handle().snapshot();
            assert!(snapshot.recorded_frames <= 1_200);
            assert!(snapshot.recorded_bytes <= max_bytes);
            if snapshot.recording_status != RecorderStatus::Active {
                assert_eq!(snapshot.recording_status, expected);
                let prefix =
                    fs::read(source.recorder.session_path().join("manifest.jsonl")).unwrap();
                let receipt = serde_json::to_value(source.recorder.last_receipt()).unwrap();
                if let Some((frozen, frozen_prefix, frozen_receipt)) = &ended {
                    assert_eq!(&snapshot, frozen);
                    assert_eq!(&prefix, frozen_prefix);
                    assert_eq!(&receipt, frozen_receipt);
                } else {
                    ended = Some((snapshot, prefix, receipt));
                }
            }
            assert!(source.terminal.is_none());
        }
        assert!(time.now_ms() > 600_000);
        assert_eq!(state.borrow().captures, 1_210);
        let (frozen, _, _) = ended.unwrap();
        assert_eq!(
            frozen.recorded_frames,
            match case {
                "count" => 1_200,
                "duration" => 2,
                _ => 1,
            }
        );
        let progress = source.progress(None);
        assert_eq!(progress["version"], 2);
        assert_eq!(progress["source_policy"], "automatic-sustained");
        assert_eq!(
            progress["recording_end_reason"],
            recording_end_reason(expected).unwrap()
        );
        assert!(progress["stop_reason"].is_null());
        assert_eq!(
            fs::read_dir(root.path().join(".local/captures"))
                .unwrap()
                .count(),
            1
        );
        let disk_bytes = fs::read_dir(source.recorder.session_path())
            .unwrap()
            .map(|entry| entry.unwrap().metadata().unwrap().len())
            .sum::<u64>();
        let rolling = fs::read_dir(source.recorder.session_path())
            .unwrap()
            .map(Result::unwrap)
            .filter(|entry| {
                entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with("live-frame-")
            })
            .collect::<Vec<_>>();
        assert_eq!(rolling.len(), 2);
        let mailbox_bytes = rolling
            .iter()
            .map(|entry| entry.metadata().unwrap().len())
            .sum::<u64>();
        assert_eq!(disk_bytes, frozen.recorded_bytes + mailbox_bytes);
        let preview = source.live_frame.as_ref().unwrap();
        assert!(!preview.archival);
        assert_eq!(preview.frame_index, 1_210);
        assert_eq!(preview.captured_at_monotonic_ms, time.now_ms());
        fs::write(&stop, b"synthetic stop").unwrap();
        assert!(source.capture().is_err());
        assert_eq!(source.terminal, Some("operator-stop"));
        fs::remove_file(&stop).unwrap();
        source.reset();
        assert!(
            source.discover().is_err(),
            "STOP never rearms this approval"
        );
        assert_eq!(state.borrow().captures, 1_210);
    }
}

#[test]
fn sustained_ended_evidence_still_rejects_source_capture_and_clock_failures() {
    for (case, reason) in [
        ("replacement", "source-changed"),
        ("pid", "source-changed"),
        ("title", "source-changed"),
        ("minimized", "source-changed"),
        ("ambiguous", "source-changed"),
        ("closed", "source-changed"),
        ("discovery-failure", "source-unavailable"),
        ("capture-failure", "capture-failed"),
        ("capture-overlap", "capture-failed"),
        ("invalid-frame", "capture-failed"),
        ("stop-during-capture", "operator-stop"),
        ("utc-rollback", "capture-failed"),
        ("mono-rollback", "capture-failed"),
    ] {
        let root = temp_root();
        let stop = root.path().join("STOP");
        let time = Rc::new(Time::default());
        let utc_time = Cell::new(SOURCE_UTC);
        let utc = || UNIX_EPOCH + Duration::from_millis(utc_time.get());
        let mut approval = sustained_approval();
        approval.max_frames = 1;
        approval.source.width = 2;
        approval.source.height = 2;
        let state = Rc::new(RefCell::new(SourceState {
            window: approval.source.clone(),
            captures: 0,
            case: "sustained-provenance",
            reset: 0,
        }));
        let mut source = ManualSource::new(
            Source {
                state: state.clone(),
                time: time.clone(),
                stop: stop.clone(),
            },
            &approval,
            root.path(),
            &stop,
            time.as_ref(),
            &utc,
        )
        .unwrap();
        source.select(&approval.source).unwrap();
        source.capture().unwrap();
        let frozen = source.recorder.handle().snapshot();
        assert_eq!(frozen.recording_status, RecorderStatus::CountLimit);
        time.0.set(600_500);
        utc_time.set(SOURCE_UTC + time.now_ms());
        if case == "mono-rollback" {
            source.check().unwrap();
            time.0.set(500);
        } else if case == "utc-rollback" {
            utc_time.set(SOURCE_UTC - 1);
        } else {
            state.borrow_mut().case = case;
        }
        assert!(source.capture().is_err(), "{case}");
        assert_eq!(source.terminal, Some(reason), "{case}");
        assert!(source.last_capture_timing().is_none());
        assert_eq!(source.recorder.handle().snapshot(), frozen);
        let failure_code = match case {
            "capture-failure" => Some("permission-denied"),
            "capture-overlap" => Some("foreign-overlap"),
            _ => None,
        };
        assert_eq!(
            source.progress(Some(reason))["capture_failure"]["code"].as_str(),
            failure_code
        );
        state.borrow_mut().case = "sustained-provenance";
        state.borrow_mut().window = approval.source.clone();
        time.0.set(601_000);
        utc_time.set(SOURCE_UTC + time.now_ms());
        source.reset();
        assert!(source.discover().is_err(), "failure cannot rearm {case}");
        assert!(
            source.capture().is_err(),
            "failure cannot retry capture {case}"
        );
        assert_eq!(
            source.progress(Some(reason))["capture_failure"]["code"].as_str(),
            failure_code
        );
    }
}

#[test]
fn sustained_unexpected_recorder_io_is_terminal_not_an_evidence_end() {
    let root = temp_root();
    let stop = root.path().join("STOP");
    let time = Rc::new(Time::default());
    let utc = || UNIX_EPOCH + Duration::from_millis(SOURCE_UTC + time.now_ms());
    let mut approval = sustained_approval();
    approval.source.width = 2;
    approval.source.height = 2;
    let state = Rc::new(RefCell::new(SourceState {
        window: approval.source.clone(),
        captures: 0,
        case: "sustained-provenance",
        reset: 0,
    }));
    let mut source = ManualSource::new(
        Source {
            state: state.clone(),
            time: time.clone(),
            stop: stop.clone(),
        },
        &approval,
        root.path(),
        &stop,
        time.as_ref(),
        &utc,
    )
    .unwrap();
    source.select(&approval.source).unwrap();
    source.capture().unwrap();
    let acknowledged = source.recorder.handle().snapshot();
    let collision = source.recorder.session_path().join("frame-0000000002.png");
    fs::write(&collision, b"synthetic existing evidence").unwrap();
    time.0.set(500);
    assert!(source.capture().is_err());
    assert_eq!(source.terminal, Some("recorder-failure"));
    assert!(source.last_capture_timing().is_none());
    let failed = source.recorder.handle().snapshot();
    assert_eq!(failed.recording_status, RecorderStatus::IoFailure);
    assert_eq!(failed.recorded_frames, acknowledged.recorded_frames);
    assert_eq!(failed.recorded_bytes, acknowledged.recorded_bytes);
    assert!(source.progress(Some("recorder-failure"))["recording_end_reason"].is_null());
    time.0.set(600_500);
    assert!(source.discover().is_err());
    assert_eq!(source.recorder.handle().snapshot(), failed);
    assert_eq!(
        fs::read(&collision).unwrap(),
        b"synthetic existing evidence"
    );
}

fn exercise_sustained_schedule(
    case: &'static str,
    job_ms: u64,
    root: tempfile::TempDir,
) -> Exercise {
    let stop = root.path().join("STOP");
    let time = Rc::new(Time::default());
    let utc = || UNIX_EPOCH + Duration::from_millis(SOURCE_UTC + time.now_ms());
    let mut approval = sustained_approval();
    approval.max_frames = 2;
    approval.cpu_visual_board = case.starts_with("sustained-cpu-board");
    let source = Rc::new(RefCell::new(SourceState {
        window: approval.source.clone(),
        captures: 0,
        case,
        reset: 0,
    }));
    let worker = Rc::new(RefCell::new(WorkerState {
        job_ms,
        sustained_schedule: AutomaticSchedule::new(approval.cpu_visual_board),
        ..Default::default()
    }));
    let mut events = Vec::new();
    inference_loop(
        ManualSource::new(
            Source {
                state: source.clone(),
                time: time.clone(),
                stop: stop.clone(),
            },
            &approval,
            root.path(),
            &stop,
            time.as_ref(),
            &utc,
        )
        .unwrap(),
        Worker {
            state: worker.clone(),
            time: time.clone(),
            root: root.path().to_path_buf(),
            case,
        },
        |delay| {
            time.0.set(time.now_ms() + delay);
            if worker.borrow().passes.len() >= 24 || time.now_ms() >= 600_000 {
                fs::write(&stop, b"synthetic stop").unwrap();
            }
        },
        |event| {
            events.push(event.clone());
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(worker.borrow().passes.len(), 24);
    (root, events, source, worker)
}

#[test]
fn sustained_board_schedule_and_runtime_admit_above_floor_distinct_unsaved_reads() {
    let (root, events, source, worker) =
        exercise_sustained_schedule("sustained-positive", 0, temp_root());
    assert!(source.borrow().captures > 2);
    assert_eq!(rows(root.path()).len(), 2);
    assert!(worker.borrow().unsaved_starts >= 20);
    let worker = worker.borrow();
    let board_jobs: Vec<_> = worker
        .passes
        .iter()
        .filter(|(_, pass)| *pass == ObservationPass::BoardReadout)
        .collect();
    assert_eq!(board_jobs.len(), 6);
    assert!(board_jobs
        .windows(2)
        .all(|pair| pair[1].0.generation > pair[0].0.generation
            && pair[1].0.captured_at_ms > pair[0].0.captured_at_ms));
    let readings: Vec<_> = events
        .iter()
        .filter(|event| event["event"] == "partial_observation")
        .collect();
    assert!(readings.iter().any(|event| event["board_count"] == 3
        && event["game_phase"] == "flop"
        && event["board_slots"][0]["rank"] == "A"
        && event["board_slots"][1]["rank"] == "K"
        && event["board_slots"][2]["rank"] == "Q"));
    let pots: Vec<_> = readings
        .iter()
        .filter(|event| event["pot_size"] == 1_050)
        .collect();
    assert!(pots.len() >= 15);
    // Two Board captures plus the numeric consensus seed consume three gaps
    // before Pot can publish again; the fourth gap is the new admitted read.
    assert!(pots
        .windows(2)
        .all(|pair| pair[1]["captured_at_unix_ms"].as_u64().unwrap()
            - pair[0]["captured_at_unix_ms"].as_u64().unwrap()
            <= 2_000));
    for seat in 0..6 {
        assert!(readings.iter().any(
            |event| event["pot_size"] == 1_050 && event["seats"][seat]["displayed_stack"] == 0
        ));
    }
    for reading in readings {
        let captured_at = reading["captured_at_unix_ms"].as_u64().unwrap();
        let original = &reading["original_capture"];
        assert_eq!(original["source_utc_unix_ms"], captured_at);
        assert_eq!(
            original["captured_at_monotonic_ms"],
            reading["observation"]["captured_at_ms"]
        );
        assert!(original["frame_index"].as_u64().is_some_and(|n| n > 0));
        assert_eq!(original["width"], 800);
        assert_eq!(original["height"], 613);
        assert_eq!(original["sha256"].as_str().unwrap().len(), 64);
        let visual = events
            .iter()
            .find(|event| {
                event["event"] == "visual_frame"
                    && event["frame"]["frame_index"] == original["frame_index"]
            })
            .unwrap();
        assert_eq!(original["sha256"], visual["frame"]["sha256"]);
        assert_eq!(
            original["source_utc_unix_ms"],
            visual["frame"]["source_utc_unix_ms"]
        );
        assert_eq!(
            original["native_source_id"]
                .as_str()
                .unwrap()
                .parse::<u64>()
                .unwrap(),
            visual["frame"]["source_id"].as_u64().unwrap()
        );
        assert_eq!(
            captured_at,
            SOURCE_UTC + reading["observation"]["captured_at_ms"].as_u64().unwrap()
        );
        assert_eq!(reading["expires_at_unix_ms"], captured_at + 5_000);
        assert!(reading["emitted_at_unix_ms"].as_u64().unwrap() < captured_at + 5_000);
        assert!(!reading["quality_approved"].as_bool().unwrap());
        assert!(reading["hero_chips"].is_null());
        assert!(
            reading["seats"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|seat| !seat["displayed_stack"].is_null())
                .count()
                <= 2,
            "no earlier seat values are merged into this new source generation"
        );
    }
    assert!(events
        .iter()
        .all(|event| event["source_policy"] == "automatic-sustained"
            && event["experimental_bet_action"] == false
            && event["event"] != "decision"));
    let progress: Vec<_> = events
        .iter()
        .filter(|event| event["event"] == "manual_capture")
        .collect();
    assert!(progress.iter().all(|event| event["version"] == 2));
    let ended = progress
        .iter()
        .find(|event| event["recording_end_reason"] == "frame-limit")
        .unwrap();
    assert!(progress
        .iter()
        .filter(|event| event["elapsed_ms"].as_u64().unwrap() >= 500)
        .all(|event| event["recording"] == ended["recording"]));
    assert_eq!(progress.last().unwrap()["stop_reason"], "operator-stop");
    assert!(events
        .iter()
        .any(|event| event["event"] == "observation_invalidated"
            && event["reason"] == "operator-stop"));
}

#[test]
fn sustained_pairs_revisit_all_seats_within_ten_seconds_at_one_second_job_latency() {
    let (_root, events, _, worker) =
        exercise_sustained_schedule("sustained-positive", 1_000, temp_root());
    let worker = worker.borrow();
    for seat in 1..=6 {
        let captures: Vec<_> = worker.passes.iter().filter_map(|(ticket, pass)| {
            matches!(pass, ObservationPass::ReadoutPair(first) if seat == *first || seat == *first + 1)
                .then_some(ticket.captured_at_ms)
        }).collect();
        assert_eq!(captures.len(), 6);
        assert!(captures.windows(2).all(|pair| pair[1] - pair[0] <= 10_000));
        assert!(events
            .iter()
            .any(|event| event["event"] == "partial_observation"
                && event["seats"][seat as usize - 1]["displayed_stack"] == 0));
    }
}

#[test]
fn sustained_cpu_board_pairs_keep_native_board_unknown_and_original_numeric_leases() {
    for job_ms in [1_500, 2_000] {
        let (_root, events, _, worker) =
            exercise_sustained_schedule("sustained-cpu-board", job_ms, temp_root());
        let worker = worker.borrow();
        assert!(worker
            .passes
            .iter()
            .all(|(_, pass)| matches!(pass, ObservationPass::ReadoutPair(_))));
        for seat in 1..=6 {
            let captures: Vec<_> = worker.passes.iter().filter_map(|(ticket, pass)| {
                matches!(pass, ObservationPass::ReadoutPair(first) if seat == *first || seat == *first + 1)
                    .then_some((ticket.captured_at_ms, ticket.generation))
            }).collect();
            assert_eq!(captures.len(), 8);
            assert!(captures
                .windows(2)
                .all(|p| p[1].0 > p[0].0 && p[1].1 > p[0].1));
            assert_eq!(
                captures.windows(2).map(|p| p[1].0 - p[0].0).max(),
                Some(job_ms * 5)
            );
            assert!(events
                .iter()
                .any(|event| event["event"] == "partial_observation"
                    && event["seats"][seat as usize - 1]["displayed_stack"] == 0));
        }
        for event in events
            .iter()
            .filter(|event| event["event"] == "partial_observation")
        {
            let captured = event["captured_at_unix_ms"].as_u64().unwrap();
            assert_eq!(
                captured,
                SOURCE_UTC + event["observation"]["captured_at_ms"].as_u64().unwrap()
            );
            assert_eq!(event["expires_at_unix_ms"], captured + 5_000);
            assert!(event["emitted_at_unix_ms"].as_u64().unwrap() < captured + 5_000);
            assert!(event["board_slots"]
                .as_array()
                .unwrap()
                .iter()
                .all(Value::is_null));
            assert!(event["board_count"].is_null() && event["game_phase"].is_null());
            assert_eq!(event["quality_approved"], false);
        }
        assert!(events.iter().all(|event| !matches!(
            event["event"].as_str(),
            Some("observation" | "table" | "decision")
        )));
    }
}

#[test]
fn sustained_cpu_board_schedule_does_not_claim_ten_seconds_for_slow_jobs() {
    let (_root, events, _, worker) =
        exercise_sustained_schedule("sustained-cpu-board", 2_500, temp_root());
    let worker = worker.borrow();
    let captures: Vec<_> = worker
        .passes
        .iter()
        .filter_map(|(ticket, pass)| {
            (*pass == ObservationPass::ReadoutPair(1)).then_some(ticket.captured_at_ms)
        })
        .collect();
    assert_eq!(captures.windows(2).map(|p| p[1] - p[0]).max(), Some(12_500));
    assert!(events
        .iter()
        .filter(|event| event["event"] == "partial_observation")
        .all(|event| event["seats"]
            .as_array()
            .unwrap()
            .iter()
            .all(|seat| seat["displayed_stack"].is_null())));
}

#[test]
fn sustained_board_pair_admits_at_1500ms_with_unknown_role() {
    assert_sustained_board_pair_at_latency(1_500);
}

#[test]
fn sustained_board_pair_admits_at_2000ms_with_unknown_role() {
    assert_sustained_board_pair_at_latency(2_000);
}

fn assert_sustained_board_pair_at_latency(job_ms: u64) {
    let (_root, events, _, worker) =
        exercise_sustained_schedule("sustained-unknown-role", job_ms, temp_root());
    let worker = worker.borrow();
    let board_jobs: Vec<_> = worker
        .passes
        .iter()
        .filter(|(_, pass)| *pass == ObservationPass::BoardReadout)
        .collect();
    assert_eq!(
        board_jobs.len(),
        6,
        "three bounded Board pairs at {job_ms} ms"
    );
    assert_eq!(
        board_jobs[1].0.captured_at_ms - board_jobs[0].0.captured_at_ms,
        job_ms
    );
    assert!(board_jobs[1].0.generation > board_jobs[0].0.generation);
    let readings: Vec<_> = events
        .iter()
        .filter(|event| event["event"] == "partial_observation")
        .collect();
    let board = readings
        .iter()
        .find(|event| event["board_count"] == 3)
        .expect("two fresh Board reads admit independently of old Pot");
    assert_eq!(board["board_slots"][0]["rank"], "A");
    assert_eq!(board["board_slots"][1]["rank"], "K");
    assert_eq!(board["board_slots"][2]["rank"], "Q");
    assert_eq!(board["game_phase"], "flop");
    assert_eq!(
        board["captured_at_unix_ms"],
        SOURCE_UTC + board_jobs[1].0.captured_at_ms
    );
    assert_eq!(
        board["emitted_at_unix_ms"],
        SOURCE_UTC + board_jobs[1].0.captured_at_ms + job_ms
    );
    assert!(board["pot_size"].is_null(), "Board never renews old Pot");
    let prior_pot = readings
        .iter()
        .rev()
        .find(|event| {
            event["pot_size"] == 1_050
                && event["captured_at_unix_ms"].as_u64().unwrap()
                    < board["captured_at_unix_ms"].as_u64().unwrap()
        })
        .unwrap();
    if job_ms == 2_000 {
        assert!(
            prior_pot["expires_at_unix_ms"].as_u64().unwrap()
                <= board["emitted_at_unix_ms"].as_u64().unwrap()
        );
        assert!(events
            .iter()
            .any(|event| event["event"] == "partial_observation_invalidated"
                && event["reason"] == "observation-expired"
                && event["observation"] == prior_pot["observation"]
                && event.get("fields").is_none()
                && event["emitted_at_unix_ms"] == prior_pot["expires_at_unix_ms"]));
    }
    assert!(readings.iter().any(|event| event["pot_size"] == 1_050
        && event["captured_at_unix_ms"].as_u64().unwrap()
            > board["captured_at_unix_ms"].as_u64().unwrap()));
    for seat in 0..6 {
        assert!(readings.iter().any(
            |event| event["pot_size"] == 1_050 && event["seats"][seat]["displayed_stack"] == 0
        ));
    }
    for reading in readings {
        let captured_at = reading["captured_at_unix_ms"].as_u64().unwrap();
        assert_eq!(reading["expires_at_unix_ms"], captured_at + 5_000);
        assert_eq!(reading["emitted_at_unix_ms"], captured_at + job_ms);
        assert!(reading["role"].is_null() && reading["hero_chips"].is_null());
        assert_eq!(reading["quality_approved"], false);
    }
    assert!(events.iter().all(|event| !matches!(
        event["event"].as_str(),
        Some("observation" | "table" | "decision")
    )));
}

#[test]
fn sustained_board_pair_rejects_stale_seed_expired_job_and_failed_core() {
    for (case, job_ms) in [
        ("sustained-unknown-role", 2_500),
        ("sustained-unknown-role", 5_000),
        ("sustained-core-rejected", 2_000),
    ] {
        let (_root, events, _, worker) = exercise_sustained_schedule(case, job_ms, temp_root());
        assert_eq!(
            worker
                .borrow()
                .passes
                .iter()
                .filter(|(_, pass)| *pass == ObservationPass::BoardReadout)
                .count(),
            6
        );
        assert!(events
            .iter()
            .all(|event| event["event"] != "partial_observation"));
        if job_ms == 2_500 {
            // Each job is within budget, but its predecessor is exactly 5 s old.
            assert!(events
                .iter()
                .any(|event| event["event"] == "perception_diagnostics"
                    && event["admission"] == "source_current"));
            assert!(events.iter().all(|event| event["event"] != "discarded"));
        } else if job_ms == 5_000 {
            assert!(events.iter().any(|event| event["event"] == "discarded"
                && event["reason"] == "decision-deadline-exceeded"));
        } else {
            assert!(events
                .iter()
                .any(|event| event["event"] == "observation_invalidated"
                    && event["reason"] == "screen-not-accepted"));
            for diagnostics in events
                .iter()
                .filter(|event| event["event"] == "perception_diagnostics")
            {
                let passes = diagnostics["passes"].as_array().unwrap();
                assert_eq!(passes.len(), 1);
                assert_eq!(passes[0]["pass"], "p0_full");
            }
        }
    }
}

#[test]
fn sustained_change_preserves_manual_and_bounded_save_before_infer_and_terminal_caps() {
    for (case, expected) in [
        ("partial", "frame-limit"),
        ("auto-count", "frame-limit"),
        ("duration-during-capture", "duration-limit"),
        ("auto-duration", "duration-limit"),
        ("recorder-failure", "recorder-failure"),
        ("worker-failure", "inference-failed"),
        ("stop-inflight", "operator-stop"),
    ] {
        let (root, events, _, worker) = exercise_in(case, temp_root());
        let terminal = events
            .iter()
            .rev()
            .find(|event| event["event"] == "manual_capture")
            .unwrap();
        assert_eq!(terminal["version"], 1);
        assert_eq!(terminal["stop_reason"], expected, "{case}");
        let saved = rows(root.path());
        for ticket in &worker.borrow().starts {
            assert!(saved
                .iter()
                .any(|row| row["captured_at_monotonic_ms"] == ticket.captured_at_ms));
        }
        if expected == "duration-limit" && case == "duration-during-capture" {
            assert!(worker.borrow().starts.is_empty());
            assert!(saved.is_empty());
        }
        if matches!(expected, "frame-limit" | "duration-limit") {
            assert_eq!(terminal["recording_end_reason"], expected);
        }
    }
}

type Exercise = (
    tempfile::TempDir,
    Vec<Value>,
    Rc<RefCell<SourceState>>,
    Rc<RefCell<WorkerState>>,
);

fn exercise(case: &'static str) -> Exercise {
    exercise_in(case, temp_root())
}

#[test]
fn exercise_retains_temp_root_for_filesystem_inspection_then_cleans_up() {
    let (root, _, _, _) = exercise("stop");
    let path = root.path().to_path_buf();
    assert!(rows(root.path()).is_empty());
    assert!(path.join("stdout.jsonl").is_file());
    assert!(path.join("approval.json").is_file());
    drop(root);
    assert!(!path.exists());
}

fn exercise_in(case: &'static str, root: tempfile::TempDir) -> Exercise {
    let mut receipt = approval_json();
    if case.starts_with("auto-") {
        receipt
            .as_object_mut()
            .unwrap()
            .remove("operator_assertion");
        receipt["source_policy"] = json!("automatic-bounded");
        receipt["automatic_assertion"] = json!("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION");
        receipt["max_frames"] = json!(if case.starts_with("auto-partial") {
            240
        } else if matches!(case, "auto-active" | "auto-slow-selection") {
            16
        } else if case == "auto-count" {
            6
        } else {
            75
        });
        if case == "auto-duration" {
            receipt["max_seconds"] = json!(2);
        }
    }
    let mut approval: Approval = serde_json::from_value(receipt.clone()).unwrap();
    if matches!(case, "late-worker" | "decision-expired") {
        approval.max_frames = 15;
    }
    let time = Rc::new(Time::default());
    let source = Rc::new(RefCell::new(SourceState {
        window: approval.source.clone(),
        captures: 0,
        case,
        reset: 0,
    }));
    let worker = Rc::new(RefCell::new(WorkerState {
        job_ms: if case == "decision-expired" { 5_000 } else { 0 },
        ..Default::default()
    }));
    let stop = root.path().join("STOP");
    if case == "stop" {
        fs::write(&stop, "synthetic stop").unwrap();
    }
    if case == "duration" {
        time.0.set(600_000);
    }
    let mut events = Vec::new();
    let result = inference_loop(
        ManualSource::new(
            Source {
                state: source.clone(),
                time: time.clone(),
                stop: stop.clone(),
            },
            &approval,
            root.path(),
            &stop,
            time.as_ref(),
            &|| UNIX_EPOCH + Duration::from_millis(SOURCE_UTC + time.now_ms()),
        )
        .unwrap(),
        Worker {
            state: worker.clone(),
            time: time.clone(),
            root: root.path().to_path_buf(),
            case,
        },
        |delay| {
            time.0.set(time.now_ms() + delay);
            if matches!(case, "resize" | "obsolete-worker-failure") && time.now_ms() == 1_500 {
                source.borrow_mut().window.width = 900;
            }
            if case == "auto-resize" && time.now_ms() == 3_000 {
                source.borrow_mut().window.width = 900;
            }
            if case == "recorder-failure" && time.now_ms() == 1_500 {
                fs::write(
                    session(root.path()).join("frame-0000000004.png"),
                    "preserve-existing-evidence",
                )
                .unwrap();
            }
            if case == "stop-inflight" && time.now_ms() == 1_500 {
                fs::write(&stop, "synthetic stop").unwrap();
            }
        },
        |event| {
            let failed_event = match case {
                "publication-failure" => Some("partial_observation"),
                "decision-table-write-failure" => Some("table"),
                "decision-observation-write-failure" => Some("observation"),
                "decision-write-failure" => Some("decision"),
                _ => None,
            };
            if failed_event.is_some_and(|failed| event["event"] == failed) {
                return Err(RunError::Message("synthetic closed sink".into()));
            }
            events.push(event.clone());
            if case == "decision-publication-expired" && event["event"] == "observation" {
                // Backpressure consumes the original lease before the next
                // event in this tick; the decision must not get a new lease.
                time.0.set(time.now_ms() + 5_000);
            }
            Ok(())
        },
    );
    assert_eq!(
        result.is_err(),
        matches!(
            case,
            "publication-failure"
                | "decision-table-write-failure"
                | "decision-observation-write-failure"
                | "decision-write-failure"
        )
    );
    let text = events
        .iter()
        .map(|value| format!("{value}\n"))
        .collect::<String>();
    fs::write(root.path().join("stdout.jsonl"), text).unwrap();
    receipt["max_frames"] = json!(approval.max_frames);
    fs::write(
        root.path().join("approval.json"),
        serde_json::to_vec_pretty(&receipt).unwrap(),
    )
    .unwrap();
    assert!(source.borrow().reset > 0);
    (root, events, source, worker)
}

#[test]
fn slow_initial_selection_cannot_make_the_recorder_skip_the_second_capture() {
    assert_eq!(poll_delay(SourcePolicy::AutomaticBounded, 500, 0, 1400), 0);
    assert_eq!(
        poll_delay(SourcePolicy::AutomaticBounded, 500, 1200, 1400),
        300
    );
    let (root, events, source, _) = exercise("auto-slow-selection");
    let manifest = rows(root.path());
    assert_eq!(manifest.len(), 16);
    assert_eq!(source.borrow().captures, 16);
    assert_eq!(manifest[0]["captured_at_monotonic_ms"], 1200);
    assert_eq!(manifest[1]["captured_at_monotonic_ms"], 1700);
    for pair in manifest.windows(2) {
        assert_eq!(
            pair[1]["captured_at_monotonic_ms"].as_u64().unwrap()
                - pair[0]["captured_at_monotonic_ms"].as_u64().unwrap(),
            500
        );
    }
    let terminal = events
        .iter()
        .rev()
        .find(|event| event["event"] == "manual_capture")
        .unwrap();
    assert_eq!(terminal["stop_reason"], "frame-limit");
    assert_eq!(terminal["capture_failures"], 0);
    assert!(events
        .iter()
        .all(|event| event["reason"] != "recorder-failure"));
}

#[test]
fn manual_inference_partial_fields_stay_non_actionable_with_pipeline_enabled() {
    let (root, events, source, worker) = exercise("partial");
    assert_eq!(source.borrow().captures, 9);
    assert_eq!(rows(root.path()).len(), 9);
    assert!(worker.borrow().starts.len() >= 2);
    let partial = events
        .iter()
        .find(|event| event["event"] == "partial_observation")
        .unwrap();
    assert_eq!(partial["pot_size"], 1050);
    assert_eq!(
        partial["captured_at_unix_ms"],
        SOURCE_UTC + partial["observation"]["captured_at_ms"].as_u64().unwrap()
    );
    assert_eq!(
        partial["expires_at_unix_ms"],
        partial["captured_at_unix_ms"].as_u64().unwrap() + 5_000
    );
    assert_eq!(partial["quality_approved"], false);
    assert!(partial["board_slots"]
        .as_array()
        .unwrap()
        .iter()
        .all(Value::is_null));
    assert!(partial["hero_seated"].is_null() && partial["hero_chips"].is_null());
    assert!(worker.borrow().recommendations.is_empty());
    assert!(events.iter().all(|event| !matches!(
        event["event"].as_str(),
        Some("observation" | "table" | "decision")
    )));
    assert!(events
        .iter()
        .all(|event| event["mode"] == "inference-enabled"
            && event["service_instance_id"] == approval().service_instance_id.as_deref().unwrap()));
    assert_eq!(
        events
            .iter()
            .rev()
            .find(|event| event["event"] == "manual_capture")
            .unwrap()["stop_reason"],
        "frame-limit"
    );
    println!(
        "MANUAL_INFERENCE_SYNTHETIC_STDOUT={}",
        root.path().join("stdout.jsonl").display()
    );
}

#[test]
fn manual_inference_forwards_validated_pipeline_decision_and_weak_table() {
    let (_root, events, _, worker) = exercise_in("decision-valid", temp_root());
    let worker = worker.borrow();
    assert!(
        worker.starts.len() >= 2,
        "independent captures must reach consensus"
    );
    assert!(worker.starts.windows(2).all(|pair| {
        pair[1].generation > pair[0].generation && pair[1].captured_at_ms > pair[0].captured_at_ms
    }));
    let decision_index = events
        .iter()
        .position(|event| event["event"] == "decision")
        .expect("validated Pipeline output must reach the sink");
    let decision = &events[decision_index];
    let (ticket, computed) = worker
        .recommendations
        .iter()
        .find(|(source, _)| json!(source) == decision["observation"])
        .unwrap();
    assert_ne!(ticket, &worker.starts[0], "one completion is not consensus");
    for (key, value) in serde_json::to_value(computed).unwrap().as_object().unwrap() {
        assert_eq!(&decision[key], value, "forward the real pipeline's {key}");
    }
    assert!(matches!(
        decision["action"].as_str(),
        Some("check" | "raise")
    ));
    if decision["action"] == "raise" {
        assert!((500..=5_000).contains(&decision["amount"].as_u64().unwrap()));
    } else {
        assert_eq!(decision["amount"], 0);
    }
    let observation = events[..decision_index]
        .iter()
        .find(|event| {
            event["event"] == "observation" && event["observation"] == decision["observation"]
        })
        .unwrap();
    assert_eq!(observation["role"], "your_turn");
    assert_eq!(
        observation["quality_approved"], false,
        "synthetic is not model certification"
    );
    for key in ["captured_at_unix_ms", "expires_at_unix_ms", "valid_for_ms"] {
        assert_eq!(decision[key], observation[key]);
    }
    assert_eq!(ticket.identity, approval().source.identity());
    assert_eq!(
        decision["captured_at_unix_ms"],
        SOURCE_UTC + ticket.captured_at_ms
    );
    assert_eq!(
        decision["expires_at_unix_ms"],
        SOURCE_UTC + ticket.captured_at_ms + 5_000
    );
    assert!(
        decision["emitted_at_unix_ms"].as_u64().unwrap()
            < decision["expires_at_unix_ms"].as_u64().unwrap()
    );
    assert_eq!(decision["mode"], "inference-enabled");
    assert_eq!(
        decision["service_instance_id"],
        approval().service_instance_id.unwrap()
    );
    let table = events[..decision_index]
        .iter()
        .find(|event| event["event"] == "table")
        .expect("the weak table event must also be forwarded");
    assert_eq!(table["hero_cards"], observation["hero_cards"]);
    for field in [
        "observation",
        "valid_for_ms",
        "expires_at_unix_ms",
        "quality_approved",
        "action",
    ] {
        assert!(
            table.get(field).is_none(),
            "weak Table cannot acquire {field}"
        );
    }
    let clears: Vec<_> = events[decision_index + 1..]
        .iter()
        .filter(|event| event["event"] == "clear")
        .collect();
    assert_eq!(
        clears.len(),
        1,
        "retain the terminal tick's queued clear exactly once"
    );
    assert_eq!(clears[0]["reason"], "capture-unavailable");
    assert!(events.iter().any(
        |event| event["event"] == "observation_invalidated" && event["reason"] == "frame-limit"
    ));
}

#[test]
fn manual_inference_rejects_untrusted_obsolete_and_expired_decisions() {
    for (case, reason) in [
        ("decision-untrusted", "inference-failed"),
        ("decision-wrong-source", "obsolete-observation"),
        ("decision-obsolete", "obsolete-observation"),
        ("decision-expired", "decision-deadline-exceeded"),
    ] {
        let (_root, events, _, worker) = exercise_in(case, temp_root());
        assert!(!worker.borrow().starts.is_empty(), "{case}");
        assert!(
            events.iter().all(|event| !matches!(
                event["event"].as_str(),
                Some("decision" | "observation" | "table")
            )),
            "{case}"
        );
        assert!(
            events
                .iter()
                .any(|event| { event["reason"] == reason || event["stop_reason"] == reason }),
            "{case}"
        );
        if case == "decision-untrusted" {
            assert!(worker.borrow().recommendations.is_empty());
        } else {
            assert!(
                !worker.borrow().recommendations.is_empty(),
                "runtime vetoes computed advice"
            );
        }
    }
}

#[test]
fn manual_inference_rechecks_decision_lease_after_observation_publication() {
    let (_root, events, _, worker) = exercise_in("decision-publication-expired", temp_root());
    assert!(!worker.borrow().recommendations.is_empty());
    let observation = events
        .iter()
        .find(|event| event["event"] == "observation")
        .unwrap();
    let invalidation = events
        .iter()
        .find(|event| {
            event["event"] == "observation_invalidated" && event["reason"] == "publication-expired"
        })
        .unwrap();
    assert_eq!(
        invalidation["generation"],
        observation["observation"]["generation"]
    );
    assert_eq!(invalidation["epoch"], observation["observation"]["epoch"]);
    assert_eq!(
        invalidation["identity"],
        observation["observation"]["identity"]
    );
    assert!(events.iter().all(|event| event["event"] != "decision"));
}

#[test]
fn manual_inference_failed_table_observation_or_decision_write_stops_publication() {
    for case in [
        "decision-table-write-failure",
        "decision-observation-write-failure",
        "decision-write-failure",
    ] {
        let (_root, events, _, worker) = exercise_in(case, temp_root());
        assert!(worker.borrow().recommendations.len() >= 2);
        assert!(
            events.iter().all(|event| event["event"] != "decision"),
            "{case}"
        );
        let terminal = events
            .iter()
            .rev()
            .find(|event| event["event"] == "manual_capture")
            .unwrap();
        assert_eq!(terminal["stop_reason"], "publication-failed");
        assert!(events
            .iter()
            .any(|event| event["event"] == "observation_invalidated"
                && event["reason"] == "publication-failed"));
    }
}

#[test]
fn automatic_activity_requires_persistent_qualified_pixels_not_role_or_model_jitter() {
    let (root, events, source, worker) = exercise("auto-active");
    let activation = events
        .iter()
        .position(|event| event["event"] == "manual_capture" && event["activity_state"] == "active")
        .unwrap_or_else(|| {
            panic!(
                "stable visible table change activates; sources={:?}",
                events
                    .iter()
                    .filter(|event| event["event"] == "perception_diagnostics")
                    .map(|event| (event["observation"].clone(), event["admission"].clone()))
                    .collect::<Vec<_>>()
            )
        });
    assert!(events[..activation].iter().all(|event| !matches!(
        event["event"].as_str(),
        Some("observation" | "history" | "decision")
    )));
    assert!(events[..activation]
        .iter()
        .any(|event| event["event"] == "partial_observation" && event["pot_size"] == 1050));
    assert!(events
        .iter()
        .any(|event| event["event"] == "status" && event["state"] == "verifying"));
    let reading = events[activation..]
        .iter()
        .find(|event| event["event"] == "partial_observation")
        .unwrap();
    assert_eq!(reading["pot_size"], 1050);
    assert!(reading["hero_seated"].is_null() && reading["hero_chips"].is_null());
    assert_eq!(
        reading["expires_at_unix_ms"].as_u64().unwrap()
            - reading["captured_at_unix_ms"].as_u64().unwrap(),
        5_000
    );
    assert!(
        events
            .iter()
            .all(|event| event["source_policy"] == "automatic-bounded"
                && event["event"] != "decision")
    );
    assert_eq!(source.borrow().captures, 16);
    assert_eq!(rows(root.path()).len(), 16);
    assert!(worker.borrow().starts.len() >= 4);
    let activated_at = events[activation]["elapsed_ms"].as_u64().unwrap();
    assert!(worker
        .borrow()
        .starts
        .iter()
        .any(|ticket| ticket.captured_at_ms > activated_at));
    assert!(
        worker
            .borrow()
            .starts
            .iter()
            .filter(|ticket| ticket.captured_at_ms == activated_at)
            .count()
            <= 1,
        "only the one already-started same-tick job may remain at activation"
    );
    let final_progress = events
        .iter()
        .rev()
        .find(|event| event["event"] == "manual_capture")
        .unwrap();
    assert_eq!(final_progress["stop_reason"], "frame-limit");
    assert_eq!(final_progress["elapsed_ms"], 7_500);
    let approval: Value =
        serde_json::from_slice(&fs::read(root.path().join("approval.json")).unwrap()).unwrap();
    assert!(approval.get("operator_assertion").is_none());
    println!(
        "AUTOMATIC_ACTIVITY_SYNTHETIC_STDOUT={}",
        root.path().join("stdout.jsonl").display()
    );
}

#[test]
fn automatic_partial_lanes_recover_after_core_only_admission_and_interruption() {
    for case in [
        "auto-partial",
        "auto-partial-obsolete",
        "auto-partial-middle",
        "auto-partial-late",
    ] {
        let (_root, events, _, _) = exercise(case);
        let activation = events
            .iter()
            .position(|event| {
                event["event"] == "manual_capture" && event["activity_state"] == "active"
            })
            .expect("field jobs also qualify actual activity witnesses");
        assert!(events[..activation].iter().all(|event| !matches!(
            event["event"].as_str(),
            Some("observation" | "history" | "decision")
        )));
        let readings: Vec<_> = events
            .iter()
            .filter(|event| event["event"] == "partial_observation")
            .collect();
        assert!(readings.iter().any(|event| event["role"] == "observing"));
        assert!(
            readings.iter().any(|event| event["pot_size"] == 1050),
            "Pot starved: {case}"
        );
        for seat in 0..6 {
            assert!(
                readings
                    .iter()
                    .any(|event| event["seats"][seat]["displayed_stack"] == 0),
                "stack {} starved: {case}",
                seat + 1
            );
        }
        for reading in readings {
            let captured = reading["captured_at_unix_ms"].as_u64().unwrap();
            assert_eq!(
                captured,
                SOURCE_UTC + reading["observation"]["captured_at_ms"].as_u64().unwrap()
            );
            assert_eq!(
                reading["expires_at_unix_ms"].as_u64().unwrap(),
                captured + 5000
            );
            assert!(reading["emitted_at_unix_ms"].as_u64().unwrap() < captured + 5000);
            assert!(reading["board_slots"]
                .as_array()
                .unwrap()
                .iter()
                .all(Value::is_null));
        }
        let reason = match case {
            "auto-partial-obsolete" | "auto-partial-middle" => Some("obsolete-observation"),
            "auto-partial-late" => Some("decision-deadline-exceeded"),
            _ => None,
        };
        if let Some(reason) = reason {
            assert!(events
                .iter()
                .any(|event| event["event"] == "discarded" && event["reason"] == reason));
        }
        assert!(events.iter().all(|event| event["event"] != "decision"));
    }
}

#[test]
fn cosmetic_and_one_stack_churn_do_not_block_independent_current_amounts() {
    let (_root, events, _, _) = exercise("auto-partial-cosmetic");
    let readings: Vec<_> = events
        .iter()
        .filter(|event| event["event"] == "partial_observation")
        .collect();
    assert!(readings.iter().any(|reading| reading["pot_size"] == 1050));
    for seat in 1..6 {
        assert!(
            readings
                .iter()
                .any(|reading| reading["seats"][seat]["displayed_stack"] == 0),
            "independently unchanged stack {} was starved",
            seat + 1
        );
    }
    for reading in readings {
        assert!(
            reading["seats"][0]["displayed_stack"].is_null(),
            "changed original crop stays unknown"
        );
        assert!(
            reading["role"].is_null(),
            "whole-frame p0 role is not current"
        );
        assert_eq!(
            reading["expires_at_unix_ms"].as_u64().unwrap(),
            reading["captured_at_unix_ms"].as_u64().unwrap() + 5000
        );
    }
    assert!(events
        .iter()
        .all(|event| !matches!(event["event"].as_str(), Some("decision" | "observation"))));
}

#[test]
fn automatic_idle_lobby_transient_ambiguous_jitter_and_resize_keep_finite_run_budgets() {
    for case in [
        "auto-idle",
        "auto-lobby",
        "auto-transient",
        "auto-ambiguous",
        "auto-jitter",
        "auto-outside",
        "auto-resize",
        "auto-count",
        "auto-duration",
    ] {
        let (root, events, source, worker) = exercise(case);
        if case == "auto-idle" {
            let starts = &worker.borrow().starts;
            assert!(
                starts.len() >= 20,
                "qualified idle probe keeps requesting fresh candidates"
            );
            assert!(
                starts
                    .windows(2)
                    .all(|pair| pair[1].captured_at_ms - pair[0].captured_at_ms <= 2_000),
                "the 5 s evidence lease must not be spent waiting for a 5 s refresh"
            );
        }
        let final_progress = events
            .iter()
            .rev()
            .find(|event| event["event"] == "manual_capture")
            .unwrap();
        let (expected, elapsed) = match case {
            "auto-count" => ("frame-limit", 2_500),
            "auto-duration" => ("duration-limit", 2_000),
            _ => ("frame-limit", 37_000),
        };
        assert_eq!(final_progress["stop_reason"], expected, "{case}");
        assert_eq!(final_progress["elapsed_ms"], elapsed, "{case}");
        assert_eq!(final_progress["activity_state"], "verifying", "{case}");
        assert!(
            !events.iter().any(|event| matches!(
                event["event"].as_str(),
                Some("observation" | "history" | "decision")
            )),
            "{case}"
        );
        assert!(
            events
                .iter()
                .any(|event| event["event"] == "observation_invalidated"
                    && event["reason"] == expected),
            "{case}"
        );
        if case == "auto-lobby" {
            assert!(events
                .iter()
                .all(|event| event["event"] != "partial_observation"));
        }
        assert!(source.borrow().captures <= 75, "{case}");
        assert!(rows(root.path()).len() <= 75, "{case}");
        assert_eq!(
            fs::read_dir(root.path().join(".local/captures"))
                .unwrap()
                .count(),
            1,
            "{case}"
        );
    }
}

#[test]
fn unchanged_observed_table_reads_amounts_without_activity_or_history() {
    let (root, events, source, worker) = exercise("auto-partial-idle");
    assert_eq!(source.borrow().captures, 240);
    assert_eq!(rows(root.path()).len(), 240);
    let readings: Vec<_> = events
        .iter()
        .filter(|event| event["event"] == "partial_observation")
        .collect();
    assert!(readings.len() > 3);
    assert!(readings.iter().any(|event| event["pot_size"] == 1050));
    for seat in 0..6 {
        assert!(readings
            .iter()
            .any(|event| event["seats"][seat]["displayed_stack"] == 0));
    }
    for reading in &readings {
        assert_eq!(reading["activity_state"], "verifying");
        assert_eq!(reading["quality_approved"], false);
        assert!(reading["hero_seated"].is_null() || reading["hero_seated"] == false);
        assert!(reading["hero_chips"].is_null());
        assert_eq!(
            reading["expires_at_unix_ms"].as_u64().unwrap(),
            reading["captured_at_unix_ms"].as_u64().unwrap() + 5000
        );
    }
    assert!(
        readings.last().unwrap()["captured_at_unix_ms"]
            .as_u64()
            .unwrap()
            - readings.first().unwrap()["captured_at_unix_ms"]
                .as_u64()
                .unwrap()
            >= 60_000
    );
    assert!(events.iter().all(|event| !matches!(
        event["event"].as_str(),
        Some("observation" | "history" | "table" | "decision")
    )));
    assert!(worker.borrow().starts.windows(2).all(|pair| {
        pair[1].captured_at_ms > pair[0].captured_at_ms && pair[1].generation > pair[0].generation
    }));
    let final_progress = events
        .iter()
        .rev()
        .find(|event| event["event"] == "manual_capture")
        .unwrap();
    assert_eq!(final_progress["activity_state"], "verifying");
    assert_eq!(final_progress["stop_reason"], "frame-limit");
    println!(
        "AUTOMATIC_IDLE_READOUT_SYNTHETIC_STDOUT={}",
        root.path().join("stdout.jsonl").display()
    );
}

#[test]
fn automatic_gate_rejects_duplicate_expired_and_geometry_only_activity_evidence() {
    fn witness(width: u32, pot: u8) -> TableContentWitness {
        let mut frame = Frame {
            width,
            height: 613,
            rgba: [64, 64, 64, 255].repeat((width * 613) as usize),
            ..Frame::default()
        };
        frame.rgba[0] = 255;
        let (x, y, _, _) = ingest::laya::geometry::region_px("pot", width, 613).unwrap();
        frame.rgba[((y * width + x) * 4) as usize] = pot;
        synthetic_analysis(
            &frame,
            Instant::now() + Duration::from_secs(5),
            "partial",
            None,
        )
        .partial
        .unwrap()
        .table_content_witness(&frame)
        .unwrap()
    }
    fn ticket(n: u64) -> Ticket {
        Ticket {
            identity: approval().source.identity(),
            generation: n,
            epoch: 1,
            captured_at_ms: n * 500,
            captured_at_unix_ms: Some(SOURCE_UTC + n * 500),
        }
    }
    let a = witness(800, 64);
    let b = witness(800, 180);
    let c = witness(800, 200);
    let resized = witness(900, 180);
    let mut gate = ActivityGate::new(SourcePolicy::AutomaticBounded);
    for n in [1, 1, 1] {
        gate.observe(ticket(n), Some(a.clone()), 500);
    }
    assert!(gate.repeats.iter().all(|repeats| *repeats == 1));
    gate.observe(ticket(2), Some(a.clone()), 1_000);
    gate.observe(ticket(3), Some(b.clone()), 1_500);
    assert!(!gate.active);
    gate.observe(ticket(4), None, 2_000);
    gate.observe(ticket(5), Some(b.clone()), 2_500);
    gate.observe(ticket(6), Some(b.clone()), 3_000);
    assert!(!gate.active, "ineligible sample reset the baseline");
    gate.observe(ticket(7), Some(resized.clone()), 3_500);
    gate.observe(ticket(8), Some(resized.clone()), 4_000);
    assert!(!gate.active, "resize alone is not activity");
    gate.observe(ticket(9), Some(a.clone()), 10_000);
    assert!(!gate.active, "expired sample is not activity");
    let mut gate = ActivityGate::new(SourcePolicy::AutomaticBounded);
    for (n, content) in [
        (1, a.clone()),
        (2, a.clone()),
        (4, b.clone()),
        (8, c),
        (11, b.clone()),
        (13, b.clone()),
    ] {
        gate.observe(ticket(n), Some(content), n * 500);
    }
    assert!(
        !gate.active,
        "intermediate jitter cannot renew an old baseline's expiry"
    );
    let mut gate = ActivityGate::new(SourcePolicy::AutomaticBounded);
    for (n, content) in [(1, a.clone()), (2, a), (3, b.clone()), (4, b)] {
        gate.observe(ticket(n), Some(content), n * 500);
    }
    assert!(
        gate.active,
        "four independent qualified sources establish a content change"
    );

    let a = witness(800, 64);
    let b = witness(800, 180);
    let mut gate = ActivityGate::new(SourcePolicy::AutomaticBounded);
    for n in 1..=2 {
        gate.observe(ticket(n), Some(a.clone()), n * 500);
    }
    for n in 3..=4 {
        let mut next = ticket(n);
        next.epoch = 3; // Source interruption or resize-away-and-back, same final geometry.
        gate.observe(next, Some(b.clone()), n * 500);
    }
    assert!(
        !gate.active,
        "a source boundary cannot masquerade as visible activity"
    );
    for n in 5..=6 {
        gate.observe(ticket(n), Some(a.clone()), n * 500);
    }
    assert_eq!(
        gate.last.as_ref().unwrap().generation,
        4,
        "epoch rollback is not evidence"
    );
    for n in 7..=8 {
        let mut next = ticket(n);
        next.epoch = 3;
        gate.observe(next, Some(a.clone()), n * 500);
    }
    assert!(gate.active, "a fresh same-epoch sequence may qualify");
}

#[test]
fn manual_inference_terminal_sources_never_rearm_or_infer_unsaved_pixels() {
    for (case, reason) in [
        ("stop", "operator-stop"),
        ("duration", "duration-limit"),
        ("replacement", "source-changed"),
        ("pid", "source-changed"),
        ("title", "source-changed"),
        ("minimized", "source-changed"),
        ("discovery-failure", "source-unavailable"),
        ("capture-failure", "capture-failed"),
        ("invalid-frame", "recorder-failure"),
        ("stop-during-capture", "operator-stop"),
        ("duration-during-capture", "duration-limit"),
    ] {
        let (root, events, source, worker) = exercise(case);
        assert!(source.borrow().captures <= 1, "{case}");
        assert!(worker.borrow().starts.is_empty(), "{case}");
        assert!(rows(root.path()).is_empty(), "{case}");
        assert_eq!(
            events
                .iter()
                .find(|event| !event["stop_reason"].is_null())
                .unwrap()["stop_reason"],
            reason,
            "{case}"
        );
        assert!(events
            .iter()
            .any(|event| event["event"] == "observation_invalidated" && event["reason"] == reason));
    }
}

#[test]
fn capture_failure_inference_progress_keeps_diagnostic_and_discards_queued_partials() {
    for (case, expected) in [
        ("capture-failure", "permission-denied"),
        ("capture-overlap", "foreign-overlap"),
        ("capture-overlap-inflight", "popup-overlap"),
        ("capture-backend", "backend"),
    ] {
        let (root, events, source, worker) = exercise(case);
        let progress: Vec<_> = events
            .iter()
            .filter(|event| event["event"] == "manual_capture")
            .collect();
        assert!(progress.first().unwrap()["capture_failure"].is_null());
        let terminal = progress.last().unwrap();
        assert_eq!(terminal["capture_failure"]["code"], expected, "{case}");
        assert_eq!(terminal["capture_failures"], 1);
        assert_eq!(terminal["stop_reason"], "capture-failed");
        assert!(!terminal["capture_failure"]["detail"]
            .as_str()
            .unwrap()
            .contains('\n'));
        assert!(events.iter().all(|event| !matches!(
            event["event"].as_str(),
            Some("partial_observation" | "observation" | "table" | "decision")
        )));
        if case == "capture-overlap-inflight" {
            assert_eq!(source.borrow().captures, 4);
            assert_eq!(worker.borrow().starts.len(), 1);
            assert_eq!(rows(root.path()).len(), 3);
        } else {
            assert_eq!(source.borrow().captures, 1);
            assert!(worker.borrow().starts.is_empty());
            assert!(rows(root.path()).is_empty());
        }
    }
}

#[test]
fn manual_inference_resize_slow_capture_and_inflight_stop_retain_budget_and_origin() {
    for case in [
        "resize",
        "stale-resize",
        "slow-capture",
        "slow-worker",
        "stop-inflight",
        "late-worker",
        "worker-failure",
        "obsolete-worker-failure",
        "recorder-failure",
        "publication-failure",
    ] {
        let (root, events, source, worker) = exercise(case);
        let saved = rows(root.path());
        let final_progress = events
            .iter()
            .rev()
            .find(|event| event["event"] == "manual_capture")
            .unwrap();
        let expected = match case {
            "stop-inflight" => "operator-stop",
            "worker-failure" | "obsolete-worker-failure" => "inference-failed",
            "recorder-failure" => "recorder-failure",
            "publication-failure" => "publication-failed",
            _ => "frame-limit",
        };
        assert_eq!(final_progress["stop_reason"], expected, "{case}");
        assert!(source.borrow().captures <= 16, "bounded {case}");
        assert_eq!(
            fs::read_dir(root.path().join(".local/captures"))
                .unwrap()
                .count(),
            1
        );
        if case == "resize" {
            assert_eq!(saved.len(), 9);
            assert!(
                saved.iter().any(|row| row["width"] == 800)
                    && saved.iter().any(|row| row["width"] == 900)
            );
            assert!(saved
                .iter()
                .all(|row| row["source_id"] == saved[0]["source_id"]));
        }
        if case == "slow-capture" {
            assert_eq!(saved[0]["captured_at_monotonic_ms"], 0);
            assert_eq!(saved[0]["source_utc_unix_ms"], SOURCE_UTC);
            assert!(worker
                .borrow()
                .starts
                .iter()
                .all(|ticket| ticket.captured_at_ms % 700 == 0));
        }
        if matches!(case, "slow-worker" | "stop-inflight") {
            assert_eq!(worker.borrow().starts.len(), 1);
            assert!(worker.borrow().job.is_some(), "does not claim cancellation");
            assert!(!events
                .iter()
                .any(|event| event["event"] == "partial_observation"));
        }
        if case == "late-worker" {
            assert!(events.iter().any(|event| event["event"] == "discarded"
                && event["reason"] == "decision-deadline-exceeded"));
            assert!(!events
                .iter()
                .any(|event| event["event"] == "partial_observation"
                    && event["observation"]["captured_at_ms"] == 1_000));
        }
        if case == "recorder-failure" {
            assert_eq!(worker.borrow().starts.len(), 1);
            assert_eq!(
                fs::read(session(root.path()).join("frame-0000000004.png")).unwrap(),
                b"preserve-existing-evidence"
            );
        }
    }
}
