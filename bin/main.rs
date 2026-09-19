//! `coinpoker` — binary entrypoint.
//!
//! Wires the ingestion, decision, mimicry, modeling, and UI crates into a
//! single semi-autonomous decision-support process.
//!
//! Modes:
//! - `coinpoker`            — headless capture pipeline (macOS): capture →
//!   change detection → VLM → decision → JSON lines on stdout.
//! - `coinpoker --stdin`    — read `GameState` JSON lines from stdin and run
//!   the decision pipeline (works on any host; used by tests and replay).
//! - `coinpoker --ui`       — reserved; exits 2 until a live UI feed exists.
//! - `coinpoker --list-windows` — list capture candidates for calibration.

use std::fmt;
use std::io::{self, BufRead, Write};
use std::process::ExitCode;

use core_engine::decision::{Action, DecisionEngine, DecisionInput};
use core_engine::equity::{Card, EquityConfig, EquityEstimator, Rank, Suit};
use ghost_layer::betting_entropy::{BettingEntropy, BettingEntropyConfig};
use ingest::capture::{CaptureConfig, WindowCapturer};
use ingest::change_detect::{ChangeDetector, ChangeDetectorConfig};
use ingest::parser::{parse_vlm_output, validate_game_state, GameState};
use ingest::prompt::build_analysis_prompt;
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::{MlxServerBackend, VlmBackend, VlmConfig};
use opponent_model::classifier::Archetype;
use opponent_model::exploit::ExploitEngine;
use ui::widgets::DecisionView;

const USAGE: &str = "Usage: coinpoker [OPTION]\n\
\n\
Options:\n\
  (no option)      Run the macOS capture pipeline\n\
  --stdin          Read GameState JSON lines from stdin\n\
  --list-windows   List windows available for capture\n\
  --ui             Reserved; exits 2 because the interactive feed is not implemented\n\
  -h, --help       Print this help\n";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Capture,
    Stdin,
    ListWindows,
    Help,
}

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

fn parse_args(args: impl IntoIterator<Item = String>) -> Result<Mode, String> {
    let args: Vec<String> = args.into_iter().collect();
    match args.as_slice() {
        [] => Ok(Mode::Capture),
        [arg] if arg == "--stdin" => Ok(Mode::Stdin),
        [arg] if arg == "--list-windows" => Ok(Mode::ListWindows),
        [arg] if arg == "--help" || arg == "-h" => Ok(Mode::Help),
        // Exit status 2 is deliberate: the option is recognized but its live
        // pipeline-to-window feed has not been implemented.
        [arg] if arg == "--ui" => Err(
            "--ui is unavailable: the interactive feed is not implemented; use --stdin for JSON-lines output"
                .to_string(),
        ),
        [arg] => Err(format!("unknown option: {arg}")),
        [_, extra, ..] => Err(format!("unexpected extra argument: {extra}")),
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

/// The decision pipeline shared by all input modes.
struct Pipeline {
    engine: DecisionEngine,
    exploit: ExploitEngine,
    estimator: EquityEstimator,
    betting: BettingEntropy,
}

impl Pipeline {
    fn new() -> Self {
        Self {
            engine: DecisionEngine::new(),
            exploit: ExploitEngine::new(),
            estimator: EquityEstimator::new(EquityConfig { iterations: 5_000 }),
            betting: BettingEntropy::new(BettingEntropyConfig::default()),
        }
    }

    /// Convert an observed state into a legal decision view.
    fn decide(&self, state: &GameState) -> Result<DecisionView, String> {
        // Opponent-history accumulation is not connected yet, so all active
        // opponents use the explicit Unknown profile.
        let archetype = Archetype::Unknown;
        let adjustment = self.exploit.adjust(archetype);

        let hero = convert_cards(&state.hero_cards)?;
        if hero.len() != 2 {
            return Err(format!(
                "equity estimate requires exactly 2 hero cards, got {}",
                hero.len()
            ));
        }
        let board = convert_cards(&state.board)?;

        let active_opponents: Vec<_> = state
            .players
            .iter()
            .filter(|player| {
                player.name != "Hero"
                    && !matches!(
                        player.last_action.as_deref(),
                        Some(action) if action.eq_ignore_ascii_case("fold")
                    )
            })
            .collect();
        let has_multiway_side_pot_risk = active_opponents.len() > 1
            && active_opponents.iter().any(|player| {
                player.chips == 0
                    || matches!(
                        player.last_action.as_deref(),
                        Some(action) if action.eq_ignore_ascii_case("allin")
                    )
            });
        if has_multiway_side_pot_risk {
            return Err(
                "multiway all-in state requires side-pot-aware EV and is not supported".to_string(),
            );
        }

        let equity = self
            .estimator
            .estimate_against_unknown(&hero, active_opponents.len(), &board)
            .map_err(|error| format!("equity estimate failed: {error}"))?;

        let has_action = |action: &str| {
            state
                .available_actions
                .iter()
                .any(|available| available == action)
        };
        let all_in_available = has_action("allin");
        let call_amount = state.to_call.min(state.hero_chips);
        let can_call = has_action("call")
            || (all_in_available && state.to_call > 0 && state.hero_chips <= state.to_call);
        // Until caller-count and range-conditioned raise equity are modeled,
        // only evaluate raises against a single active opponent.
        let can_raise = active_opponents.len() == 1
            && (has_action("raise") || (all_in_available && state.hero_chips > call_amount));
        let hero_contribution = state
            .players
            .iter()
            .find(|player| player.name == "Hero")
            .map(|player| player.bet_amount)
            .ok_or_else(|| "actionable state has no Hero player".to_string())?;
        let all_in_raise_to = hero_contribution.saturating_add(state.hero_chips);
        let min_raise_to = state.min_raise_to.unwrap_or(all_in_raise_to);
        let max_raise_to = state.max_raise_to.unwrap_or(all_in_raise_to);

        let target_increment = (f64::from(state.pot_size) * 0.75 * adjustment.raise_size_multiplier)
            .round()
            .max(1.0) as u32;
        let raise_to = if can_raise {
            if !has_action("raise") {
                all_in_raise_to
            } else {
                let min_increment = min_raise_to.saturating_sub(hero_contribution);
                let max_increment = max_raise_to.saturating_sub(hero_contribution);
                let mut rng = rand::thread_rng();
                let increment = self
                    .betting
                    .humanize_bounded(
                        &mut rng,
                        target_increment,
                        state.pot_size,
                        min_increment,
                        max_increment,
                    )
                    .map_err(|error| format!("raise humanization failed: {error}"))?;
                hero_contribution.saturating_add(increment)
            }
        } else {
            0
        };
        let call_target = hero_contribution.saturating_add(state.to_call);
        let expected_caller_contribution = raise_to.saturating_sub(call_target);
        let per_opponent_fold = (0.3 * adjustment.fold_equity_multiplier).clamp(0.0, 1.0);
        let fold_equity = per_opponent_fold.powi(active_opponents.len() as i32);

        let input = DecisionInput {
            pot: state.pot_size,
            to_call: state.to_call,
            equity,
            hero_chips: state.hero_chips,
            hero_contribution,
            fold_equity,
            raise_to,
            min_raise_to,
            expected_caller_contribution,
            can_fold: has_action("fold"),
            can_check: has_action("check"),
            can_call,
            can_raise,
        };
        let decision = self
            .engine
            .decide(&input)
            .map_err(|error| format!("decision failed: {error}"))?;

        let (action, amount) = match decision.action {
            Action::Raise
                if all_in_available
                    && decision.amount == hero_contribution.saturating_add(state.hero_chips) =>
            {
                ("allin".to_string(), decision.amount)
            }
            Action::Raise if has_action("raise") => ("raise".to_string(), decision.amount),
            Action::Raise => {
                return Err("decision engine selected an unavailable raise".to_string());
            }
            Action::Call if has_action("call") => ("call".to_string(), decision.amount),
            Action::Call if all_in_available && state.hero_chips <= state.to_call => {
                ("allin".to_string(), decision.amount)
            }
            Action::Call => {
                return Err("decision engine selected an unavailable call".to_string());
            }
            Action::Check if has_action("check") => ("check".to_string(), 0),
            Action::Check => {
                return Err("decision engine selected an unavailable check".to_string());
            }
            Action::Fold if has_action("fold") => ("fold".to_string(), 0),
            Action::Fold => {
                return Err("decision engine selected an unavailable fold".to_string());
            }
        };

        Ok(DecisionView {
            action,
            amount,
            ev: decision.ev,
            pot_odds: decision.pot_odds,
            equity: decision.equity,
            break_even: decision.break_even,
            opponent: Some(format!("{archetype:?}").to_lowercase()),
            confidence: Some(0.0),
        })
    }
}

/// Convert ingest card strings into core-engine cards without dropping errors.
fn convert_cards(cards: &[ingest::parser::Card]) -> Result<Vec<Card>, String> {
    cards
        .iter()
        .enumerate()
        .map(|(index, card)| {
            let rank = match card.rank.as_str() {
                "A" => Rank::Ace,
                "K" => Rank::King,
                "Q" => Rank::Queen,
                "J" => Rank::Jack,
                "T" => Rank::Ten,
                "9" => Rank::Nine,
                "8" => Rank::Eight,
                "7" => Rank::Seven,
                "6" => Rank::Six,
                "5" => Rank::Five,
                "4" => Rank::Four,
                "3" => Rank::Three,
                "2" => Rank::Two,
                invalid => return Err(format!("card {index} has invalid rank {invalid:?}")),
            };
            let suit = match card.suit.as_str() {
                "spades" => Suit::Spades,
                "hearts" => Suit::Hearts,
                "diamonds" => Suit::Diamonds,
                "clubs" => Suit::Clubs,
                invalid => return Err(format!("card {index} has invalid suit {invalid:?}")),
            };
            Ok(Card::new(rank, suit))
        })
        .collect()
}

/// Read `GameState` JSON lines from stdin and emit decision JSON lines.
fn run_stdin_pipeline() -> Result<(), RunError> {
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();
    let mut state_machine = StateMachine::new();
    let mut decision_active = false;

    for line in io::stdin().lock().lines() {
        let line = line?;
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

/// Capture-driven pipeline (macOS): poll frames, fire the VLM on change,
/// and emit decisions when the hero must act.
fn run_capture_pipeline() -> Result<(), RunError> {
    let capturer = WindowCapturer::new(capture_config_from_env()).map_err(|error| {
        RunError::Message(format!(
            "capture unavailable: {error}\nScreen capture requires macOS 14+ with Screen Recording permission granted in System Settings."
        ))
    })?;

    let config = vlm_config_from_env().map_err(RunError::Message)?;
    let backend = MlxServerBackend::new(config);
    let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
    let mut state_machine = StateMachine::new();
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();

    loop {
        let frame = match capturer.capture_frame() {
            Ok(frame) => frame,
            Err(error) => {
                report_warning(format_args!("capture error: {error}"));
                detector.reset();
                state_machine.reset();
                emitter.emit_clear("capture-unavailable")?;
                std::thread::sleep(std::time::Duration::from_secs(1));
                continue;
            }
        };

        if !detector.detect(&frame).is_changed() {
            std::thread::sleep(std::time::Duration::from_millis(100));
            continue;
        }

        let prompt = build_analysis_prompt();
        let output = match backend.analyze(&frame, &prompt) {
            Ok(output) => output,
            Err(error) => {
                report_warning(format_args!("vlm error: {error}"));
                detector.reset();
                state_machine.reset();
                emitter.emit_clear("vlm-error")?;
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };

        let current_frame = match capturer.capture_frame() {
            Ok(frame) => frame,
            Err(error) => {
                report_warning(format_args!(
                    "freshness check failed after inference: {error}"
                ));
                detector.reset();
                state_machine.reset();
                emitter.emit_clear("freshness-check-failed")?;
                continue;
            }
        };
        if detector.detect(&current_frame).is_changed() {
            report_warning(format_args!(
                "decision suppressed: table changed during VLM inference"
            ));
            detector.reset();
            state_machine.reset();
            emitter.emit_clear("state-changed-during-inference")?;
            continue;
        }

        let state = match parse_vlm_output(&output) {
            Ok(state) => state,
            Err(error) => {
                report_warning(format_args!("parse error: {error}"));
                detector.reset();
                state_machine.reset();
                emitter.emit_clear("invalid-observation")?;
                continue;
            }
        };

        match state_machine.update(state) {
            TableEvent::ActionRequired(state) | TableEvent::StateChanged(state)
                if state.action_required =>
            {
                let view = match pipeline.decide(&state) {
                    Ok(view) => view,
                    Err(error) => {
                        report_warning(format_args!("decision suppressed: {error}"));
                        detector.reset();
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

fn capture_config_from_env() -> CaptureConfig {
    let mut config = CaptureConfig::default();
    if let Ok(title) = std::env::var("COINPOKER_WINDOW_TITLE") {
        if !title.trim().is_empty() {
            config.window_title = title;
        }
    }
    if let Ok(app_name) = std::env::var("COINPOKER_APP_NAME") {
        if !app_name.trim().is_empty() {
            config.app_name = app_name;
        }
    }
    config
}

fn vlm_config_from_env() -> Result<VlmConfig, String> {
    let mut config = VlmConfig::default();
    if let Ok(endpoint) = std::env::var("COINPOKER_VLM_ENDPOINT") {
        if !endpoint.trim().is_empty() {
            config.endpoint = endpoint;
        }
    }
    if let Ok(model) = std::env::var("COINPOKER_VLM_MODEL") {
        if !model.trim().is_empty() {
            config.model = model;
        }
    }

    let remote_allowed = std::env::var("COINPOKER_ALLOW_REMOTE_VLM")
        .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    validate_vlm_endpoint(&config.endpoint, remote_allowed)?;

    Ok(config)
}

fn validate_vlm_endpoint(endpoint: &str, remote_allowed: bool) -> Result<(), String> {
    let parsed = url::Url::parse(endpoint)
        .map_err(|error| format!("invalid COINPOKER_VLM_ENDPOINT: {error}"))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err("VLM endpoint must use HTTP or HTTPS".to_string());
    }
    let loopback = match parsed.host() {
        Some(url::Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
        Some(url::Host::Ipv4(address)) => address.is_loopback(),
        Some(url::Host::Ipv6(address)) => address.is_loopback(),
        None => return Err("VLM endpoint must include a host".to_string()),
    };

    if loopback {
        return Ok(());
    }
    if !remote_allowed {
        return Err(
            "refusing non-loopback COINPOKER_VLM_ENDPOINT; set COINPOKER_ALLOW_REMOTE_VLM=1 only after reviewing screenshot privacy"
                .to_string(),
        );
    }
    if parsed.scheme() != "https" {
        return Err("remote VLM endpoints must use HTTPS".to_string());
    }
    Ok(())
}

fn report_warning(arguments: fmt::Arguments<'_>) {
    let _ = writeln!(io::stderr().lock(), "{arguments}");
}

#[cfg(test)]
mod tests {
    use super::validate_vlm_endpoint;

    #[test]
    fn local_vlm_endpoints_are_allowed_without_opt_in() {
        for endpoint in [
            "http://127.0.0.1:8080/v1/chat/completions",
            "http://localhost:8080/v1/chat/completions",
            "https://[::1]:8443/v1/chat/completions",
        ] {
            validate_vlm_endpoint(endpoint, false).expect("loopback endpoint");
        }
    }

    #[test]
    fn remote_vlm_endpoint_requires_opt_in_and_https() {
        let endpoint = "https://vlm.example.com/v1/chat/completions";
        assert!(validate_vlm_endpoint(endpoint, false).is_err());
        validate_vlm_endpoint(endpoint, true).expect("opted-in HTTPS endpoint");
        assert!(validate_vlm_endpoint("http://vlm.example.com/v1", true).is_err());
    }

    #[test]
    fn deceptive_or_invalid_hosts_are_rejected() {
        assert!(validate_vlm_endpoint("http://localhost:8080@evil.example/v1", false).is_err());
        assert!(validate_vlm_endpoint("file:///tmp/socket", true).is_err());
        assert!(validate_vlm_endpoint("not a URL", true).is_err());
    }
}
