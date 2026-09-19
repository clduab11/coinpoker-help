//! Game-phase tracking and event emission.
//!
//! Tracks transitions between lobby, seated/dealing, action-required, and
//! showdown states, emitting an event only when something actionable
//! changes. Downstream consumers (decision engine, UI) subscribe to these
//! events rather than polling raw states.

use crate::parser::{GamePhase, GameState};

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
}
