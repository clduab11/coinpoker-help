//! Cross-crate integration smoke test: observed state → parse → state machine
//! → decision → humanized sizing → serializable decision view.
//!
//! Runs on any host (no screen capture or VLM server required).

use core_engine::decision::{DecisionEngine, DecisionInput};
use core_engine::equity::{Card, EquityConfig, EquityEstimator, Rank, Suit};
use ghost_layer::betting_entropy::{BettingEntropy, BettingEntropyConfig};
use ingest::parser::{parse_vlm_output, GameState};
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::VlmOutput;
use opponent_model::classifier::{Archetype, Classifier, ClassifierConfig};
use opponent_model::exploit::ExploitEngine;
use rand::SeedableRng;
use ui::widgets::DecisionView;

const FLOP_STATE: &str = include_str!("fixtures/flop_state.json");

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

#[test]
fn cross_crate_pipeline_produces_a_decision_view() {
    // 1. VLM output → GameState.
    let output = VlmOutput {
        text: FLOP_STATE.to_string(),
    };
    let state: GameState = parse_vlm_output(&output).expect("parse state");

    // 2. State machine emits ActionRequired on first observation.
    let mut sm = StateMachine::new();
    let event = sm.update(state.clone());
    assert!(matches!(event, TableEvent::ActionRequired(_)));

    // 3. Opponent classification (no history yet → Unknown).
    let classifier = Classifier::new(ClassifierConfig::default());
    let archetype = Archetype::Unknown;
    let _ = classifier;
    let adjustment = ExploitEngine::new().adjust(archetype);

    // 4. Equity: hero top pair + top kicker against one unknown opponent.
    let estimator = EquityEstimator::new(EquityConfig { iterations: 2_000 });
    let hero = convert_cards(&state.hero_cards);
    let board = convert_cards(&state.board);
    let equity = estimator
        .estimate_against_unknown(&hero, 1, &board)
        .expect("estimate");
    assert!(equity > 0.5, "top pair should be ahead, got {equity}");

    // 5. Decision engine recommends an action.
    let engine = DecisionEngine::new();
    let decision = engine
        .decide(&DecisionInput {
            pot: state.pot_size,
            to_call: state.to_call,
            equity,
            hero_chips: state.hero_chips,
            hero_contribution: 0,
            fold_equity: (0.3 * adjustment.fold_equity_multiplier).clamp(0.0, 1.0),
            raise_to: 1_000,
            min_raise_to: 1_000,
            expected_caller_contribution: 500,
            can_fold: true,
            can_check: false,
            can_call: true,
            can_raise: true,
        })
        .expect("fixture offers legal actions");

    // 6. Ghost layer humanizes the sizing.
    let betting = BettingEntropy::new(BettingEntropyConfig::default());
    let mut rng = rand::rngs::StdRng::seed_from_u64(1);
    let amount = if decision.action == core_engine::decision::Action::Raise {
        betting
            .humanize_bounded(
                &mut rng,
                decision.amount,
                state.pot_size,
                decision.amount,
                state.hero_chips,
            )
            .expect("legal sizing bounds")
    } else {
        decision.amount
    };

    // 7. A serializable view reaches the UI layer.
    let view = DecisionView {
        action: format!("{:?}", decision.action).to_lowercase(),
        amount,
        sizing_provenance: None,
        ev: decision.ev,
        pot_odds: decision.pot_odds,
        equity: decision.equity,
        break_even: decision.break_even,
        opponent: Some("unknown".to_string()),
        confidence: Some(0.0),
    };
    let json = serde_json::to_string(&view).expect("serialize view");
    let parsed: serde_json::Value = serde_json::from_str(&json).expect("valid json");
    assert!(parsed["action"].is_string());
    assert!(parsed["ev"].is_number());
    assert!(parsed["equity"].is_number());
}

#[test]
fn state_machine_and_parser_agree_on_phases() {
    let output = VlmOutput {
        text: FLOP_STATE.to_string(),
    };
    let state = parse_vlm_output(&output).expect("parse");
    assert_eq!(state.game_phase, ingest::parser::GamePhase::Flop);
    assert_eq!(state.board.len(), 3);
    assert_eq!(state.hero_cards.len(), 2);
}
