//! The decision pipeline: observed state → legal, humanized decision view.
//!
//! Shared by every input mode (stdin replay, capture, overlay UI) so the
//! decision logic cannot drift between them.

use std::collections::HashMap;

use core_engine::decision::{Action, DecisionEngine, DecisionInput};
use core_engine::equity::{Card, EquityConfig, EquityEstimator, Rank, Suit};
use ghost_layer::betting_entropy::{BettingEntropy, BettingEntropyConfig};
use ingest::parser::{GamePhase, GameState};
use opponent_model::classifier::{Archetype, Classification, Classifier, ClassifierConfig};
use opponent_model::exploit::ExploitEngine;
use opponent_model::features::StatsAccumulator;
use ui::widgets::DecisionView;

/// Minimum model-reported confidence for a state to drive a decision.
///
/// VLM output is untrusted: observations reporting lower confidence are
/// suppressed rather than acted on.
pub const MIN_PERCEPTION_CONFIDENCE: f64 = 0.5;

/// Accumulates the opponent observations exposed by successive game states.
#[derive(Debug, Default)]
struct OpponentTracker {
    stats: HashMap<String, StatsAccumulator>,
    last_preflop_hand: Option<String>,
    last_actions: HashMap<String, (GamePhase, Option<String>, u32)>,
}

impl OpponentTracker {
    fn observe(&mut self, state: &GameState) {
        if state.game_phase == GamePhase::Preflop {
            let hand = state
                .hero_cards
                .iter()
                .map(|card| format!("{}:{}", card.rank, card.suit))
                .collect::<Vec<_>>()
                .join("|");
            if self.last_preflop_hand.as_deref() != Some(hand.as_str()) {
                self.last_preflop_hand = Some(hand);
                for player in state.players.iter().filter(|player| player.name != "Hero") {
                    let action = player.last_action.as_deref().unwrap_or_default();
                    self.stats
                        .entry(player.name.clone())
                        .or_default()
                        .observe_hand(
                            matches!(action, "call" | "raise" | "allin" | "bet"),
                            matches!(action, "raise" | "allin"),
                        );
                }
            }
        }

        for player in state.players.iter().filter(|player| player.name != "Hero") {
            let observation = (
                state.game_phase,
                player.last_action.clone(),
                player.bet_amount,
            );
            if self.last_actions.get(&player.name) == Some(&observation) {
                continue;
            }
            self.last_actions.insert(player.name.clone(), observation);

            if state.game_phase == GamePhase::Preflop {
                continue;
            }
            let stats = self.stats.entry(player.name.clone()).or_default();
            match player.last_action.as_deref().unwrap_or_default() {
                "bet" | "raise" | "allin" => stats.observe_aggressive_action(),
                "call" => stats.observe_passive_call(),
                _ => {}
            }
        }
    }

    fn classify(&self, name: &str, classifier: &Classifier) -> Classification {
        let stats = self
            .stats
            .get(name)
            .map(StatsAccumulator::stats)
            .unwrap_or_default();
        classifier.classify(&stats)
    }
}

/// The decision pipeline shared by all input modes.
pub struct Pipeline {
    engine: DecisionEngine,
    exploit: ExploitEngine,
    estimator: EquityEstimator,
    betting: BettingEntropy,
    classifier: Classifier,
    opponents: OpponentTracker,
}

impl Pipeline {
    /// Construct a pipeline with production defaults.
    pub fn new() -> Self {
        Self {
            engine: DecisionEngine::new(),
            exploit: ExploitEngine::new(),
            estimator: EquityEstimator::new(EquityConfig { iterations: 5_000 }),
            betting: BettingEntropy::new(BettingEntropyConfig::default()),
            classifier: Classifier::new(ClassifierConfig::default()),
            opponents: OpponentTracker::default(),
        }
    }

    /// Convert an observed state into a legal decision view.
    ///
    /// # Errors
    ///
    /// Returns a human-readable reason when the state must not drive a
    /// decision: low model confidence, unreadable cards, multiway all-in
    /// side-pot risk, or an illegal engine recommendation.
    pub fn decide(&mut self, state: &GameState) -> Result<DecisionView, String> {
        // Low model-reported confidence suppresses output entirely.
        if let Some(confidence) = state.confidence {
            if confidence < MIN_PERCEPTION_CONFIDENCE {
                return Err(format!(
                    "perception confidence {confidence:.2} is below the minimum {MIN_PERCEPTION_CONFIDENCE}"
                ));
            }
        }

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

        self.opponents.observe(state);
        let classification = active_opponents
            .first()
            .map(|player| self.opponents.classify(&player.name, &self.classifier))
            .unwrap_or_else(|| self.classifier.classify(&Default::default()));
        let adjustment = self.exploit.adjust(classification.archetype);

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
        let mut sizing_provenance = None;
        let raise_to = if can_raise {
            if !has_action("raise") {
                all_in_raise_to
            } else {
                let min_increment = min_raise_to.saturating_sub(hero_contribution);
                let max_increment = max_raise_to.saturating_sub(hero_contribution);
                let mut rng = rand::thread_rng();
                let size = self
                    .betting
                    .humanize_bounded_with_provenance(
                        &mut rng,
                        target_increment,
                        state.pot_size,
                        min_increment,
                        max_increment,
                    )
                    .map_err(|error| format!("raise humanization failed: {error}"))?;
                sizing_provenance = Some(size.provenance.annotation().to_string());
                hero_contribution.saturating_add(size.amount)
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
        let sizing_provenance = (action == "raise").then_some(sizing_provenance).flatten();

        Ok(DecisionView {
            action,
            amount,
            sizing_provenance,
            ev: decision.ev,
            pot_odds: decision.pot_odds,
            equity: decision.equity,
            break_even: decision.break_even,
            opponent: Some(archetype_label(classification.archetype).to_string()),
            confidence: Some(classification.confidence),
        })
    }
}

fn archetype_label(archetype: Archetype) -> &'static str {
    match archetype {
        Archetype::Lag => "lag",
        Archetype::Tag => "tag",
        Archetype::LoosePassive => "loose-passive",
        Archetype::TightPassive => "tight-passive",
        Archetype::Unknown => "unknown",
    }
}

impl Default for Pipeline {
    fn default() -> Self {
        Self::new()
    }
}

/// Convert ingest card strings into core-engine cards without dropping errors.
///
/// # Errors
///
/// Returns a human-readable message naming the offending card index for
/// unknown ranks or suits.
pub fn convert_cards(cards: &[ingest::parser::Card]) -> Result<Vec<Card>, String> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use ingest::parser::{parse_vlm_output, Card, GamePhase, PlayerState};
    use ingest::vlm::VlmOutput;

    const ACTION_STATE: &str = r#"{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"A","suit":"hearts"}],"board":[{"rank":"K","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],"pot_size":1000,"to_call":0,"hero_chips":5000,"min_raise_to":500,"max_raise_to":5000,"players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Villain","chips":5000,"last_action":"check","bet_amount":0}],"action_required":true,"available_actions":["check","raise"]}"#;

    fn actionable_state() -> GameState {
        parse_vlm_output(&VlmOutput {
            text: ACTION_STATE.to_string(),
        })
        .expect("fixture state")
    }

    #[test]
    fn actionable_states_produce_a_decision_view() {
        let view = Pipeline::new()
            .decide(&actionable_state())
            .expect("decision");
        assert!(matches!(
            view.action.as_str(),
            "check" | "raise" | "call" | "fold" | "allin"
        ));
        assert!(view.equity > 0.0);
        assert_eq!(view.opponent.as_deref(), Some("unknown"));
        assert_eq!(view.confidence, Some(0.0));
    }

    #[test]
    fn low_confidence_observations_are_suppressed() {
        let mut state = actionable_state();
        state.confidence = Some(MIN_PERCEPTION_CONFIDENCE);
        Pipeline::new()
            .decide(&state)
            .expect("confidence at the minimum is allowed");

        state.confidence = Some(MIN_PERCEPTION_CONFIDENCE - f64::EPSILON);
        let error = Pipeline::new()
            .decide(&state)
            .expect_err("below the minimum");
        assert!(error.contains("confidence"), "{error}");
    }

    #[test]
    fn missing_confidence_does_not_suppress() {
        let state = actionable_state();
        assert_eq!(state.confidence, None);
        Pipeline::new()
            .decide(&state)
            .expect("no confidence reported");
    }

    #[test]
    fn invalid_cards_are_reported_with_index() {
        let mut state = actionable_state();
        state.hero_cards[1] = Card {
            rank: "X".to_string(),
            suit: "spades".to_string(),
        };
        let error = Pipeline::new().decide(&state).expect_err("invalid rank");
        assert!(error.contains("card 1"), "{error}");
    }

    #[test]
    fn hero_card_count_is_enforced() {
        let mut state = actionable_state();
        state.hero_cards.truncate(1);
        let error = Pipeline::new().decide(&state).expect_err("one hero card");
        assert!(error.contains("exactly 2 hero cards"), "{error}");
    }

    #[test]
    fn multiway_allin_risk_is_refused() {
        let mut state = actionable_state();
        state.players.push(PlayerState {
            name: "Second".to_string(),
            chips: 0,
            last_action: Some("allin".to_string()),
            bet_amount: 100,
        });
        state.players.push(PlayerState {
            name: "Third".to_string(),
            chips: 500,
            last_action: None,
            bet_amount: 0,
        });
        let error = Pipeline::new().decide(&state).expect_err("side-pot risk");
        assert!(error.contains("side-pot"), "{error}");
    }

    #[test]
    fn missing_hero_player_is_refused() {
        let mut state = actionable_state();
        state.players.retain(|player| player.name != "Hero");
        let error = Pipeline::new().decide(&state).expect_err("no hero");
        assert!(error.contains("no Hero player"), "{error}");
    }

    #[test]
    fn convert_cards_maps_every_rank_and_suit() {
        let cards: Vec<core_engine::equity::Card> = convert_cards(&[
            ingest::parser::Card {
                rank: "A".to_string(),
                suit: "spades".to_string(),
            },
            ingest::parser::Card {
                rank: "2".to_string(),
                suit: "clubs".to_string(),
            },
        ])
        .expect("valid cards");
        assert_eq!(cards.len(), 2);

        let bad = convert_cards(&[ingest::parser::Card {
            rank: "A".to_string(),
            suit: "stars".to_string(),
        }]);
        assert!(bad.is_err());
    }

    #[test]
    fn default_pipeline_matches_new() {
        // Both must be constructible and decide identically on the fixture.
        let state = actionable_state();
        let a = Pipeline::new().decide(&state).expect("new");
        let b = Pipeline::default().decide(&state).expect("default");
        assert_eq!(a.action, b.action);
        assert_eq!(a.opponent, b.opponent);
        assert_eq!(
            state.game_phase,
            GamePhase::Flop,
            "fixture must remain a flop state"
        );
    }

    #[test]
    fn observed_opponent_history_drives_a_real_classification() {
        let classifier = Classifier::new(ClassifierConfig::default());
        let mut tracker = OpponentTracker::default();
        let mut state = actionable_state();
        state.game_phase = GamePhase::Preflop;
        state.board.clear();
        state.players[1].last_action = Some("call".to_string());

        for hand in 0..20 {
            state.hero_cards[0].rank = format!("hand-{hand}");
            tracker.observe(&state);
            state.game_phase = GamePhase::Flop;
            state.players[1].last_action = Some("raise".to_string());
            tracker.observe(&state);
            state.game_phase = GamePhase::Preflop;
            state.players[1].last_action = Some("call".to_string());
        }

        let classification = tracker.classify("Villain", &classifier);
        assert_eq!(classification.archetype, Archetype::Lag);
        assert!(classification.confidence > 0.5);
    }

    #[test]
    fn raise_recommendations_expose_ghost_sizing_provenance() {
        let mut state = actionable_state();
        state.available_actions = vec!["raise".to_string()];
        let view = Pipeline::new().decide(&state).expect("forced raise");
        assert_eq!(view.action, "raise");
        assert!(matches!(
            view.sizing_provenance.as_deref(),
            Some("ghost-menu") | Some("ghost-off-grid")
        ));
    }
}
