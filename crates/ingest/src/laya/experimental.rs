//! Session-opted-in, unvalidated p6/p7 diagnostics. Never an approved registry.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::client::PassAnswers;
use super::questions::{Calibration, Layout, Pass, Question, QuestionType};
use super::scene::{SCENE_NOTE, SCENE_QUESTIONS};
use crate::capture::Frame;
use crate::partial::{
    DiagnosticReason as Reason, EvidenceStatus as Status, FieldName, PassDiagnostic,
    PerceptionDiagnostics, QuestionDiagnostic, SafeAnswer, SegmentDiagnostic,
};
use crate::vlm::{VlmError, VlmResponseError};

pub const DONOR_PASS: &str = "p5_seat_1_stack";
pub const MIN_INHERITED_CUTOFF: f64 = 0.8;
pub const GEOMETRY_SOURCE: &str = ".local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/crop-geometry.json#F001";

// Exact F001 measurements. The artifact is DRAFT with human review PENDING.
const WAGER_BOUNDS: [[u32; 4]; 6] = [
    [315, 172, 387, 232],
    [567, 199, 734, 311],
    [576, 376, 743, 496],
    [409, 422, 594, 506],
    [157, 376, 333, 496],
    [157, 199, 333, 311],
];
const SCENE_BOUNDS: [[u32; 4]; 6] = [
    [360, 44, 558, 200],
    [666, 93, 882, 272],
    [684, 350, 891, 555],
    [342, 478, 558, 680],
    [9, 350, 225, 555],
    [18, 93, 234, 272],
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentalRegion {
    pub id: String,
    pub reference_dimensions: [u32; 2],
    pub bounds: [u32; 4],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentalDescriptor {
    pub version: u8,
    pub pass: String,
    pub seat: u8,
    pub region: ExperimentalRegion,
    pub diagnostic_only: bool,
    pub training: String,
    pub geometry_status: String,
    pub human_review: String,
}

fn schema() -> VlmError {
    VlmError::Parse(VlmResponseError::Schema)
}

impl ExperimentalDescriptor {
    pub fn wager(seat: u8) -> Result<Self, VlmError> {
        Self::new(seat, true)
    }

    pub fn scene(seat: u8) -> Result<Self, VlmError> {
        Self::new(seat, false)
    }

    fn new(seat: u8, wager: bool) -> Result<Self, VlmError> {
        if !(1..=6).contains(&seat) {
            return Err(VlmError::Unavailable("invalid-observation-seat".into()));
        }
        let family = if wager { "wager" } else { "scene" };
        Ok(Self {
            version: 1,
            pass: format!("p{}_seat_{seat}_{family}", if wager { 6 } else { 7 }),
            seat,
            region: ExperimentalRegion {
                id: format!("seat_{seat}_{family}"),
                reference_dimensions: [900, 686],
                bounds: if wager { WAGER_BOUNDS } else { SCENE_BOUNDS }[seat as usize - 1],
            },
            diagnostic_only: true,
            training: "unvalidated".into(),
            geometry_status: "DRAFT".into(),
            human_review: "PENDING".into(),
        })
    }

    pub fn is_wager(&self) -> bool {
        self.pass == format!("p6_seat_{}_wager", self.seat)
    }

    pub fn validate(&self) -> Result<(), VlmError> {
        let expected = Self::new(self.seat, self.is_wager())?;
        if *self != expected {
            return Err(schema());
        }
        Ok(())
    }

    pub fn crop_bounds(&self, width: u32, height: u32) -> Option<[u32; 4]> {
        self.validate().ok()?;
        let [w, h] = self.region.reference_dimensions;
        let scale = |value: u32, size: u32, reference: u32| {
            u32::try_from(
                (u64::from(value) * u64::from(size) + u64::from(reference) / 2)
                    / u64::from(reference),
            )
            .ok()
        };
        let [a, b, c, d] = self.region.bounds;
        let bounds = [
            scale(a, width, w)?,
            scale(b, height, h)?,
            scale(c, width, w)?,
            scale(d, height, h)?,
        ];
        let [a, b, c, d] = bounds;
        let min = super::geometry::regions().geometry.min_crop_px;
        (c <= width && d <= height && c.saturating_sub(a) >= min && d.saturating_sub(b) >= min)
            .then_some(bounds)
    }

    pub fn pass_descriptor(&self) -> Result<Pass, VlmError> {
        self.validate()?;
        if self.is_wager() {
            let mut pass = super::question_set()
                .pass(DONOR_PASS)
                .ok_or_else(schema)?
                .clone();
            pass.id.clone_from(&self.pass);
            pass.regions = vec![self.region.id.clone()];
            pass.glyph_style = Some("white".into());
            pass.amount = None;
            pass.calibration = Calibration::Uncalibrated;
            // A donor cutoff, never a fitted p6 acceptance floor.
            pass.threshold = pass.threshold.max(MIN_INHERITED_CUTOFF);
            return Ok(pass);
        }
        Ok(Pass {
            id: self.pass.clone(),
            tier: 2,
            layout: Layout::Slots,
            regions: vec![self.region.id.clone()],
            calibration: Calibration::Uncalibrated,
            note: SCENE_NOTE.into(),
            // Unused: diagnostic questions have effective_floor=None.
            threshold: 0.0,
            glyph_style: None,
            amount: None,
            questions: SCENE_QUESTIONS
                .iter()
                .map(|(_, id, instructions, labels)| Question {
                    id: (*id).into(),
                    kind: QuestionType::Choice,
                    instructions: (*instructions).into(),
                    criteria: Some(serde_json::json!(labels)),
                    on_low_confidence: "unknown".into(),
                    envelope: (*id).into(),
                    image: Some(0),
                    vocab: None,
                    option_order: None,
                })
                .collect(),
        })
    }
}

/// Helper-reported transfer provenance, not validation or field admission.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentalProvenance {
    pub diagnostic_only: bool,
    pub training: String,
    pub geometry_status: String,
    pub human_review: String,
    pub donor_pass: Option<String>,
    pub inherited_cutoff: Option<f64>,
}

impl ExperimentalProvenance {
    pub fn validate(&self, descriptor: &ExperimentalDescriptor) -> Result<(), VlmError> {
        descriptor.validate()?;
        if !self.diagnostic_only
            || self.training != "unvalidated"
            || self.geometry_status != "DRAFT"
            || self.human_review != "PENDING"
            || if descriptor.is_wager() {
                self.donor_pass.as_deref() != Some(DONOR_PASS)
                    || !self
                        .inherited_cutoff
                        .is_some_and(|f| f.is_finite() && (MIN_INHERITED_CUTOFF..=1.0).contains(&f))
            } else {
                self.donor_pass.is_some() || self.inherited_cutoff.is_some()
            }
        {
            return Err(schema());
        }
        Ok(())
    }
}

#[derive(Clone, PartialEq)]
struct CropWitness {
    dimensions: [u32; 2],
    digest: [u8; 32],
}

impl std::fmt::Debug for CropWitness {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("CropWitness(<in-memory>)")
    }
}

/// Only original requested-crop pixels can make a diagnostic source-current.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ExperimentalDiagnostics {
    // Keep diagnostic metadata from enlarging every runtime event's inline payload.
    pub descriptor: Box<ExperimentalDescriptor>,
    #[serde(flatten)]
    pub provenance: ExperimentalProvenance,
    pub geometry_source: &'static str,
    pub crop_bounds: [u32; 4],
    pub crop_dimensions: [u32; 2],
    pub core_accepted: bool,
    #[serde(skip)]
    witness: CropWitness,
}

impl ExperimentalDiagnostics {
    pub fn bind(
        descriptor: ExperimentalDescriptor,
        provenance: ExperimentalProvenance,
        frame: &Frame,
        core_accepted: bool,
    ) -> Result<Self, VlmError> {
        provenance.validate(&descriptor)?;
        let crop_bounds = descriptor
            .crop_bounds(frame.width, frame.height)
            .ok_or_else(schema)?;
        let [a, b, c, d] = crop_bounds;
        Ok(Self {
            descriptor: Box::new(descriptor),
            provenance,
            geometry_source: GEOMETRY_SOURCE,
            crop_bounds,
            crop_dimensions: [c - a, d - b],
            core_accepted,
            witness: CropWitness {
                dimensions: [frame.width, frame.height],
                digest: crop_digest(frame, crop_bounds).ok_or_else(schema)?,
            },
        })
    }

    /// No rebinding, frame substitution, clock renewal, or field admission.
    pub fn source_matches(&self, latest: &Frame) -> bool {
        self.core_accepted
            && self.provenance.validate(&self.descriptor).is_ok()
            && self.geometry_source == GEOMETRY_SOURCE
            && self.witness.dimensions == [latest.width, latest.height]
            && self.descriptor.crop_bounds(latest.width, latest.height) == Some(self.crop_bounds)
            && self.crop_dimensions
                == [
                    self.crop_bounds[2] - self.crop_bounds[0],
                    self.crop_bounds[3] - self.crop_bounds[1],
                ]
            && crop_digest(latest, self.crop_bounds) == Some(self.witness.digest)
    }
}

fn crop_digest(frame: &Frame, bounds: [u32; 4]) -> Option<[u8; 32]> {
    frame.validate().ok()?;
    let [a, b, c, d] = bounds;
    if a >= c || b >= d || c > frame.width || d > frame.height {
        return None;
    }
    let mut hash = Sha256::new();
    hash.update(frame.width.to_le_bytes());
    hash.update(frame.height.to_le_bytes());
    for coordinate in bounds {
        hash.update(coordinate.to_le_bytes());
    }
    for row in b as usize..d as usize {
        let start = row * frame.bytes_per_row();
        hash.update(&frame.rgba[start + a as usize * 4..start + c as usize * 4]);
    }
    Some(hash.finalize().into())
}

/// Preserve safe closed answers, but never mark an experimental question accepted.
pub(super) fn append_diagnostics(
    diagnostics: &mut PerceptionDiagnostics,
    descriptor: &ExperimentalDescriptor,
    answers: &PassAnswers,
    bounds: [u32; 4],
    failure: Option<Reason>,
    inherited_cutoff: Option<f64>,
    total_ms: f64,
) {
    let pass = descriptor
        .pass_descriptor()
        .expect("validated experimental descriptor");
    let question = |id: &str| {
        let q = pass.question(id).expect("closed experimental question");
        let answer = answers.answers.get(id);
        let score = answer
            .filter(|a| a.p.is_finite() && (0.0..=1.0).contains(&a.p))
            .map(|a| a.p);
        let safe = answer
            .and_then(|a| a.choice.as_ref())
            .filter(|label| q.has_option(label));
        let reason = failure.unwrap_or_else(|| {
            if answer.is_none() {
                Reason::MissingAnswer
            } else if answer.is_some_and(|a| a.truncated) {
                Reason::Truncated
            } else if score.is_none() || safe.is_none() {
                Reason::InvalidAnswer
            } else if safe.is_some_and(|label| label == "unknown") {
                Reason::ExplicitUnknown
            } else {
                Reason::UnapprovedCapability
            }
        });
        QuestionDiagnostic {
            question: id.into(),
            answer: safe.cloned().map(SafeAnswer::Choice),
            score,
            effective_floor: None,
            status: if matches!(reason, Reason::InvalidAnswer | Reason::Truncated) {
                Status::Rejected
            } else {
                Status::Unknown
            },
            reason,
            truncated: answer.is_some_and(|a| a.truncated),
        }
    };
    let [a, b, c, d] = bounds;
    diagnostics.passes.push(PassDiagnostic {
        pass: pass.id.clone(),
        crop_bounds: vec![bounds],
        crop_dimensions: vec![[c - a, d - b]],
        questions: pass.questions.iter().map(|q| question(&q.id)).collect(),
        segments: answers.segments.map(|s| SegmentDiagnostic {
            n: s.n,
            overflow: s.overflow,
        }),
        total_ms: Some(total_ms),
    });
    let fields: Vec<_> = if descriptor.is_wager() {
        vec![(FieldName::VisibleWager, None)]
    } else {
        SCENE_QUESTIONS
            .iter()
            .map(|(field, id, _, _)| (*field, Some(*id)))
            .collect()
    };
    for (field, id) in fields {
        let reason = if let Some(reason) = failure {
            reason
        } else if let Some(id) = id {
            question(id).reason
        } else {
            match answers.segments {
                None => Reason::MissingSegments,
                Some(s) if s.overflow || s.n > super::question_set().max_glyphs => {
                    Reason::SegmentationOverflow
                }
                Some(s) if s.n == 0 => Reason::EmptySegmentation,
                Some(s) => {
                    let mut text = String::new();
                    let mut reason = Reason::UnapprovedCapability;
                    for k in 1..=s.n {
                        let q = question(&format!("g{k}"));
                        if q.reason != Reason::UnapprovedCapability {
                            reason = q.reason;
                            break;
                        }
                        if !q
                            .score
                            .zip(inherited_cutoff)
                            .is_some_and(|(score, cutoff)| score >= cutoff)
                        {
                            reason = Reason::BelowFloor;
                            break;
                        }
                        if let Some(SafeAnswer::Choice(label)) = q.answer {
                            text.push_str(&label);
                        }
                    }
                    if reason == Reason::UnapprovedCapability
                        && super::assembly::parse_amount(&text).is_none()
                    {
                        Reason::InvalidAmount
                    } else {
                        reason
                    }
                }
            }
        };
        diagnostics
            .fields
            .retain(|f| f.field != field || f.seat != Some(descriptor.seat));
        super::partial::record(
            &mut diagnostics.fields,
            field,
            Some(descriptor.seat),
            None,
            Status::Unknown,
            reason,
        );
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::super::client::{Answer, Segments};
    use super::*;

    pub(crate) fn provenance(wager: bool) -> ExperimentalProvenance {
        ExperimentalProvenance {
            diagnostic_only: true,
            training: "unvalidated".into(),
            geometry_status: "DRAFT".into(),
            human_review: "PENDING".into(),
            donor_pass: wager.then(|| DONOR_PASS.into()),
            inherited_cutoff: wager.then_some(MIN_INHERITED_CUTOFF),
        }
    }

    #[test]
    fn all_measured_draft_crops_are_explicit_unvalidated_and_scaled_without_new_regions() {
        for seat in 1..=6 {
            for descriptor in [
                ExperimentalDescriptor::wager(seat).unwrap(),
                ExperimentalDescriptor::scene(seat).unwrap(),
            ] {
                descriptor.validate().unwrap();
                assert_eq!(descriptor.region.reference_dimensions, [900, 686]);
                assert_eq!(
                    descriptor.crop_bounds(900, 686),
                    Some(descriptor.region.bounds)
                );
                assert_eq!(
                    descriptor.crop_bounds(1800, 1372),
                    Some(descriptor.region.bounds.map(|v| v * 2))
                );
                assert!(descriptor.crop_bounds(2, 2).is_none());
                assert_eq!(
                    descriptor.region.bounds,
                    if descriptor.is_wager() {
                        WAGER_BOUNDS
                    } else {
                        SCENE_BOUNDS
                    }[seat as usize - 1]
                );
                let wire = serde_json::to_value(&descriptor).unwrap();
                assert_eq!(wire["diagnostic_only"], true);
                assert_eq!(wire["training"], "unvalidated");
                assert_eq!(wire["geometry_status"], "DRAFT");
                assert_eq!(wire["human_review"], "PENDING");
                for prohibited in [
                    "trained_candidate",
                    "held_out_approved",
                    "human_verified",
                    "fitted_floor",
                ] {
                    assert!(wire.get(prohibited).is_none());
                }
                assert!(super::super::question_set()
                    .pass(&descriptor.pass)
                    .is_none());
                assert!(
                    super::super::geometry::region_px(&descriptor.region.id, 900, 686).is_none()
                );
                let roundtrip: ExperimentalDescriptor = serde_json::from_value(wire).unwrap();
                assert_eq!(descriptor, roundtrip);
            }
        }
        for seat in [0, 7, u8::MAX] {
            assert!(ExperimentalDescriptor::wager(seat).is_err());
            assert!(ExperimentalDescriptor::scene(seat).is_err());
        }
    }

    #[test]
    fn descriptor_cannot_claim_approval_or_substitute_a_crop() {
        let original = serde_json::to_value(ExperimentalDescriptor::wager(1).unwrap()).unwrap();
        for (key, value) in [
            ("version", serde_json::json!(2)),
            ("seat", serde_json::json!(7)),
            ("pass", serde_json::json!("p3_pot")),
            ("diagnostic_only", serde_json::json!(false)),
            ("training", serde_json::json!("trained")),
            ("geometry_status", serde_json::json!("VERIFIED")),
            ("human_review", serde_json::json!("VERIFIED")),
        ] {
            let mut wire = original.clone();
            wire[key] = value;
            let descriptor: ExperimentalDescriptor = serde_json::from_value(wire).unwrap();
            assert!(descriptor.validate().is_err(), "{key}");
        }
        let mut changed: ExperimentalDescriptor = serde_json::from_value(original.clone()).unwrap();
        changed.region.bounds[0] += 1;
        assert!(changed.validate().is_err());
        changed = serde_json::from_value(original.clone()).unwrap();
        changed.region.reference_dimensions[1] += 1;
        assert!(changed.validate().is_err());
        let mut forged = original;
        forged["held_out_approved"] = serde_json::json!(true);
        assert!(serde_json::from_value::<ExperimentalDescriptor>(forged).is_err());
    }

    #[test]
    fn wager_reuses_exact_it1_glyph_template_without_target_calibration() {
        let donor = super::super::question_set().pass(DONOR_PASS).unwrap();
        for seat in 1..=6 {
            let pass = ExperimentalDescriptor::wager(seat)
                .unwrap()
                .pass_descriptor()
                .unwrap();
            assert_eq!(pass.note, donor.note);
            assert_eq!(pass.layout, donor.layout);
            assert_eq!(pass.glyph_style.as_deref(), Some("white"));
            assert_eq!(pass.calibration, Calibration::Uncalibrated);
            assert_eq!(pass.threshold, donor.threshold.max(MIN_INHERITED_CUTOFF));
            assert!(pass.amount.is_none());
            assert_eq!(pass.questions.len(), donor.questions.len());
            for (a, b) in pass.questions.iter().zip(&donor.questions) {
                assert_eq!(a.id, b.id);
                assert_eq!(a.kind, b.kind);
                assert_eq!(a.instructions, b.instructions);
                assert_eq!(a.wire_criteria(), b.wire_criteria());
                assert_eq!(a.image, b.image);
                assert_eq!(a.option_order, b.option_order);
            }
            let scene = ExperimentalDescriptor::scene(seat)
                .unwrap()
                .pass_descriptor()
                .unwrap();
            assert_eq!(scene.calibration, Calibration::Uncalibrated);
            assert_eq!(scene.note, SCENE_NOTE);
            assert_eq!(scene.questions.len(), SCENE_QUESTIONS.len());
        }
    }

    #[test]
    fn transfer_cutoff_cannot_drop_below_point_eight_or_become_a_scene_floor() {
        let wager = ExperimentalDescriptor::wager(1).unwrap();
        let scene = ExperimentalDescriptor::scene(1).unwrap();
        let mut transfer = provenance(true);
        for cutoff in [0.0, 0.799999999, 1.000001, f64::NAN, f64::INFINITY] {
            transfer.inherited_cutoff = Some(cutoff);
            assert!(transfer.validate(&wager).is_err());
        }
        for cutoff in [0.8, 0.99, 1.0] {
            transfer.inherited_cutoff = Some(cutoff);
            assert!(transfer.validate(&wager).is_ok());
            assert!(transfer.validate(&scene).is_err());
        }
        assert!(provenance(false).validate(&scene).is_ok());
        assert!(provenance(false).validate(&wager).is_err());
        assert_eq!(
            serde_json::to_value(provenance(false)).unwrap()["inherited_cutoff"],
            serde_json::Value::Null
        );
        assert_eq!(
            super::super::question_set()
                .pass(DONOR_PASS)
                .unwrap()
                .threshold,
            0.8
        );
    }

    #[test]
    fn exact_original_requested_crop_binding_rejects_mutation_geometry_and_unqualified_core() {
        let original = Frame::new(900, 686, vec![64; 900 * 686 * 4]).unwrap();
        for wager in [true, false] {
            let descriptor = if wager {
                ExperimentalDescriptor::wager(1)
            } else {
                ExperimentalDescriptor::scene(1)
            }
            .unwrap();
            let proof = ExperimentalDiagnostics::bind(
                descriptor.clone(),
                provenance(wager),
                &original,
                true,
            )
            .unwrap();
            assert!(proof.source_matches(&original));
            let mut outside = original.clone();
            outside.rgba[0] += 1;
            assert!(
                proof.source_matches(&outside),
                "outside animation is not a requested-crop veto"
            );
            let mut inside = outside;
            let [x, y, _, _] = proof.crop_bounds;
            inside.rgba[((y * original.width + x) * 4) as usize] += 1;
            assert!(!proof.source_matches(&inside));
            assert!(
                proof.source_matches(&original),
                "a failed comparison must not renew the source witness"
            );
            assert!(
                !proof.source_matches(&Frame::new(1800, 1372, vec![64; 1800 * 1372 * 4]).unwrap())
            );
            assert!(!proof.source_matches(&Frame {
                width: 900,
                height: 686,
                rgba: vec![0],
                ..Frame::default()
            }));
            let unqualified =
                ExperimentalDiagnostics::bind(descriptor, provenance(wager), &original, false)
                    .unwrap();
            assert!(!unqualified.source_matches(&original));
            let wire = serde_json::to_value(&proof).unwrap();
            assert_eq!(wire["geometry_source"], GEOMETRY_SOURCE);
            assert!(wire.get("witness").is_none());
            assert!(wire.get("rgba").is_none());
            assert!(wire.get("frame_sha256").is_none());
        }
    }

    #[test]
    fn empty_segmentation_is_unknown_never_zero_and_no_experiment_has_an_acceptance_floor() {
        for (n, expected) in [
            (0, Reason::EmptySegmentation),
            (1, Reason::UnapprovedCapability),
        ] {
            let descriptor = ExperimentalDescriptor::wager(1).unwrap();
            let answers = PassAnswers {
                segments: Some(Segments { n, overflow: false }),
                answers: [(
                    "g1".into(),
                    Answer {
                        choice: Some("0".into()),
                        p: 0.99,
                        truncated: false,
                    },
                )]
                .into(),
                acceptance_floor: None,
            };
            let mut diagnostics = PerceptionDiagnostics::default();
            append_diagnostics(
                &mut diagnostics,
                &descriptor,
                &answers,
                descriptor.region.bounds,
                None,
                Some(0.8),
                1.0,
            );
            assert_eq!(diagnostics.fields[0].status, Status::Unknown);
            assert_eq!(diagnostics.fields[0].reason, expected);
            assert_eq!(diagnostics.fields[0].admission_status, Status::Unknown);
            assert!(diagnostics.passes[0]
                .questions
                .iter()
                .all(|q| q.effective_floor.is_none() && q.status != Status::Accepted));
            assert!(!diagnostics.source_current);
            let wire = serde_json::to_value(&diagnostics).unwrap();
            assert!(
                wire.get("seats").is_none()
                    && wire.get("state").is_none()
                    && wire.get("actions").is_none()
            );
        }
        let descriptor = ExperimentalDescriptor::scene(6).unwrap();
        let answers = PassAnswers {
            answers: SCENE_QUESTIONS
                .iter()
                .map(|(_, id, _, labels)| {
                    (
                        (*id).into(),
                        Answer {
                            choice: Some(labels[0].into()),
                            p: 1.0,
                            truncated: false,
                        },
                    )
                })
                .collect(),
            ..Default::default()
        };
        let mut diagnostics = PerceptionDiagnostics::default();
        append_diagnostics(
            &mut diagnostics,
            &descriptor,
            &answers,
            descriptor.region.bounds,
            None,
            None,
            1.0,
        );
        assert!(diagnostics
            .fields
            .iter()
            .all(|f| f.status == Status::Unknown && f.reason == Reason::UnapprovedCapability));
        assert!(diagnostics.passes[0]
            .questions
            .iter()
            .all(|q| q.status == Status::Unknown
                && q.reason == Reason::UnapprovedCapability
                && q.effective_floor.is_none()));
    }

    #[test]
    fn diagnostic_expiry_never_admits_experimental_fields_or_renews_source_provenance() {
        use crate::partial::DiagnosticAdmission;
        let source = Frame::new(900, 686, vec![64; 900 * 686 * 4]).unwrap();
        let descriptor = ExperimentalDescriptor::wager(1).unwrap();
        let proof =
            ExperimentalDiagnostics::bind(descriptor.clone(), provenance(true), &source, true)
                .unwrap();
        let answers = PassAnswers {
            answers: [(
                "g1".into(),
                Answer {
                    choice: Some("7".into()),
                    p: 1.0,
                    truncated: false,
                },
            )]
            .into(),
            segments: Some(Segments {
                n: 1,
                overflow: false,
            }),
            acceptance_floor: None,
        };
        let mut diagnostics = PerceptionDiagnostics {
            experimental: Some(proof.clone()),
            ..Default::default()
        };
        append_diagnostics(
            &mut diagnostics,
            &descriptor,
            &answers,
            proof.crop_bounds,
            None,
            Some(0.8),
            1.0,
        );
        for admission in [
            DiagnosticAdmission::SourceCurrent,
            DiagnosticAdmission::ObsoleteObservation,
            DiagnosticAdmission::ObservationExpired,
            DiagnosticAdmission::DecisionBudgetExpired,
        ] {
            diagnostics.set_admission(admission, None);
            assert_eq!(
                diagnostics.source_current,
                admission == DiagnosticAdmission::SourceCurrent
            );
            assert_eq!(diagnostics.experimental.as_ref(), Some(&proof));
            assert!(diagnostics
                .fields
                .iter()
                .all(|f| f.status == Status::Unknown && f.admission_status != Status::Accepted));
            assert!(diagnostics
                .passes
                .iter()
                .flat_map(|p| &p.questions)
                .all(|q| q.effective_floor.is_none() && q.status != Status::Accepted));
        }
    }
}
