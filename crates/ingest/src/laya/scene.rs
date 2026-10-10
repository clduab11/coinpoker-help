//! Opt-in, closed seat-scene readings. No names, hidden cards or action inference.

use serde::{Deserialize, Serialize};

use super::client::PassAnswers;
use super::questions::{Calibration, Layout, Pass, Question, QuestionType};
use crate::partial::{
    Badge, Capability, DiagnosticAdmission, DiagnosticReason as Reason, EvidenceStatus as Status,
    FieldEvidence, FieldName, PartialObservation, PerceptionDiagnostics, SeatStatus, SeatView,
    TrainingStatus,
};
use crate::vlm::{VlmError, VlmResponseError};

pub const SCENE_REGISTRY_VERSION: u32 = 1;
pub const SCENE_PROVENANCE: &str = "observation-only-calibrated-pass";
pub const SCENE_NOTE: &str =
    "Observed per-seat visible scene only; not names, hidden cards, hand roster or actions.";
pub type SceneRegion = super::wager::WagerRegion;

// Option order is part of the model input and deliberately fixed.
pub const SCENE_QUESTIONS: [(FieldName, &str, &str, &[&str]); 7] = [
    (
        FieldName::Occupied,
        "occupied",
        "Is this physical seat visibly occupied or open?",
        &["occupied", "open", "unknown"],
    ),
    (
        FieldName::Status,
        "status",
        "Read only the visible participation status of this seat.",
        &["active", "folded", "all_in", "sitting_out", "unknown"],
    ),
    (
        FieldName::Badge,
        "badge",
        "Read only this seat's visible badge, or none if visibly absent.",
        &[
            "none",
            "fold",
            "check",
            "call",
            "bet",
            "raise",
            "all_in",
            "small_blind",
            "big_blind",
            "unknown",
        ],
    ),
    (
        FieldName::Dealer,
        "dealer",
        "Is the dealer button visibly at this seat?",
        &["dealer_here", "not_dealer", "unknown"],
    ),
    (
        FieldName::SmallBlind,
        "small_blind",
        "Is the small-blind marker visibly at this seat?",
        &["small_blind_here", "not_small_blind", "unknown"],
    ),
    (
        FieldName::BigBlind,
        "big_blind",
        "Is the big-blind marker visibly at this seat?",
        &["big_blind_here", "not_big_blind", "unknown"],
    ),
    (
        FieldName::Acting,
        "acting",
        "Does visible acting evidence identify this seat as the current actor?",
        &["yes", "no", "unknown"],
    ),
];
pub const SCENE_FIELDS: [FieldName; 7] = [
    FieldName::Occupied,
    FieldName::Status,
    FieldName::Badge,
    FieldName::Dealer,
    FieldName::SmallBlind,
    FieldName::BigBlind,
    FieldName::Acting,
];

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScenePassConfig {
    pub seat: u8,
    pub pass: String,
    pub region: Option<SceneRegion>,
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
pub struct ScenePassRegistry {
    pub version: u32,
    pub model_alias: String,
    pub passes: Vec<ScenePassConfig>,
}

impl ScenePassRegistry {
    pub fn validate_for_model(&self, model: &str) -> Result<(), VlmError> {
        self.validate_namespace()?;
        if self.model_alias != model {
            return Err(VlmError::Parse(VlmResponseError::Schema));
        }
        Ok(())
    }

    pub(crate) fn validate_namespace(&self) -> Result<(), VlmError> {
        if self.version != SCENE_REGISTRY_VERSION
            || self.model_alias.is_empty()
            || self.model_alias.len() > 128
            || !self
                .model_alias
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
            || self.passes.len() > 6
            || self.passes.iter().enumerate().any(|(i, entry)| {
                !(1..=6).contains(&entry.seat)
                    || entry.pass != format!("p7_seat_{}_scene", entry.seat)
                    || self.passes[..i]
                        .iter()
                        .any(|other| other.seat == entry.seat)
            })
        {
            return Err(VlmError::Parse(VlmResponseError::Schema));
        }
        Ok(())
    }

    pub fn seat(&self, seat: u8) -> Option<&ScenePassConfig> {
        self.passes.iter().find(|entry| entry.seat == seat)
    }

    pub fn wire_capability(&self, entry: &ScenePassConfig) -> serde_json::Value {
        let mut value = serde_json::to_value(entry).expect("qualified finite registry");
        value["registry_version"] = self.version.into();
        value["model_alias"] = self.model_alias.clone().into();
        value
    }
}

impl ScenePassConfig {
    pub fn qualification(&self) -> Result<(), Reason> {
        if !(1..=6).contains(&self.seat) || self.pass != format!("p7_seat_{}_scene", self.seat) {
            return Err(Reason::InvalidCapability);
        }
        let region = self.region.as_ref().ok_or(Reason::UnknownRegion)?;
        if region.id != format!("seat_{}_scene", self.seat) {
            return Err(Reason::UnknownRegion);
        }
        let [w, h] = region.reference_dimensions;
        let [a, b, c, d] = region.bounds.ok_or(Reason::UnknownRegion)?;
        if w == 0 || h == 0 || a >= c || b >= d || c > w || d > h {
            return Err(Reason::UnknownRegion);
        }
        if !self
            .fitted_floor
            .is_some_and(|f| f.is_finite() && f > 0.0 && f <= 1.0)
        {
            return Err(Reason::InvalidFloor);
        }
        if !self.trained_candidate || !self.held_out_approved || !self.human_verified {
            return Err(Reason::UnapprovedCapability);
        }
        if self.provenance != SCENE_PROVENANCE
            || [
                self.candidate_sha256.as_deref(),
                self.model_sha256.as_deref(),
                self.capability_evidence_sha256.as_deref(),
            ]
            .iter()
            .any(|value| {
                !value.is_some_and(|s| {
                    s.len() == 64
                        && s.bytes()
                            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
                        && s.bytes().any(|c| c != b'0')
                })
            })
        {
            return Err(Reason::InvalidCapability);
        }
        Ok(())
    }

    pub fn crop_bounds(&self, width: u32, height: u32) -> Option<[u32; 4]> {
        self.qualification().ok()?;
        let region = self.region.as_ref()?;
        let bounds = region.bounds?;
        let [w, h] = region.reference_dimensions;
        let scale = |value: u32, size: u32, reference: u32| {
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

    pub fn pass_descriptor(&self) -> Option<Pass> {
        self.qualification().ok()?;
        Some(Pass {
            id: self.pass.clone(),
            tier: 2,
            layout: Layout::Slots,
            regions: vec![self.region.as_ref()?.id.clone()],
            calibration: Calibration::Calibrated,
            note: SCENE_NOTE.into(),
            threshold: self.fitted_floor?,
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

    pub fn capabilities(&self) -> Vec<Capability> {
        if self.qualification().is_err() {
            return Vec::new();
        }
        SCENE_FIELDS
            .into_iter()
            .map(|field| Capability {
                field,
                seat: Some(self.seat),
                training: TrainingStatus::ReadOnlyApproved,
                acceptance_floor: self.fitted_floor,
                held_out_approved: true,
                human_verified: true,
                provenance: SCENE_PROVENANCE,
            })
            .collect()
    }
}

pub(crate) fn field_known(seat: &SeatView, field: FieldName) -> bool {
    match field {
        FieldName::Occupied => seat.occupied.is_some(),
        FieldName::Status => seat.status.is_some(),
        FieldName::Badge => seat.badge.is_some(),
        FieldName::Dealer => seat.dealer.is_some(),
        FieldName::SmallBlind => seat.small_blind.is_some(),
        FieldName::BigBlind => seat.big_blind.is_some(),
        FieldName::Acting => seat.acting.is_some(),
        _ => false,
    }
}

pub(crate) fn clear_field(seat: &mut SeatView, field: FieldName) {
    match field {
        FieldName::Occupied => seat.occupied = None,
        FieldName::Status => seat.status = None,
        FieldName::Badge => seat.badge = None,
        FieldName::Dealer => seat.dealer = None,
        FieldName::SmallBlind => seat.small_blind = None,
        FieldName::BigBlind => seat.big_blind = None,
        FieldName::Acting => seat.acting = None,
        _ => {}
    }
}

pub(crate) fn retain_agreement(seat: &mut SeatView, current: &SeatView, previous: &SeatView) {
    if current.occupied == previous.occupied {
        seat.occupied = current.occupied;
    }
    if current.status == previous.status {
        seat.status = current.status;
    }
    if current.badge == previous.badge {
        seat.badge = current.badge;
    }
    if current.dealer == previous.dealer {
        seat.dealer = current.dealer;
    }
    if current.small_blind == previous.small_blind {
        seat.small_blind = current.small_blind;
    }
    if current.big_blind == previous.big_blind {
        seat.big_blind = current.big_blind;
    }
    if current.acting == previous.acting {
        seat.acting = current.acting;
    }
}

/// Extend the already core-gated candidate, without re-requesting any existing pass.
pub fn extend_partial(
    candidate: &mut Option<PartialObservation>,
    diagnostics: &mut PerceptionDiagnostics,
    frame: (u32, u32),
    threshold: Option<f32>,
    registry: &ScenePassRegistry,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
) -> Result<(), VlmError> {
    registry.validate_namespace()?;
    let Some(partial) = candidate.as_mut() else {
        return Ok(());
    };
    // A scene extension must be applied before binding the original frame.
    if partial.source_witness.is_some() || (partial.frame_width, partial.frame_height) != frame {
        return Err(VlmError::Parse(VlmResponseError::Schema));
    }
    for seat in 1..=6 {
        partial.scene_sources[seat as usize - 1] = None;
        for capability in partial
            .view
            .capabilities
            .iter_mut()
            .filter(|c| c.seat == Some(seat) && SCENE_FIELDS.contains(&c.field))
        {
            capability.training = TrainingStatus::Unsupported;
            capability.acceptance_floor = None;
            capability.held_out_approved = false;
            capability.human_verified = false;
            capability.provenance = "observation-only-proposal";
        }
        partial
            .evidence
            .retain(|f| !(f.seat == Some(seat) && SCENE_FIELDS.contains(&f.field)));
        for field in SCENE_FIELDS {
            clear_field(&mut partial.view.seats[seat as usize - 1], field);
        }
        let qualification = registry
            .seat(seat)
            .ok_or(Reason::Unsupported)
            .and_then(|entry| entry.qualification());
        if let Err(reason) = qualification {
            for field in SCENE_FIELDS {
                super::partial::record(
                    &mut partial.evidence,
                    field,
                    Some(seat),
                    None,
                    Status::Unknown,
                    reason,
                );
            }
            continue;
        }
        let entry = registry.seat(seat).unwrap();
        let pass = entry.pass_descriptor().unwrap();
        let bounds = entry.crop_bounds(frame.0, frame.1).unwrap();
        let [a, b, c, d] = bounds;
        let min = super::geometry::regions().geometry.min_crop_px;
        let crop_ok = c <= frame.0
            && d <= frame.1
            && c.saturating_sub(a) >= min
            && d.saturating_sub(b) >= min;
        let (answers, failure) = if !crop_ok {
            (PassAnswers::default(), Some(Reason::CropTooSmall))
        } else {
            match run(&pass) {
                Ok(answers) => (answers, None),
                Err(VlmError::Deadline) => {
                    diagnostics.admission = DiagnosticAdmission::DecisionBudgetExpired;
                    (PassAnswers::default(), Some(Reason::DecisionDeadline))
                }
                Err(VlmError::Unavailable(code))
                    if code == "scene-capability-identity-mismatch" =>
                {
                    (PassAnswers::default(), Some(Reason::IdentityMismatch))
                }
                Err(VlmError::Unavailable(code)) if code == "scene-fitted-floor-mismatch" => {
                    (PassAnswers::default(), Some(Reason::InvalidFloor))
                }
                Err(_) => (PassAnswers::default(), Some(Reason::PassUnavailable)),
            }
        };
        let floor = answers
            .acceptance_floor
            .filter(|f| f.is_finite() && *f <= 1.0 && *f >= entry.fitted_floor.unwrap())
            .map(|f| f.max(threshold.map_or(0.0, f64::from)));
        let reading = super::partial::Reading {
            pass: &pass,
            answers,
            floor,
            failure,
        };
        for (field, id, _, _) in SCENE_QUESTIONS {
            let mut evidence = reading.diagnostic(id);
            if evidence.status == Status::Accepted && reading.choice(id) == Some("unknown") {
                evidence.status = Status::Unknown;
                evidence.reason = Reason::ExplicitUnknown;
            }
            if evidence.status == Status::Accepted {
                let label = reading.choice(id).unwrap();
                let target = &mut partial.view.seats[seat as usize - 1];
                match field {
                    FieldName::Occupied => target.occupied = Some(label == "occupied"),
                    FieldName::Status => {
                        target.status = match label {
                            "active" => Some(SeatStatus::Active),
                            "folded" => Some(SeatStatus::Folded),
                            "all_in" => Some(SeatStatus::AllIn),
                            "sitting_out" => Some(SeatStatus::SittingOut),
                            _ => None,
                        }
                    }
                    FieldName::Badge => {
                        target.badge = match label {
                            "none" => Some(Badge::None),
                            "fold" => Some(Badge::Fold),
                            "check" => Some(Badge::Check),
                            "call" => Some(Badge::Call),
                            "bet" => Some(Badge::Bet),
                            "raise" => Some(Badge::Raise),
                            "all_in" => Some(Badge::AllIn),
                            "small_blind" => Some(Badge::SmallBlind),
                            "big_blind" => Some(Badge::BigBlind),
                            _ => None,
                        }
                    }
                    FieldName::Dealer => target.dealer = Some(label == "dealer_here"),
                    FieldName::SmallBlind => target.small_blind = Some(label == "small_blind_here"),
                    FieldName::BigBlind => target.big_blind = Some(label == "big_blind_here"),
                    FieldName::Acting => target.acting = Some(label == "yes"),
                    _ => unreachable!(),
                }
            }
            super::partial::record(
                &mut partial.evidence,
                field,
                Some(seat),
                None,
                evidence.status,
                evidence.reason,
            );
        }
        diagnostics.passes.push(crate::partial::PassDiagnostic {
            pass: pass.id.clone(),
            crop_bounds: vec![bounds],
            crop_dimensions: vec![[c.saturating_sub(a), d.saturating_sub(b)]],
            questions: SCENE_QUESTIONS
                .iter()
                .map(|(_, id, _, _)| {
                    let mut question = reading.diagnostic(id);
                    if question.status == Status::Accepted && reading.choice(id) == Some("unknown")
                    {
                        question.status = Status::Unknown;
                        question.reason = Reason::ExplicitUnknown;
                    }
                    question
                })
                .collect(),
            segments: None,
            total_ms: None,
        });
        partial.scene_sources[seat as usize - 1] = Some(entry.clone());
        for qualified in entry.capabilities() {
            if let Some(capability) = partial
                .view
                .capabilities
                .iter_mut()
                .find(|c| c.field == qualified.field && c.seat == qualified.seat)
            {
                *capability = qualified;
            }
        }
        if diagnostics.admission == DiagnosticAdmission::DecisionBudgetExpired {
            diagnostics.fields.clone_from(&partial.evidence);
            diagnostics.set_admission(DiagnosticAdmission::DecisionBudgetExpired, None);
            *candidate = None;
            return Ok(());
        }
    }
    reject_contradictions(partial);
    partial.view.refresh_verified_fields();
    diagnostics.fields.clone_from(&partial.evidence);
    Ok(())
}

fn reject(partial: &mut PartialObservation, seat: u8, field: FieldName) {
    clear_field(&mut partial.view.seats[seat as usize - 1], field);
    for evidence in partial
        .evidence
        .iter_mut()
        .filter(|f| f.field == field && f.seat == Some(seat))
    {
        *evidence = FieldEvidence {
            status: Status::Rejected,
            reason: Reason::SceneContradiction,
            admission_status: Status::Rejected,
            admission_reason: Reason::SceneContradiction,
            ..evidence.clone()
        };
    }
}

fn reject_contradictions(partial: &mut PartialObservation) {
    for seat in 1..=6 {
        let value = &partial.view.seats[seat as usize - 1];
        if value.occupied == Some(false) {
            let has_status = value.status.is_some();
            let has_badge = value.badge.is_some_and(|b| b != Badge::None);
            let acting = value.acting == Some(true);
            if has_status {
                reject(partial, seat, FieldName::Status);
            }
            if has_badge {
                reject(partial, seat, FieldName::Badge);
            }
            if acting {
                reject(partial, seat, FieldName::Acting);
            }
        }
    }
    for field in [
        FieldName::Dealer,
        FieldName::SmallBlind,
        FieldName::BigBlind,
        FieldName::Acting,
    ] {
        let positive: Vec<u8> = partial
            .view
            .seats
            .iter()
            .filter(|seat| match field {
                FieldName::Dealer => seat.dealer == Some(true),
                FieldName::SmallBlind => {
                    seat.small_blind == Some(true) || seat.badge == Some(Badge::SmallBlind)
                }
                FieldName::BigBlind => {
                    seat.big_blind == Some(true) || seat.badge == Some(Badge::BigBlind)
                }
                FieldName::Acting => seat.acting == Some(true),
                _ => false,
            })
            .map(|s| s.seat)
            .collect();
        if positive.len() > 1 {
            for seat in positive {
                let badge = partial.view.seats[seat as usize - 1].badge;
                reject(partial, seat, field);
                if (field == FieldName::SmallBlind && badge == Some(Badge::SmallBlind))
                    || (field == FieldName::BigBlind && badge == Some(Badge::BigBlind))
                {
                    reject(partial, seat, FieldName::Badge);
                }
            }
        }
    }
    for seat in 1..=6 {
        let value = &partial.view.seats[seat as usize - 1];
        if value.small_blind == Some(true) && value.big_blind == Some(true) {
            reject(partial, seat, FieldName::SmallBlind);
            reject(partial, seat, FieldName::BigBlind);
        }
        let value = &partial.view.seats[seat as usize - 1];
        if value.acting == Some(true)
            && matches!(
                value.status,
                Some(SeatStatus::Folded | SeatStatus::AllIn | SeatStatus::SittingOut)
            )
        {
            reject(partial, seat, FieldName::Acting);
        }
    }
}
