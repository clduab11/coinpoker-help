//! End-to-end pipeline smoke test: observed state → parse → state machine →
//! decision → humanized sizing → serializable decision view.
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

/// A flop state where the hero holds top pair and faces a half-pot bet.
const FLOP_STATE: &str = r#"{
    "game_phase": "flop",
    "hero_cards": [{"rank": "A", "suit": "spades"}, {"rank": "K", "suit": "hearts"}],
    "board": [{"rank": "A", "suit": "diamonds"}, {"rank": "7", "suit": "clubs"}, {"rank": "2", "suit": "spades"}],
    "pot_size": 1000,
    "to_call": 500,
    "hero_chips": 5000,
    "players": [
        {"name": "Hero", "chips": 5000, "last_action": "check", "bet_amount": 0},
        {"name": "Villain", "chips": 5000, "last_action": "bet", "bet_amount": 500}
    ],
    "action_required": true,
    "available_actions": ["fold", "call", "raise"]
}"#;

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
fn full_pipeline_produces_a_decision_view() {
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

    // 4. Equity: hero top pair + top kicker vs a representative hand.
    let estimator = EquityEstimator::new(EquityConfig { iterations: 2_000 });
    let hero = convert_cards(&state.hero_cards);
    let board = convert_cards(&state.board);
    let opponent = vec![
        Card::new(Rank::Queen, Suit::Hearts),
        Card::new(Rank::Jack, Suit::Hearts),
    ];
    let equity = estimator
        .estimate(&[hero, opponent], &board)
        .expect("estimate")[0];
    assert!(equity > 0.5, "top pair should be ahead, got {equity}");

    // 5. Decision engine recommends an action.
    let engine = DecisionEngine::new();
    let decision = engine.decide(&DecisionInput {
        pot: state.pot_size,
        to_call: state.to_call,
        equity,
        hero_chips: state.hero_chips,
        fold_equity: (0.3 * adjustment.fold_equity_multiplier).clamp(0.0, 1.0),
        raise_amount: 750,
        can_check: false,
    });

    // 6. Ghost layer humanizes the sizing.
    let betting = BettingEntropy::new(BettingEntropyConfig::default());
    let mut rng = rand::rngs::StdRng::seed_from_u64(1);
    let amount = if decision.action == core_engine::decision::Action::Raise {
        betting.humanize(&mut rng, decision.amount, state.pot_size)
    } else {
        decision.amount
    };

    // 7. A serializable view reaches the UI layer.
    let view = DecisionView {
        action: format!("{:?}", decision.action).to_lowercase(),
        amount,
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
