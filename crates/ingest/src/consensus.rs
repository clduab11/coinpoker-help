//! Frame-consensus gating for accepted game states.
//!
//! A single VLM observation is untrusted: transient animation frames,
//! compression artifacts, and model jitter can each produce a wrong state.
//! The consensus tracker requires `required` identical observations within
//! a sliding window of the last `window` observations before a state is
//! accepted. The default is 2-of-3: two matching observations out of the
//! last three.
//!
//! The caller feeds every successfully parsed observation in and only
//! forwards [`ConsensusOutcome::Accepted`] states to the state machine;
//! [`ConsensusOutcome::Pending`] means the evidence is not yet consistent.

use std::collections::VecDeque;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::parser::GameState;

/// Semantic validation errors for [`ConsensusConfig`].
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum ConsensusConfigError {
    /// The sliding window must hold at least one observation.
    #[error("consensus window must be at least 1")]
    WindowTooSmall,
    /// More matches are required than the window can hold.
    #[error("consensus requires {required} matches within a window of {window}")]
    RequiredExceedsWindow { required: usize, window: usize },
}

/// Configuration for the consensus tracker.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConsensusConfig {
    /// Sliding window of recent observations.
    pub window: usize,
    /// Identical observations required within the window to accept.
    pub required: usize,
}

impl Default for ConsensusConfig {
    fn default() -> Self {
        Self {
            window: 3,
            required: 2,
        }
    }
}

impl ConsensusConfig {
    /// Validate the configuration: the window must be non-empty and the
    /// required matches must fit inside it.
    pub fn validate(&self) -> Result<(), ConsensusConfigError> {
        if self.window < 1 {
            return Err(ConsensusConfigError::WindowTooSmall);
        }
        if self.required > self.window {
            return Err(ConsensusConfigError::RequiredExceedsWindow {
                required: self.required,
                window: self.window,
            });
        }
        Ok(())
    }
}

/// Result of feeding an observation to the tracker.
#[derive(Debug, Clone, PartialEq)]
pub enum ConsensusOutcome {
    /// Enough matching observations accumulated; the state is accepted.
    Accepted(GameState),
    /// Not enough matching observations yet.
    Pending,
}

/// Sliding-window consensus over parsed game states.
#[derive(Debug, Clone)]
pub struct ConsensusTracker {
    config: ConsensusConfig,
    window: VecDeque<GameState>,
}

impl ConsensusTracker {
    /// Construct a tracker after validating its configuration.
    pub fn try_new(config: ConsensusConfig) -> Result<Self, ConsensusConfigError> {
        config.validate()?;
        Ok(Self {
            config,
            window: VecDeque::with_capacity(config.window),
        })
    }

    /// The validated configuration in use.
    pub fn config(&self) -> &ConsensusConfig {
        &self.config
    }

    /// Feed one observation and report whether consensus was reached.
    ///
    /// The state is accepted when at least `required` observations equal to
    /// it are present in the window. Re-accepting an already-accepted state
    /// is the caller's concern: the downstream state machine collapses
    /// repeated states to `NoChange`.
    pub fn observe(&mut self, state: GameState) -> ConsensusOutcome {
        self.window.push_back(state);
        while self.window.len() > self.config.window {
            self.window.pop_front();
        }

        let accepted = self
            .window
            .iter()
            .max_by_key(|candidate| {
                self.window
                    .iter()
                    .filter(|observed| **observed == **candidate)
                    .count()
            })
            .cloned();
        let accepted = match accepted {
            Some(state) => state,
            None => return ConsensusOutcome::Pending,
        };
        let matches = self
            .window
            .iter()
            .filter(|observed| **observed == accepted)
            .count();

        if matches >= self.config.required {
            ConsensusOutcome::Accepted(accepted)
        } else {
            ConsensusOutcome::Pending
        }
    }

    /// Discard all pending observations.
    ///
    /// Called when the pipeline resets (capture error, VLM error, invalid
    /// observation) so stale evidence cannot confirm a future state.
    pub fn reset(&mut self) {
        self.window.clear();
    }

    /// Number of observations currently held.
    pub fn len(&self) -> usize {
        self.window.len()
    }

    /// Whether the tracker holds no observations.
    pub fn is_empty(&self) -> bool {
        self.window.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parser::{Card, GamePhase};

    fn state(pot: u32) -> GameState {
        GameState {
            game_phase: GamePhase::Preflop,
            hero_cards: vec![],
            board: vec![],
            pot_size: pot,
            to_call: 0,
            hero_chips: 0,
            min_raise_to: None,
            max_raise_to: None,
            players: vec![],
            action_required: false,
            available_actions: vec![],
            confidence: None,
        }
    }

    fn cards(pot: u32, rank: &str) -> GameState {
        let mut s = state(pot);
        s.hero_cards = vec![Card {
            rank: rank.to_string(),
            suit: "spades".to_string(),
        }];
        s
    }

    #[test]
    fn default_config_is_two_of_three() {
        let config = ConsensusConfig::default();
        assert_eq!((config.window, config.required), (3, 2));
        assert!(config.validate().is_ok());
    }

    #[test]
    fn invalid_configs_are_rejected() {
        assert_eq!(
            ConsensusConfig {
                window: 0,
                required: 1
            }
            .validate(),
            Err(ConsensusConfigError::WindowTooSmall)
        );
        assert_eq!(
            ConsensusConfig {
                window: 2,
                required: 3
            }
            .validate(),
            Err(ConsensusConfigError::RequiredExceedsWindow {
                required: 3,
                window: 2
            })
        );
        assert!(ConsensusTracker::try_new(ConsensusConfig {
            window: 2,
            required: 3
        })
        .is_err());
    }

    #[test]
    fn single_observation_is_pending_under_two_of_three() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
        assert_eq!(tracker.len(), 1);
    }

    #[test]
    fn two_matching_observations_are_accepted() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
        let outcome = tracker.observe(state(100));
        assert!(matches!(outcome, ConsensusOutcome::Accepted(ref s) if s.pot_size == 100));
    }

    #[test]
    fn disagreement_stays_pending_until_matches_accumulate() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
        assert!(matches!(
            tracker.observe(state(200)),
            ConsensusOutcome::Pending
        ));
        // Two out of the last three now agree on 200.
        let outcome = tracker.observe(state(200));
        assert!(matches!(outcome, ConsensusOutcome::Accepted(ref s) if s.pot_size == 200));
    }

    #[test]
    fn window_evicts_stale_observations() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        // A, B, C: all distinct, nothing accepted.
        for pot in [100, 200, 300] {
            assert!(matches!(
                tracker.observe(state(pot)),
                ConsensusOutcome::Pending
            ));
        }
        // The 100 observation has been evicted; a single new 100 cannot
        // reach consensus with nothing else.
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Accepted(_)
        ));
    }

    #[test]
    fn equality_spans_the_full_state() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        // Same pot, different hero cards: not the same state.
        assert!(matches!(
            tracker.observe(cards(100, "A")),
            ConsensusOutcome::Pending
        ));
        assert!(matches!(
            tracker.observe(cards(100, "K")),
            ConsensusOutcome::Pending
        ));
        assert!(matches!(
            tracker.observe(cards(100, "A")),
            ConsensusOutcome::Accepted(_)
        ));
    }

    #[test]
    fn confidence_differences_prevent_consensus() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        let mut first = state(100);
        first.confidence = Some(0.9);
        let mut second = state(100);
        second.confidence = Some(0.4);
        assert!(matches!(tracker.observe(first), ConsensusOutcome::Pending));
        assert!(matches!(tracker.observe(second), ConsensusOutcome::Pending));
    }

    #[test]
    fn reset_discards_pending_evidence() {
        let mut tracker =
            ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid config");
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
        tracker.reset();
        assert!(tracker.is_empty());
        // The pre-reset observation cannot confirm a post-reset state.
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Pending
        ));
    }

    #[test]
    fn one_of_one_config_accepts_immediately() {
        let mut tracker = ConsensusTracker::try_new(ConsensusConfig {
            window: 1,
            required: 1,
        })
        .expect("valid config");
        assert!(matches!(
            tracker.observe(state(100)),
            ConsensusOutcome::Accepted(_)
        ));
    }
}

#[cfg(test)]
mod proptests {
    use super::*;
    use crate::parser::{Card, GamePhase, PlayerState};
    use proptest::prelude::*;

    fn arb_state() -> impl Strategy<Value = GameState> {
        (
            prop_oneof![
                Just(GamePhase::Lobby),
                Just(GamePhase::Preflop),
                Just(GamePhase::Flop),
            ],
            0u32..1_000,
            prop::bool::ANY,
        )
            .prop_map(|(game_phase, pot_size, with_cards)| GameState {
                game_phase,
                hero_cards: if with_cards {
                    vec![Card {
                        rank: "A".to_string(),
                        suit: "spades".to_string(),
                    }]
                } else {
                    vec![]
                },
                board: vec![],
                pot_size,
                to_call: 0,
                hero_chips: 0,
                min_raise_to: None,
                max_raise_to: None,
                players: vec![PlayerState {
                    name: "Hero".to_string(),
                    chips: 0,
                    last_action: None,
                    bet_amount: 0,
                }],
                action_required: false,
                available_actions: vec![],
                confidence: None,
            })
    }

    proptest! {
        #[test]
        fn repeated_identical_states_always_reach_consensus(
            state in arb_state(),
            window in 1usize..6,
        ) {
            let required = 1.max(window / 2);
            let mut tracker = ConsensusTracker::try_new(ConsensusConfig { window, required })
                .expect("valid config");
            for i in 0..required {
                let outcome = tracker.observe(state.clone());
                if i == required - 1 {
                    prop_assert!(matches!(outcome, ConsensusOutcome::Accepted(_)));
                } else {
                    prop_assert!(matches!(outcome, ConsensusOutcome::Pending));
                }
            }
        }

        #[test]
        fn accepted_states_always_have_enough_matches(
            seed_state in arb_state(),
            noise in prop::collection::vec(0u32..1_000, 0..8),
        ) {
            let mut tracker = ConsensusTracker::try_new(ConsensusConfig::default())
                .expect("valid config");
            // Every acceptance must be backed by enough matches in the
            // window at the moment it is accepted.
            for value in noise {
                let mut observation = seed_state.clone();
                observation.pot_size = value;
                if let ConsensusOutcome::Accepted(state) = tracker.observe(observation) {
                    let matches = tracker
                        .window
                        .iter()
                        .filter(|observed| **observed == state)
                        .count();
                    prop_assert!(matches >= tracker.config().required);
                }
            }
            if let ConsensusOutcome::Accepted(state) = tracker.observe(seed_state) {
                let matches = tracker
                    .window
                    .iter()
                    .filter(|observed| **observed == state)
                    .count();
                prop_assert!(matches >= tracker.config().required);
            }
        }
    }
}
