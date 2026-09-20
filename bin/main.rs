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
//! - `coinpoker --ui`       — run the live pipeline and mirror decisions to a
//!   transparent, click-through study overlay window.
//! - `coinpoker --list-windows` — list capture candidates for calibration.

use std::fmt;
use std::io::{self, BufRead, Write};
use std::process::ExitCode;
use std::sync::mpsc;

use coinpoker::cli::{parse_options, Mode, USAGE};
use coinpoker::config::{capture_config_from_env, vlm_config_from_env};
use coinpoker::pipeline::{Pipeline, MIN_PERCEPTION_CONFIDENCE};
use ingest::capture::WindowCapturer;
use ingest::change_detect::{ZoneChangeDetector, ZoneChangeDetectorConfig};
use ingest::consensus::{ConsensusConfig, ConsensusOutcome, ConsensusTracker};
use ingest::parser::{parse_vlm_output, validate_game_state, GameState};
use ingest::prompt::build_analysis_prompt;
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::{MlxServerBackend, VlmBackend};
use ui::overlay::{OverlayEvent, TableBounds};
#[cfg(feature = "ws")]
use ui::ws::EventMirrorServer;

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
    let options = match parse_options(std::env::args().skip(1)) {
        Ok(options) => options,
        Err(message) => {
            let _ = writeln!(io::stderr().lock(), "{message}\n\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    let mode = options.mode;

    let result = match mode {
        Mode::Capture => run_capture_pipeline(),
        Mode::Stdin => run_stdin_pipeline(),
        Mode::ListWindows => list_windows(),
        Mode::Ui => run_ui_overlay(options.overlay_settings),
        Mode::Help => write!(io::stdout().lock(), "{USAGE}").map_err(RunError::from),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(RunError::Io(error)) if error.kind() == io::ErrorKind::BrokenPipe => ExitCode::SUCCESS,
        Err(error) => {
            let _ = writeln!(io::stderr().lock(), "{error}");
            if matches!(mode, Mode::Ui) {
                ExitCode::from(2)
            } else {
                ExitCode::FAILURE
            }
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
    let mut pipeline = Pipeline::new();
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

/// A started live pipeline: capture, VLM backend, and per-observation state.
struct LivePipeline {
    capturer: WindowCapturer,
    backend: MlxServerBackend,
    zone_detector: ZoneChangeDetector,
    consensus: ConsensusTracker,
    state_machine: StateMachine,
    pipeline: Pipeline,
}

/// Construct and start the capture pipeline, failing fast on startup errors.
fn start_live_pipeline() -> Result<LivePipeline, RunError> {
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
    let zone_detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
    let consensus = ConsensusTracker::try_new(ConsensusConfig::default())
        .map_err(|error| RunError::Message(format!("consensus configuration invalid: {error}")))?;

    Ok(LivePipeline {
        capturer,
        backend,
        zone_detector,
        consensus,
        state_machine: StateMachine::new(),
        pipeline: Pipeline::new(),
    })
}

/// Run the live capture loop forever, forwarding events to `sink`.
///
/// Capture → zone change detection → VLM → 2-of-3 consensus → state machine
/// → decision. The table window's on-screen bounds are polled each iteration
/// and forwarded as position events so the overlay can track the table.
fn run_live_loop(live: &mut LivePipeline, mut sink: impl FnMut(OverlayEvent)) -> ! {
    loop {
        if let Some(bounds) = live.capturer.window_bounds() {
            sink(OverlayEvent::Position(TableBounds {
                x: bounds.x,
                y: bounds.y,
                width: bounds.width,
                height: bounds.height,
            }));
        }

        let frame = match live.capturer.latest_frame() {
            Ok(Some(frame)) => frame,
            Ok(None) => {
                std::thread::sleep(std::time::Duration::from_millis(100));
                continue;
            }
            Err(error) => {
                report_warning(format_args!("capture error: {error}"));
                live.zone_detector.reset();
                live.consensus.reset();
                live.state_machine.reset();
                sink(OverlayEvent::Clear("capture-unavailable".to_string()));
                // The delegate-reported stop (window closed, permission
                // revoked) needs a restart before frames flow again.
                let _ = live.capturer.stop();
                if live.capturer.start().is_err() {
                    std::thread::sleep(std::time::Duration::from_secs(1));
                }
                continue;
            }
        };

        if !live.zone_detector.detect(&frame).changed {
            std::thread::sleep(std::time::Duration::from_millis(100));
            continue;
        }

        let prompt = build_analysis_prompt();
        let output = match live.backend.analyze(&frame, &prompt) {
            Ok(output) => output,
            Err(error) => {
                report_warning(format_args!("vlm error: {error}"));
                live.zone_detector.reset();
                live.consensus.reset();
                live.state_machine.reset();
                sink(OverlayEvent::Clear("vlm-error".to_string()));
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };

        // Freshness check: a new frame arriving during inference that still
        // changes a decision-relevant zone invalidates the observation.
        match live.capturer.latest_frame() {
            Ok(Some(current_frame)) => {
                if live.zone_detector.detect(&current_frame).changed {
                    report_warning(format_args!(
                        "decision suppressed: table changed during VLM inference"
                    ));
                    live.consensus.reset();
                    live.state_machine.reset();
                    sink(OverlayEvent::Clear(
                        "state-changed-during-inference".to_string(),
                    ));
                    continue;
                }
            }
            Ok(None) => {}
            Err(error) => {
                report_warning(format_args!(
                    "freshness check failed after inference: {error}"
                ));
                live.consensus.reset();
                live.state_machine.reset();
                sink(OverlayEvent::Clear("freshness-check-failed".to_string()));
                continue;
            }
        }

        let state = match parse_vlm_output(&output) {
            Ok(state) => state,
            Err(error) => {
                report_warning(format_args!("parse error: {error}"));
                live.zone_detector.reset();
                live.consensus.reset();
                live.state_machine.reset();
                sink(OverlayEvent::Clear("invalid-observation".to_string()));
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
                live.consensus.reset();
                live.state_machine.reset();
                sink(OverlayEvent::Clear("low-confidence".to_string()));
                continue;
            }
        }

        // 2-of-N consensus: only states confirmed by repeated observation
        // reach the state machine.
        let confirmed = match live.consensus.observe(state) {
            ConsensusOutcome::Accepted(state) => state,
            ConsensusOutcome::Pending => {
                std::thread::sleep(std::time::Duration::from_millis(100));
                continue;
            }
        };

        match live.state_machine.update(confirmed) {
            TableEvent::ActionRequired(state) | TableEvent::StateChanged(state)
                if state.action_required =>
            {
                let view = match live.pipeline.decide(&state) {
                    Ok(view) => view,
                    Err(error) => {
                        report_warning(format_args!("decision suppressed: {error}"));
                        live.zone_detector.reset();
                        live.consensus.reset();
                        live.state_machine.reset();
                        sink(OverlayEvent::Clear("decision-suppressed".to_string()));
                        continue;
                    }
                };
                sink(OverlayEvent::Decision(view));
            }
            TableEvent::StateChanged(_) | TableEvent::Showdown(_) => {
                sink(OverlayEvent::Clear("action-not-required".to_string()));
            }
            TableEvent::NoChange | TableEvent::ActionRequired(_) => {}
        }

        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

/// Headless capture pipeline: forward decisions as JSON lines on stdout.
fn run_capture_pipeline() -> Result<(), RunError> {
    let mut pipeline = start_live_pipeline()?;
    let emitter = ui::headless::stdout();
    run_live_loop(&mut pipeline, |event| match event {
        OverlayEvent::Decision(view) => {
            let _ = emitter.emit_decision(&view);
        }
        OverlayEvent::Clear(reason) => {
            let _ = emitter.emit_clear(&reason);
        }
        OverlayEvent::Position(_) => {}
    })
}

/// Live pipeline with a desktop study overlay.
fn run_ui_overlay(settings: ui::overlay::OverlaySettings) -> Result<(), RunError> {
    let mut pipeline = start_live_pipeline()?;
    let (tx, rx) = mpsc::channel::<OverlayEvent>();
    #[cfg(feature = "ws")]
    let mirror = EventMirrorServer::bind()
        .map_err(|error| RunError::Message(format!("WebSocket mirror failed: {error}")))?;
    #[cfg(feature = "ws")]
    let publisher = {
        eprintln!(
            "WebSocket overlay mirror listening on ws://{}",
            mirror.local_addr()
        );
        mirror.publisher()
    };
    std::thread::spawn(move || {
        run_live_loop(&mut pipeline, |event| {
            #[cfg(feature = "ws")]
            publisher.publish(&event);
            let _ = tx.send(event);
        });
    });
    ui::app::run_overlay(rx, settings)
        .map_err(|error| RunError::Message(format!("overlay failed: {error}")))?;
    Ok(())
}

fn report_warning(arguments: fmt::Arguments<'_>) {
    let _ = writeln!(io::stderr().lock(), "{arguments}");
}
