use std::io::{self, Write};
use std::path::PathBuf;
use std::process::Command;

use ingest::capture::{CaptureError, Frame, PlatformCapture, WindowCapturer};
use ingest::runtime::{
    Analysis, Clock, InferenceFailure, LiveEvent, LiveRuntime, MonotonicClock, ThreadWorker,
};
use ingest::screen::parse_screen_output;
use ingest::vlm::{OpenAiServerBackend, VlmBackend};
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
) -> Result<Analysis<ui::widgets::DecisionView>, InferenceFailure> {
    let output = backend
        .analyze(frame, &ingest::prompt::build_analysis_prompt())
        .map_err(|error| InferenceFailure { code: error.code() })?;
    // Error codes are typed constants, never model payloads or parser messages.
    let observation =
        parse_screen_output(&output).map_err(|error| InferenceFailure { code: error.code() })?;
    let recommendation = observation
        .state
        .as_ref()
        .filter(|s| s.action_required)
        .and_then(|state| pipeline.decide(state).ok());
    Ok(Analysis {
        observation,
        recommendation,
    })
}

pub fn run(options: Options) -> Result<(), RunError> {
    if !cfg!(target_os = "windows") {
        return Err(RunError::Message(
            "live capture requires Windows 10 version 1903 or later; use --stdin on this platform"
                .into(),
        ));
    }
    emit(
        &json!({"schema_version":2,"event":"configuration","runtime":options.runtime,
        "identity_configured":options.discovery.has_identity(),"model":options.vlm.model,
        "vlm_timeout_secs":options.vlm.timeout_secs,"visual_calibration":"not_validated"}),
    )?;
    if !options.discovery.has_identity() {
        emit(
            &json!({"schema_version":2,"event":"status","state":"configuration_required",
            "reason":"run --list-windows; configure --exe-name using the actual executable name"}),
        )?;
        return Err(RunError::Message(
            "no calibrated application identity configured".into(),
        ));
    }
    let backend = OpenAiServerBackend::new(options.vlm)
        .map_err(|error| RunError::Message(error.to_string()))?;
    let pipeline = Pipeline::new();
    let worker = ThreadWorker::new(move |frame| analyze_frame(&backend, &pipeline, frame));
    let poll_ms = options.runtime.poll_ms;
    let max_frame_age_ms = options.runtime.max_frame_age_ms;
    let mut runtime = LiveRuntime::new(
        PlatformCapture::default(),
        worker,
        options.discovery,
        options.runtime,
    )
    .map_err(|e| RunError::Message(e.into()))?;
    let clock = MonotonicClock::default();
    loop {
        for event in runtime.tick(&clock) {
            let record = match event {
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
                    let valid_for_ms = valid_for_ms.min(
                        max_frame_age_ms
                            .saturating_sub(clock.now_ms().saturating_sub(ticket.captured_at_ms)),
                    );
                    if valid_for_ms == 0 {
                        runtime.publication_dropped();
                        emit(
                            &json!({"schema_version":2,"event":"discarded","generation":ticket.generation,"reason":"publication-expired"}),
                        )?;
                        continue;
                    }
                    let mut record = serde_json::to_value(value)
                        .map_err(|e| RunError::Message(e.to_string()))?;
                    let fields = record.as_object_mut().expect("DecisionView is an object");
                    fields.insert("schema_version".into(), json!(2));
                    fields.insert("event".into(), json!("decision"));
                    fields.insert("observation".into(), json!(ticket));
                    fields.insert("valid_for_ms".into(), json!(valid_for_ms));
                    let emitted_at = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map_err(|_| {
                            RunError::Message("system clock predates the Unix epoch".into())
                        })?
                        .as_millis() as u64;
                    fields.insert("emitted_at_unix_ms".into(), json!(emitted_at));
                    fields.insert(
                        "expires_at_unix_ms".into(),
                        json!(emitted_at.saturating_add(valid_for_ms)),
                    );
                    record
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
            emit(&record)?;
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
        let failure = analyze_frame(&backend, &Pipeline::new(), &frame)
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
            (
                VlmError::Parse(VlmResponseError::FinishReason),
                "finish-reason",
            ),
            (VlmError::Truncated, "truncated"),
            (
                VlmError::Parse(VlmResponseError::Schema),
                "invalid-vlm-schema",
            ),
            (
                VlmError::Parse(VlmResponseError::Choices),
                "invalid-vlm-choices",
            ),
            (
                VlmError::Parse(VlmResponseError::EmptyContent),
                "invalid-vlm-empty",
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
        ] {
            assert_worker_category(Err(error), category);
        }
    }
}
