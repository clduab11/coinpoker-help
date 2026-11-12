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
    Some(f64::from(to_call) / (f64::from(pot) + f64::from(to_call)))
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
    Some(
        f64::from(to_call)
            / (f64::from(pot) + f64::from(to_call) + f64::from(estimated_future_bet)),
    )
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
    equity * (f64::from(pot) + f64::from(to_call)) - f64::from(to_call)
}

/// Expected value of paying `hero_raise_cost` to raise, in chips, given an
/// estimated probability `fold_equity` that all opponents fold.
///
/// Both `hero_raise_cost` and `expected_caller_contribution` are incremental
/// amounts added to the current pot. The caller contribution is the aggregate
/// expected amount from every caller, not a per-opponent amount. When all
/// opponents fold the hero wins the current pot; otherwise the final pot
/// includes the current pot and both incremental contributions.
pub fn ev_raise(
    equity: f64,
    pot: u32,
    hero_raise_cost: u32,
    expected_caller_contribution: u32,
    fold_equity: f64,
) -> f64 {
    let fold_win = fold_equity * f64::from(pot);
    let called_pot =
        f64::from(pot) + f64::from(hero_raise_cost) + f64::from(expected_caller_contribution);
    let called = (1.0 - fold_equity) * (equity * called_pot - f64::from(hero_raise_cost));
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
    fn ev_raise_accounts_for_fold_equity_and_caller_contributions() {
        // Guaranteed fold: hero wins the pot outright.
        let ev = ev_raise(0.3, 100, 200, 200, 1.0);
        assert!((ev - 100.0).abs() < 1e-9);
        // No fold equity: the called pot includes both incremental contributions.
        let ev = ev_raise(0.3, 100, 80, 60, 0.0);
        assert!((ev - (0.3 * 240.0 - 80.0)).abs() < 1e-9);
    }

    #[test]
    fn arithmetic_widens_before_adding_chip_amounts() {
        let max = u32::MAX;
        assert!((pot_odds_fraction(max, max).unwrap() - 0.5).abs() < 1e-9);
        assert!(implied_odds_fraction(max, max, max).unwrap().is_finite());
        assert!(ev_call(0.5, max, max).is_finite());
        assert!(ev_raise(0.5, max, max, max, 0.0).is_finite());
    }
}

#[cfg(test)]
mod proptests {
    use super::*;
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn pot_odds_fraction_is_bounded(
            pot in 0..=u32::MAX,
            to_call in 1..=u32::MAX,
        ) {
            let odds = pot_odds_fraction(pot, to_call).unwrap();
            prop_assert!((0.0..=1.0).contains(&odds));
        }

        #[test]
        fn pot_odds_ratio_is_positive(
            pot in 1..=u32::MAX,
            to_call in 1..=u32::MAX,
        ) {
            let ratio = pot_odds_ratio(pot, to_call).unwrap();
            prop_assert!(ratio > 0.0);
        }

        #[test]
        fn implied_odds_improve_over_pot_odds(
            pot in 0..=u32::MAX,
            to_call in 1..=u32::MAX,
            future_bet in 1..=u32::MAX,
        ) {
            let plain = pot_odds_fraction(pot, to_call).unwrap();
            let implied = implied_odds_fraction(pot, to_call, future_bet).unwrap();
            prop_assert!(implied <= plain);
        }

        #[test]
        fn break_even_equity_equals_pot_odds(
            pot in 0..=u32::MAX,
            to_call in 1..=u32::MAX,
        ) {
            let be = break_even_equity(pot, to_call).unwrap();
            let odds = pot_odds_fraction(pot, to_call).unwrap();
            prop_assert!((be - odds).abs() < 1e-12);
        }

        #[test]
        fn ev_call_zero_at_break_even(
            pot in 0..=u32::MAX,
            to_call in 1..=u32::MAX,
        ) {
            let be = break_even_equity(pot, to_call).unwrap();
            let ev = ev_call(be, pot, to_call);
            // Use relative tolerance for large values
            let expected = 0.0;
            let tol = (f64::from(pot) + f64::from(to_call)) * 1e-15 + 1e-12;
            prop_assert!((ev - expected).abs() <= tol);
        }

        #[test]
        fn ev_call_monotonic_in_equity(
            pot in 0..=u32::MAX,
            to_call in 1..=u32::MAX,
            e1 in 0.0..1.0f64,
            e2 in 0.0..1.0f64,
        ) {
            let ev1 = ev_call(e1, pot, to_call);
            let ev2 = ev_call(e2, pot, to_call);
            if e1 < e2 {
                prop_assert!(ev1 <= ev2 + 1e-12);
            }
        }

        #[test]
        fn ev_raise_with_full_fold_equity_wins_pot(
            equity in 0.0..1.0f64,
            pot in 0..=u32::MAX,
            hero_cost in 1..=u32::MAX,
            caller_contrib in 0..=u32::MAX,
        ) {
            let ev = ev_raise(equity, pot, hero_cost, caller_contrib, 1.0);
            prop_assert!((ev - f64::from(pot)).abs() < 1e-9);
        }

        #[test]
        fn ev_raise_with_zero_fold_equity_is_called_ev(
            equity in 0.0..1.0f64,
            pot in 0..=u32::MAX,
            hero_cost in 1..=u32::MAX,
            caller_contrib in 0..=u32::MAX,
        ) {
            let ev = ev_raise(equity, pot, hero_cost, caller_contrib, 0.0);
            let called_pot = f64::from(pot) + f64::from(hero_cost) + f64::from(caller_contrib);
            let expected = equity * called_pot - f64::from(hero_cost);
            prop_assert!((ev - expected).abs() < 1e-9);
        }
    }
}
