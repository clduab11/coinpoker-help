//! Game-phase tracking and event emission.
//!
//! Tracks transitions between lobby, seated/dealing, action-required, and
//! showdown states, emitting an event only when something actionable
//! changes. Downstream consumers (decision engine, UI) subscribe to these
//! events rather than polling raw states.

use crate::parser::{validate_game_state, GamePhase, GameState};

/// Check a transition on the screen gate's accepted table timeline.
///
/// This guard deliberately does not change [`StateMachine::update`]: stdin and
/// replay callers retain their existing event semantics. Screen observations
/// must pass both poker validation and this temporal check before acceptance.
///
/// Streets cannot be skipped, even during a non-action all-in runout; without
/// the intervening observations we cannot establish continuity. A new hand
/// requires an accepted showdown or an explicitly witnessed, empty, non-action
/// preflop state. Empty refers to cards, not the pot: blinds may already be posted.
/// The screen gate additionally requires readable evidence and fresh consensus
/// for that marker, so unreadable cards must never be represented as empty ones.
/// Within a hand, hero cards are immutable and the board must retain its prefix.
/// This is intentionally conservative about folded/mucked or newly readable cards.
pub fn validate_transition(previous: &GameState, next: &GameState) -> Result<(), &'static str> {
    validate_game_state(previous).map_err(|_| "previous table state is invalid")?;
    validate_game_state(next).map_err(|_| "next table state is invalid")?;

    let street = |phase| match phase {
        GamePhase::Lobby => None,
        GamePhase::Preflop => Some(0),
        GamePhase::Flop => Some(1),
        GamePhase::Turn => Some(2),
        GamePhase::River => Some(3),
        GamePhase::Showdown => Some(4),
    };
    let previous_street = street(previous.game_phase).ok_or("previous screen is not a table")?;
    let next_street = street(next.game_phase).ok_or("next screen is not a table")?;

    if is_inter_hand_marker(next)
        || (previous.game_phase == GamePhase::Showdown && next.game_phase == GamePhase::Preflop)
    {
        return Ok(());
    }
    if is_inter_hand_marker(previous) {
        return if next.game_phase == GamePhase::Preflop {
            Ok(())
        } else {
            Err("dealt preflop must be observed after the inter-hand marker")
        };
    }
    if next_street < previous_street {
        return Err("phase regressed without an inter-hand marker or showdown");
    }
    if next_street > previous_street + 1 {
        return Err("street was skipped on the accepted timeline");
    }
    if previous.hero_cards != next.hero_cards {
        return Err("hero cards changed within a hand");
    }
    if !next.board.starts_with(&previous.board) {
        return Err("board does not preserve the accepted prefix");
    }
    Ok(())
}

fn is_inter_hand_marker(state: &GameState) -> bool {
    state.game_phase == GamePhase::Preflop
        && state.hero_cards.is_empty()
        && state.board.is_empty()
        && !state.action_required
        && state.available_actions.is_empty()
        && state.to_call == 0
        && state.min_raise_to.is_none()
        && state.max_raise_to.is_none()
}

/// Events emitted by the state machine.
#[derive(Debug, Clone, PartialEq)]
pub enum TableEvent {
    /// Decision-relevant table state changed.
    StateChanged(GameState),
    /// It is the hero's turn to act.
    ActionRequired(GameState),
    /// The hand reached showdown.
    Showdown(GameState),
    /// The state is unchanged from the last processed state.
    NoChange,
}

/// Tracks table state across observations and emits [`TableEvent`]s.
#[derive(Debug, Clone, Default)]
pub struct StateMachine {
    last_state: Option<GameState>,
}

impl StateMachine {
    pub fn new() -> Self {
        Self::default()
    }

    /// Process an observed state and return the event it represents.
    pub fn update(&mut self, state: GameState) -> TableEvent {
        let event = match &self.last_state {
            None => {
                // First observation: report state, and action if required.
                if state.action_required {
                    TableEvent::ActionRequired(state.clone())
                } else if state.game_phase == GamePhase::Showdown {
                    TableEvent::Showdown(state.clone())
                } else {
                    TableEvent::StateChanged(state.clone())
                }
            }
            Some(prev) => {
                let action_turned_on = !prev.action_required && state.action_required;

                if state.game_phase == GamePhase::Showdown && prev.game_phase != GamePhase::Showdown
                {
                    TableEvent::Showdown(state.clone())
                } else if action_turned_on {
                    TableEvent::ActionRequired(state.clone())
                } else if prev != &state {
                    TableEvent::StateChanged(state.clone())
                } else {
                    TableEvent::NoChange
                }
            }
        };

        self.last_state = Some(state);
        event
    }

    /// The most recently processed state, if any.
    pub fn last_state(&self) -> Option<&GameState> {
        self.last_state.as_ref()
    }

    /// Reset tracking so the next observation is treated as the first.
    pub fn reset(&mut self) {
        self.last_state = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::{Card, PlayerState};

    fn state(phase: GamePhase, action: bool, pot: u32, board: usize) -> GameState {
        GameState {
            game_phase: phase,
            hero_cards: vec![],
            board: [
                ("Q", "diamonds"),
                ("7", "clubs"),
                ("2", "spades"),
                ("9", "hearts"),
                ("J", "clubs"),
            ]
            .into_iter()
            .take(board)
            .map(|(rank, suit)| Card {
                rank: rank.to_string(),
                suit: suit.to_string(),
            })
            .collect(),
            pot_size: pot,
            to_call: 0,
            hero_chips: 0,
            min_raise_to: None,
            max_raise_to: None,
            players: vec![],
            action_required: action,
            available_actions: if action {
                vec!["fold".to_string(), "call".to_string()]
            } else {
                vec![]
            },
        }
    }

    #[test]
    fn first_observation_emits_state_changed() {
        let mut sm = StateMachine::new();
        let event = sm.update(state(GamePhase::Preflop, false, 100, 0));
        assert_eq!(
            event,
            TableEvent::StateChanged(state(GamePhase::Preflop, false, 100, 0))
        );
    }

    #[test]
    fn first_observation_with_action_emits_action_required() {
        let mut sm = StateMachine::new();
        let event = sm.update(state(GamePhase::Preflop, true, 100, 0));
        assert!(matches!(event, TableEvent::ActionRequired(_)));
    }

    #[test]
    fn unchanged_state_emits_no_change() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::Preflop, false, 100, 0));
        let event = sm.update(state(GamePhase::Preflop, false, 100, 0));
        assert_eq!(event, TableEvent::NoChange);
    }

    #[test]
    fn pot_change_emits_state_changed() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::Preflop, false, 100, 0));
        let event = sm.update(state(GamePhase::Preflop, false, 250, 0));
        assert!(matches!(event, TableEvent::StateChanged(_)));
    }

    #[test]
    fn action_turning_on_emits_action_required_once() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::Preflop, false, 100, 0));
        let event = sm.update(state(GamePhase::Preflop, true, 100, 0));
        assert!(matches!(event, TableEvent::ActionRequired(_)));
        // Action still required on the next observation: no repeat event.
        let event = sm.update(state(GamePhase::Preflop, true, 100, 0));
        assert_eq!(event, TableEvent::NoChange);
    }

    #[test]
    fn to_call_change_emits_state_changed_while_action_remains_required() {
        let mut sm = StateMachine::new();
        let initial = state(GamePhase::Preflop, true, 100, 0);
        sm.update(initial.clone());

        let mut changed = initial;
        changed.to_call = 50;
        assert!(matches!(sm.update(changed), TableEvent::StateChanged(_)));
    }

    #[test]
    fn hero_card_change_emits_state_changed_while_action_remains_required() {
        let mut sm = StateMachine::new();
        let initial = state(GamePhase::Preflop, true, 100, 0);
        sm.update(initial.clone());

        let mut changed = initial;
        changed.hero_cards = vec![
            Card {
                rank: "A".to_string(),
                suit: "spades".to_string(),
            },
            Card {
                rank: "K".to_string(),
                suit: "hearts".to_string(),
            },
        ];
        assert!(matches!(sm.update(changed), TableEvent::StateChanged(_)));
    }

    #[test]
    fn available_action_change_emits_state_changed_while_action_remains_required() {
        let mut sm = StateMachine::new();
        let initial = state(GamePhase::Preflop, true, 100, 0);
        sm.update(initial.clone());

        let mut changed = initial;
        changed.available_actions.push("raise".to_string());
        assert!(matches!(sm.update(changed), TableEvent::StateChanged(_)));
    }

    #[test]
    fn player_change_emits_state_changed_while_action_remains_required() {
        let mut sm = StateMachine::new();
        let initial = state(GamePhase::Preflop, true, 100, 0);
        sm.update(initial.clone());

        let mut changed = initial;
        changed.players.push(PlayerState {
            name: "Villain".to_string(),
            chips: 2_000,
            last_action: Some("raise".to_string()),
            bet_amount: 100,
        });
        assert!(matches!(sm.update(changed), TableEvent::StateChanged(_)));
    }

    #[test]
    fn street_transition_emits_state_changed() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::Preflop, false, 100, 0));
        let event = sm.update(state(GamePhase::Flop, false, 100, 3));
        assert!(matches!(event, TableEvent::StateChanged(_)));
    }

    #[test]
    fn showdown_transition_emits_showdown() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::River, false, 500, 5));
        let event = sm.update(state(GamePhase::Showdown, false, 500, 5));
        assert!(matches!(event, TableEvent::Showdown(_)));
    }

    #[test]
    fn reset_forces_first_observation_semantics() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::Preflop, false, 100, 0));
        sm.reset();
        let event = sm.update(state(GamePhase::Preflop, false, 100, 0));
        assert!(matches!(event, TableEvent::StateChanged(_)));
    }

    #[test]
    fn initial_showdown_is_emitted_once_and_later_changes_are_reported() {
        let mut sm = StateMachine::new();
        let initial = state(GamePhase::Showdown, false, 500, 5);
        assert_eq!(
            sm.update(initial.clone()),
            TableEvent::Showdown(initial.clone())
        );
        assert_eq!(sm.update(initial.clone()), TableEvent::NoChange);
        let mut changed = initial;
        changed.pot_size = 600;
        assert_eq!(
            sm.update(changed.clone()),
            TableEvent::StateChanged(changed)
        );
    }

    #[test]
    fn last_state_tracks_changes_and_reset_clears_it() {
        let mut sm = StateMachine::new();
        assert_eq!(sm.last_state(), None);
        let observed = state(GamePhase::Flop, false, 250, 3);
        sm.update(observed.clone());
        assert_eq!(sm.last_state(), Some(&observed));
        sm.reset();
        assert_eq!(sm.last_state(), None);
    }

    #[test]
    fn update_keeps_replay_semantics_without_the_screen_transition_guard() {
        let mut sm = StateMachine::new();
        sm.update(state(GamePhase::River, false, 500, 5));
        let next = state(GamePhase::Preflop, true, 100, 0);
        assert_eq!(sm.update(next.clone()), TableEvent::ActionRequired(next));
    }

    fn tracked_state(phase: GamePhase, action: bool) -> GameState {
        let mut observed = state(phase, action, 100, phase.expected_board_cards());
        observed.hero_cards = vec![
            Card {
                rank: "A".to_string(),
                suit: "spades".to_string(),
            },
            Card {
                rank: "K".to_string(),
                suit: "hearts".to_string(),
            },
        ];
        observed.hero_chips = 1_000;
        observed.players = ["Hero", "Seat1"]
            .into_iter()
            .map(|name| PlayerState {
                name: name.to_string(),
                chips: 1_000,
                last_action: None,
                bet_amount: 0,
            })
            .collect();
        observed.available_actions = if action {
            vec!["check".to_string()]
        } else {
            vec![]
        };
        validate_game_state(&observed).expect("valid temporal fixture");
        observed
    }

    fn inter_hand_marker() -> GameState {
        let mut marker = tracked_state(GamePhase::Preflop, false);
        marker.hero_cards.clear();
        marker
    }

    #[test]
    fn temporal_guard_allows_stable_states_actions_and_adjacent_streets() {
        let phases = [
            GamePhase::Preflop,
            GamePhase::Flop,
            GamePhase::Turn,
            GamePhase::River,
            GamePhase::Showdown,
        ];
        for phase in phases {
            let observed = tracked_state(phase, false);
            assert_eq!(validate_transition(&observed, &observed), Ok(()));
            let mut changed = observed.clone();
            changed.pot_size += 50;
            if phase != GamePhase::Showdown {
                changed.action_required = true;
                changed.available_actions.push("check".to_string());
            }
            assert_eq!(validate_transition(&observed, &changed), Ok(()));
        }
        for pair in phases.windows(2) {
            assert_eq!(
                validate_transition(
                    &tracked_state(pair[0], false),
                    &tracked_state(pair[1], false)
                ),
                Ok(())
            );
        }
    }

    #[test]
    fn temporal_guard_rejects_regressions_and_direct_actionable_hand_resets() {
        for (previous, next) in [
            (GamePhase::Flop, GamePhase::Preflop),
            (GamePhase::Turn, GamePhase::Flop),
            (GamePhase::River, GamePhase::Turn),
            (GamePhase::Showdown, GamePhase::River),
        ] {
            for action in [false, true] {
                assert!(validate_transition(
                    &tracked_state(previous, false),
                    &tracked_state(next, action)
                )
                .is_err());
            }
        }
    }

    #[test]
    fn temporal_guard_rejects_all_skipped_streets_including_all_in_runouts() {
        let phases = [
            GamePhase::Preflop,
            GamePhase::Flop,
            GamePhase::Turn,
            GamePhase::River,
            GamePhase::Showdown,
        ];
        for (index, previous) in phases.iter().enumerate() {
            for next in phases.iter().skip(index + 2) {
                let mut all_in = tracked_state(*previous, false);
                all_in.hero_chips = 0;
                all_in.players[0].chips = 0;
                all_in.players[0].last_action = Some("allin".to_string());
                let mut runout = all_in.clone();
                runout.game_phase = *next;
                runout.board = tracked_state(*next, false).board;
                assert_eq!(
                    validate_transition(&all_in, &runout),
                    Err("street was skipped on the accepted timeline")
                );
            }
        }
    }

    #[test]
    fn temporal_guard_rejects_card_mutation_and_board_prefix_changes() {
        let previous = tracked_state(GamePhase::Flop, false);
        let mut next = tracked_state(GamePhase::Turn, false);
        next.hero_cards[0].rank = "T".to_string();
        assert_eq!(
            validate_transition(&previous, &next),
            Err("hero cards changed within a hand")
        );
        next.hero_cards.clear();
        assert!(validate_transition(&previous, &next).is_err());
        next.hero_cards = previous.hero_cards.clone();
        next.board[0].rank = "8".to_string();
        assert_eq!(
            validate_transition(&previous, &next),
            Err("board does not preserve the accepted prefix")
        );
        next = previous.clone();
        next.board.swap(0, 1);
        assert!(validate_transition(&previous, &next).is_err());
    }

    #[test]
    fn temporal_guard_allows_a_new_hand_only_after_a_clear_boundary() {
        let previous = tracked_state(GamePhase::River, false);
        let marker = inter_hand_marker();
        let mut dealt = tracked_state(GamePhase::Preflop, true);
        dealt.hero_cards[0].rank = "T".to_string();
        assert!(validate_transition(&previous, &dealt).is_err());
        assert_eq!(validate_transition(&previous, &marker), Ok(()));
        assert_eq!(validate_transition(&marker, &dealt), Ok(()));
        assert_eq!(
            validate_transition(&tracked_state(GamePhase::Showdown, false), &dealt),
            Ok(())
        );
        assert!(validate_transition(&marker, &tracked_state(GamePhase::Flop, false)).is_err());
    }

    #[test]
    fn temporal_guard_does_not_treat_uncleared_preflop_states_as_a_marker() {
        let previous = tracked_state(GamePhase::River, false);
        let mut marker = inter_hand_marker();
        marker.to_call = 50;
        assert!(validate_transition(&previous, &marker).is_err());
        marker.to_call = 0;
        marker.min_raise_to = Some(100);
        assert!(validate_transition(&previous, &marker).is_err());
        marker.min_raise_to = None;
        marker.hero_cards = tracked_state(GamePhase::Preflop, false).hero_cards;
        assert!(validate_transition(&previous, &marker).is_err());
    }

    #[test]
    fn temporal_guard_rejects_invalid_poker_states_and_lobby_states() {
        let previous = tracked_state(GamePhase::Flop, false);
        let mut invalid = previous.clone();
        invalid.board.clear();
        assert_eq!(
            validate_transition(&previous, &invalid),
            Err("next table state is invalid")
        );
        assert_eq!(
            validate_transition(&invalid, &previous),
            Err("previous table state is invalid")
        );
        let lobby = state(GamePhase::Lobby, false, 0, 0);
        assert!(validate_transition(&previous, &lobby).is_err());
        assert!(validate_transition(&lobby, &previous).is_err());
    }
}
