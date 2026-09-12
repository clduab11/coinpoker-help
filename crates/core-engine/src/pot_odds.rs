//! Pot odds, implied odds, and multi-way expected value.
//!
//! Pure, deterministic functions over pot size, call amount, and stack
//! depths. No I/O, no randomness — fully unit-testable.

/// Pot odds as a fraction of the final pot the caller must commit.
///
/// `to_call / (pot + to_call)`. Returns `None` when `to_call` is zero
/// (there is no bet to call, so pot odds are undefined).
pub fn pot_odds_fraction(pot: u32, to_call: u32) -> Option<f64> {
    if to_call == 0 {
        return None;
    }
    Some(f64::from(to_call) / f64::from(pot + to_call))
}

/// Pot odds expressed as a ratio `pot : to_call` (e.g. `3.0` means 3:1).
///
/// Returns `None` when `to_call` is zero.
pub fn pot_odds_ratio(pot: u32, to_call: u32) -> Option<f64> {
    if to_call == 0 {
        return None;
    }
    Some(f64::from(pot) / f64::from(to_call))
}

/// Implied odds as a fraction, accounting for an estimated future bet that
/// the opponent will call if the hero improves.
///
/// `to_call / (pot + to_call + estimated_future_bet)`.
pub fn implied_odds_fraction(pot: u32, to_call: u32, estimated_future_bet: u32) -> Option<f64> {
    if to_call == 0 {
        return None;
    }
    Some(f64::from(to_call) / f64::from(pot + to_call + estimated_future_bet))
}

/// The minimum equity required for a call to break even.
///
/// Equivalent to [`pot_odds_fraction`]; a call is profitable when the
/// hero's equity exceeds this value.
pub fn break_even_equity(pot: u32, to_call: u32) -> Option<f64> {
    pot_odds_fraction(pot, to_call)
}

/// Expected value of calling, in chips.
///
/// `ev = equity * (pot + to_call) - to_call`.
pub fn ev_call(equity: f64, pot: u32, to_call: u32) -> f64 {
    equity * f64::from(pot + to_call) - f64::from(to_call)
}

/// Expected value of raising to `raise_amount`, in chips, given an
/// estimated probability `fold_equity` that all opponents fold.
///
/// When opponents fold the hero wins the current pot; otherwise the
/// raise is treated as a call at the higher price.
pub fn ev_raise(equity: f64, pot: u32, raise_amount: u32, fold_equity: f64) -> f64 {
    let fold_win = fold_equity * f64::from(pot);
    let called =
        (1.0 - fold_equity) * (equity * f64::from(pot + raise_amount) - f64::from(raise_amount));
    fold_win + called
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pot_odds_fraction_is_commitment_share() {
        // Pot 100, call 50 -> 50 / 150 = 1/3.
        assert!((pot_odds_fraction(100, 50).unwrap() - 1.0 / 3.0).abs() < 1e-9);
        // Pot 300, call 100 -> 100 / 400 = 0.25.
        assert!((pot_odds_fraction(300, 100).unwrap() - 0.25).abs() < 1e-9);
    }

    #[test]
    fn pot_odds_undefined_when_no_bet_to_call() {
        assert_eq!(pot_odds_fraction(100, 0), None);
        assert_eq!(pot_odds_ratio(100, 0), None);
        assert_eq!(implied_odds_fraction(100, 0, 500), None);
    }

    #[test]
    fn pot_odds_ratio_is_pot_over_call() {
        assert!((pot_odds_ratio(300, 100).unwrap() - 3.0).abs() < 1e-9);
    }

    #[test]
    fn implied_odds_improve_with_future_bets() {
        let plain = pot_odds_fraction(100, 50).unwrap();
        let implied = implied_odds_fraction(100, 50, 400).unwrap();
        assert!(implied < plain);
        // 50 / (100 + 50 + 400) = 50 / 550.
        assert!((implied - 50.0 / 550.0).abs() < 1e-9);
    }

    #[test]
    fn ev_call_is_zero_at_break_even_equity() {
        // Pot 100, call 50: break-even equity is 1/3.
        let be = break_even_equity(100, 50).unwrap();
        assert!((ev_call(be, 100, 50)).abs() < 1e-9);
        assert!(ev_call(0.5, 100, 50) > 0.0);
        assert!(ev_call(0.2, 100, 50) < 0.0);
    }

    #[test]
    fn ev_raise_accounts_for_fold_equity() {
        // Guaranteed fold: hero wins the pot outright.
        let ev = ev_raise(0.3, 100, 200, 1.0);
        assert!((ev - 100.0).abs() < 1e-9);
        // No fold equity: equivalent to calling 200 into 100.
        let ev = ev_raise(0.3, 100, 200, 0.0);
        assert!((ev - (0.3 * 300.0 - 200.0)).abs() < 1e-9);
    }
}
