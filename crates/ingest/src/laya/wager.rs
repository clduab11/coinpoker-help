//! Explicit Stage-4 candidate configuration, never populated from the old it1 passes.

use serde::{Deserialize, Serialize};

use super::questions::{Calibration, Pass, QuestionSet};
use crate::partial::{Capability, DiagnosticReason, FieldName, TrainingStatus};
use crate::vlm::{VlmError, VlmResponseError};

pub const WAGER_REGISTRY_VERSION: u32 = 1;
pub const WAGER_PROVENANCE: &str = "observation-only-calibrated-pass";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WagerRegion {
    pub id: String,
    pub reference_dimensions: [u32; 2],
    pub bounds: Option<[u32; 4]>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WagerPassConfig {
    pub seat: u8,
    pub pass: String,
    pub region: Option<WagerRegion>,
    pub fitted_floor: Option<f64>,
    #[serde(default)]
    pub trained_candidate: bool,
    pub candidate_sha256: Option<String>,
    pub model_sha256: Option<String>,
    pub capability_evidence_sha256: Option<String>,
    #[serde(default)]
    pub held_out_approved: bool,
    #[serde(default)]
    pub human_verified: bool,
    pub provenance: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WagerPassRegistry {
    pub version: u32,
    pub model_alias: String,
    pub passes: Vec<WagerPassConfig>,
}

impl WagerPassRegistry {
    /// Validate the registry namespace. Per-seat capability qualification stays independent.
    pub fn validate_for_model(&self, model: &str) -> Result<(), VlmError> {
        self.validate_namespace()?;
        if self.model_alias != model {
            return Err(VlmError::Parse(VlmResponseError::Schema));
        }
        Ok(())
    }

    pub(crate) fn validate_namespace(&self) -> Result<(), VlmError> {
        if self.version != WAGER_REGISTRY_VERSION
            || self.model_alias.is_empty()
            || self.model_alias.len() > 128
            || !self
                .model_alias
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
            || self.passes.len() > 6
            || self.passes.iter().enumerate().any(|(i, entry)| {
                !(1..=6).contains(&entry.seat)
                    || entry.pass != format!("p6_seat_{}_wager", entry.seat)
                    || self.passes[..i]
                        .iter()
                        .any(|other| other.seat == entry.seat)
            })
        {
            return Err(VlmError::Parse(VlmResponseError::Schema));
        }
        Ok(())
    }

    pub fn seat(&self, seat: u8) -> Option<&WagerPassConfig> {
        self.passes.iter().find(|entry| entry.seat == seat)
    }

    /// The helper must verify this identity/config against its own approved registry.
    pub fn wire_capability(&self, entry: &WagerPassConfig) -> serde_json::Value {
        let mut value = serde_json::to_value(entry).expect("qualified finite registry");
        value["registry_version"] = self.version.into();
        value["model_alias"] = self.model_alias.clone().into();
        value
    }
}

impl WagerPassConfig {
    pub fn qualification(&self) -> Result<(), DiagnosticReason> {
        if !(1..=6).contains(&self.seat) || self.pass != format!("p6_seat_{}_wager", self.seat) {
            return Err(DiagnosticReason::InvalidCapability);
        }
        let region = self
            .region
            .as_ref()
            .ok_or(DiagnosticReason::UnknownRegion)?;
        if region.id != format!("seat_{}_wager", self.seat) {
            return Err(DiagnosticReason::UnknownRegion);
        }
        let [w, h] = region.reference_dimensions;
        let [a, b, c, d] = region.bounds.ok_or(DiagnosticReason::UnknownRegion)?;
        if w == 0 || h == 0 || a >= c || b >= d || c > w || d > h {
            return Err(DiagnosticReason::UnknownRegion);
        }
        if !self
            .fitted_floor
            .is_some_and(|f| f.is_finite() && f > 0.0 && f <= 1.0)
        {
            return Err(DiagnosticReason::InvalidFloor);
        }
        if !self.trained_candidate || !self.held_out_approved || !self.human_verified {
            return Err(DiagnosticReason::UnapprovedCapability);
        }
        if self.provenance != WAGER_PROVENANCE
            || !valid_digest(self.candidate_sha256.as_deref())
            || !valid_digest(self.model_sha256.as_deref())
            || !valid_digest(self.capability_evidence_sha256.as_deref())
        {
            return Err(DiagnosticReason::InvalidCapability);
        }
        Ok(())
    }

    pub fn crop_bounds(&self, width: u32, height: u32) -> Option<[u32; 4]> {
        self.qualification().ok()?;
        let region = self.region.as_ref()?;
        let bounds = region.bounds?;
        let [w, h] = region.reference_dimensions;
        let scale = |value: u32, size: u32, reference: u32| -> Option<u32> {
            u32::try_from(
                (u64::from(value) * u64::from(size) + u64::from(reference) / 2)
                    / u64::from(reference),
            )
            .ok()
        };
        Some([
            scale(bounds[0], width, w)?,
            scale(bounds[1], height, h)?,
            scale(bounds[2], width, w)?,
            scale(bounds[3], height, h)?,
        ])
    }

    pub fn pass_descriptor(&self, qs: &QuestionSet) -> Option<Pass> {
        self.qualification().ok()?;
        let mut pass = qs.pass("p5_seat_1_stack")?.clone();
        pass.id.clone_from(&self.pass);
        pass.note =
            "Observed per-seat visible wager glyphs; not stack, street contribution or call cost."
                .into();
        pass.regions = vec![self.region.as_ref()?.id.clone()];
        pass.glyph_style = Some("white".into());
        pass.amount = Some(format!("seat_{}_visible_wager", self.seat));
        pass.calibration = Calibration::Calibrated;
        pass.threshold = self.fitted_floor?;
        Some(pass)
    }

    pub fn capability(&self) -> Option<Capability> {
        self.qualification().ok()?;
        Some(Capability {
            field: FieldName::VisibleWager,
            seat: Some(self.seat),
            training: TrainingStatus::ReadOnlyApproved,
            acceptance_floor: self.fitted_floor,
            held_out_approved: true,
            human_verified: true,
            provenance: WAGER_PROVENANCE,
        })
    }
}

fn valid_digest(value: Option<&str>) -> bool {
    value.is_some_and(|s| {
        s.len() == 64
            && s.as_bytes()
                .iter()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(c))
            && s.bytes().any(|c| c != b'0')
    })
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    pub(crate) fn registry() -> WagerPassRegistry {
        WagerPassRegistry {
            version: 1,
            model_alias: "coinpoker-laya-vision".into(),
            passes: (1..=6)
                .map(|seat| WagerPassConfig {
                    seat,
                    pass: format!("p6_seat_{seat}_wager"),
                    region: Some(WagerRegion {
                        id: format!("seat_{seat}_wager"),
                        reference_dimensions: [800, 613],
                        bounds: Some([100, 100, 160, 130]),
                    }),
                    fitted_floor: Some(0.99),
                    trained_candidate: true,
                    candidate_sha256: Some("1".repeat(64)),
                    model_sha256: Some("2".repeat(64)),
                    capability_evidence_sha256: Some("3".repeat(64)),
                    held_out_approved: true,
                    human_verified: true,
                    provenance: WAGER_PROVENANCE.into(),
                })
                .collect(),
        }
    }
    #[test]
    fn registry_descriptors_are_versioned_distinct_closed_and_scaled_without_old_regions() {
        let registry = registry();
        let roundtrip: WagerPassRegistry =
            serde_json::from_str(&serde_json::to_string(&registry).unwrap()).unwrap();
        assert_eq!(registry, roundtrip);
        registry
            .validate_for_model("coinpoker-laya-vision")
            .unwrap();
        let entry = &registry.passes[0];
        assert_eq!(entry.crop_bounds(1600, 1226), Some([200, 200, 320, 260]));
        let descriptor = entry.pass_descriptor(super::super::question_set()).unwrap();
        assert_eq!(descriptor.id, "p6_seat_1_wager");
        assert_eq!(descriptor.regions, ["seat_1_wager"]);
        assert_eq!(descriptor.glyph_style.as_deref(), Some("white"));
        assert_eq!(descriptor.questions.len(), 8);
        assert_eq!(descriptor.threshold, 0.99);
        assert!(super::super::question_set()
            .pass("p6_seat_1_wager")
            .is_none());
        assert!(!super::super::geometry::regions()
            .regions
            .contains_key("seat_1_wager"));
    }
}
