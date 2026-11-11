//! Feature extraction from historical hand data.
//!
//! Computes VPIP, PFR, aggression factor, went-to-showdown, and related
//! statistics that drive archetype classification.

use serde::{Deserialize, Serialize};

/// Aggregated per-player statistics.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PlayerStats {
    /// Number of hands observed.
    pub hands: u32,
    /// Voluntarily put money in pot, preflop (0.0..=1.0).
    pub vpip: f64,
    /// Preflop raise percentage (0.0..=1.0).
    pub pfr: f64,
    /// Aggression factor: (bets + raises) / calls.
    pub aggression_factor: f64,
    /// Went to showdown when seeing the flop (0.0..=1.0).
    pub went_to_showdown: f64,
    /// Won at showdown (0.0..=1.0).
    pub won_at_showdown: f64,
}

impl Default for PlayerStats {
    fn default() -> Self {
        Self {
            hands: 0,
            vpip: 0.0,
            pfr: 0.0,
            aggression_factor: 0.0,
            went_to_showdown: 0.0,
            won_at_showdown: 0.0,
        }
    }
}

/// Incrementally accumulates observations into [`PlayerStats`].
#[derive(Debug, Clone, Default, PartialEq)]
pub struct StatsAccumulator {
    hands: u32,
    vpip_count: u32,
    pfr_count: u32,
    aggressive_actions: u32,
    passive_calls: u32,
    saw_flop: u32,
    showdowns: u32,
    showdown_wins: u32,
}

impl StatsAccumulator {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record a hand for this player.
    ///
    /// - `voluntarily_entered`: the player put money in the pot preflop
    ///   beyond the forced blind (VPIP).
    /// - `raised_preflop`: the player raised preflop (PFR).
    pub fn observe_hand(&mut self, voluntarily_entered: bool, raised_preflop: bool) {
        self.hands += 1;
        if voluntarily_entered {
            self.vpip_count += 1;
        }
        if raised_preflop {
            self.pfr_count += 1;
        }
    }

    /// Record a postflop aggressive action (bet or raise).
    pub fn observe_aggressive_action(&mut self) {
        self.aggressive_actions += 1;
    }

    /// Record a postflop passive call.
    pub fn observe_passive_call(&mut self) {
        self.passive_calls += 1;
    }

    /// Record that the player saw the flop in a hand.
    pub fn observe_flop_seen(&mut self) {
        self.saw_flop += 1;
    }

    /// Record that the player reached showdown, and whether they won it.
    pub fn observe_showdown(&mut self, won: bool) {
        self.showdowns += 1;
        if won {
            self.showdown_wins += 1;
        }
    }

    /// Snapshot the current statistics.
    pub fn stats(&self) -> PlayerStats {
        PlayerStats {
            hands: self.hands,
            vpip: ratio(self.vpip_count, self.hands),
            pfr: ratio(self.pfr_count, self.hands),
            aggression_factor: if self.passive_calls == 0 {
                if self.aggressive_actions == 0 {
                    0.0
                } else {
                    // AF is mathematically unbounded when the denominator is
                    // zero. Use the largest finite value so the statistic stays
                    // serializable while still classifying as aggressive.
                    f64::MAX
                }
            } else {
                f64::from(self.aggressive_actions) / f64::from(self.passive_calls)
            },
            went_to_showdown: ratio(self.showdowns, self.saw_flop),
            won_at_showdown: ratio(self.showdown_wins, self.showdowns),
        }
    }
}

fn ratio(num: u32, den: u32) -> f64 {
    if den == 0 {
        0.0
    } else {
        f64::from(num) / f64::from(den)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_accumulator_has_zero_stats() {
        let stats = StatsAccumulator::new().stats();
        assert_eq!(stats, PlayerStats::default());
    }

    #[test]
    fn vpip_and_pfr_are_ratios_of_hands() {
        let mut acc = StatsAccumulator::new();
        // 4 hands: enter 3, raise 2.
        acc.observe_hand(true, true);
        acc.observe_hand(true, true);
        acc.observe_hand(true, false);
        acc.observe_hand(false, false);
        let stats = acc.stats();
        assert_eq!(stats.hands, 4);
        assert!((stats.vpip - 0.75).abs() < 1e-9);
        assert!((stats.pfr - 0.5).abs() < 1e-9);
    }

    #[test]
    fn aggression_factor_is_bets_raises_over_calls() {
        let mut acc = StatsAccumulator::new();
        acc.observe_aggressive_action();
        acc.observe_aggressive_action();
        acc.observe_aggressive_action();
        acc.observe_passive_call();
        let stats = acc.stats();
        assert!((stats.aggression_factor - 3.0).abs() < 1e-9);
    }

    #[test]
    fn aggression_factor_without_calls_is_unbounded_but_finite() {
        let mut acc = StatsAccumulator::new();
        assert_eq!(acc.stats().aggression_factor, 0.0);
        acc.observe_aggressive_action();
        assert_eq!(acc.stats().aggression_factor, f64::MAX);
    }

    #[test]
    fn showdown_ratios_use_correct_denominators() {
        let mut acc = StatsAccumulator::new();
        // 4 hands see the flop; 2 reach showdown; 1 showdown win.
        acc.observe_flop_seen();
        acc.observe_showdown(true);
        acc.observe_flop_seen();
        acc.observe_showdown(false);
        acc.observe_flop_seen();
        acc.observe_flop_seen();
        let stats = acc.stats();
        assert!((stats.went_to_showdown - 0.5).abs() < 1e-9);
        assert!((stats.won_at_showdown - 0.5).abs() < 1e-9);
    }
}
