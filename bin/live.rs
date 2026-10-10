use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::Command;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use ingest::capture::{CaptureError, Frame, PlatformCapture, WindowCapturer};
use ingest::discovery::DiscoveryConfig;
use ingest::laya::LayaBackend;
use ingest::runtime::{
    Analysis, Clock, InferenceFailure, LiveEvent, LiveRuntime, MonotonicClock, RuntimeConfig,
    ThreadWorker, Ticket, CAPTURE_HEALTH_INTERVAL_MS, DECISION_DEADLINE_CODE,
    PUBLICATION_RESERVE_MS,
};
use ingest::screen::parse_screen_output;
use ingest::vlm::VlmBackend;
use opponent_model::observer::{Capture, GapReason, Id, Observer};
use serde_json::json;

use crate::config::Options;
use crate::{Pipeline, RunError};

pub fn emit(value: &serde_json::Value) -> Result<(), RunError> {
    let mut out = io::stdout().lock();
    serde_json::to_writer(&mut out, value).map_err(|e| RunError::Message(e.to_string()))?;
    writeln!(out)?;
    out.flush()?;
    Ok(())
}

pub fn list_windows() -> Result<(), RunError> {
    let snapshot = WindowCapturer::discover().map_err(|error| {
        let state = if error == CaptureError::PermissionDenied {
            "permission_required"
        } else {
            "capture_unavailable"
        };
        let _ = emit(
            &json!({"schema_version":2,"event":"status","state":state,"reason":error.to_string()}),
        );
        RunError::Message(error.to_string())
    })?;
    for application in snapshot.applications {
        emit(&json!({"schema_version":2,"event":"application","application":application}))?;
    }
    for window in snapshot.windows {
        emit(&json!({"schema_version":2,"event":"window","window":window}))?;
    }
    Ok(())
}

fn analyze_frame(
    backend: &impl VlmBackend,
    pipeline: &Pipeline,
    frame: &Frame,
    deadline: Instant,
) -> Result<Analysis<ui::widgets::DecisionView>, InferenceFailure> {
    let output = backend
        .analyze_with_deadline(frame, &ingest::prompt::build_analysis_prompt(), deadline)
        .map_err(|error| InferenceFailure { code: error.code() })?;
    // Error codes are typed constants, never model payloads or parser messages.
    let observation =
        parse_screen_output(&output).map_err(|error| InferenceFailure { code: error.code() })?;
    if Instant::now() >= deadline {
        return Err(InferenceFailure {
            code: DECISION_DEADLINE_CODE,
        });
    }
    let recommendation = observation
        .state
        .as_ref()
        .filter(|s| s.action_required)
        .and_then(|state| pipeline.decide(state).ok());
    if Instant::now() >= deadline {
        return Err(InferenceFailure {
            code: DECISION_DEADLINE_CODE,
        });
    }
    Ok(Analysis {
        observation,
        recommendation,
    })
}

/// The calibrated lobby size, when both dimensions are configured (R18).
pub fn lobby_size(discovery: &DiscoveryConfig) -> Option<(u32, u32)> {
    match (discovery.lobby_width, discovery.lobby_height) {
        (Some(width), Some(height)) if width > 0 && height > 0 => Some((width, height)),
        _ => None,
    }
}

fn configuration_event(options: &Options) -> serde_json::Value {
    json!({"schema_version":2,"event":"configuration","runtime":options.runtime,
        "identity_configured":options.discovery.has_identity(),"model":options.vlm.model,
        "vlm_timeout_secs":options.vlm.timeout_secs,"visual_calibration":"not_validated",
        "perception":"laya-vision","question_set_version":ingest::laya::question_set_version(),
        "laya_threshold":options.vlm.threshold,"laya_calibrated":ingest::laya::calibrated(),
        "quality_approved":ingest::laya::calibrated(),"capture_health_interval_ms":CAPTURE_HEALTH_INTERVAL_MS,
        "decision_publication_reserve_ms":PUBLICATION_RESERVE_MS,"recording_enabled":false})
}

fn unix_ms() -> Result<u64, RunError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis().min(u128::from(u64::MAX)) as u64)
        .map_err(|_| RunError::Message("system clock predates the Unix epoch".into()))
}

/// A result must still fit both source-bound limits at publication, not get a new lease.
fn leased_record(
    mut record: serde_json::Value,
    event: &str,
    ticket: Ticket,
    valid_for_ms: u64,
    now_ms: u64,
    emitted_at_unix_ms: u64,
    config: &RuntimeConfig,
) -> Option<serde_json::Value> {
    let age = now_ms.checked_sub(ticket.captured_at_ms)?;
    let valid_for_ms = valid_for_ms.min(
        config
            .max_frame_age_ms
            .min(config.decision_budget_ms)
            .saturating_sub(age),
    );
    if valid_for_ms == 0 {
        return None;
    }
    let fields = record
        .as_object_mut()
        .expect("sanitized event DTO is an object");
    fields.insert("schema_version".into(), json!(2));
    fields.insert("event".into(), json!(event));
    fields.insert("observation".into(), json!(ticket));
    fields.insert(
        "captured_at_unix_ms".into(),
        json!(emitted_at_unix_ms.saturating_sub(age)),
    );
    fields.insert("valid_for_ms".into(), json!(valid_for_ms));
    fields.insert("emitted_at_unix_ms".into(), json!(emitted_at_unix_ms));
    fields.insert(
        "expires_at_unix_ms".into(),
        json!(emitted_at_unix_ms.saturating_add(valid_for_ms)),
    );
    Some(record)
}

fn event_record(
    event: LiveEvent<ui::widgets::DecisionView>,
    now_ms: u64,
    emitted_at_unix_ms: u64,
    config: &RuntimeConfig,
) -> Result<Option<serde_json::Value>, RunError> {
    let mut record = match event {
        LiveEvent::Status {
            state,
            reason,
            identity,
        } => {
            json!({"schema_version":2,"event":"status","state":state,"reason":reason,"identity":identity})
        }
        LiveEvent::Clear { reason, generation } => {
            json!({"schema_version":2,"event":"clear","reason":reason,"generation":generation})
        }
        LiveEvent::Recommendation {
            ticket,
            value,
            valid_for_ms,
        } => {
            let record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            return Ok(leased_record(
                record,
                "decision",
                ticket,
                valid_for_ms,
                now_ms,
                emitted_at_unix_ms,
                config,
            ));
        }
        LiveEvent::Observation {
            ticket,
            value,
            valid_for_ms,
        } => {
            // This live worker uses Laya only. In 0.4.0 a full admitted state has
            // already passed confident unseated R15/R17, parser and runtime gates.
            // Never extend this provenance to weak Table events or a future model.
            let value = if ingest::laya::question_set_version() == "0.4.0" {
                value.with_confirmed_unseated_admission()
            } else {
                value
            };
            let record =
                serde_json::to_value(value).map_err(|e| RunError::Message(e.to_string()))?;
            return Ok(leased_record(
                record,
                "observation",
                ticket,
                valid_for_ms,
                now_ms,
                emitted_at_unix_ms,
                config,
            ));
        }
        LiveEvent::ObservationInvalidated {
            reason,
            generation,
            epoch,
            identity,
        } => {
            json!({"schema_version":2,"event":"observation_invalidated","reason":reason,
                "generation":generation,"epoch":epoch,"identity":identity})
        }
        LiveEvent::CaptureHealth {
            frame_count,
            frame_width,
            frame_height,
            captured_at_ms,
            generation,
            epoch,
            fresh_capture,
            identity,
        } => {
            let capture_age = captured_at_ms.and_then(|captured| now_ms.checked_sub(captured));
            let fresh_capture =
                fresh_capture && capture_age.is_some_and(|age| age < CAPTURE_HEALTH_INTERVAL_MS);
            let captured_at_unix_ms = capture_age.map(|age| emitted_at_unix_ms.saturating_sub(age));
            json!({"schema_version":2,"event":"capture_health","frame_count":frame_count,
                "frame_width":frame_width,"frame_height":frame_height,"captured_at_ms":captured_at_ms,
                "captured_at_unix_ms":captured_at_unix_ms,
                "generation":generation,"epoch":epoch,"fresh_capture":fresh_capture,"identity":identity,
                "recording_enabled":false,"recorded_frames":0})
        }
        LiveEvent::Table {
            game_phase,
            hero_cards,
            board,
            action_required,
        } => {
            json!({"schema_version":2,"event":"table","game_phase":game_phase,"hero_cards":hero_cards,"board":board,"action_required":action_required})
        }
        LiveEvent::Discarded { generation, reason } => {
            json!({"schema_version":2,"event":"discarded","generation":generation,"reason":reason})
        }
    };
    record
        .as_object_mut()
        .unwrap()
        .insert("emitted_at_unix_ms".into(), json!(emitted_at_unix_ms));
    Ok(Some(record))
}

/// Gap-only integration: no GameState/player/seat adapter can grant history trust.
struct AdmittedHistory {
    observer: Observer,
    ids: RandomState,
    session_id: Id,
    sequence: u64,
    last_generation: u64,
    last_captured_at_ms: Option<u64>,
    minimum_epoch: u64,
}

impl AdmittedHistory {
    fn new() -> Result<Self, RunError> {
        let ids = RandomState::new();
        let session_id = Id(ids.hash_one((std::process::id(), unix_ms()?)).max(1));
        Ok(Self {
            observer: Observer::default(),
            ids,
            session_id,
            sequence: 0,
            last_generation: 0,
            last_captured_at_ms: None,
            minimum_epoch: 0,
        })
    }

    fn record_admission(&mut self, ticket: &Ticket, now_ms: u64, config: &RuntimeConfig) -> bool {
        // A blocked stdout write must not turn an expired observation into a capture.
        let Some(age) = now_ms.checked_sub(ticket.captured_at_ms) else {
            return false;
        };
        if age >= config.max_frame_age_ms.min(config.decision_budget_ms)
            || ticket.generation <= self.last_generation
            || ticket.epoch < self.minimum_epoch
            || self
                .last_captured_at_ms
                .is_some_and(|last| ticket.captured_at_ms < last)
        {
            return false;
        }
        let Some(sequence) = self.sequence.checked_add(1) else {
            return false;
        };
        self.sequence = sequence;
        self.last_generation = ticket.generation;
        self.last_captured_at_ms = Some(ticket.captured_at_ms);
        self.minimum_epoch = ticket.epoch;
        // Hash only run/process/window provenance, never names or model fields.
        let table_id = Id(self
            .ids
            .hash_one((
                self.session_id.0,
                ticket.identity.process_id,
                ticket.identity.hwnd,
            ))
            .max(1));
        let _ = self.observer.record_gap(
            Capture {
                session_id: self.session_id,
                table_id,
                sequence,
                captured_at_ms: ticket.captured_at_ms,
                ticket: Id(ticket.generation.max(1)),
            },
            GapReason::UnvalidatedSource,
        );
        true
    }

    fn invalidate(&mut self, generation: u64, epoch: u64) {
        // Every admitted capture already broke continuity with UnvalidatedSource.
        // Reject replay without manufacturing another capture or resetting the ledger.
        self.last_generation = self.last_generation.max(generation);
        self.minimum_epoch = self.minimum_epoch.max(epoch);
    }
}

fn history_record(observer: &Observer, emitted_at_unix_ms: u64) -> serde_json::Value {
    json!({"schema_version":2,"event":"history","summary":observer.summary(),
        "emitted_at_unix_ms":emitted_at_unix_ms})
}

fn emit_with_history(
    record: &serde_json::Value,
    ticket: Option<&Ticket>,
    history: &mut AdmittedHistory,
    clock: &impl Clock,
    config: &RuntimeConfig,
    sink: &mut impl FnMut(&serde_json::Value) -> Result<(), RunError>,
) -> Result<(), RunError> {
    sink(record)?;
    match record["event"].as_str() {
        Some("observation_invalidated") => {
            if let (Some(generation), Some(epoch)) =
                (record["generation"].as_u64(), record["epoch"].as_u64())
            {
                history.invalidate(generation, epoch);
            }
        }
        Some("observation") => {
            if ticket.is_some_and(|ticket| history.record_admission(ticket, clock.now_ms(), config))
            {
                sink(&history_record(&history.observer, unix_ms()?))?;
            }
        }
        _ => {}
    }
    Ok(())
}

pub fn run(options: Options) -> Result<(), RunError> {
    if !cfg!(target_os = "windows") {
        return Err(RunError::Message(
            "live capture requires Windows 10 version 1903 or later; use --stdin on this platform"
                .into(),
        ));
    }
    emit(&configuration_event(&options))?;
    if !options.discovery.has_identity() {
        emit(
            &json!({"schema_version":2,"event":"status","state":"configuration_required",
            "reason":"run --list-windows; configure --exe-name using the actual executable name"}),
        )?;
        return Err(RunError::Message(
            "no calibrated application identity configured".into(),
        ));
    }
    let backend = LayaBackend::new(options.vlm, lobby_size(&options.discovery))
        .map_err(|error| RunError::Message(error.to_string()))?;
    let pipeline = Pipeline::new();
    let worker =
        ThreadWorker::new(move |job| analyze_frame(&backend, &pipeline, &job.frame, job.deadline));
    let poll_ms = options.runtime.poll_ms;
    let config = options.runtime.clone();
    let mut runtime = LiveRuntime::new(
        PlatformCapture::default(),
        worker,
        options.discovery,
        options.runtime,
    )
    .map_err(|e| RunError::Message(e.into()))?;
    let clock = MonotonicClock::default();
    let mut history = AdmittedHistory::new()?;
    loop {
        for event in runtime.tick(&clock) {
            let ticket = match &event {
                LiveEvent::Observation { ticket, .. }
                | LiveEvent::Recommendation { ticket, .. } => Some(ticket.clone()),
                _ => None,
            };
            let emitted_at = unix_ms()?;
            match event_record(event, clock.now_ms(), emitted_at, &config)? {
                Some(record) => emit_with_history(
                    &record,
                    ticket.as_ref(),
                    &mut history,
                    &clock,
                    &config,
                    &mut emit,
                )?,
                None => {
                    runtime.publication_dropped();
                    let ticket = ticket.expect("only leased events can expire at publication");
                    emit(
                        &json!({"schema_version":2,"event":"discarded","generation":ticket.generation,
                        "reason":"publication-expired","emitted_at_unix_ms":emitted_at}),
                    )?;
                    emit_with_history(
                        &json!({"schema_version":2,"event":"observation_invalidated","generation":ticket.generation,
                        "epoch":ticket.epoch,"identity":ticket.identity,"reason":"publication-expired",
                        "emitted_at_unix_ms":emitted_at}),
                        None,
                        &mut history,
                        &clock,
                        &config,
                        &mut emit,
                    )?;
                }
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(poll_ms));
    }
}

pub fn support_script(name: &str) -> Result<PathBuf, RunError> {
    let candidates = [
        std::env::var_os("COINPOKER_SUPPORT_DIR").map(PathBuf::from),
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(PathBuf::from)),
        std::env::current_dir().ok(),
        Some(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")),
    ];
    candidates.into_iter().flatten().map(|dir| dir.join("scripts").join(name))
        .find(|path| path.is_file()).ok_or_else(|| RunError::Message(format!("missing scripts/{name}; run from the repository or unpack the complete release artifact")))
}

pub fn doctor(options: Options) -> Result<(), RunError> {
    let script = support_script("doctor.py")?;
    let interpreter = if cfg!(windows) { "python" } else { "python3" };
    let mut command = Command::new(interpreter);
    command
        .arg(script)
        .arg("--binary")
        .arg(std::env::current_exe()?)
        .env("COINPOKER_VLM_ENDPOINT", options.vlm.endpoint)
        .env("COINPOKER_VLM_MODEL", options.vlm.model);
    for (name, value) in [
        ("COINPOKER_EXE_NAME", options.discovery.exe_name),
        (
            "COINPOKER_PID",
            options.discovery.process_id.map(|p| p.to_string()),
        ),
        (
            "COINPOKER_WINDOW_HWND",
            options
                .discovery
                .window_hwnd
                .map(|hwnd| format!("0x{hwnd:x}")),
        ),
        ("COINPOKER_WINDOW_TITLE", options.discovery.table_title),
        ("COINPOKER_LOBBY_TITLE", options.discovery.lobby_title),
        (
            "COINPOKER_LOBBY_SIZE",
            match (
                options.discovery.lobby_width,
                options.discovery.lobby_height,
            ) {
                (Some(width), Some(height)) if width > 0 && height > 0 => {
                    Some(format!("{width}x{height}"))
                }
                _ => None,
            },
        ),
    ] {
        if let Some(value) = value {
            command.env(name, value);
        } else {
            command.env_remove(name);
        }
    }
    let status = command.status()?;
    if status.success() {
        Ok(())
    } else {
        Err(RunError::Message(
            "doctor found failed or blocked checks; see its report".into(),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ingest::vlm::{VlmError, VlmOutput, VlmResponseError};
    use std::cell::RefCell;

    const SENTINEL: &str = "SYNTHETIC_REJECTED_FIELD_SENTINEL";

    struct ScriptedBackend(RefCell<Option<Result<VlmOutput, VlmError>>>);

    impl VlmBackend for ScriptedBackend {
        fn analyze(&self, _: &Frame, prompt: &str) -> Result<VlmOutput, VlmError> {
            assert_eq!(prompt, ingest::prompt::build_analysis_prompt());
            self.0.borrow_mut().take().expect("one combined VLM job")
        }
    }

    fn assert_worker_category(response: Result<VlmOutput, VlmError>, category: &str) {
        let backend = ScriptedBackend(RefCell::new(Some(response)));
        let frame = Frame::new(1, 1, vec![0, 0, 0, 255]).unwrap();
        let failure = analyze_frame(
            &backend,
            &Pipeline::new(),
            &frame,
            Instant::now() + std::time::Duration::from_secs(5),
        )
        .err()
        .expect("invalid input must suppress all advice");
        assert_eq!(failure.code, category);
        let record = json!({"schema_version":2,"event":"status","state":"recovering",
            "reason":failure.code,"identity":null})
        .to_string();
        assert!(!record.contains(SENTINEL));
        assert!(!record.contains("invalid game state"));
        assert!(!record.contains("completion finish reason"));
        assert!(!record.contains("finish_reason"));
    }

    #[test]
    fn safe_category_live_screen_failures_do_not_leak_rejected_fields() {
        let complete = json!({
            "screen_kind":"poker_table",
            "evidence":{"table_layout":true,"hero_cards":true,"board_area":true,
                "pot":true,"action_controls":true,"readable":true},
            "state":{"game_phase":"preflop","hero_cards":[
                {"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],
                "board":[],"pot_size":100,"to_call":0,"hero_chips":1000,
                "min_raise_to":null,"max_raise_to":null,"players":[
                    {"name":"Hero","chips":1000,"last_action":null,"bet_amount":50},
                    {"name":SENTINEL,"chips":1000,"last_action":null,"bet_amount":50}],
                "action_required":true,"available_actions":["check"]}
        });
        for category in [
            "board-count",
            "hero-cards",
            "action-required",
            "schema",
            "invalid-observation",
        ] {
            let mut response = complete.clone();
            match category {
                "board-count" => {
                    response["state"]["board"] = json!([{"rank":SENTINEL,"suit":"clubs"}])
                }
                "hero-cards" => response["state"]["hero_cards"][0]["rank"] = json!(SENTINEL),
                "action-required" => response["state"]["available_actions"] = json!([SENTINEL]),
                "schema" => response["screen_kind"] = json!(SENTINEL),
                "invalid-observation" => response["state"]["players"][0]["name"] = json!(SENTINEL),
                _ => unreachable!(),
            }
            assert_worker_category(
                Ok(VlmOutput {
                    text: response.to_string(),
                }),
                category,
            );
        }
    }

    #[test]
    fn safe_category_live_backend_failures_ignore_backend_messages() {
        for (error, category) in [
            (VlmError::Deadline, "decision-deadline-exceeded"),
            (
                VlmError::Parse(VlmResponseError::Schema),
                "invalid-vlm-schema",
            ),
            (
                VlmError::Parse(VlmResponseError::Encoding),
                "invalid-vlm-encoding",
            ),
            (VlmError::Parse(VlmResponseError::Size), "invalid-vlm-size"),
            (
                VlmError::Request(format!(
                    "missing or unsupported completion finish reason {SENTINEL}"
                )),
                "vlm-unavailable",
            ),
            (VlmError::Unavailable(SENTINEL.into()), "vlm-unavailable"),
            (VlmError::ImageEncoding(SENTINEL.into()), "vlm-unavailable"),
            (VlmError::InvalidEndpoint(SENTINEL), "vlm-unavailable"),
            (
                VlmError::Server {
                    status: 404,
                    body: SENTINEL.into(),
                },
                "unsupported-model-api",
            ),
            (
                VlmError::Server {
                    status: 500,
                    body: SENTINEL.into(),
                },
                "vlm-unavailable",
            ),
            (
                VlmError::Server {
                    status: 302,
                    body: SENTINEL.into(),
                },
                "vlm-unavailable",
            ),
        ] {
            assert_worker_category(Err(error), category);
        }
    }

    #[test]
    fn configuration_event_reports_laya_perception() {
        let options = crate::config::parse(
            ["--lobby-size", "1280x1032", "--laya-threshold", "0.9"].map(String::from),
            |_| None,
        )
        .unwrap();
        assert_eq!(lobby_size(&options.discovery), Some((1280, 1032)));
        let event = configuration_event(&options);
        assert_eq!(event["event"], "configuration");
        assert_eq!(event["perception"], "laya-vision");
        assert_eq!(event["question_set_version"], "0.4.0");
        assert_eq!(event["laya_calibrated"], false);
        assert!((event["laya_threshold"].as_f64().unwrap() - 0.9).abs() < 1e-6);
        assert_eq!(event["model"], "coinpoker-laya-vision");
        assert_eq!(event["vlm_timeout_secs"], 5);
        assert_eq!(event["runtime"]["decision_budget_ms"], 5_000);
        assert_eq!(event["runtime"]["max_frame_age_ms"], 8_000);
        assert_eq!(event["decision_publication_reserve_ms"], 300);
        assert_eq!(event["quality_approved"], false);
        assert_eq!(event["recording_enabled"], false);
        assert_eq!(event["visual_calibration"], "not_validated");
        assert!(event.get("identity_configured").is_some() && event.get("runtime").is_some());

        let defaults = crate::config::parse(std::iter::empty(), |_| None).unwrap();
        assert_eq!(lobby_size(&defaults.discovery), None);
        assert!(configuration_event(&defaults)["laya_threshold"].is_null());
        LayaBackend::new(defaults.vlm, None).expect("default backend constructs without I/O");
    }

    fn observation_event(actionable: bool) -> LiveEvent<ui::widgets::DecisionView> {
        let state: ingest::parser::GameState = serde_json::from_value(json!({
            "game_phase":"preflop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],
            "board":[],"pot_size":100,"to_call":0,"hero_chips":1000,
            "min_raise_to":null,"max_raise_to":null,"players":[
                {"name":"Hero","chips":1000,"last_action":null,"bet_amount":50},
                {"name":SENTINEL,"chips":1000,"last_action":null,"bet_amount":50}],
            "action_required":actionable,"available_actions":if actionable { vec!["check"] } else { vec![] }
        })).unwrap();
        LiveEvent::Observation {
            ticket: Ticket {
                identity: ingest::discovery::TableIdentity {
                    exe_name: "Synthetic.exe".into(),
                    process_id: 42,
                    hwnd: 7,
                },
                generation: 2,
                epoch: 3,
                captured_at_ms: 100,
            },
            value: ingest::runtime::ObservationView::from_accepted_state(&state),
            valid_for_ms: 4_900,
        }
    }

    #[test]
    fn current_observation_records_are_allowlisted_leased_and_name_private() {
        let config = RuntimeConfig::default();
        for actionable in [true, false] {
            let event = event_record(observation_event(actionable), 200, 10_000, &config)
                .unwrap()
                .unwrap();
            assert_eq!(event["schema_version"], 2);
            assert_eq!(event["event"], "observation");
            assert_eq!(event["observation"]["captured_at_ms"], 100);
            assert_eq!(event["observation"]["generation"], 2);
            assert_eq!(event["observation"]["epoch"], 3);
            assert_eq!(event["captured_at_unix_ms"], 9_900);
            assert_eq!(event["emitted_at_unix_ms"], 10_000);
            assert_eq!(event["expires_at_unix_ms"], 14_900);
            assert_eq!(event["valid_for_ms"], 4_900);
            assert_eq!(event["quality_approved"], false);
            assert_eq!(event["hero_seated"], true);
            assert_eq!(event["action_required"], actionable);
            assert_eq!(
                event["role"],
                if actionable {
                    "your_turn"
                } else {
                    "seated_waiting"
                }
            );
            assert!(event["acting_seat"].is_null() && event["acting_to_call"].is_null());
            assert_eq!(event["wagers"], json!([]));
            assert_eq!(event["hero_chips"], 1_000);
            assert_eq!(
                event["metrics"],
                json!({"hand_rank":null,"pot_odds":null,"draw":null,"equity_pct":null})
            );
            assert!(event.get("players").is_none() && event.get("state").is_none());
            assert!(!event.to_string().contains(SENTINEL));
            assert!(!event.to_string().contains("Hero"));
            if actionable {
                assert_eq!(event["available_actions"], json!(["check"]));
                assert_eq!(event["to_call"], 0);
                assert_eq!(event["hero_chips"], 1_000);
            } else {
                for field in [
                    "available_actions",
                    "to_call",
                    "min_raise_to",
                    "max_raise_to",
                ] {
                    assert!(event[field].is_null(), "{field} must stay unavailable");
                }
            }
        }
    }

    #[test]
    fn current_laya_unseated_admission_propagates_without_hero_placeholders() {
        let state: ingest::parser::GameState = serde_json::from_value(json!({
            "game_phase":"preflop","hero_cards":[],"board":[],"pot_size":100,
            "to_call":0,"hero_chips":0,"min_raise_to":null,"max_raise_to":null,
            "players":[],"action_required":false,"available_actions":[]
        }))
        .unwrap();
        let mut observation = observation_event(false);
        if let LiveEvent::Observation { value, .. } = &mut observation {
            *value = ingest::runtime::ObservationView::from_accepted_state(&state);
            assert_eq!(value.role, ingest::runtime::ObservationRole::Uncertain);
        }
        let record = event_record(observation, 200, 10_000, &RuntimeConfig::default())
            .unwrap()
            .unwrap();
        assert_eq!(record["role"], "observing");
        assert_eq!(record["hero_seated"], false);
        assert_eq!(record["action_required"], false);
        assert_eq!(
            record["verified_fields"],
            json!(["pot_size", "hero_seated", "action_required"])
        );
        for field in [
            "to_call",
            "hero_chips",
            "min_raise_to",
            "max_raise_to",
            "acting_seat",
            "acting_to_call",
        ] {
            assert!(record[field].is_null(), "{field} has no unseated evidence");
        }
        assert_eq!(record["quality_approved"], false);
        assert_eq!(
            record["metrics"],
            json!({"hand_rank":null,"pot_odds":null,"draw":null,"equity_pct":null})
        );
        assert_eq!(record["expires_at_unix_ms"], 14_900);
    }

    #[test]
    fn publication_rechecks_total_deadline_and_frame_age_without_renewing_leases() {
        let config = RuntimeConfig::default();
        for now in [99, 5_100, 6_000] {
            assert!(event_record(observation_event(false), now, 10_000, &config)
                .unwrap()
                .is_none());
        }
        let last_millisecond = event_record(observation_event(false), 5_099, 20_000, &config)
            .unwrap()
            .unwrap();
        assert_eq!(last_millisecond["valid_for_ms"], 1);
        assert_eq!(last_millisecond["expires_at_unix_ms"], 20_001);
        let younger_cap = RuntimeConfig {
            max_frame_age_ms: 500,
            ..RuntimeConfig::default()
        };
        assert!(
            event_record(observation_event(false), 600, 10_000, &younger_cap)
                .unwrap()
                .is_none()
        );
        let mut event = observation_event(false);
        if let LiveEvent::Observation { valid_for_ms, .. } = &mut event {
            *valid_for_ms = 10;
        }
        assert_eq!(
            event_record(event, 200, 10_000, &config).unwrap().unwrap()["valid_for_ms"],
            10
        );
    }

    #[test]
    fn decision_publication_uses_the_same_total_deadline() {
        let ticket = match observation_event(false) {
            LiveEvent::Observation { ticket, .. } => ticket,
            _ => unreachable!(),
        };
        let value = ui::widgets::DecisionView {
            action: "check".into(),
            amount: 0,
            ev: 0.0,
            pot_odds: None,
            equity: 0.0,
            break_even: None,
            opponent: Some("unknown".into()),
            confidence: None,
        };
        let event = LiveEvent::Recommendation {
            ticket,
            value,
            valid_for_ms: 7_900,
        };
        assert!(
            event_record(event, 5_100, 10_000, &RuntimeConfig::default())
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn health_and_invalidation_have_time_and_no_advice_or_recording_claim() {
        let config = RuntimeConfig::default();
        let event = event_record(
            LiveEvent::CaptureHealth {
                frame_count: 12,
                frame_width: None,
                frame_height: None,
                captured_at_ms: None,
                generation: 2,
                epoch: 4,
                fresh_capture: false,
                identity: None,
            },
            300,
            10_000,
            &config,
        )
        .unwrap()
        .unwrap();
        assert_eq!(event["event"], "capture_health");
        assert_eq!(event["frame_count"], 12);
        assert_eq!(event["fresh_capture"], false);
        assert_eq!(event["recording_enabled"], false);
        assert_eq!(event["recorded_frames"], 0);
        assert_eq!(event["emitted_at_unix_ms"], 10_000);
        assert!(event["identity"].is_null() && event["frame_width"].is_null());
        let event = event_record(
            LiveEvent::ObservationInvalidated {
                reason: "capture-unavailable",
                generation: 2,
                epoch: 4,
                identity: None,
            },
            300,
            10_000,
            &config,
        )
        .unwrap()
        .unwrap();
        assert_eq!(event["event"], "observation_invalidated");
        assert_eq!(event["epoch"], 4);
        assert_eq!(event["emitted_at_unix_ms"], 10_000);
        assert!(event.get("valid_for_ms").is_none() && event.get("available_actions").is_none());
    }

    #[test]
    fn delayed_health_publication_cannot_claim_a_fresh_capture() {
        let event = event_record(
            LiveEvent::CaptureHealth {
                frame_count: 12,
                frame_width: Some(160),
                frame_height: Some(120),
                captured_at_ms: Some(300),
                generation: 2,
                epoch: 4,
                fresh_capture: true,
                identity: None,
            },
            1_300,
            10_000,
            &RuntimeConfig::default(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(event["fresh_capture"], false);
        assert_eq!(event["captured_at_unix_ms"], 9_000);
        assert_eq!(event["frame_count"], 12);
    }

    #[test]
    fn weak_table_record_has_no_authoritative_source_or_lease() {
        let event = event_record(
            LiveEvent::Table {
                game_phase: ingest::parser::GamePhase::Preflop,
                hero_cards: vec![],
                board: vec![],
                action_required: false,
            },
            300,
            10_000,
            &RuntimeConfig::default(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(event["event"], "table");
        for field in [
            "observation",
            "available_actions",
            "valid_for_ms",
            "expires_at_unix_ms",
            "quality_approved",
        ] {
            assert!(
                event.get(field).is_none(),
                "weak table may not acquire {field}"
            );
        }
    }

    struct HistoryClock(std::cell::Cell<u64>);
    impl Clock for HistoryClock {
        fn now_ms(&self) -> u64 {
            self.0.get()
        }
    }

    fn history_source() -> (Ticket, serde_json::Value) {
        let event = observation_event(true);
        let ticket = match &event {
            LiveEvent::Observation { ticket, .. } => ticket.clone(),
            _ => unreachable!(),
        };
        let record = event_record(event, 200, 10_000, &RuntimeConfig::default())
            .unwrap()
            .unwrap();
        (ticket, record)
    }

    #[test]
    fn admitted_observation_emits_one_opaque_gap_summary_after_successful_write() {
        let mut history = AdmittedHistory::new().unwrap();
        let (ticket, record) = history_source();
        let clock = HistoryClock(std::cell::Cell::new(200));
        let mut written = Vec::new();
        emit_with_history(
            &record,
            Some(&ticket),
            &mut history,
            &clock,
            &RuntimeConfig::default(),
            &mut |record| {
                written.push(record.clone());
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(written.len(), 2);
        assert_eq!(written[0]["event"], "observation");
        assert_eq!(written[1]["schema_version"], 2);
        assert_eq!(written[1]["event"], "history");
        assert!(written[1]["emitted_at_unix_ms"].as_u64().is_some());
        let summary = &written[1]["summary"];
        assert!(summary["session_id"].as_u64().unwrap() > 0);
        assert!(summary["table_id"].as_u64().unwrap() > 0);
        assert_eq!(summary["coverage"]["accepted_captures"], 1);
        assert_eq!(summary["coverage"]["unvalidated_captures"], 1);
        assert_eq!(summary["coverage"]["complete"], false);
        assert_eq!(summary["coverage"]["ordered_prefix"], false);
        assert_eq!(
            summary["counts"],
            json!(opponent_model::observer::ActionCounts::default())
        );
        assert_eq!(summary["occupants"], json!([]));
        assert!(summary["hand_id"].is_null());
        let gap = &summary["events"][0];
        assert_eq!(gap["event_sequence"], 1);
        assert_eq!(gap["event"], "gap");
        assert_eq!(gap["reason"], "unvalidated_source");
        assert_eq!(gap["capture"]["sequence"], 1);
        assert_eq!(gap["capture"]["captured_at_ms"], ticket.captured_at_ms);
        assert_eq!(gap["capture"]["ticket"], ticket.generation.max(1));
        let json = written[1].to_string();
        for private in [
            SENTINEL,
            "Hero",
            "Synthetic.exe",
            "players",
            "hero_cards",
            "pot_size",
        ] {
            assert!(
                !json.contains(private),
                "history must not contain {private}"
            );
        }
        assert_eq!(
            history_record(&history.observer, 12_345)["emitted_at_unix_ms"],
            12_345
        );

        emit_with_history(
            &record,
            Some(&ticket),
            &mut history,
            &clock,
            &RuntimeConfig::default(),
            &mut |record| {
                written.push(record.clone());
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(
            written.len(),
            3,
            "duplicate source must not re-admit or emit another history summary"
        );
        assert_eq!(history.sequence, 1);
        assert_eq!(history.observer.summary().gaps, 1);
    }

    #[test]
    fn weak_table_and_failed_observation_writes_cannot_admit_history() {
        let mut history = AdmittedHistory::new().unwrap();
        let (ticket, record) = history_source();
        let clock = HistoryClock(std::cell::Cell::new(200));
        let mut written = Vec::new();
        let weak = json!({"schema_version":2,"event":"table","hero_cards":[],"board":[]});
        emit_with_history(
            &weak,
            Some(&ticket),
            &mut history,
            &clock,
            &RuntimeConfig::default(),
            &mut |record| {
                written.push(record.clone());
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(written, vec![weak]);
        assert_eq!(history.sequence, 0);
        let error = emit_with_history(
            &record,
            Some(&ticket),
            &mut history,
            &clock,
            &RuntimeConfig::default(),
            &mut |_| Err(RunError::Message("synthetic-write-failure".into())),
        );
        assert!(error.is_err());
        assert!(history.observer.events().is_empty());
        assert_eq!(history.sequence, 0);
        assert_eq!(history.observer.summary().coverage.accepted_captures, 0);
    }

    #[test]
    fn observation_expired_while_writing_cannot_become_a_history_capture() {
        let mut history = AdmittedHistory::new().unwrap();
        let (ticket, record) = history_source();
        let clock = HistoryClock(std::cell::Cell::new(200));
        let config = RuntimeConfig::default();
        let mut written = Vec::new();
        emit_with_history(
            &record,
            Some(&ticket),
            &mut history,
            &clock,
            &config,
            &mut |record| {
                written.push(record.clone());
                clock
                    .0
                    .set(ticket.captured_at_ms + config.decision_budget_ms);
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(
            written.len(),
            1,
            "only the source-bound expired record exists, never a history admission"
        );
        assert!(history.observer.events().is_empty());
        assert_eq!(history.sequence, 0);
        assert!(
            !history.record_admission(&ticket, 99, &config),
            "future captures also fail closed"
        );
        let younger = RuntimeConfig {
            max_frame_age_ms: 500,
            ..config
        };
        assert!(!history.record_admission(&ticket, 600, &younger));
    }

    #[test]
    fn invalidation_blocks_old_sources_without_fabricating_another_capture() {
        let mut history = AdmittedHistory::new().unwrap();
        let (ticket, record) = history_source();
        let clock = HistoryClock(std::cell::Cell::new(200));
        let config = RuntimeConfig::default();
        let mut written = Vec::new();
        emit_with_history(
            &record,
            Some(&ticket),
            &mut history,
            &clock,
            &config,
            &mut |record| {
                written.push(record.clone());
                Ok(())
            },
        )
        .unwrap();
        let old_table = history.observer.summary().table_id;
        let invalidated = event_record(
            LiveEvent::ObservationInvalidated {
                reason: "capture-unavailable",
                generation: ticket.generation,
                epoch: ticket.epoch + 1,
                identity: None,
            },
            200,
            10_000,
            &config,
        )
        .unwrap()
        .unwrap();
        emit_with_history(
            &invalidated,
            None,
            &mut history,
            &clock,
            &config,
            &mut |record| {
                written.push(record.clone());
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(history.observer.events().len(), 1);
        assert_eq!(
            history.sequence, 1,
            "invalidation is not a fake captured frame"
        );
        assert!(!history.record_admission(&ticket, 200, &config));
        let mut next = ticket.clone();
        next.generation += 1;
        next.captured_at_ms += 100;
        assert!(
            !history.record_admission(&next, 200, &config),
            "new generation with retired epoch remains invalid"
        );
        next.epoch += 1;
        next.identity.hwnd += 1;
        assert!(history.record_admission(&next, 200, &config));
        let summary = history.observer.summary();
        assert_eq!(history.sequence, 2);
        assert_eq!(summary.coverage.accepted_captures, 2);
        assert_eq!(summary.coverage.unvalidated_captures, 2);
        assert_ne!(summary.table_id, old_table);
        assert_eq!(
            summary.counts,
            opponent_model::observer::ActionCounts::default()
        );
        assert!(
            summary.occupants.is_empty()
                && !summary.coverage.complete
                && !summary.coverage.ordered_prefix
        );
        let record = history_record(&history.observer, 12_345);
        assert_eq!(record["summary"]["events"][1]["event"], "gap");
        assert_eq!(record["summary"]["events"][1]["reason"], "identity_changed");
        assert_eq!(record["summary"]["events"][2]["event_sequence"], 3);
        assert_eq!(record["summary"]["events"][2]["capture"]["sequence"], 2);
        assert_eq!(
            record["summary"]["events"][2]["reason"],
            "unvalidated_source"
        );
    }

    #[test]
    fn a_new_run_does_not_inherit_history_or_admission_counters() {
        let (ticket, _) = history_source();
        let config = RuntimeConfig::default();
        let mut first = AdmittedHistory::new().unwrap();
        assert!(first.record_admission(&ticket, 200, &config));
        let prefix = first.observer.events().to_vec();
        let mut restarted = AdmittedHistory::new().unwrap();
        assert!(restarted.session_id.0 > 0);
        assert!(restarted.observer.events().is_empty());
        assert_eq!(restarted.sequence, 0);
        assert_eq!(
            restarted.observer.summary().coverage.unvalidated_captures,
            0
        );
        assert!(restarted.record_admission(&ticket, 200, &config));
        let summary = restarted.observer.summary();
        assert_eq!(summary.session_id, Some(restarted.session_id));
        assert_eq!(summary.events.len(), 1);
        assert_eq!(summary.events[0].event_sequence, 1);
        assert_eq!(summary.events[0].capture.sequence, 1);
        assert_eq!(summary.gaps, 1);
        assert!(summary.occupants.is_empty() && !summary.coverage.complete);
        assert_eq!(first.observer.events(), prefix.as_slice());
    }
}
