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
    /// The table state changed meaningfully (new street, new cards, new pot).
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
    last_phase: Option<GamePhase>,
    last_action_required: bool,
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
                let phase_changed = prev.game_phase != state.game_phase;
                let action_turned_on = !self.last_action_required && state.action_required;
                let state_meaningfully_changed =
                    prev.pot_size != state.pot_size || prev.board != state.board;

                if state.game_phase == GamePhase::Showdown && prev.game_phase != GamePhase::Showdown
                {
                    TableEvent::Showdown(state.clone())
                } else if action_turned_on {
                    TableEvent::ActionRequired(state.clone())
                } else if phase_changed || state_meaningfully_changed {
                    TableEvent::StateChanged(state.clone())
                } else {
                    TableEvent::NoChange
                }
            }
        };

        self.last_phase = Some(state.game_phase);
        self.last_action_required = state.action_required;
        self.last_state = Some(state);
        event
    }

    /// The most recently processed state, if any.
    pub fn last_state(&self) -> Option<&GameState> {
        self.last_state.as_ref()
    }

    /// Reset tracking so the next observation is treated as the first.
    pub fn reset(&mut self) {
        self.last_phase = None;
        self.last_action_required = false;
        self.last_state = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::Card;

    fn state(phase: GamePhase, action: bool, pot: u32, board: usize) -> GameState {
        GameState {
            game_phase: phase,
            hero_cards: vec![],
            board: vec![
                Card {
                    rank: "Q".to_string(),
                    suit: "diamonds".to_string(),
                };
                board
            ],
            pot_size: pot,
            to_call: 0,
            hero_chips: 0,
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
