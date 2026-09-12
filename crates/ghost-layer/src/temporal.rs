//! Log-normal reaction-time sampling.
//!
//! Samples human-like action latency from a log-normal distribution
//! clamped to [10ms, 3000ms], with the median correlated to decision
//! complexity (a preflop fold is fast; a river all-in is slow).

use std::time::Duration;

use rand::Rng;
use rand_distr::{Distribution, LogNormal};

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

/// Samples human-like reaction times.
#[derive(Debug, Clone)]
pub struct TemporalSampler {
    config: TemporalConfig,
}

impl TemporalSampler {
    pub fn new(config: TemporalConfig) -> Self {
        Self { config }
    }

    /// Sample a reaction time for the given decision complexity.
    pub fn sample<R: Rng + ?Sized>(&self, rng: &mut R, complexity: DecisionComplexity) -> Duration {
        let median_ms = complexity.median_ms();
        // Log-normal: exp(N(mu, sigma)) where mu = ln(median).
        let dist = LogNormal::new(median_ms.ln(), self.config.sigma_log)
            .expect("valid log-normal parameters");
        let raw_ms: f64 = dist.sample(rng);
        let clamped = raw_ms.clamp(self.config.min_ms, self.config.max_ms);
        Duration::from_millis(clamped.round() as u64)
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
