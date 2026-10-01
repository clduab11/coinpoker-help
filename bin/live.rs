use std::io::{self, Write};
use std::path::PathBuf;
use std::process::Command;

use ingest::capture::{CaptureError, PlatformCapture, WindowCapturer};
use ingest::runtime::{
    Analysis, Clock, InferenceFailure, LiveEvent, LiveRuntime, MonotonicClock, ThreadWorker,
};
use ingest::screen::parse_screen_output;
use ingest::vlm::{OpenAiServerBackend, VlmBackend, VlmError};
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
    let worker = ThreadWorker::new(move |frame| {
        let output = backend
            .analyze(frame, &ingest::prompt::build_analysis_prompt())
            .map_err(|error| InferenceFailure {
                code: match error {
                    VlmError::Server {
                        status: 400 | 404 | 422,
                        ..
                    } => "unsupported-model-api",
                    VlmError::Parse(_) | VlmError::Truncated(_) => "invalid-vlm-response",
                    _ => "vlm-unavailable",
                },
            })?;
        // Do not log model payloads or parser messages: either can contain personal data.
        let observation = parse_screen_output(&output).map_err(|_| InferenceFailure {
            code: "invalid-observation",
        })?;
        let recommendation = observation
            .state
            .as_ref()
            .filter(|s| s.action_required)
            .and_then(|state| pipeline.decide(state).ok());
        Ok(Analysis {
            observation,
            recommendation,
        })
    });
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
