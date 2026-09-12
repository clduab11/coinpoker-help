//! Fold/Call/Raise recommendation with confidence bounds.
//!
//! Combines pot odds, equity, and expected value into a single recommended
//! action, annotated with the underlying probability metrics.

use serde::Serialize;

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
    /// Estimated probability all opponents fold to a raise (0.0..=1.0).
    pub fold_equity: f64,
    /// Raise amount to evaluate, in chips (total, not on top).
    pub raise_amount: u32,
    /// Whether the hero may check (no bet to call).
    pub can_check: bool,
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

/// Produces Fold/Call/Raise recommendations from equity and pot odds.
#[derive(Debug, Clone, Default)]
pub struct DecisionEngine;

impl DecisionEngine {
    pub fn new() -> Self {
        Self
    }

    /// Compute the recommended action for the given inputs.
    pub fn decide(&self, input: &DecisionInput) -> Decision {
        let pot_odds = pot_odds_fraction(input.pot, input.to_call);
        let break_even = break_even_equity(input.pot, input.to_call);

        // No bet to call: check when equity is weak, raise when strong.
        if input.to_call == 0 {
            if input.can_check && input.equity < 0.5 {
                return Decision {
                    action: Action::Check,
                    amount: 0,
                    ev: 0.0,
                    pot_odds,
                    equity: input.equity,
                    break_even,
                };
            }
            let raise = input.raise_amount.min(input.hero_chips).max(1);
            let ev = ev_raise(input.equity, input.pot, raise, input.fold_equity);
            return Decision {
                action: Action::Raise,
                amount: raise,
                ev,
                pot_odds,
                equity: input.equity,
                break_even,
            };
        }

        let call_ev = ev_call(input.equity, input.pot, input.to_call);
        let raise = input
            .raise_amount
            .min(input.hero_chips)
            .max(input.to_call + 1);
        let raise_ev = ev_raise(input.equity, input.pot, raise, input.fold_equity);

        // Raising dominates when it is strictly more profitable than calling.
        if raise_ev > call_ev && raise_ev > 0.0 {
            return Decision {
                action: Action::Raise,
                amount: raise,
                ev: raise_ev,
                pot_odds,
                equity: input.equity,
                break_even,
            };
        }

        // Calling is profitable when equity beats the break-even threshold.
        if call_ev > 0.0 {
            return Decision {
                action: Action::Call,
                amount: input.to_call,
                ev: call_ev,
                pot_odds,
                equity: input.equity,
                break_even,
            };
        }

        Decision {
            action: Action::Fold,
            amount: 0,
            ev: 0.0,
            pot_odds,
            equity: input.equity,
            break_even,
        }
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
            fold_equity: 0.0,
            raise_amount: pot * 3,
            can_check: true,
        }
    }

    #[test]
    fn folds_when_equity_is_below_break_even() {
        // Pot 100, call 100: break-even equity is 50%.
        let d = DecisionEngine::new().decide(&input(100, 100, 0.3));
        assert_eq!(d.action, Action::Fold);
        assert_eq!(d.ev, 0.0);
    }

    #[test]
    fn calls_when_equity_beats_break_even() {
        let d = DecisionEngine::new().decide(&input(100, 100, 0.7));
        assert_eq!(d.action, Action::Call);
        assert!(d.ev > 0.0);
    }

    #[test]
    fn checks_when_no_bet_and_weak_equity() {
        let d = DecisionEngine::new().decide(&input(100, 0, 0.3));
        assert_eq!(d.action, Action::Check);
        assert_eq!(d.pot_odds, None);
    }

    #[test]
    fn raises_when_no_bet_and_strong_equity() {
        let d = DecisionEngine::new().decide(&input(100, 0, 0.8));
        assert_eq!(d.action, Action::Raise);
        assert!(d.amount > 0);
    }

    #[test]
    fn fold_equity_can_turn_a_raise_profitable() {
        // Equity alone is -EV to call, but a modest raise with high fold
        // equity wins the pot often enough to be profitable.
        let mut i = input(100, 50, 0.3);
        i.fold_equity = 0.6;
        i.raise_amount = 150;
        let d = DecisionEngine::new().decide(&i);
        assert_eq!(d.action, Action::Raise);
        assert!(d.ev > 0.0);
    }

    #[test]
    fn decision_serializes_for_the_ui_layer() {
        let d = DecisionEngine::new().decide(&input(100, 100, 0.7));
        let json = serde_json::to_string(&d).expect("serialize");
        assert!(json.contains("\"action\":\"call\""));
    }
}
