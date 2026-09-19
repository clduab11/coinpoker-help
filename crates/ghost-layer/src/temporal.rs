//! Log-normal reaction-time sampling.
//!
//! Samples human-like action latency from a log-normal distribution
//! clamped to [10ms, 3000ms], with the median correlated to decision
//! complexity (a preflop fold is fast; a river all-in is slow).

use std::time::Duration;

use rand::Rng;
use rand_distr::{Distribution, LogNormal};
use thiserror::Error;

/// Decision complexity tiers, ordered from fastest to slowest.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DecisionComplexity {
    /// Folding before the flop — the fastest human action.
    PreflopFold,
    /// Calling or checking preflop.
    PreflopCall,
    /// Raising preflop.
    PreflopRaise,
    /// A postflop check or fold.
    PostflopSimple,
    /// A postflop call.
    PostflopCall,
    /// A postflop raise.
    PostflopRaise,
    /// A river all-in or other high-stakes decision.
    RiverAllin,
}

impl DecisionComplexity {
    /// Median reaction time in milliseconds for this complexity tier.
    pub fn median_ms(&self) -> f64 {
        match self {
            DecisionComplexity::PreflopFold => 500.0,
            DecisionComplexity::PreflopCall => 800.0,
            DecisionComplexity::PreflopRaise => 1200.0,
            DecisionComplexity::PostflopSimple => 1100.0,
            DecisionComplexity::PostflopCall => 1500.0,
            DecisionComplexity::PostflopRaise => 1800.0,
            DecisionComplexity::RiverAllin => 2500.0,
        }
    }
}

/// Configuration for the temporal variance sampler.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TemporalConfig {
    /// Spread of the log-normal distribution (log-space sigma).
    pub sigma_log: f64,
    /// Lower clamp for sampled reaction times, in milliseconds.
    pub min_ms: f64,
    /// Upper clamp for sampled reaction times, in milliseconds.
    pub max_ms: f64,
}

impl Default for TemporalConfig {
    fn default() -> Self {
        Self {
            sigma_log: 0.35,
            min_ms: 10.0,
            max_ms: 3000.0,
        }
    }
}

/// Semantic validation errors for [`TemporalConfig`].
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum TemporalConfigError {
    #[error("temporal sigma_log must be finite")]
    NonFiniteSigma,
    #[error("temporal sigma_log must be greater than zero")]
    NonPositiveSigma,
    #[error("temporal min_ms must be finite and non-negative")]
    InvalidMinimum,
    #[error("temporal max_ms must be finite and non-negative")]
    InvalidMaximum,
    #[error("temporal min_ms cannot exceed max_ms")]
    InvertedBounds,
}

impl TemporalConfig {
    /// Validate parameters before constructing a sampler or loading a profile.
    pub fn validate(&self) -> Result<(), TemporalConfigError> {
        if !self.sigma_log.is_finite() {
            return Err(TemporalConfigError::NonFiniteSigma);
        }
        if self.sigma_log <= 0.0 {
            return Err(TemporalConfigError::NonPositiveSigma);
        }
        if !self.min_ms.is_finite() || self.min_ms < 0.0 {
            return Err(TemporalConfigError::InvalidMinimum);
        }
        if !self.max_ms.is_finite() || self.max_ms < 0.0 {
            return Err(TemporalConfigError::InvalidMaximum);
        }
        if self.min_ms > self.max_ms {
            return Err(TemporalConfigError::InvertedBounds);
        }
        Ok(())
    }
}

/// Samples human-like reaction times.
#[derive(Debug, Clone)]
pub struct TemporalSampler {
    config: TemporalConfig,
}

impl TemporalSampler {
    /// Construct a sampler. Invalid manually supplied configuration is handled
    /// safely by [`Self::sample`]; prefer [`Self::try_new`] when validation
    /// feedback is useful.
    pub fn new(config: TemporalConfig) -> Self {
        Self { config }
    }

    /// Construct a sampler after validating its configuration.
    pub fn try_new(config: TemporalConfig) -> Result<Self, TemporalConfigError> {
        config.validate()?;
        Ok(Self { config })
    }

    /// Sample a reaction time for the given decision complexity.
    pub fn sample<R: Rng + ?Sized>(&self, rng: &mut R, complexity: DecisionComplexity) -> Duration {
        let median_ms = complexity.median_ms();
        // Log-normal: exp(N(mu, sigma)) where mu = ln(median). Fall back to
        // the median for an invalid manually constructed sigma.
        let raw_ms = LogNormal::new(median_ms.ln(), self.config.sigma_log)
            .map(|dist| dist.sample(rng))
            .unwrap_or(median_ms);

        // Normalize manually constructed invalid bounds without using
        // f64::clamp, which panics for NaN or inverted bounds.
        let min_ms = if self.config.min_ms.is_finite() && self.config.min_ms >= 0.0 {
            self.config.min_ms
        } else {
            0.0
        };
        let max_ms = if self.config.max_ms.is_finite() && self.config.max_ms >= min_ms {
            self.config.max_ms
        } else {
            min_ms
        };
        let bounded_ms = raw_ms.max(min_ms).min(max_ms);
        Duration::from_millis(bounded_ms.round() as u64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::SeedableRng;

    fn rng() -> rand::rngs::StdRng {
        rand::rngs::StdRng::seed_from_u64(42)
    }

    #[test]
    fn rejects_invalid_temporal_config() {
        let config = TemporalConfig {
            sigma_log: 0.0,
            ..TemporalConfig::default()
        };
        assert_eq!(
            config.validate(),
            Err(TemporalConfigError::NonPositiveSigma)
        );
        assert_eq!(
            TemporalSampler::try_new(config).unwrap_err(),
            TemporalConfigError::NonPositiveSigma
        );
    }

    #[test]
    fn invalid_manual_config_does_not_panic() {
        let sampler = TemporalSampler::new(TemporalConfig {
            sigma_log: f64::NAN,
            min_ms: 100.0,
            max_ms: 10.0,
        });
        assert_eq!(
            sampler
                .sample(&mut rng(), DecisionComplexity::PreflopFold)
                .as_millis(),
            100
        );
    }

    #[test]
    fn samples_stay_within_clamp_bounds() {
        let sampler = TemporalSampler::new(TemporalConfig::default());
        let mut rng = rng();
        for complexity in [
            DecisionComplexity::PreflopFold,
            DecisionComplexity::PreflopCall,
            DecisionComplexity::PreflopRaise,
            DecisionComplexity::PostflopSimple,
            DecisionComplexity::PostflopCall,
            DecisionComplexity::PostflopRaise,
            DecisionComplexity::RiverAllin,
        ] {
            for _ in 0..500 {
                let ms = sampler.sample(&mut rng, complexity).as_millis();
                assert!(ms >= 10, "below min: {ms}");
                assert!(ms <= 3000, "above max: {ms}");
            }
        }
    }

    #[test]
    fn medians_increase_with_complexity() {
        let sampler = TemporalSampler::new(TemporalConfig::default());
        let mut rng = rng();

        let fold = median_of(&sampler, &mut rng, DecisionComplexity::PreflopFold);
        let call = median_of(&sampler, &mut rng, DecisionComplexity::PostflopCall);
        let allin = median_of(&sampler, &mut rng, DecisionComplexity::RiverAllin);

        assert!(fold < call, "fold {fold} !< call {call}");
        assert!(call < allin, "call {call} !< allin {allin}");
    }

    #[test]
    fn sampling_is_deterministic_for_a_seed() {
        let sampler = TemporalSampler::new(TemporalConfig::default());
        let mut a = rng();
        let mut b = rng();
        let x = sampler.sample(&mut a, DecisionComplexity::RiverAllin);
        let y = sampler.sample(&mut b, DecisionComplexity::RiverAllin);
        assert_eq!(x, y);
    }

    fn median_of<R: Rng + ?Sized>(
        sampler: &TemporalSampler,
        rng: &mut R,
        complexity: DecisionComplexity,
    ) -> u128 {
        let mut samples: Vec<u128> = (0..2000)
            .map(|_| sampler.sample(rng, complexity).as_millis())
            .collect();
        samples.sort_unstable();
        samples[samples.len() / 2]
    }
}
