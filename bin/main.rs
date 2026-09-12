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
//! - `coinpoker --ui`       — egui desktop decision panel.
//! - `coinpoker --list-windows` — list capture candidates for calibration.

use core_engine::decision::{DecisionEngine, DecisionInput};
use core_engine::equity::{Card, EquityConfig, EquityEstimator, Rank, Suit};
use ghost_layer::betting_entropy::{BettingEntropy, BettingEntropyConfig};
use ingest::capture::{CaptureConfig, WindowCapturer};
use ingest::change_detect::{ChangeDetector, ChangeDetectorConfig};
use ingest::parser::{parse_vlm_output, GameState};
use ingest::prompt::build_analysis_prompt;
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::{MlxServerBackend, VlmBackend, VlmConfig};
use opponent_model::classifier::Archetype;
use opponent_model::exploit::ExploitEngine;
use ui::widgets::DecisionView;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("--ui") => {
            if let Err(e) = ui::app::run() {
                eprintln!("ui error: {e}");
                std::process::exit(1);
            }
        }
        Some("--list-windows") => {
            let capturer = match WindowCapturer::new(CaptureConfig::default()) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("capture unavailable: {e}");
                    std::process::exit(1);
                }
            };
            match capturer.list_candidate_windows() {
                Ok(windows) => {
                    for w in windows {
                        println!(
                            "title={:?} app={:?} on_screen={}",
                            w.title, w.app_name, w.on_screen
                        );
                    }
                }
                Err(e) => {
                    eprintln!("list windows failed: {e}");
                    std::process::exit(1);
                }
            }
        }
        Some("--stdin") => run_stdin_pipeline(),
        _ => run_capture_pipeline(),
    }
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

    /// Convert an observed state into a decision view.
    fn decide(&self, state: &GameState) -> DecisionView {
        // v1 opponent modeling: classify the first non-hero player using
        // default statistics (no history yet) — yields Unknown until the
        // accumulator is fed real observations.
        let archetype = state
            .players
            .iter()
            .find(|p| p.name != "Hero")
            .map(|_| Archetype::Unknown)
            .unwrap_or(Archetype::Unknown);

        let adjustment = self.exploit.adjust(archetype);

        // Estimate equity against a representative opponent hand. Fixed
        // representative hands can collide with the hero's cards or the
        // board, so try candidates in order until one is conflict-free.
        let hero = convert_cards(&state.hero_cards);
        let board = convert_cards(&state.board);
        let equity = if hero.len() == 2 && board.len() <= 5 {
            representative_hands(archetype)
                .into_iter()
                .find_map(|opponent| {
                    self.estimator
                        .estimate(&[hero.clone(), opponent], &board)
                        .ok()
                        .map(|e| e[0])
                })
                .unwrap_or_else(|| {
                    eprintln!("equity estimate failed; falling back to 0.5");
                    0.5
                })
        } else {
            0.5
        };

        let base_raise = (state.pot_size as f64 * 0.75).round().max(1.0) as u32;
        let raise_amount = (base_raise as f64 * adjustment.raise_size_multiplier).round() as u32;

        let input = DecisionInput {
            pot: state.pot_size,
            to_call: state.to_call,
            equity,
            hero_chips: state.hero_chips,
            fold_equity: (0.3 * adjustment.fold_equity_multiplier).clamp(0.0, 1.0),
            raise_amount,
            can_check: state.to_call == 0,
        };
        let decision = self.engine.decide(&input);

        // Humanize the recommended raise size through the betting-entropy
        // menu so the operator sees discretized, human-plausible sizing.
        let amount = if decision.action == core_engine::decision::Action::Raise {
            let mut rng = rand::thread_rng();
            self.betting
                .humanize(&mut rng, decision.amount, state.pot_size)
        } else {
            decision.amount
        };

        DecisionView {
            action: format!("{:?}", decision.action).to_lowercase(),
            amount,
            ev: decision.ev,
            pot_odds: decision.pot_odds,
            equity: decision.equity,
            break_even: decision.break_even,
            opponent: Some(format!("{archetype:?}").to_lowercase()),
            confidence: Some(0.0),
        }
    }
}

/// Convert ingest card strings into core-engine cards.
fn convert_cards(cards: &[ingest::parser::Card]) -> Vec<Card> {
    cards
        .iter()
        .filter_map(|c| {
            let rank = match c.rank.as_str() {
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
                _ => return None,
            };
            let suit = match c.suit.as_str() {
                "spades" => Suit::Spades,
                "hearts" => Suit::Hearts,
                "diamonds" => Suit::Diamonds,
                "clubs" => Suit::Clubs,
                _ => return None,
            };
            Some(Card::new(rank, suit))
        })
        .collect()
}

/// Representative opponent holdings per archetype (v1 simplification;
/// range-based equity is planned for the opponent-model v2). Multiple
/// candidates are tried in order to avoid card collisions with the hero
/// and the board.
fn representative_hands(archetype: Archetype) -> Vec<Vec<Card>> {
    match archetype {
        Archetype::Lag => vec![
            vec![
                Card::new(Rank::Queen, Suit::Spades),
                Card::new(Rank::Nine, Suit::Spades),
            ],
            vec![
                Card::new(Rank::Jack, Suit::Hearts),
                Card::new(Rank::Ten, Suit::Clubs),
            ],
            vec![
                Card::new(Rank::Eight, Suit::Diamonds),
                Card::new(Rank::Seven, Suit::Diamonds),
            ],
        ],
        Archetype::Tag => vec![
            vec![
                Card::new(Rank::Ace, Suit::Hearts),
                Card::new(Rank::Jack, Suit::Hearts),
            ],
            vec![
                Card::new(Rank::King, Suit::Diamonds),
                Card::new(Rank::Queen, Suit::Diamonds),
            ],
            vec![
                Card::new(Rank::Ace, Suit::Clubs),
                Card::new(Rank::Ten, Suit::Clubs),
            ],
        ],
        Archetype::LoosePassive => vec![
            vec![
                Card::new(Rank::Seven, Suit::Diamonds),
                Card::new(Rank::Two, Suit::Clubs),
            ],
            vec![
                Card::new(Rank::Nine, Suit::Hearts),
                Card::new(Rank::Four, Suit::Spades),
            ],
            vec![
                Card::new(Rank::Six, Suit::Clubs),
                Card::new(Rank::Three, Suit::Diamonds),
            ],
        ],
        Archetype::TightPassive => vec![
            vec![
                Card::new(Rank::Ace, Suit::Clubs),
                Card::new(Rank::Queen, Suit::Clubs),
            ],
            vec![
                Card::new(Rank::King, Suit::Spades),
                Card::new(Rank::Jack, Suit::Spades),
            ],
            vec![
                Card::new(Rank::Ace, Suit::Diamonds),
                Card::new(Rank::Ten, Suit::Diamonds),
            ],
        ],
        Archetype::Unknown => vec![
            vec![
                Card::new(Rank::King, Suit::Hearts),
                Card::new(Rank::Ten, Suit::Hearts),
            ],
            vec![
                Card::new(Rank::Queen, Suit::Clubs),
                Card::new(Rank::Jack, Suit::Clubs),
            ],
            vec![
                Card::new(Rank::Nine, Suit::Diamonds),
                Card::new(Rank::Eight, Suit::Diamonds),
            ],
        ],
    }
}

/// Read `GameState` JSON lines from stdin and emit decision JSON lines.
fn run_stdin_pipeline() {
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();
    let mut state_machine = StateMachine::new();

    for line in std::io::stdin().lines() {
        let line = match line {
            Ok(l) => l,
            Err(e) => {
                eprintln!("stdin error: {e}");
                break;
            }
        };
        let state: GameState = match serde_json::from_str(&line) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("invalid state line: {e}");
                continue;
            }
        };

        if let TableEvent::ActionRequired(s) | TableEvent::StateChanged(s) =
            state_machine.update(state)
        {
            if s.action_required {
                let view = pipeline.decide(&s);
                if let Err(e) = emitter.emit_decision(&view) {
                    eprintln!("emit error: {e}");
                }
            }
        }
    }
}

/// Capture-driven pipeline (macOS): poll frames, fire the VLM on change,
/// and emit decisions when the hero must act.
fn run_capture_pipeline() {
    let capturer = match WindowCapturer::new(CaptureConfig::default()) {
        Ok(c) => c,
        Err(e) => {
            eprintln!(
                "capture unavailable: {e}\n\
                 Screen capture requires macOS 14+ with Screen Recording \
                 permission granted in System Settings."
            );
            std::process::exit(1);
        }
    };

    let backend = MlxServerBackend::new(VlmConfig::default());
    let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
    let mut state_machine = StateMachine::new();
    let pipeline = Pipeline::new();
    let emitter = ui::headless::stdout();

    loop {
        let frame = match capturer.capture_frame() {
            Ok(f) => f,
            Err(e) => {
                eprintln!("capture error: {e}");
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
            Ok(o) => o,
            Err(e) => {
                eprintln!("vlm error: {e}");
                std::thread::sleep(std::time::Duration::from_millis(200));
                continue;
            }
        };

        let state = match parse_vlm_output(&output) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("parse error: {e}");
                continue;
            }
        };

        if let TableEvent::ActionRequired(s) | TableEvent::StateChanged(s) =
            state_machine.update(state)
        {
            if s.action_required {
                let view = pipeline.decide(&s);
                if let Err(e) = emitter.emit_decision(&view) {
                    eprintln!("emit error: {e}");
                }
            }
        }

        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}
