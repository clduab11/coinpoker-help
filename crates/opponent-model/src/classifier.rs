//! Archetype classification (LAG/TAG/LP/TP).
//!
//! Deterministic threshold classifier over extracted features. A
//! `linfa`-backed model is planned as an optional v2 upgrade.

use serde::{Deserialize, Serialize};

use crate::features::PlayerStats;

/// Opponent archetypes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum Archetype {
    /// Loose-aggressive: high VPIP, high aggression.
    Lag,
    /// Tight-aggressive: low VPIP, high aggression.
    Tag,
    /// Loose-passive: high VPIP, low aggression.
    LoosePassive,
    /// Tight-passive: low VPIP, low aggression.
    TightPassive,
    /// Insufficient data to classify.
    Unknown,
}

/// Thresholds for the deterministic classifier.
#[derive(Debug, Clone, PartialEq)]
pub struct ClassifierConfig {
    /// VPIP above this is "loose".
    pub loose_vpip: f64,
    /// Aggression factor above this is "aggressive".
    pub aggressive_af: f64,
    /// Minimum hands before a classification is trusted.
    pub min_hands: u32,
}

impl Default for ClassifierConfig {
    fn default() -> Self {
        Self {
            loose_vpip: 0.30,
            aggressive_af: 2.0,
            min_hands: 20,
        }
    }
}

/// Classification result with a confidence score.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Classification {
    pub archetype: Archetype,
    /// Confidence in [0, 1], based on distance from the decision boundary.
    pub confidence: f64,
}

/// Classifies player statistics into archetypes.
#[derive(Debug, Clone)]
pub struct Classifier {
    config: ClassifierConfig,
}

impl Classifier {
    pub fn new(config: ClassifierConfig) -> Self {
        Self { config }
    }

    /// Classify a player's statistics.
    pub fn classify(&self, stats: &PlayerStats) -> Classification {
        if stats.hands < self.config.min_hands {
            return Classification {
                archetype: Archetype::Unknown,
                confidence: 0.0,
            };
        }

        let loose = stats.vpip > self.config.loose_vpip;
        let aggressive = stats.aggression_factor > self.config.aggressive_af;

        let archetype = match (loose, aggressive) {
            (true, true) => Archetype::Lag,
            (false, true) => Archetype::Tag,
            (true, false) => Archetype::LoosePassive,
            (false, false) => Archetype::TightPassive,
        };

        // Confidence: how far the decisive features sit from their
        // thresholds, normalized and averaged.
        let vpip_distance = (stats.vpip - self.config.loose_vpip).abs();
        let af_distance = (stats.aggression_factor - self.config.aggressive_af).abs();
        let vpip_confidence = (vpip_distance / self.config.loose_vpip).min(1.0);
        let af_confidence = (af_distance / self.config.aggressive_af).min(1.0);
        let confidence = 0.5 + 0.5 * ((vpip_confidence + af_confidence) / 2.0);

        Classification {
            archetype,
            confidence,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stats(vpip: f64, af: f64, hands: u32) -> PlayerStats {
        PlayerStats {
            hands,
            vpip,
            pfr: 0.0,
            aggression_factor: af,
            went_to_showdown: 0.0,
            won_at_showdown: 0.0,
        }
    }

    #[test]
    fn classifies_the_four_archetypes() {
        let c = Classifier::new(ClassifierConfig::default());
        assert_eq!(c.classify(&stats(0.45, 3.0, 100)).archetype, Archetype::Lag);
        assert_eq!(c.classify(&stats(0.20, 3.0, 100)).archetype, Archetype::Tag);
        assert_eq!(
            c.classify(&stats(0.45, 1.0, 100)).archetype,
            Archetype::LoosePassive
        );
        assert_eq!(
            c.classify(&stats(0.20, 1.0, 100)).archetype,
            Archetype::TightPassive
        );
    }

    #[test]
    fn insufficient_hands_yields_unknown() {
        let c = Classifier::new(ClassifierConfig::default());
        let result = c.classify(&stats(0.45, 3.0, 5));
        assert_eq!(result.archetype, Archetype::Unknown);
        assert_eq!(result.confidence, 0.0);
    }

    #[test]
    fn confidence_grows_with_distance_from_boundaries() {
        let c = Classifier::new(ClassifierConfig::default());
        let near = c.classify(&stats(0.31, 2.1, 100));
        let far = c.classify(&stats(0.60, 5.0, 100));
        assert!(far.confidence > near.confidence);
        assert!((0.0..=1.0).contains(&near.confidence));
    }
}
