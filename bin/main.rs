//! `coinpoker` — binary entrypoint.
//!
//! Wires the ingestion, decision, mimicry, modeling, and UI crates into a
//! single semi-autonomous decision-support process.
//!
//! Modes:
//! - `coinpoker`            — headless capture pipeline (macOS): capture →
//!   zone change detection → VLM → 2-of-3 consensus → decision → JSON lines
//!   on stdout.
//! - `coinpoker --stdin`    — read `GameState` JSON lines from stdin and run
//!   the decision pipeline (works on any host; used by tests and replay).
//! - `coinpoker --ui`       — reserved; exits 2 until a live UI feed exists.
//! - `coinpoker --list-windows` — list capture candidates for calibration.

use std::fmt;
use std::io::{self, BufRead, Write};
use std::process::ExitCode;

use coinpoker::cli::{parse_args, Mode, USAGE};
use coinpoker::config::{capture_config_from_env, vlm_config_from_env};
use coinpoker::pipeline::{Pipeline, MIN_PERCEPTION_CONFIDENCE};
use ingest::capture::WindowCapturer;
use ingest::change_detect::{ZoneChangeDetector, ZoneChangeDetectorConfig};
use ingest::consensus::{ConsensusConfig, ConsensusOutcome, ConsensusTracker};
use ingest::parser::{parse_vlm_output, validate_game_state, GameState};
use ingest::prompt::build_analysis_prompt;
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::{MlxServerBackend, VlmBackend};

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
    let mode = match parse_args(std::env::args().skip(1)) {
        Ok(mode) => mode,
        Err(message) => {
            let _ = writeln!(io::stderr().lock(), "{message}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };

    let result = match mode {
        Mode::Capture => run_capture_pipeline(),
        Mode::Stdin => run_stdin_pipeline(),
        Mode::ListWindows => list_windows(),
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

fn list_windows() -> Result<(), RunError> {
    let windows = WindowCapturer::list_windows()
        .map_err(|error| RunError::Message(format!("list windows failed: {error}")))?;
    let mut output = io::stdout().lock();
    for window in windows {
        writeln!(
            output,
            "title={:?} app={:?} on_screen={}",
            window.title, window.app_name, window.on_screen
        )?;
    }
    Ok(())
}

/// Read `GameState` JSON lines from stdin and emit decision JSON lines.
fn run_stdin_pipeline() -> Result<(), RunError> {
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();
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
                report_warning(format_args!("invalid state line: {error}"));
                if decision_active {
                    emitter.emit_clear("invalid-state")?;
                    decision_active = false;
                }
                continue;
            }
        };
        if let Err(error) = validate_game_state(&state) {
            report_warning(format_args!("invalid state line: {error}"));
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

/// Capture-driven pipeline (macOS): consume SCStream frames, fire the VLM
/// when a decision-relevant zone changes, require 2-of-3 consensus on the
/// observed state, and emit decisions when the hero must act.
fn run_capture_pipeline() -> Result<(), RunError> {
    let mut capturer = WindowCapturer::new(capture_config_from_env()).map_err(|error| {
        RunError::Message(format!(
            "capture unavailable: {error}\nScreen capture requires macOS 14+ with Screen Recording permission granted in System Settings."
        ))
    })?;
    capturer
        .start()
        .map_err(|error| RunError::Message(format!("starting capture stream failed: {error}")))?;

    let config = vlm_config_from_env().map_err(RunError::Message)?;
    let backend = MlxServerBackend::new(config);
    let mut zone_detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    let mut consensus = ConsensusTracker::try_new(ConsensusConfig::default())
        .map_err(|error| RunError::Message(format!("consensus configuration invalid: {error}")))?;
    let mut state_machine = StateMachine::new();
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();

    loop {
        let frame = match capturer.latest_frame() {
            Ok(Some(frame)) => frame,
            Ok(None) => {
                std::thread::sleep(std::time::Duration::from_millis(100));
                continue;
            }
            Err(error) => {
                report_warning(format_args!("capture error: {error}"));
                zone_detector.reset();
                consensus.reset();
                state_machine.reset();
                emitter.emit_clear("capture-unavailable")?;
                // The delegate-reported stop (window closed, permission
                // revoked) needs a restart before frames flow again.
                let _ = capturer.stop();
                if capturer.start().is_err() {
                    std::thread::sleep(std::time::Duration::from_secs(1));
                }
                continue;
            }
        };

        if !zone_detector.detect(&frame).changed {
            std::thread::sleep(std::time::Duration::from_millis(100));
            continue;
        }

        let prompt = build_analysis_prompt();
        let output = match backend.analyze(&frame, &prompt) {
            Ok(output) => output,
            Err(error) => {
                report_warning(format_args!("vlm error: {error}"));
                zone_detector.reset();
                consensus.reset();
                state_machine.reset();
                emitter.emit_clear("vlm-error")?;
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };

        // Freshness check: a new frame arriving during inference that still
        // changes a decision-relevant zone invalidates the observation.
        match capturer.latest_frame() {
            Ok(Some(current_frame)) => {
                if zone_detector.detect(&current_frame).changed {
                    report_warning(format_args!(
                        "decision suppressed: table changed during VLM inference"
                    ));
                    consensus.reset();
                    state_machine.reset();
                    emitter.emit_clear("state-changed-during-inference")?;
                    continue;
                }
            }
            Ok(None) => {}
            Err(error) => {
                report_warning(format_args!(
                    "freshness check failed after inference: {error}"
                ));
                consensus.reset();
                state_machine.reset();
                emitter.emit_clear("freshness-check-failed")?;
                continue;
            }
        }

        let state = match parse_vlm_output(&output) {
            Ok(state) => state,
            Err(error) => {
                report_warning(format_args!("parse error: {error}"));
                zone_detector.reset();
                consensus.reset();
                state_machine.reset();
                emitter.emit_clear("invalid-observation")?;
                continue;
            }
        };

        // VLM output is untrusted: a low-confidence observation is discarded
        // before it can influence consensus or the state machine.
        if let Some(confidence) = state.confidence {
            if confidence < MIN_PERCEPTION_CONFIDENCE {
                report_warning(format_args!(
                    "observation discarded: perception confidence {confidence:.2} is below the minimum {MIN_PERCEPTION_CONFIDENCE}"
                ));
                consensus.reset();
                state_machine.reset();
                emitter.emit_clear("low-confidence")?;
                continue;
            }
        }

        // 2-of-N consensus: only states confirmed by repeated observation
        // reach the state machine.
        let confirmed = match consensus.observe(state) {
            ConsensusOutcome::Accepted(state) => state,
            ConsensusOutcome::Pending => {
                std::thread::sleep(std::time::Duration::from_millis(100));
                continue;
            }
        };

        match state_machine.update(confirmed) {
            TableEvent::ActionRequired(state) | TableEvent::StateChanged(state)
                if state.action_required =>
            {
                let view = match pipeline.decide(&state) {
                    Ok(view) => view,
                    Err(error) => {
                        report_warning(format_args!("decision suppressed: {error}"));
                        zone_detector.reset();
                        consensus.reset();
                        state_machine.reset();
                        emitter.emit_clear("decision-suppressed")?;
                        continue;
                    }
                };
                emitter.emit_decision(&view)?;
            }
            TableEvent::StateChanged(_) | TableEvent::Showdown(_) => {
                emitter.emit_clear("action-not-required")?;
            }
            TableEvent::NoChange | TableEvent::ActionRequired(_) => {}
        }

        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

fn report_warning(arguments: fmt::Arguments<'_>) {
    let _ = writeln!(io::stderr().lock(), "{arguments}");
}
