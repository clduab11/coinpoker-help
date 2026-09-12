//! Serializable human-parity parameter store.
//!
//! Holds timing curves, sizing preferences, and deviation frequencies so a
//! behavioral profile can be persisted and reused across sessions.

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::betting_entropy::BettingEntropyConfig;
use crate::temporal::TemporalConfig;

/// Errors produced when loading or saving a profile.
#[derive(Debug, Error)]
pub enum ProfileError {
    #[error("profile I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("profile parse error: {0}")]
    Parse(#[from] serde_json::Error),
}

/// The full set of human-parity parameters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GhostProfile {
    /// Name of the profile (e.g. "default", "reg-vs-fish").
    pub name: String,
    /// Reaction-time distribution parameters.
    pub temporal: TemporalConfig,
    /// Bet-sizing discretization parameters.
    pub betting: BettingEntropyConfig,
}

impl Default for GhostProfile {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            temporal: TemporalConfig::default(),
            betting: BettingEntropyConfig::default(),
        }
    }
}

impl GhostProfile {
    /// Serialize the profile to a JSON string.
    pub fn to_json(&self) -> Result<String, ProfileError> {
        Ok(serde_json::to_string_pretty(self)?)
    }

    /// Deserialize a profile from a JSON string.
    pub fn from_json(json: &str) -> Result<Self, ProfileError> {
        Ok(serde_json::from_str(json)?)
    }

    /// Save the profile to a file.
    pub fn save(&self, path: &std::path::Path) -> Result<(), ProfileError> {
        std::fs::write(path, self.to_json()?)?;
        Ok(())
    }

    /// Load a profile from a file.
    pub fn load(path: &std::path::Path) -> Result<Self, ProfileError> {
        let json = std::fs::read_to_string(path)?;
        Self::from_json(&json)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_profile_has_human_plausible_parameters() {
        let p = GhostProfile::default();
        assert_eq!(p.name, "default");
        assert!(p.temporal.min_ms >= 10.0);
        assert!(p.temporal.max_ms <= 3000.0);
        assert!(p.betting.off_grid_probability > 0.0 && p.betting.off_grid_probability < 0.2);
    }

    #[test]
    fn json_round_trip_preserves_parameters() {
        let p = GhostProfile::default();
        let json = p.to_json().expect("serialize");
        let restored = GhostProfile::from_json(&json).expect("deserialize");
        assert_eq!(p, restored);
    }

    #[test]
    fn save_and_load_round_trip() {
        let dir = std::env::temp_dir().join("ghost-layer-profile-test");
        std::fs::create_dir_all(&dir).expect("create temp dir");
        let path = dir.join("profile.json");

        let p = GhostProfile::default();
        p.save(&path).expect("save");
        let restored = GhostProfile::load(&path).expect("load");
        assert_eq!(p, restored);

        std::fs::remove_file(&path).expect("cleanup");
    }

    #[test]
    fn rejects_malformed_json() {
        assert!(GhostProfile::from_json("{not json").is_err());
    }
}
