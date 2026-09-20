//! Weighted bet-sizing menu with rare off-grid events.
//!
//! Maps continuous solver outputs to human-like discretized sizing
//! (0.5x, 0.75x, 1.0x, 2.0x, 2.5x, 3.0x, 3.5x pot, …) with a small
//! probability of off-grid jitter, mimicking how humans snap to familiar
//! bet sizes rather than betting arbitrary amounts.

use rand::Rng;
use thiserror::Error;

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

/// Semantic validation errors for [`BettingEntropyConfig`].
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum BettingEntropyConfigError {
    #[error("off_grid_probability must be finite and between zero and one")]
    InvalidProbability,
    #[error("off_grid_jitter must be finite and non-negative")]
    InvalidJitter,
}

impl BettingEntropyConfig {
    /// Validate parameters before constructing a sampler or loading a profile.
    pub fn validate(&self) -> Result<(), BettingEntropyConfigError> {
        if !self.off_grid_probability.is_finite()
            || !(0.0..=1.0).contains(&self.off_grid_probability)
        {
            return Err(BettingEntropyConfigError::InvalidProbability);
        }
        if !self.off_grid_jitter.is_finite() || self.off_grid_jitter < 0.0 {
            return Err(BettingEntropyConfigError::InvalidJitter);
        }
        Ok(())
    }
}

/// Errors from bounded bet humanization.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum HumanizeError {
    #[error("minimum legal bet {min} exceeds maximum legal bet {max}")]
    InvalidLegalBounds { min: u32, max: u32 },
}

/// Origin of a humanized bet size.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum SizingProvenance {
    /// Snapped to one of [`SIZING_MENU`]'s familiar pot fractions.
    Menu,
    /// Produced by the configured off-grid jitter path.
    OffGrid,
    /// Returned unchanged because no pot-relative sizing was possible.
    Passthrough,
}

impl SizingProvenance {
    /// Short UI annotation identifying the sizing source.
    pub const fn annotation(self) -> &'static str {
        match self {
            Self::Menu => "ghost-menu",
            Self::OffGrid => "ghost-off-grid",
            Self::Passthrough => "ghost-passthrough",
        }
    }
}

/// A humanized chip amount and the path that produced it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HumanizedSize {
    pub amount: u32,
    pub provenance: SizingProvenance,
}

/// Maps solver-recommended bet sizes to human-like discretized sizes.
#[derive(Debug, Clone)]
pub struct BettingEntropy {
    config: BettingEntropyConfig,
}

impl BettingEntropy {
    /// Construct a humanizer. Invalid manually supplied configuration is
    /// handled safely by [`Self::humanize`]; prefer [`Self::try_new`] when
    /// validation feedback is useful.
    pub fn new(config: BettingEntropyConfig) -> Self {
        Self { config }
    }

    /// Construct a humanizer after validating its configuration.
    pub fn try_new(config: BettingEntropyConfig) -> Result<Self, BettingEntropyConfigError> {
        config.validate()?;
        Ok(Self { config })
    }

    /// Convert a target bet (in chips) into a human-like bet size.
    ///
    /// With probability `off_grid_probability` the result is jittered
    /// off-grid by up to `off_grid_jitter`; otherwise it snaps to the
    /// nearest menu fraction of the pot. A zero target remains zero.
    pub fn humanize<R: Rng + ?Sized>(&self, rng: &mut R, target_bet: u32, pot: u32) -> u32 {
        self.humanize_with_provenance(rng, target_bet, pot).amount
    }

    /// Humanize a target and retain the source of the returned sizing.
    pub fn humanize_with_provenance<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        target_bet: u32,
        pot: u32,
    ) -> HumanizedSize {
        if target_bet == 0 || pot == 0 {
            return HumanizedSize {
                amount: target_bet,
                provenance: SizingProvenance::Passthrough,
            };
        }

        let target_fraction = f64::from(target_bet) / f64::from(pot);
        let probability = self.config.off_grid_probability;
        let off_grid = probability.is_finite()
            && probability > 0.0
            && probability <= 1.0
            && rng.gen_bool(probability);

        if off_grid {
            // A zero or invalid jitter produces the unchanged target instead
            // of constructing an empty/invalid gen_range interval.
            let jitter_limit = self.config.off_grid_jitter;
            let jitter = if jitter_limit.is_finite() && jitter_limit > 0.0 {
                rng.gen_range(-jitter_limit..jitter_limit)
            } else {
                0.0
            };
            let fraction = (target_fraction * (1.0 + jitter)).max(0.0);
            return HumanizedSize {
                amount: (f64::from(pot) * fraction).round().max(1.0) as u32,
                provenance: SizingProvenance::OffGrid,
            };
        }

        // Snap to the nearest menu item. total_cmp remains defined for every
        // floating-point value and avoids a partial_cmp unwrap.
        let nearest = SIZING_MENU
            .iter()
            .copied()
            .min_by(|a, b| {
                let da = (*a - target_fraction).abs();
                let db = (*b - target_fraction).abs();
                da.total_cmp(&db)
            })
            .unwrap_or(1.0);

        HumanizedSize {
            amount: (f64::from(pot) * nearest).round().max(1.0) as u32,
            provenance: SizingProvenance::Menu,
        }
    }

    /// Humanize a target while enforcing explicit legal amount bounds.
    pub fn humanize_bounded<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        target_bet: u32,
        pot: u32,
        min_legal: u32,
        max_legal: u32,
    ) -> Result<u32, HumanizeError> {
        Ok(self
            .humanize_bounded_with_provenance(rng, target_bet, pot, min_legal, max_legal)?
            .amount)
    }

    /// Humanize a target within legal bounds while retaining its provenance.
    pub fn humanize_bounded_with_provenance<R: Rng + ?Sized>(
        &self,
        rng: &mut R,
        target_bet: u32,
        pot: u32,
        min_legal: u32,
        max_legal: u32,
    ) -> Result<HumanizedSize, HumanizeError> {
        if min_legal > max_legal {
            return Err(HumanizeError::InvalidLegalBounds {
                min: min_legal,
                max: max_legal,
            });
        }
        let mut size = self.humanize_with_provenance(rng, target_bet, pot);
        size.amount = size.amount.max(min_legal).min(max_legal);
        Ok(size)
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
    fn zero_jitter_is_safe() {
        let entropy = BettingEntropy::try_new(BettingEntropyConfig {
            off_grid_probability: 1.0,
            off_grid_jitter: 0.0,
        })
        .expect("valid config");
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(entropy.humanize(&mut rng, 500, 1000), 500);
    }

    #[test]
    fn zero_target_is_preserved() {
        let entropy = BettingEntropy::new(BettingEntropyConfig::default());
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(entropy.humanize(&mut rng, 0, 1000), 0);
    }

    #[test]
    fn bounded_humanization_respects_legal_amounts() {
        let entropy = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 0.0,
            off_grid_jitter: 0.0,
        });
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(
            entropy
                .humanize_bounded(&mut rng, 2400, 1000, 100, 1200)
                .expect("valid bounds"),
            1200
        );
        assert_eq!(
            entropy
                .humanize_bounded(&mut rng, 100, 1000, 400, 800)
                .expect("valid bounds"),
            400
        );
    }

    #[test]
    fn bounded_humanization_rejects_inverted_bounds() {
        let entropy = BettingEntropy::new(BettingEntropyConfig::default());
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(
            entropy.humanize_bounded(&mut rng, 500, 1000, 600, 500),
            Err(HumanizeError::InvalidLegalBounds { min: 600, max: 500 })
        );
    }

    #[test]
    fn zero_pot_passes_target_through() {
        let entropy = BettingEntropy::new(BettingEntropyConfig::default());
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        assert_eq!(entropy.humanize(&mut rng, 500, 0), 500);
    }

    #[test]
    fn positive_target_never_returns_zero() {
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

    #[test]
    fn provenance_describes_menu_off_grid_and_passthrough_paths() {
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        let menu = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 0.0,
            off_grid_jitter: 0.0,
        });
        assert_eq!(
            menu.humanize_with_provenance(&mut rng, 480, 1000),
            HumanizedSize {
                amount: 500,
                provenance: SizingProvenance::Menu,
            }
        );
        assert_eq!(
            menu.humanize_with_provenance(&mut rng, 500, 0).provenance,
            SizingProvenance::Passthrough
        );

        let off_grid = BettingEntropy::new(BettingEntropyConfig {
            off_grid_probability: 1.0,
            off_grid_jitter: 0.05,
        });
        assert_eq!(
            off_grid
                .humanize_with_provenance(&mut rng, 500, 1000)
                .provenance,
            SizingProvenance::OffGrid
        );
        assert_eq!(SizingProvenance::Menu.annotation(), "ghost-menu");
    }
}

#[cfg(test)]
mod proptests {
    use super::*;
    use proptest::prelude::*;
    use rand::SeedableRng;

    fn arb_betting_entropy_config() -> impl Strategy<Value = BettingEntropyConfig> {
        (0.0..=1.0f64, 0.0..=0.5f64).prop_map(|(prob, jitter)| BettingEntropyConfig {
            off_grid_probability: prob,
            off_grid_jitter: jitter,
        })
    }

    proptest! {
        #[test]
        fn humanize_output_is_bounded(
            config in arb_betting_entropy_config().prop_filter("valid", |c| c.validate().is_ok()),
            pot in 1..=100_000u32,
            target in 0..=100_000u32,
            seed in 0..=u64::MAX,
        ) {
            let jitter_limit = config.off_grid_jitter;
            let entropy = BettingEntropy::new(config);
            let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
            let bet = entropy.humanize(&mut rng, target, pot);
            if target == 0 {
                prop_assert_eq!(bet, 0);
            } else {
                prop_assert!(bet >= 1);
                // Off-grid scales the target by at most (1 + jitter); snapping
                // never exceeds the largest menu item (3.5x pot). The result
                // cannot exceed the larger of the two bounds.
                let off_grid_max = (f64::from(target) * (1.0 + jitter_limit)).round().max(1.0) as u32;
                let snap_max = (f64::from(pot) * 3.5).round().max(1.0) as u32;
                prop_assert!(bet <= off_grid_max.max(snap_max));
            }
        }

        #[test]
        fn humanize_bounded_respects_legal_bounds(
            config in arb_betting_entropy_config().prop_filter("valid", |c| c.validate().is_ok()),
            pot in 1..=100_000u32,
            target in 0..=100_000u32,
            min_legal in 1..=10_000u32,
            max_legal in 1..=10_000u32,
            seed in 0..=u64::MAX,
        ) {
            if min_legal > max_legal {
                return Ok(());
            }
            let entropy = BettingEntropy::new(config);
            let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
            let bet = entropy.humanize_bounded(&mut rng, target, pot, min_legal, max_legal).unwrap();
            prop_assert!(bet >= min_legal);
            prop_assert!(bet <= max_legal);
        }

        #[test]
        fn off_grid_output_stays_within_jitter_bounds(
            jitter in 0.001..=0.2f64,
            pot in 100..=10_000u32,
            target in 100..=10_000u32,
            seed in 0..=u64::MAX,
        ) {
            // Force every sample off-grid so the jitter invariant always applies.
            let config = BettingEntropyConfig {
                off_grid_probability: 1.0,
                off_grid_jitter: jitter,
            };
            let entropy = BettingEntropy::new(config);
            let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
            let target_fraction = f64::from(target) / f64::from(pot);

            for _ in 0..100 {
                let bet = entropy.humanize(&mut rng, target, pot);
                let fraction = f64::from(bet) / f64::from(pot);
                let lower = (target_fraction * (1.0 - jitter)).max(0.0);
                let upper = target_fraction * (1.0 + jitter);
                // Tolerate integer-chip rounding and the 1-chip floor.
                prop_assert!(fraction >= lower - 0.02);
                prop_assert!(fraction <= upper + 0.02);
            }
        }
    }
}
