use super::*;
use ingest::vlm::{VlmError, VlmOutput, VlmResponseError};
use std::cell::RefCell;

fn emit_with_history(
    record: &serde_json::Value,
    ticket: Option<&Ticket>,
    history: &mut AdmittedHistory,
    clock: &impl Clock,
    config: &RuntimeConfig,
    sink: &mut impl FnMut(&serde_json::Value) -> Result<(), RunError>,
) -> Result<(), RunError> {
    super::emit_with_history(record, ticket, None, history, clock, config, sink)
}

// Existing publication tests exercise the explicitly disabled recorder path.
fn event_record(
    event: LiveEvent<crate::ui::widgets::DecisionView>,
    now_ms: u64,
    emitted_at_unix_ms: u64,
    config: &RuntimeConfig,
) -> Result<Option<serde_json::Value>, RunError> {
    super::event_record(
        event,
        now_ms,
        emitted_at_unix_ms,
        config,
        RecorderSnapshot::default(),
    )
}

#[test]
fn recorder_configuration_opt_in_is_truthful_and_has_no_private_path() {
    let options = crate::config::parse(
        ["--record-dir", ".local/captures"].map(String::from),
        |_| None,
    )
    .unwrap();
    let event = configuration_event(&options);
    assert_eq!(event["recording_enabled"], true);
    for private in [".local", "record_dir", "rgba", "png"] {
        assert!(!event.to_string().contains(private));
    }
}

#[test]
fn recorder_health_emits_only_durable_metadata_without_a_current_image_claim() {
    use ingest::recorder::RecorderStatus;
    for status in [
        RecorderStatus::Active,
        RecorderStatus::CountLimit,
        RecorderStatus::DiskLimit,
        RecorderStatus::IoFailure,
    ] {
        let event = super::event_record(
            LiveEvent::CaptureHealth {
                frame_count: 50,
                frame_width: Some(2),
                frame_height: Some(2),
                captured_at_ms: Some(200),
                generation: 3,
                epoch: 4,
                fresh_capture: true,
                identity: None,
            },
            1_500,
            10_000,
            &RuntimeConfig::default(),
            RecorderSnapshot {
                recording_enabled: true,
                recorded_frames: 2,
                recorded_bytes: 800,
                recording_status: status,
                recording_complete: status == RecorderStatus::Active,
            },
        )
        .unwrap()
        .unwrap();
        assert_eq!(event["recording_enabled"], true);
        assert_eq!(event["recorded_frames"], 2);
        assert_eq!(event["recorded_bytes"], 800);
        assert_eq!(
            event["recording_status"],
            serde_json::to_value(status).unwrap()
        );
        assert_eq!(
            event["recording_complete"],
            status == RecorderStatus::Active
        );
        assert_eq!(event["fresh_capture"], false);
        for private in ["path", "png", "rgba", ".local", "manifest", "image"] {
            assert!(!event.to_string().contains(private));
        }
    }
}

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
            "action_required":true,"available_actions":["check"],"confidence":null}
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
            "board-count" => response["state"]["board"] = json!([{"rank":SENTINEL,"suit":"clubs"}]),
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

fn observation_event(actionable: bool) -> LiveEvent<crate::ui::widgets::DecisionView> {
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
            captured_at_unix_ms: None,
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
    let value = crate::ui::widgets::DecisionView {
        action: "check".into(),
        amount: 0,
        sizing_provenance: None,
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
fn recorded_source_utc_is_not_rebased_and_clock_jumps_cannot_extend_a_lease() {
    let config = RuntimeConfig::default();
    let mut event = observation_event(false);
    if let LiveEvent::Observation { ticket, .. } = &mut event {
        ticket.captured_at_unix_ms = Some(10_000);
    }
    let record = event_record(event.clone(), 200, 10_250, &config)
        .unwrap()
        .unwrap();
    assert_eq!(record["captured_at_unix_ms"], 10_000);
    assert_eq!(record["observation"]["captured_at_unix_ms"], 10_000);
    assert_eq!(record["expires_at_unix_ms"], 15_000);
    assert_eq!(record["valid_for_ms"], 4_750);
    assert!(event_record(event.clone(), 200, 9_999, &config)
        .unwrap()
        .is_none());
    assert!(event_record(event.clone(), 200, 15_000, &config)
        .unwrap()
        .is_none());
    assert!(event_record(event, 5_100, 10_250, &config)
        .unwrap()
        .is_none());
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
        json!(core_engine::opponent::observer::ActionCounts::default())
    );
    assert_eq!(summary["occupants"], json!([]));
    assert!(summary["hand_id"].is_null());
    let gap = &summary["events"][0];
    assert_eq!(gap["event_sequence"], 1);
    assert_eq!(gap["event"], "gap");
    assert_eq!(gap["reason"], "unvalidated_source");
    assert_eq!(gap["capture"]["sequence"], 1);
    assert_eq!(gap["capture"]["captured_at_ms"], ticket.captured_at_ms);
    assert_eq!(gap["capture"]["ticket"], history.sequence);
    assert_eq!(written[1]["history_snapshot"], true);
    assert_eq!(written[1]["history_since"], 0);
    assert_eq!(written[1]["history_through"], 1);
    assert_eq!(written[1]["history_omitted"], 0);
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
        history_record(&mut history, 12_345)["emitted_at_unix_ms"],
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
        core_engine::opponent::observer::ActionCounts::default()
    );
    assert!(
        summary.occupants.is_empty()
            && !summary.coverage.complete
            && !summary.coverage.ordered_prefix
    );
    let record = history_record(&mut history, 12_345);
    // The new window is a new table, so the cursor cannot extend across it.
    assert_eq!(record["history_snapshot"], true);
    assert_eq!(record["history_since"], 1);
    assert_eq!(record["history_through"], 3);
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
fn history_delta_reconstructs_the_same_bounded_view_as_a_snapshot() {
    let mut history = AdmittedHistory::new().unwrap();
    let (ticket, record) = history_source();
    let clock = HistoryClock(std::cell::Cell::new(0));
    let config = RuntimeConfig::default();
    let mut merged: Vec<u64> = Vec::new();
    let mut deltas = 0u32;
    let mut snapshots = 0u32;
    for index in 1..=300u64 {
        let mut next = ticket.clone();
        next.generation = ticket.generation + index;
        next.captured_at_ms = ticket.captured_at_ms + index;
        clock.0.set(next.captured_at_ms + 1);
        emit_with_history(
            &record,
            Some(&next),
            &mut history,
            &clock,
            &config,
            &mut |value| {
                if value["event"] == "history" {
                    assert_eq!(value["history_omitted"], 0);
                    if value["history_snapshot"] == true {
                        merged.clear();
                        snapshots += 1;
                    } else {
                        deltas += 1;
                    }
                    for event in value["summary"]["events"].as_array().unwrap() {
                        merged.push(event["event_sequence"].as_u64().unwrap());
                    }
                    assert_eq!(
                        value["history_through"].as_u64().unwrap(),
                        merged.last().copied().unwrap_or(0),
                        "the cursor is exactly the newest delivered event"
                    );
                }
                Ok(())
            },
        )
        .unwrap();
    }
    assert!(
        snapshots >= 2 && deltas >= 200,
        "{snapshots} snapshots, {deltas} deltas"
    );
    assert!(
        merged.windows(2).all(|pair| pair[1] == pair[0] + 1),
        "deltas extend one contiguous ascending run"
    );
    let view: Vec<u64> = history
        .observer
        .summary()
        .events
        .iter()
        .map(|event| event.event_sequence)
        .collect();
    assert_eq!(view.len(), MAX_EVENT_VIEW);
    assert!(merged.len() >= view.len());
    assert_eq!(
        merged[merged.len() - view.len()..].to_vec(),
        view,
        "merged deltas reconstruct the bounded view a snapshot would give"
    );
}

#[test]
fn a_long_session_stays_bounded_where_full_reemission_would_exceed_the_log_cap() {
    // The budget `MAX_LOG` enforced in scripts/laya_capture.py when the 2026-10-25
    // session failed. The supervisor's budget is larger now, but unbounded
    // re-emission is still the defect this test guards.
    const MAX_LOG: usize = 20 * 1024 * 1024;
    let mut history = AdmittedHistory::new().unwrap();
    let (ticket, record) = history_source();
    let clock = HistoryClock(std::cell::Cell::new(0));
    let config = RuntimeConfig::default();
    let mut bounded = 0usize;
    let mut naive = 0usize;
    for index in 1..=700u64 {
        let mut next = ticket.clone();
        next.generation = ticket.generation + index;
        next.captured_at_ms = ticket.captured_at_ms + index;
        clock.0.set(next.captured_at_ms + 1);
        emit_with_history(
            &record,
            Some(&next),
            &mut history,
            &clock,
            &config,
            &mut |value| {
                if value["event"] == "history" {
                    bounded += value.to_string().len() + 1;
                }
                Ok(())
            },
        )
        .unwrap();
        // What the pre-fix emitter wrote after this same admission.
        naive += json!({"schema_version": 2, "event": "history",
            "summary": history.observer.summary(), "emitted_at_unix_ms": 0})
        .to_string()
        .len()
            + 1;
    }
    assert!(
        naive > MAX_LOG,
        "the unbounded re-emission would have blown the cap: {naive} bytes"
    );
    assert!(
        bounded < MAX_LOG / 5,
        "a bounded session stays well inside the cap: {bounded} bytes"
    );
    assert!(bounded * 10 < naive);
    println!("BOUNDED_HISTORY_BYTES={bounded} UNBOUNDED_HISTORY_BYTES={naive} MAX_LOG={MAX_LOG}");
}

#[test]
fn history_snapshot_on_target_change_and_bounded_cadence() {
    let mut history = AdmittedHistory::new().unwrap();
    let (ticket, record) = history_source();
    let clock = HistoryClock(std::cell::Cell::new(0));
    let config = RuntimeConfig::default();
    let mut snapshots = Vec::new();
    for index in 1..=(5 + u64::from(HISTORY_SNAPSHOT_INTERVAL) + 1) {
        let mut next = ticket.clone();
        next.generation = ticket.generation + index;
        next.captured_at_ms = ticket.captured_at_ms + index;
        if index >= 5 {
            // A resize keeps the approved identity; a new window is a new table,
            // so the consumer's cursor belongs to the old one from here on.
            next.identity.hwnd += 1;
        }
        clock.0.set(next.captured_at_ms + 1);
        emit_with_history(
            &record,
            Some(&next),
            &mut history,
            &clock,
            &config,
            &mut |value| {
                if value["event"] == "history" {
                    assert_eq!(value["history_omitted"], 0);
                    if value["history_snapshot"] == true {
                        snapshots.push(index);
                    }
                }
                Ok(())
            },
        )
        .unwrap();
    }
    assert_eq!(
        snapshots,
        vec![1, 5, 5 + u64::from(HISTORY_SNAPSHOT_INTERVAL) + 1],
        "a complete view opens the session, follows a target change, and repeats on cadence"
    );
}

#[test]
fn history_reports_events_a_single_record_cannot_carry() {
    let mut history = AdmittedHistory::new().unwrap();
    let (ticket, record) = history_source();
    let clock = HistoryClock(std::cell::Cell::new(0));
    let config = RuntimeConfig::default();
    let mut first = ticket.clone();
    first.generation = ticket.generation + 1;
    first.captured_at_ms = ticket.captured_at_ms + 1;
    clock.0.set(first.captured_at_ms + 1);
    let mut written = Vec::new();
    emit_with_history(
        &record,
        Some(&first),
        &mut history,
        &clock,
        &config,
        &mut |value| {
            written.push(value.clone());
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(written[1]["history_snapshot"], true);
    assert_eq!(written[1]["history_through"], 1);
    // More events than one bounded view can hold arrive before the next emission.
    for index in 2..=(MAX_EVENT_VIEW as u64 + 2) {
        let mut next = ticket.clone();
        next.generation = ticket.generation + index;
        next.captured_at_ms = ticket.captured_at_ms + index;
        assert!(history.record_admission(&next, next.captured_at_ms + 1, &config));
    }
    let record = history_record(&mut history, 12_345);
    assert_eq!(record["history_snapshot"], true);
    assert_eq!(record["history_through"], MAX_EVENT_VIEW as u64 + 2);
    assert_eq!(
        record["history_omitted"], 1,
        "a full view that cannot hold every pending event says so"
    );
    assert_eq!(
        record["summary"]["events"].as_array().unwrap().len(),
        MAX_EVENT_VIEW
    );
}

#[test]
fn current_capture_health_tracks_unvalidated_gaps_without_inference() {
    let mut history = AdmittedHistory::new().unwrap();
    let (mut ticket, mut observation) = history_source();
    let health = json!({"schema_version":2,"event":"capture_health","fresh_capture":true});
    let clock = HistoryClock(std::cell::Cell::new(200));
    let config = RuntimeConfig::default();
    let mut written = Vec::new();
    for _ in 0..2 {
        emit_with_history(
            &health,
            Some(&ticket),
            &mut history,
            &clock,
            &config,
            &mut |v| {
                written.push(v.clone());
                Ok(())
            },
        )
        .unwrap();
    }
    assert_eq!(
        history.sequence, 1,
        "one capture cannot be renewed by a heartbeat"
    );
    ticket.captured_at_ms += 100;
    emit_with_history(
        &health,
        Some(&ticket),
        &mut history,
        &clock,
        &config,
        &mut |v| {
            written.push(v.clone());
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(
        history.sequence, 2,
        "unchanged content can still yield a new real capture"
    );
    let table = history.observer.summary().table_id;
    let session = history.session_id;
    ticket.generation += 1;
    ticket.captured_at_ms += 100;
    clock.0.set(300);
    observation["role"] = json!("your_turn");
    observation["quality_approved"] = json!(true);
    emit_with_history(
        &observation,
        Some(&ticket),
        &mut history,
        &clock,
        &config,
        &mut |v| {
            written.push(v.clone());
            Ok(())
        },
    )
    .unwrap();
    let summary = history.observer.summary();
    assert_eq!(history.session_id, session);
    assert_eq!(
        summary.table_id, table,
        "seating must not restart the table history"
    );
    assert_eq!(summary.coverage.unvalidated_captures, 3);
    assert_eq!(
        summary.counts,
        core_engine::opponent::observer::ActionCounts::default()
    );
    assert!(summary.occupants.is_empty());
    assert!(!summary.coverage.complete);
}

#[test]
fn stale_or_unavailable_health_cannot_create_a_history_capture() {
    let mut history = AdmittedHistory::new().unwrap();
    let (ticket, _) = history_source();
    let clock = HistoryClock(std::cell::Cell::new(200));
    let config = RuntimeConfig::default();
    let health = json!({"schema_version":2,"event":"capture_health","fresh_capture":false});
    emit_with_history(
        &health,
        Some(&ticket),
        &mut history,
        &clock,
        &config,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert_eq!(history.sequence, 0);
    let health = json!({"schema_version":2,"event":"capture_health","fresh_capture":true});
    emit_with_history(
        &health,
        Some(&ticket),
        &mut history,
        &clock,
        &config,
        &mut |_| {
            clock
                .0
                .set(ticket.captured_at_ms + CAPTURE_HEALTH_INTERVAL_MS);
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(
        history.sequence, 0,
        "blocked output cannot prolong a source heartbeat"
    );
    assert!(!history.record_source(&ticket, 99, &config, true));
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

fn stack_partial() -> PartialObservationView {
    let mut value = PartialObservationView {
        pot_size: Some(125),
        ..PartialObservationView::default()
    };
    value
        .verified_fields
        .push(ingest::partial::VerifiedField::PotSize);
    for (index, field) in STACK_FIELDS.into_iter().enumerate() {
        value.seats[index].displayed_stack = Some(100 + index as u32);
        value.verified_fields.push(field);
    }
    value
}

#[test]
fn scoped_partial_invalidation_serializes_only_original_source_and_no_lease() {
    let (mut ticket, _) = history_source();
    ticket.captured_at_unix_ms = Some(9_900);
    let record = event_record(
        LiveEvent::<crate::ui::widgets::DecisionView>::PartialObservationInvalidated {
            ticket: ticket.clone(),
            reason: "source-region-changed",
            fields: None,
        },
        200,
        10_000,
        &RuntimeConfig::default(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(record["event"], "partial_observation_invalidated");
    assert_eq!(record["observation"], json!(ticket));
    assert_eq!(record["generation"], ticket.generation);
    assert_eq!(record["epoch"], ticket.epoch);
    assert_eq!(record["identity"], json!(ticket.identity));
    assert_eq!(record["captured_at_unix_ms"], 9900);
    assert_eq!(record["emitted_at_unix_ms"], 10_000);
    for key in [
        "fields",
        "expires_at_unix_ms",
        "valid_for_ms",
        "pot_size",
        "seats",
        "decision",
    ] {
        assert!(
            record.get(key).is_none(),
            "an invalidation cannot grant {key}"
        );
    }
}

#[test]
fn field_invalidation_serializes_exact_allowlist_without_reissuing_lease() {
    use ingest::partial::VerifiedField;
    let (mut ticket, _) = history_source();
    ticket.captured_at_unix_ms = Some(9_900);
    let record = event_record(
        LiveEvent::<crate::ui::widgets::DecisionView>::PartialObservationInvalidated {
            ticket: ticket.clone(),
            reason: "source-region-changed",
            fields: Some(vec![VerifiedField::Stack1, VerifiedField::BoardCount]),
        },
        400,
        10_200,
        &RuntimeConfig::default(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(
        record["fields"],
        json!(["seats.1.displayed_stack", "board_count"])
    );
    assert_eq!(record["observation"], json!(ticket));
    assert_eq!(record["captured_at_unix_ms"], 9_900);
    assert_eq!(record["emitted_at_unix_ms"], 10_200);
    assert_eq!(record.as_object().unwrap().len(), 10);
    for key in [
        "valid_for_ms",
        "expires_at_unix_ms",
        "pot_size",
        "seats",
        "quality_approved",
    ] {
        assert!(
            record.get(key).is_none(),
            "an invalidation cannot grant {key}"
        );
    }
}

#[test]
fn partial_publication_keeps_six_stacks_and_pot_without_cards_or_phase() {
    let (ticket, _) = history_source();
    let config = RuntimeConfig::default();
    let record = event_record(
        LiveEvent::PartialObservation {
            ticket: ticket.clone(),
            value: Box::new(stack_partial()),
            valid_for_ms: 4900,
        },
        200,
        10_000,
        &config,
    )
    .unwrap()
    .unwrap();
    assert_eq!(record["event"], "partial_observation");
    assert_eq!(record["pot_size"], 125);
    assert!(record["game_phase"].is_null());
    assert!(record["board_count"].is_null());
    assert_eq!(record["quality_approved"], false);
    for index in 0..6 {
        assert_eq!(record["seats"][index]["seat"], index + 1);
        assert_eq!(record["seats"][index]["displayed_stack"], index + 100);
        assert!(record["seats"][index]["visible_wager"].is_null());
        assert!(record["seats"][index]["street_contribution"].is_null());
    }
    assert!(record.get("recommendation").is_none());
    assert!(record.get("decision").is_none());
    assert!(event_record(
        LiveEvent::PartialObservation {
            ticket,
            value: Box::new(stack_partial()),
            valid_for_ms: 4900,
        },
        5100,
        20_000,
        &config
    )
    .unwrap()
    .is_none());
}

#[test]
fn heartbeat_does_not_erase_original_source_bound_partial_stacks() {
    let (ticket, _) = history_source();
    let config = RuntimeConfig::default();
    let mut history = AdmittedHistory::new().unwrap();
    let mut heartbeat = ticket.clone();
    heartbeat.captured_at_ms = 190;
    assert!(history.record_source(&heartbeat, 200, &config, true));
    assert!(history.record_partial(&ticket, &stack_partial(), 200, &config));
    let view = history.partial.view(200);
    for (index, seat) in view.seats.iter().enumerate() {
        let stack = seat.displayed_stack.as_ref().unwrap();
        assert_eq!(stack.value, 100 + index as u64);
        assert_eq!(stack.source_capture.captured_at_ms, ticket.captured_at_ms);
        assert_eq!(stack.expires_at_ms, ticket.captured_at_ms + 5000);
        assert!(seat.visible_wager.is_none() && seat.street_commitment.is_none());
        assert!(seat.occupant_epoch.is_none() && seat.position.is_none());
    }
    assert!(view.call_cost.is_none() && view.pot_odds.is_none());
    assert_eq!(
        history.partial.history().counts,
        core_engine::opponent::observer::ActionCounts::default()
    );
    assert!(!history.record_partial(&ticket, &stack_partial(), 250, &config));
    assert!(history
        .partial
        .view(5100)
        .seats
        .iter()
        .all(|s| s.displayed_stack.is_none()));
}

#[test]
fn partial_history_checks_expiry_after_stdout_and_preserves_gaps_on_replacement() {
    let (ticket, _) = history_source();
    let config = RuntimeConfig::default();
    let clock = HistoryClock(std::cell::Cell::new(200));
    let value = stack_partial();
    let record = event_record(
        LiveEvent::PartialObservation {
            ticket: ticket.clone(),
            value: Box::new(value.clone()),
            valid_for_ms: 4900,
        },
        200,
        10_000,
        &config,
    )
    .unwrap()
    .unwrap();
    let mut history = AdmittedHistory::new().unwrap();
    let mut written = Vec::new();
    super::emit_with_history(
        &record,
        Some(&ticket),
        Some(&value),
        &mut history,
        &clock,
        &config,
        &mut |record| {
            written.push(record.clone());
            clock.0.set(5100);
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(written.len(), 1);
    assert_eq!(history.partial_sequence, 0);
    assert!(history.partial.view(5100).capture.is_none());

    let mut history = AdmittedHistory::new().unwrap();
    assert!(history.record_partial(&ticket, &value, 200, &config));
    let prefix = history.partial.history().events;
    history.invalidate(ticket.generation + 1, ticket.epoch + 1);
    assert!(!history.record_partial(&ticket, &value, 250, &config));
    let mut replacement = ticket;
    replacement.generation += 2;
    replacement.epoch += 2;
    replacement.captured_at_ms = 300;
    replacement.identity.hwnd += 1;
    assert!(history.record_partial(&replacement, &value, 350, &config));
    let summary = history.partial.history();
    assert!(summary.events.starts_with(&prefix));
    assert!(summary.occupants.is_empty());
    assert_eq!(
        summary.counts,
        core_engine::opponent::observer::ActionCounts::default()
    );
}

#[test]
fn obsolete_diagnostics_survive_only_as_private_non_admission_records() {
    let (ticket, _) = history_source();
    let record = event_record(
        LiveEvent::PerceptionDiagnostics {
            ticket,
            value: ingest::partial::PerceptionDiagnostics::default(),
            valid_for_ms: 0,
        },
        6000,
        10_000,
        &RuntimeConfig::default(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(record["event"], "perception_diagnostics");
    assert_eq!(record["valid_for_ms"], 0);
    assert_eq!(record["source_current"], false);
    assert_eq!(record["source_age_ms"], 5900);
    assert_eq!(record["captured_at_unix_ms"], 4100);
    assert_eq!(record["expires_at_unix_ms"], 9100);
    assert!(record.get("seats").is_none() && record.get("recommendation").is_none());
}

#[test]
fn late_laya_finish_retains_private_traces_and_cannot_seed_any_reading() {
    let analysis = finish_laya_analysis(
        ingest::laya::LayaAnalysis {
            output: ingest::vlm::VlmOutput {
                text: "not parsed after expiry".into(),
            },
            partial: None,
            diagnostics: ingest::partial::PerceptionDiagnostics::default(),
        },
        Some(&Pipeline::new()),
        Instant::now() - std::time::Duration::from_millis(1),
    )
    .unwrap();
    assert!(analysis.partial.is_none() && analysis.recommendation.is_none());
    assert_eq!(
        analysis.observation.screen_kind,
        ingest::screen::ScreenKind::Unknown
    );
    assert!(analysis.observation.state.is_none());
    let diagnostics = analysis.diagnostics.unwrap();
    assert!(!diagnostics.source_current);
    assert_eq!(
        diagnostics.admission,
        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired
    );
}

#[test]
fn partial_publication_preserves_the_existing_public_history_prefix() {
    let (ticket, _) = history_source();
    let config = RuntimeConfig::default();
    let clock = HistoryClock(std::cell::Cell::new(200));
    let mut history = AdmittedHistory::new().unwrap();
    let mut health = ticket.clone();
    health.captured_at_ms = 190;
    assert!(history.record_source(&health, 200, &config, true));
    let prefix = history.observer.summary();
    let value = stack_partial();
    let record = event_record(
        LiveEvent::PartialObservation {
            ticket: ticket.clone(),
            value: Box::new(value.clone()),
            valid_for_ms: 4900,
        },
        200,
        10_000,
        &config,
    )
    .unwrap()
    .unwrap();
    let mut written = Vec::new();
    super::emit_with_history(
        &record,
        Some(&ticket),
        Some(&value),
        &mut history,
        &clock,
        &config,
        &mut |r| {
            written.push(r.clone());
            Ok(())
        },
    )
    .unwrap();
    assert_eq!(written.len(), 2);
    assert_eq!(written[1]["summary"], serde_json::to_value(prefix).unwrap());
    assert!(history.partial.view(200).seats[0].displayed_stack.is_some());
}

#[test]
fn cdp_poller_reports_unavailable_once_for_a_closed_port() {
    let mut records: Vec<serde_json::Value> = Vec::new();
    crate::live::run_cdp_poller(
        59223,
        std::time::Duration::from_millis(5),
        Some(2),
        &mut |record| records.push(record.clone()),
    );
    assert_eq!(records.len(), 1, "steady state stays quiet: {records:?}");
    assert_eq!(records[0]["kind"], "cdp-status");
    assert_eq!(records[0]["state"], "unavailable");
    assert_eq!(records[0]["port"], 59223);
}
