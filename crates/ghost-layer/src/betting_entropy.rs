//! Weighted bet-sizing menu with rare off-grid events.
//!
//! Maps continuous solver outputs to human-like discretized sizing
//! (0.5x, 0.75x, 1.0x, 2.0x, 2.5x, 3.0x, 3.5x pot, …) with a small
//! probability of off-grid jitter, mimicking how humans snap to familiar
//! bet sizes rather than betting arbitrary amounts.

use rand::Rng;

/// The canonical human discretization menu, as pot fractions.
pub const SIZING_MENU: [f64; 11] = [0.33, 0.5, 0.66, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5];

/// Configuration for the betting entropy sampler.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct BettingEntropyConfig {
    /// Probability of an off-grid sizing event (0.0..=1.0).
    pub off_grid_probability: f64,
    /// Maximum relative jitter applied to off-grid sizes.
    pub off_grid_jitter: f64,
}

impl Default for BettingEntropyConfig {
    fn default() -> Self {
        Self {
            off_grid_probability: 0.08,
            off_grid_jitter: 0.05,
        }
    }
}

/// Maps solver-recommended bet sizes to human-like discretized sizes.
#[derive(Debug, Clone)]
pub struct BettingEntropy {
    config: BettingEntropyConfig,
}

impl BettingEntropy {
    pub fn new(config: BettingEntropyConfig) -> Self {
        Self { config }
    }

    /// Convert a target bet (in chips) into a human-like bet size.
    ///
    /// With probability `off_grid_probability` the result is jittered
    /// off-grid by up to `off_grid_jitter`; otherwise it snaps to the
    /// nearest menu fraction of the pot.
    pub fn humanize<R: Rng + ?Sized>(&self, rng: &mut R, target_bet: u32, pot: u32) -> u32 {
        if pot == 0 {
            return target_bet;
        }

        let target_fraction = f64::from(target_bet) / f64::from(pot);

        if rng.gen_bool(self.config.off_grid_probability) {
            // Rare off-grid event: jitter around the target fraction.
            let jitter = rng.gen_range(-self.config.off_grid_jitter..self.config.off_grid_jitter);
            let fraction = (target_fraction * (1.0 + jitter)).max(0.0);
            return (f64::from(pot) * fraction).round().max(1.0) as u32;
        }

        // Snap to the nearest menu item.
        let nearest = SIZING_MENU
            .iter()
            .min_by(|a, b| {
                let da = (**a - target_fraction).abs();
                let db = (**b - target_fraction).abs();
                da.partial_cmp(&db).expect("finite values")
            })
            .copied()
            .expect("menu is non-empty");

        (f64::from(pot) * nearest).round().max(1.0) as u32
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;

    #[test]
    fn snaps_to_nearest_menu_item_when_no_off_grid_event() {
        let entropy = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 0.0,
            off_grid_jitter: 0.05,
        });
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);

        // Pot 1000, target 2400 -> fraction 2.4 -> snaps to 2.5x = 2500.
        assert_eq!(entropy.humanize(&mut rng, 2400, 1000), 2500);
        // Pot 1000, target 480 -> fraction 0.48 -> snaps to 0.5x = 500.
        assert_eq!(entropy.humanize(&mut rng, 480, 1000), 500);
    }

    #[test]
    fn off_grid_events_stay_within_jitter_bounds() {
        let entropy = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 1.0,
            off_grid_jitter: 0.05,
        });
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);

        for _ in 0..1000 {
            let bet = entropy.humanize(&mut rng, 2000, 1000);
            // 2000 ± 5% = [1900, 2100].
            assert!(
                (1900..=2100).contains(&bet),
                "off-grid bet out of bounds: {bet}"
            );
        }
    }

    #[test]
    fn zero_pot_passes_target_through() {
        let entropy = BettingEntropy::new(BettingEntropyConfig::default());
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(entropy.humanize(&mut rng, 500, 0), 500);
    }

    #[test]
    fn never_returns_zero() {
        let entropy = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 1.0,
            off_grid_jitter: 0.9,
        });
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        for _ in 0..1000 {
            assert!(entropy.humanize(&mut rng, 10, 1000) >= 1);
        }
    }

    #[test]
    fn deterministic_for_a_seed() {
        let entropy = BettingEntropy::new(BettingEntropyConfig::default());
        let mut a = rand::rngs::StdRng::seed_from_u64(99);
        let mut b = rand::rngs::StdRng::seed_from_u64(99);
        let x = entropy.humanize(&mut a, 1750, 1000);
        let y = entropy.humanize(&mut b, 1750, 1000);
        assert_eq!(x, y);
    }
}
