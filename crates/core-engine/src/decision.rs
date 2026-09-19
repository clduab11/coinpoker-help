//! Fold/Check/Call/Raise recommendations over explicitly legal actions.
//!
//! Combines pot odds, equity, stack limits, and expected value into a single
//! recommended action annotated with the underlying probability metrics.

use serde::Serialize;
use thiserror::Error;

use crate::pot_odds::{break_even_equity, ev_call, ev_raise, pot_odds_fraction};

/// The actions a decision can recommend.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Action {
    Fold,
    Check,
    Call,
    Raise,
}

/// Inputs to the decision engine for one decision point.
#[derive(Debug, Clone, PartialEq)]
pub struct DecisionInput {
    /// Current pot size in chips.
    pub pot: u32,
    /// Amount required to call, in chips (0 when facing no bet).
    pub to_call: u32,
    /// Hero's estimated equity against the active opponents (0.0..=1.0).
    pub equity: f64,
    /// Hero's remaining stack in chips.
    pub hero_chips: u32,
    /// Hero's chips already committed on the current street.
    pub hero_contribution: u32,
    /// Estimated probability all opponents fold to a raise (0.0..=1.0).
    pub fold_equity: f64,
    /// Total raise-to amount to evaluate, including the hero's contribution.
    pub raise_to: u32,
    /// Exact minimum legal total raise-to amount for a full raise.
    pub min_raise_to: u32,
    /// Aggregate incremental contribution expected from all callers after a raise.
    pub expected_caller_contribution: u32,
    /// Whether the hero may fold.
    pub can_fold: bool,
    /// Whether the hero may check.
    pub can_check: bool,
    /// Whether the hero may call.
    pub can_call: bool,
    /// Whether the hero may raise.
    pub can_raise: bool,
}

/// A decision recommendation with supporting metrics.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Decision {
    pub action: Action,
    /// Recommended total amount for a raise; 0 otherwise.
    pub amount: u32,
    /// Expected value of the recommended action, in chips.
    pub ev: f64,
    /// Pot odds as a fraction of the final pot (None when facing no bet).
    pub pot_odds: Option<f64>,
    /// Equity used for the decision.
    pub equity: f64,
    /// Break-even equity required to call (None when facing no bet).
    pub break_even: Option<f64>,
}

/// Errors produced when no recommendation can be made.
#[derive(Debug, Error, Clone, Copy, PartialEq, Eq)]
pub enum DecisionError {
    #[error("no legal action is available")]
    NoLegalAction,
}

/// Produces Fold/Call/Raise recommendations from equity and pot odds.
#[derive(Debug, Clone, Default)]
pub struct DecisionEngine;

impl DecisionEngine {
    pub fn new() -> Self {
        Self
    }

    /// Compute the highest-EV legal action for the given inputs.
    pub fn decide(&self, input: &DecisionInput) -> Result<Decision, DecisionError> {
        let call_amount = input.to_call.min(input.hero_chips);
        let pot_odds = pot_odds_fraction(input.pot, call_amount);
        let break_even = break_even_equity(input.pot, call_amount);
        let zero_ev_decision = |action| Decision {
            action,
            amount: 0,
            ev: 0.0,
            pot_odds,
            equity: input.equity,
            break_even,
        };

        // Checking and folding both have zero incremental EV. Prefer a legal
        // check because it preserves the hand at no cost.
        let mut best = if input.can_check {
            Some(zero_ev_decision(Action::Check))
        } else if input.can_fold {
            Some(zero_ev_decision(Action::Fold))
        } else {
            None
        };

        // A zero-chip "call" is not an actionable call. Short all-in calls are
        // evaluated at the actual amount the hero can contribute.
        if input.can_call && input.to_call > 0 && call_amount > 0 {
            let call_ev = ev_call(input.equity, input.pot, call_amount);
            if best.as_ref().is_none_or(|current| call_ev > current.ev) {
                best = Some(Decision {
                    action: Action::Call,
                    amount: call_amount,
                    ev: call_ev,
                    pot_odds,
                    equity: input.equity,
                    break_even,
                });
            }
        }

        if input.can_raise && input.hero_chips > call_amount {
            let call_to = input.hero_contribution.saturating_add(input.to_call);
            let max_raise_to = input.hero_contribution.saturating_add(input.hero_chips);
            let raise_to = if max_raise_to < input.min_raise_to {
                // An all-in that exceeds the call target remains legal even
                // when it is too short to satisfy the normal minimum raise.
                max_raise_to
            } else {
                input.raise_to.max(input.min_raise_to).min(max_raise_to)
            };

            if raise_to > call_to {
                let hero_raise_cost = raise_to.saturating_sub(input.hero_contribution);
                let raise_ev = ev_raise(
                    input.equity,
                    input.pot,
                    hero_raise_cost,
                    input.expected_caller_contribution,
                    input.fold_equity,
                );

                if best.as_ref().is_none_or(|current| raise_ev > current.ev) {
                    best = Some(Decision {
                        action: Action::Raise,
                        amount: raise_to,
                        ev: raise_ev,
                        pot_odds,
                        equity: input.equity,
                        break_even,
                    });
                }
            }
        }

        best.ok_or(DecisionError::NoLegalAction)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(pot: u32, to_call: u32, equity: f64) -> DecisionInput {
        DecisionInput {
            pot,
            to_call,
            equity,
            hero_chips: 10_000,
            hero_contribution: 0,
            fold_equity: 0.0,
            raise_to: pot.saturating_mul(3),
            min_raise_to: to_call.saturating_add(1),
            expected_caller_contribution: pot.saturating_mul(3),
            can_fold: to_call > 0,
            can_check: to_call == 0,
            can_call: true,
            can_raise: true,
        }
    }

    fn decide(input: &DecisionInput) -> Decision {
        DecisionEngine::new()
            .decide(input)
            .expect("fixture has a legal action")
    }

    #[test]
    fn folds_when_equity_is_below_break_even() {
        // Pot 100, call 100: break-even equity is 50%.
        let d = decide(&input(100, 100, 0.3));
        assert_eq!(d.action, Action::Fold);
        assert_eq!(d.ev, 0.0);
    }

    #[test]
    fn calls_when_equity_beats_break_even() {
        let mut i = input(100, 100, 0.7);
        i.can_raise = false;
        let d = decide(&i);
        assert_eq!(d.action, Action::Call);
        assert!(d.ev > 0.0);
    }

    #[test]
    fn checks_when_no_bet_and_weak_equity() {
        let d = decide(&input(100, 0, 0.3));
        assert_eq!(d.action, Action::Check);
        assert_eq!(d.pot_odds, None);
    }

    #[test]
    fn raises_when_no_bet_and_strong_equity() {
        let d = decide(&input(100, 0, 0.8));
        assert_eq!(d.action, Action::Raise);
        assert!(d.amount > 0);
    }

    #[test]
    fn fold_equity_can_turn_a_raise_profitable() {
        // Equity alone is -EV to call, but a modest raise with high fold
        // equity wins the pot often enough to be profitable.
        let mut i = input(100, 50, 0.3);
        i.fold_equity = 0.6;
        i.raise_to = 150;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert!(d.ev > 0.0);
    }

    #[test]
    fn zero_stack_never_calls_or_raises() {
        let mut i = input(100, 100, 1.0);
        i.hero_chips = 0;
        i.can_check = false;
        let d = decide(&i);
        assert_eq!(d.action, Action::Fold);
        assert_eq!(d.amount, 0);
    }

    #[test]
    fn short_stack_call_is_capped_and_evaluated_at_stack() {
        let mut i = input(100, 100, 0.5);
        i.hero_chips = 40;
        i.can_check = false;
        let d = decide(&i);
        assert_eq!(d.action, Action::Call);
        assert_eq!(d.amount, 40);
        assert!((d.ev - 30.0).abs() < 1e-9);
        assert!((d.pot_odds.unwrap() - 40.0 / 140.0).abs() < 1e-9);
    }

    #[test]
    fn unavailable_call_is_not_recommended() {
        let mut i = input(100, 50, 1.0);
        i.can_check = false;
        i.can_call = false;
        i.can_raise = false;
        assert_eq!(decide(&i).action, Action::Fold);
    }

    #[test]
    fn unavailable_raise_is_not_recommended() {
        let mut i = input(100, 50, 0.3);
        i.can_check = false;
        i.can_raise = false;
        i.fold_equity = 1.0;
        assert_ne!(decide(&i).action, Action::Raise);
    }

    #[test]
    fn stack_that_cannot_exceed_call_never_raises() {
        let mut i = input(100, 100, 1.0);
        i.hero_chips = 50;
        i.can_check = false;
        i.fold_equity = 1.0;
        let d = decide(&i);
        assert_ne!(d.action, Action::Raise);
        assert!(d.amount <= i.hero_chips);
    }

    #[test]
    fn short_all_in_below_minimum_raise_is_legal() {
        let mut i = input(100, 50, 0.0);
        i.hero_chips = 51;
        i.hero_contribution = 20;
        i.raise_to = 150;
        i.min_raise_to = 100;
        i.expected_caller_contribution = 1;
        i.can_check = false;
        i.can_call = false;
        i.fold_equity = 1.0;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert_eq!(d.amount, 71);
    }

    #[test]
    fn raise_to_is_capped_at_contribution_plus_remaining_stack() {
        let mut i = input(100, 0, 0.0);
        i.hero_chips = 60;
        i.hero_contribution = 40;
        i.raise_to = 200;
        i.min_raise_to = 80;
        i.can_call = false;
        i.fold_equity = 1.0;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert_eq!(d.amount, 100);
    }

    #[test]
    fn raise_ev_uses_incremental_hero_cost() {
        let mut i = input(100, 0, 0.5);
        i.hero_chips = 100;
        i.hero_contribution = 40;
        i.raise_to = 100;
        i.min_raise_to = 80;
        i.expected_caller_contribution = 60;
        i.can_check = false;
        i.can_call = false;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert_eq!(d.amount, 100);
        assert!((d.ev - 50.0).abs() < 1e-9);
    }

    #[test]
    fn full_raise_is_promoted_to_exact_minimum() {
        let mut i = input(100, 30, 0.0);
        i.hero_chips = 100;
        i.hero_contribution = 20;
        i.raise_to = 70;
        i.min_raise_to = 100;
        i.can_check = false;
        i.can_call = false;
        i.fold_equity = 1.0;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert_eq!(d.amount, 100);
    }

    #[test]
    fn raise_to_stack_cap_saturates_without_overflow() {
        let mut i = input(100, 0, 0.0);
        i.hero_chips = 20;
        i.hero_contribution = u32::MAX - 10;
        i.raise_to = u32::MAX;
        i.min_raise_to = u32::MAX - 5;
        i.can_call = false;
        i.fold_equity = 1.0;
        let d = decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert_eq!(d.amount, u32::MAX);
    }

    #[test]
    fn negative_ev_raise_loses_to_free_check() {
        let mut i = input(100, 0, 0.0);
        i.raise_to = 100;
        i.expected_caller_contribution = 100;
        let d = decide(&i);
        assert_eq!(d.action, Action::Check);
        assert_eq!(d.ev, 0.0);
    }

    #[test]
    fn returns_error_when_no_action_is_legal() {
        let mut i = input(100, 50, 0.5);
        i.can_fold = false;
        i.can_check = false;
        i.can_call = false;
        i.can_raise = false;
        assert_eq!(
            DecisionEngine::new().decide(&i),
            Err(DecisionError::NoLegalAction)
        );
    }

    #[test]
    fn selects_only_legal_call_when_zero_ev_actions_are_unavailable() {
        let mut i = input(100, 100, 0.1);
        i.can_fold = false;
        i.can_check = false;
        i.can_raise = false;
        let d = decide(&i);
        assert_eq!(d.action, Action::Call);
        assert!(d.ev < 0.0);
    }

    #[test]
    fn decision_serializes_for_the_ui_layer() {
        let mut i = input(100, 100, 0.7);
        i.can_raise = false;
        let d = decide(&i);
        let json = serde_json::to_string(&d).expect("serialize");
        assert!(json.contains("\"action\":\"call\""));
    }
}
