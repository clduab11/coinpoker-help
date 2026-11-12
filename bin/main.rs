//! `coinpoker` — binary entrypoint.
//!
//! Wires the ingestion, decision, sizing, modeling, and UI layers into a
//! single decision-support process. The shared decision pipeline and the UI
//! surfaces live in the `coinpoker` library crate; this binary keeps the IO
//! loops and mode dispatch.
//!
//! Modes:
//! - `coinpoker`            — headless capture pipeline (Windows): capture →
//!   change detection → VLM → decision → JSON lines on stdout.
//! - `coinpoker --stdin`    — read `GameState` JSON lines from stdin and run
//!   the decision pipeline (works on any host; used by tests and replay).
//! - `coinpoker --ui`       — live pipeline with a transparent, click-through
//!   study overlay (`desktop` feature; `ws` adds a mirror socket).
//! - `coinpoker --list-windows` — list capture candidates for calibration.
//! - `coinpoker --doctor`   — local installation/model/capture diagnostics.
//! - `coinpoker --evaluate PATH` — offline fixture-manifest evaluation.

use std::fmt;
use std::io::{self, BufRead, Write};
use std::process::ExitCode;

use ingest::parser::{validate_game_state, GameState, ParseError};
use ingest::state_machine::{StateMachine, TableEvent};

use config::{Mode, USAGE};

mod config;
mod evaluation;
mod live;
mod manual_capture;
mod manual_inference;

/// Decision pipeline + UI types re-exported at the crate root so the binary
/// modules can keep the `crate::...` paths they used before the lib split.
pub use coinpoker::pipeline;
pub use coinpoker::pipeline::Pipeline;
pub use coinpoker::ui;

#[derive(Debug)]
enum RunError {
    Io(io::Error),
    Message(String),
}

impl fmt::Display for RunError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => error.fmt(formatter),
            Self::Message(message) => formatter.write_str(message),
        }
    }
}

impl From<io::Error> for RunError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args
        .first()
        .is_some_and(|arg| matches!(arg.as_str(), "--capture-only" | "--manual-inference"))
    {
        return match manual_capture::run(&args) {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) => {
                let _ = writeln!(io::stderr().lock(), "{error}");
                ExitCode::FAILURE
            }
        };
    }
    let options = match config::parse(args, |key| std::env::var(key).ok()) {
        Ok(options) => options,
        Err(message) => {
            let _ = writeln!(io::stderr().lock(), "{message}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };

    let result = match options.mode.clone() {
        Mode::Capture => live::run(options),
        Mode::Stdin => run_stdin_pipeline(),
        Mode::ListWindows => live::list_windows(),
        Mode::Doctor => live::doctor(options),
        Mode::Evaluate(path) => evaluation::run(&path, options.vlm),
        #[cfg(feature = "desktop")]
        Mode::Ui => live::run_ui_overlay(options),
        #[cfg(not(feature = "desktop"))]
        Mode::Ui => Err(RunError::Message(
            "--ui requires the desktop feature; rebuild with --features desktop".into(),
        )),
        Mode::Help => write!(io::stdout().lock(), "{USAGE}").map_err(RunError::from),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(RunError::Io(error)) if error.kind() == io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,
        Err(error) => {
            let _ = writeln!(io::stderr().lock(), "{error}");
            ExitCode::FAILURE
        }
    }
}

/// Read `GameState` JSON lines from stdin and emit decision JSON lines.
fn run_stdin_pipeline() -> Result<(), RunError> {
    let pipeline = Pipeline::new();
    let emitter = crate::ui::headless::stdout();
    let mut state_machine = StateMachine::new();
    let mut decision_active = false;

    for line in io::stdin().lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let state: GameState = match serde_json::from_str(&line) {
            Ok(state) => state,
            Err(error) => {
                report_warning(format_args!("{}", ParseError::from(error).code()));
                state_machine.reset();
                if decision_active {
                    emitter.emit_clear("invalid-state")?;
                    decision_active = false;
                }
                continue;
            }
        };
        if let Err(error) = validate_game_state(&state) {
            report_warning(format_args!("{}", error.code()));
            state_machine.reset();
            if decision_active {
                emitter.emit_clear("invalid-state")?;
                decision_active = false;
            }
            continue;
        }

        match state_machine.update(state) {
            TableEvent::ActionRequired(state) | TableEvent::StateChanged(state)
                if state.action_required =>
            {
                let view = match pipeline.decide(&state) {
                    Ok(view) => view,
                    Err(error) => {
                        report_warning(format_args!("decision suppressed: {error}"));
                        state_machine.reset();
                        if decision_active {
                            emitter.emit_clear("decision-suppressed")?;
                            decision_active = false;
                        }
                        continue;
                    }
                };
                emitter.emit_decision(&view)?;
                decision_active = true;
            }
            TableEvent::StateChanged(_) | TableEvent::Showdown(_) => {
                if decision_active {
                    emitter.emit_clear("action-not-required")?;
                    decision_active = false;
                }
            }
            TableEvent::NoChange | TableEvent::ActionRequired(_) => {}
        }
    }
    Ok(())
}

fn report_warning(arguments: fmt::Arguments<'_>) {
    let _ = writeln!(io::stderr().lock(), "{arguments}");
}

#[cfg(test)]
mod tests {
    use super::config::validate_vlm_endpoint;

    #[test]
    fn local_laya_endpoints_are_allowed() {
        for endpoint in [
            "http://127.0.0.1:18090/v1/laya/predict",
            "http://localhost:18090/v1/laya/predict",
            "https://[::1]:18090/v1/laya/predict",
        ] {
            validate_vlm_endpoint(endpoint).expect("loopback endpoint");
        }
    }

    #[test]
    fn remote_laya_endpoints_are_always_rejected() {
        for endpoint in [
            "https://vlm.example.com/v1/laya/predict",
            "http://vlm.example.com/v1",
            "http://192.168.1.2/v1/laya/predict",
            "http://localhost.evil.com/",
        ] {
            let error = validate_vlm_endpoint(endpoint).unwrap_err();
            assert!(error.contains("loopback"), "{error}");
        }
    }

    #[test]
    fn deceptive_or_invalid_hosts_are_rejected() {
        assert!(validate_vlm_endpoint("http://localhost:8080@evil.example/v1").is_err());
        assert!(validate_vlm_endpoint("file:///tmp/socket").is_err());
        assert!(validate_vlm_endpoint("not a URL").is_err());
    }
}
