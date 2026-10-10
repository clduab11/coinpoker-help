//! Read-only field evidence, deliberately separate from actionable GameState.

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::capture::Frame;
use crate::parser::{Card, GamePhase};
use crate::runtime::ObservationRole;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FieldName {
    ScreenKind,
    TableLayout,
    Readable,
    Role,
    HeroSeated,
    GamePhase,
    BoardCount,
    BoardSlot,
    PotSize,
    Occupied,
    Status,
    DisplayedStack,
    VisibleWager,
    StreetContribution,
    Dealer,
    SmallBlind,
    BigBlind,
    Position,
    PositionGroup,
    Badge,
    Acting,
    OccupantEpoch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceStatus {
    Accepted,
    Unknown,
    Rejected,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum DiagnosticReason {
    Accepted,
    MissingAnswer,
    BelowFloor,
    Truncated,
    InvalidAnswer,
    InvalidFloor,
    DependencyUnknown,
    DependencyRejected,
    NonTable,
    LobbyGeometry,
    CropTooSmall,
    Unsupported,
    MissingSegments,
    EmptySegmentation,
    SegmentationOverflow,
    InvalidAmount,
    BoardPresenceUnknown,
    BoardNoncontiguous,
    BoardCountInvalid,
    PhaseBoardMismatch,
    DuplicateCard,
    RoleContradiction,
    PassUnavailable,
    AwaitingConsensus,
    UnknownRegion,
    UnapprovedCapability,
    InvalidCapability,
    IdentityMismatch,
    DecisionDeadline,
    SourceRegionChanged,
    MissingSourceWitness,
    ExplicitUnknown,
    SceneContradiction,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FieldEvidence {
    pub field: FieldName,
    pub seat: Option<u8>,
    pub board_slot: Option<u8>,
    pub status: EvidenceStatus,
    pub reason: DiagnosticReason,
    pub admission_status: EvidenceStatus,
    pub admission_reason: DiagnosticReason,
}

/// Closed public allowlist, not an arbitrary model-supplied string.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum VerifiedField {
    #[serde(rename = "role")]
    Role,
    #[serde(rename = "hero_seated")]
    HeroSeated,
    #[serde(rename = "game_phase")]
    GamePhase,
    #[serde(rename = "board_count")]
    BoardCount,
    #[serde(rename = "pot_size")]
    PotSize,
    #[serde(rename = "board_slots.1")]
    Board1,
    #[serde(rename = "board_slots.2")]
    Board2,
    #[serde(rename = "board_slots.3")]
    Board3,
    #[serde(rename = "board_slots.4")]
    Board4,
    #[serde(rename = "board_slots.5")]
    Board5,
    #[serde(rename = "seats.1.displayed_stack")]
    Stack1,
    #[serde(rename = "seats.2.displayed_stack")]
    Stack2,
    #[serde(rename = "seats.3.displayed_stack")]
    Stack3,
    #[serde(rename = "seats.4.displayed_stack")]
    Stack4,
    #[serde(rename = "seats.5.displayed_stack")]
    Stack5,
    #[serde(rename = "seats.6.displayed_stack")]
    Stack6,
    #[serde(rename = "seats.1.visible_wager")]
    Wager1,
    #[serde(rename = "seats.2.visible_wager")]
    Wager2,
    #[serde(rename = "seats.3.visible_wager")]
    Wager3,
    #[serde(rename = "seats.4.visible_wager")]
    Wager4,
    #[serde(rename = "seats.5.visible_wager")]
    Wager5,
    #[serde(rename = "seats.6.visible_wager")]
    Wager6,
    #[serde(rename = "seats.1.occupied")]
    Occupied1,
    #[serde(rename = "seats.1.status")]
    Status1,
    #[serde(rename = "seats.1.badge")]
    Badge1,
    #[serde(rename = "seats.1.dealer")]
    Dealer1,
    #[serde(rename = "seats.1.small_blind")]
    SmallBlind1,
    #[serde(rename = "seats.1.big_blind")]
    BigBlind1,
    #[serde(rename = "seats.1.acting")]
    Acting1,
    #[serde(rename = "seats.2.occupied")]
    Occupied2,
    #[serde(rename = "seats.2.status")]
    Status2,
    #[serde(rename = "seats.2.badge")]
    Badge2,
    #[serde(rename = "seats.2.dealer")]
    Dealer2,
    #[serde(rename = "seats.2.small_blind")]
    SmallBlind2,
    #[serde(rename = "seats.2.big_blind")]
    BigBlind2,
    #[serde(rename = "seats.2.acting")]
    Acting2,
    #[serde(rename = "seats.3.occupied")]
    Occupied3,
    #[serde(rename = "seats.3.status")]
    Status3,
    #[serde(rename = "seats.3.badge")]
    Badge3,
    #[serde(rename = "seats.3.dealer")]
    Dealer3,
    #[serde(rename = "seats.3.small_blind")]
    SmallBlind3,
    #[serde(rename = "seats.3.big_blind")]
    BigBlind3,
    #[serde(rename = "seats.3.acting")]
    Acting3,
    #[serde(rename = "seats.4.occupied")]
    Occupied4,
    #[serde(rename = "seats.4.status")]
    Status4,
    #[serde(rename = "seats.4.badge")]
    Badge4,
    #[serde(rename = "seats.4.dealer")]
    Dealer4,
    #[serde(rename = "seats.4.small_blind")]
    SmallBlind4,
    #[serde(rename = "seats.4.big_blind")]
    BigBlind4,
    #[serde(rename = "seats.4.acting")]
    Acting4,
    #[serde(rename = "seats.5.occupied")]
    Occupied5,
    #[serde(rename = "seats.5.status")]
    Status5,
    #[serde(rename = "seats.5.badge")]
    Badge5,
    #[serde(rename = "seats.5.dealer")]
    Dealer5,
    #[serde(rename = "seats.5.small_blind")]
    SmallBlind5,
    #[serde(rename = "seats.5.big_blind")]
    BigBlind5,
    #[serde(rename = "seats.5.acting")]
    Acting5,
    #[serde(rename = "seats.6.occupied")]
    Occupied6,
    #[serde(rename = "seats.6.status")]
    Status6,
    #[serde(rename = "seats.6.badge")]
    Badge6,
    #[serde(rename = "seats.6.dealer")]
    Dealer6,
    #[serde(rename = "seats.6.small_blind")]
    SmallBlind6,
    #[serde(rename = "seats.6.big_blind")]
    BigBlind6,
    #[serde(rename = "seats.6.acting")]
    Acting6,
}

pub const SCENE_VERIFIED_FIELDS: [[VerifiedField; 7]; 6] = [
    [
        VerifiedField::Occupied1,
        VerifiedField::Status1,
        VerifiedField::Badge1,
        VerifiedField::Dealer1,
        VerifiedField::SmallBlind1,
        VerifiedField::BigBlind1,
        VerifiedField::Acting1,
    ],
    [
        VerifiedField::Occupied2,
        VerifiedField::Status2,
        VerifiedField::Badge2,
        VerifiedField::Dealer2,
        VerifiedField::SmallBlind2,
        VerifiedField::BigBlind2,
        VerifiedField::Acting2,
    ],
    [
        VerifiedField::Occupied3,
        VerifiedField::Status3,
        VerifiedField::Badge3,
        VerifiedField::Dealer3,
        VerifiedField::SmallBlind3,
        VerifiedField::BigBlind3,
        VerifiedField::Acting3,
    ],
    [
        VerifiedField::Occupied4,
        VerifiedField::Status4,
        VerifiedField::Badge4,
        VerifiedField::Dealer4,
        VerifiedField::SmallBlind4,
        VerifiedField::BigBlind4,
        VerifiedField::Acting4,
    ],
    [
        VerifiedField::Occupied5,
        VerifiedField::Status5,
        VerifiedField::Badge5,
        VerifiedField::Dealer5,
        VerifiedField::SmallBlind5,
        VerifiedField::BigBlind5,
        VerifiedField::Acting5,
    ],
    [
        VerifiedField::Occupied6,
        VerifiedField::Status6,
        VerifiedField::Badge6,
        VerifiedField::Dealer6,
        VerifiedField::SmallBlind6,
        VerifiedField::BigBlind6,
        VerifiedField::Acting6,
    ],
];

pub const BOARD_FIELDS: [VerifiedField; 5] = [
    VerifiedField::Board1,
    VerifiedField::Board2,
    VerifiedField::Board3,
    VerifiedField::Board4,
    VerifiedField::Board5,
];
pub const STACK_FIELDS: [VerifiedField; 6] = [
    VerifiedField::Stack1,
    VerifiedField::Stack2,
    VerifiedField::Stack3,
    VerifiedField::Stack4,
    VerifiedField::Stack5,
    VerifiedField::Stack6,
];
pub const WAGER_FIELDS: [VerifiedField; 6] = [
    VerifiedField::Wager1,
    VerifiedField::Wager2,
    VerifiedField::Wager3,
    VerifiedField::Wager4,
    VerifiedField::Wager5,
    VerifiedField::Wager6,
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TrainingStatus {
    TrainedUnapproved,
    ReadOnlyApproved,
    Unsupported,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Capability {
    pub field: FieldName,
    pub seat: Option<u8>,
    pub training: TrainingStatus,
    pub acceptance_floor: Option<f64>,
    pub held_out_approved: bool,
    pub human_verified: bool,
    pub provenance: &'static str,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SeatStatus {
    Active,
    Folded,
    AllIn,
    SittingOut,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Position {
    Utg,
    Hj,
    Co,
    Btn,
    Sb,
    Bb,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PositionGroup {
    Early,
    Middle,
    Late,
    Blind,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Badge {
    None,
    Fold,
    Check,
    Call,
    Bet,
    Raise,
    AllIn,
    SmallBlind,
    BigBlind,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SeatView {
    /// Physical clockwise slot: top, upper right, lower right, bottom, lower left, upper left.
    pub seat: u8,
    pub occupied: Option<bool>,
    pub status: Option<SeatStatus>,
    pub displayed_stack: Option<u32>,
    pub visible_wager: Option<u32>,
    pub street_contribution: Option<u32>,
    pub dealer: Option<bool>,
    pub small_blind: Option<bool>,
    pub big_blind: Option<bool>,
    pub position: Option<Position>,
    pub position_group: Option<PositionGroup>,
    pub badge: Option<Badge>,
    pub acting: Option<bool>,
    pub occupant_epoch: Option<u64>,
}
impl SeatView {
    pub fn unknown(seat: u8) -> Self {
        Self {
            seat,
            occupied: None,
            status: None,
            displayed_stack: None,
            visible_wager: None,
            street_contribution: None,
            dealer: None,
            small_blind: None,
            big_blind: None,
            position: None,
            position_group: None,
            badge: None,
            acting: None,
            occupant_epoch: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PartialObservationView {
    pub role: Option<ObservationRole>,
    pub hero_seated: Option<bool>,
    pub game_phase: Option<GamePhase>,
    pub board_count: Option<u8>,
    pub board_slots: [Option<Card>; 5],
    pub pot_size: Option<u32>,
    pub seats: [SeatView; 6],
    pub verified_fields: Vec<VerifiedField>,
    pub capabilities: Vec<Capability>,
    pub quality_approved: bool,
}
impl Default for PartialObservationView {
    fn default() -> Self {
        Self {
            role: None,
            hero_seated: None,
            game_phase: None,
            board_count: None,
            board_slots: std::array::from_fn(|_| None),
            pot_size: None,
            seats: std::array::from_fn(|i| SeatView::unknown(i as u8 + 1)),
            verified_fields: Vec::new(),
            capabilities: capabilities(),
            quality_approved: false,
        }
    }
}
impl PartialObservationView {
    pub(crate) fn refresh_verified_fields(&mut self) {
        self.verified_fields.clear();
        for (known, field) in [
            (self.role.is_some(), VerifiedField::Role),
            (self.hero_seated.is_some(), VerifiedField::HeroSeated),
            (self.game_phase.is_some(), VerifiedField::GamePhase),
            (self.board_count.is_some(), VerifiedField::BoardCount),
            (self.pot_size.is_some(), VerifiedField::PotSize),
        ] {
            if known {
                self.verified_fields.push(field);
            }
        }
        for (slot, field) in self.board_slots.iter().zip(BOARD_FIELDS) {
            if slot.is_some() {
                self.verified_fields.push(field);
            }
        }
        for (seat, field) in self.seats.iter().zip(STACK_FIELDS) {
            if seat.displayed_stack.is_some() {
                self.verified_fields.push(field);
            }
        }
        for (seat, field) in self.seats.iter().zip(WAGER_FIELDS) {
            if seat.visible_wager.is_some() {
                self.verified_fields.push(field);
            }
        }
        for (seat, paths) in self.seats.iter().zip(SCENE_VERIFIED_FIELDS) {
            for (field, path) in crate::laya::scene::SCENE_FIELDS.into_iter().zip(paths) {
                if crate::laya::scene::field_known(seat, field) {
                    self.verified_fields.push(path);
                }
            }
        }
        self.quality_approved = false;
    }
}

pub fn capabilities() -> Vec<Capability> {
    let mut result = Vec::new();
    for (field, floor) in [
        (FieldName::Role, Some(0.995)),
        (FieldName::HeroSeated, Some(0.995)),
        (FieldName::GamePhase, Some(0.995)),
        (FieldName::BoardCount, Some(1.0)),
        (FieldName::BoardSlot, Some(1.0)),
        (FieldName::PotSize, Some(0.8)),
    ] {
        result.push(Capability {
            field,
            seat: None,
            training: TrainingStatus::TrainedUnapproved,
            acceptance_floor: floor,
            held_out_approved: false,
            human_verified: false,
            provenance: "it1-existing-pass",
        });
    }
    for seat in 1..=6 {
        result.push(Capability {
            field: FieldName::DisplayedStack,
            seat: Some(seat),
            training: TrainingStatus::TrainedUnapproved,
            acceptance_floor: Some(0.8),
            held_out_approved: false,
            human_verified: false,
            provenance: "it1-existing-pass",
        });
        for field in UNSUPPORTED_SEAT_FIELDS {
            result.push(Capability {
                field,
                seat: Some(seat),
                training: TrainingStatus::Unsupported,
                acceptance_floor: None,
                held_out_approved: false,
                human_verified: false,
                provenance: "observation-only-proposal",
            });
        }
    }
    result
}

pub const UNSUPPORTED_SEAT_FIELDS: [FieldName; 12] = [
    FieldName::Occupied,
    FieldName::Status,
    FieldName::VisibleWager,
    FieldName::StreetContribution,
    FieldName::Dealer,
    FieldName::SmallBlind,
    FieldName::BigBlind,
    FieldName::Position,
    FieldName::PositionGroup,
    FieldName::Badge,
    FieldName::Acting,
    FieldName::OccupantEpoch,
];

/// Internal candidate; it has no recommendation, player name or untyped payload.
#[derive(Debug, Clone, PartialEq)]
pub struct PartialObservation {
    pub view: PartialObservationView,
    pub evidence: Vec<FieldEvidence>,
    pub frame_width: u32,
    pub frame_height: u32,
    pub(crate) core_accepted: bool,
    pub(crate) wager_sources: [Option<crate::laya::wager::WagerPassConfig>; 6],
    pub(crate) scene_sources: [Option<crate::laya::scene::ScenePassConfig>; 6],
    pub(crate) source_witness: Option<SourceRegionWitnesses>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceWitnessError {
    InvalidFrame,
    GeometryMismatch,
    AlreadyBound,
}

// No Serialize implementation, pixels, names, frame clones or persisted identifiers.
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct SourceRegionWitnesses {
    p0: RegionWitness,
    board: [Option<RegionWitness>; 5],
    pot: Option<RegionWitness>,
    stacks: [Option<RegionWitness>; 6],
    wagers: [Option<RegionWitness>; 6],
    scenes: [Option<RegionWitness>; 6],
}
impl std::fmt::Debug for SourceRegionWitnesses {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("SourceRegionWitnesses(<in-memory>)")
    }
}
#[derive(Clone, PartialEq, Eq)]
struct RegionWitness {
    bounds: [u32; 4],
    digest: [u8; 32],
}

fn region_digest(frame: &Frame, bounds: [u32; 4]) -> Option<[u8; 32]> {
    if frame.validate().is_err() {
        return None;
    }
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
    let stride = frame.bytes_per_row();
    for row in b as usize..d as usize {
        hash.update(&frame.rgba[row * stride + a as usize * 4..row * stride + c as usize * 4]);
    }
    Some(hash.finalize().into())
}
fn region_witness(frame: &Frame, bounds: [u32; 4]) -> Option<RegionWitness> {
    Some(RegionWitness {
        bounds,
        digest: region_digest(frame, bounds)?,
    })
}
fn trained_region_witness(frame: &Frame, name: &str) -> Option<RegionWitness> {
    let (a, b, c, d) = crate::laya::geometry::region_px(name, frame.width, frame.height)?;
    region_witness(frame, [a, b, c, d])
}
fn region_matches(frame: &Frame, witness: Option<&RegionWitness>) -> Result<(), DiagnosticReason> {
    let witness = witness.ok_or(DiagnosticReason::MissingSourceWitness)?;
    if region_digest(frame, witness.bounds) == Some(witness.digest) {
        Ok(())
    } else {
        Err(DiagnosticReason::SourceRegionChanged)
    }
}

impl PartialObservation {
    pub fn core_accepted(&self) -> bool {
        self.core_accepted
    }

    /// Bind exactly once to the original analyzed Frame; offline score candidates are unbound.
    pub fn bind_source_frame(&mut self, frame: &Frame) -> Result<(), SourceWitnessError> {
        if self.source_witness.is_some() {
            return Err(SourceWitnessError::AlreadyBound);
        }
        if frame.validate().is_err() || frame.width == 0 || frame.height == 0 {
            return Err(SourceWitnessError::InvalidFrame);
        }
        if (frame.width, frame.height) != (self.frame_width, self.frame_height) {
            return Err(SourceWitnessError::GeometryMismatch);
        }
        self.source_witness = Some(SourceRegionWitnesses {
            p0: region_witness(frame, [0, 0, frame.width, frame.height])
                .ok_or(SourceWitnessError::InvalidFrame)?,
            board: std::array::from_fn(|i| {
                trained_region_witness(frame, &format!("board_slot_{}", i + 1))
            }),
            pot: trained_region_witness(frame, "pot"),
            stacks: std::array::from_fn(|i| {
                trained_region_witness(frame, &format!("seat_{}_stack", i + 1))
            }),
            wagers: std::array::from_fn(|i| {
                self.wager_sources[i]
                    .as_ref()
                    .and_then(|source| source.crop_bounds(frame.width, frame.height))
                    .and_then(|bounds| region_witness(frame, bounds))
            }),
            scenes: std::array::from_fn(|i| {
                self.scene_sources[i]
                    .as_ref()
                    .and_then(|source| source.crop_bounds(frame.width, frame.height))
                    .and_then(|bounds| region_witness(frame, bounds))
            }),
        });
        Ok(())
    }

    /// Compare with an ALREADY captured frame. This never replaces the original witness or TTL.
    /// True means the frame/witness binding exists, not that every individual field survived.
    pub fn retain_source_current_fields(&mut self, latest: &Frame) -> bool {
        let Some(proof) = self.source_witness.as_ref().filter(|_| {
            latest.validate().is_ok()
                && (latest.width, latest.height) == (self.frame_width, self.frame_height)
        }) else {
            self.view.role = None;
            self.view.hero_seated = None;
            self.view.game_phase = None;
            self.view.board_count = None;
            self.view.board_slots = std::array::from_fn(|_| None);
            self.view.pot_size = None;
            self.view.seats = std::array::from_fn(|i| SeatView::unknown(i as u8 + 1));
            for field in &mut self.evidence {
                field.admission_status = EvidenceStatus::Rejected;
                field.admission_reason = DiagnosticReason::MissingSourceWitness;
            }
            self.view.refresh_verified_fields();
            return false;
        };
        let mut failed = Vec::new();
        if let Err(reason) = region_matches(latest, Some(&proof.p0)) {
            for field in [FieldName::Role, FieldName::HeroSeated, FieldName::GamePhase] {
                failed.push((field, None, reason));
            }
        }
        if let Some(reason) = proof
            .board
            .iter()
            .find_map(|witness| region_matches(latest, witness.as_ref()).err())
        {
            for field in [
                FieldName::BoardSlot,
                FieldName::BoardCount,
                FieldName::GamePhase,
            ] {
                failed.push((field, None, reason));
            }
        }
        if self.view.pot_size.is_some() {
            if let Err(reason) = region_matches(latest, proof.pot.as_ref()) {
                failed.push((FieldName::PotSize, None, reason));
            }
        }
        for i in 0..6 {
            for (field, value, witness) in [
                (
                    FieldName::DisplayedStack,
                    self.view.seats[i].displayed_stack,
                    proof.stacks[i].as_ref(),
                ),
                (
                    FieldName::VisibleWager,
                    self.view.seats[i].visible_wager,
                    proof.wagers[i].as_ref(),
                ),
            ] {
                if value.is_some() {
                    if let Err(reason) = region_matches(latest, witness) {
                        failed.push((field, Some(i as u8 + 1), reason));
                    }
                }
            }
            if crate::laya::scene::SCENE_FIELDS
                .iter()
                .any(|field| crate::laya::scene::field_known(&self.view.seats[i], *field))
            {
                if let Err(reason) = region_matches(latest, proof.scenes[i].as_ref()) {
                    for field in crate::laya::scene::SCENE_FIELDS {
                        failed.push((field, Some(i as u8 + 1), reason));
                    }
                }
            }
        }
        for (field, seat, reason) in failed {
            match field {
                FieldName::Role => self.view.role = None,
                FieldName::HeroSeated => self.view.hero_seated = None,
                FieldName::GamePhase => self.view.game_phase = None,
                FieldName::BoardCount => self.view.board_count = None,
                FieldName::BoardSlot => self.view.board_slots = std::array::from_fn(|_| None),
                FieldName::PotSize => self.view.pot_size = None,
                FieldName::DisplayedStack => {
                    self.view.seats[seat.unwrap() as usize - 1].displayed_stack = None
                }
                FieldName::VisibleWager => {
                    self.view.seats[seat.unwrap() as usize - 1].visible_wager = None
                }
                field if crate::laya::scene::SCENE_FIELDS.contains(&field) => {
                    crate::laya::scene::clear_field(
                        &mut self.view.seats[seat.unwrap() as usize - 1],
                        field,
                    );
                }
                _ => unreachable!(),
            }
            for evidence in self
                .evidence
                .iter_mut()
                .filter(|e| e.field == field && e.seat == seat)
            {
                evidence.admission_status = EvidenceStatus::Rejected;
                evidence.admission_reason = reason;
            }
        }
        self.view.refresh_verified_fields();
        true
    }

    /// Emit only values present in BOTH reads, always from the current read.
    /// Amount agreement never requires whole-state/card/role agreement.
    pub(crate) fn consensus(&self, previous: &Self) -> PartialObservationView {
        let mut value = self.view.clone();
        if value.role != previous.view.role {
            value.role = None;
        }
        if value.hero_seated != previous.view.hero_seated {
            value.hero_seated = None;
        }
        if value.pot_size != previous.view.pot_size {
            value.pot_size = None;
        }
        let same_board_context = value.board_count == previous.view.board_count
            && value.game_phase == previous.view.game_phase;
        if value.board_count != previous.view.board_count {
            value.board_count = None;
        }
        if value.game_phase != previous.view.game_phase {
            value.game_phase = None;
        }
        for i in 0..5 {
            if !same_board_context || value.board_slots[i] != previous.view.board_slots[i] {
                value.board_slots[i] = None;
            }
        }
        for i in 0..6 {
            let stack = value.seats[i].displayed_stack;
            let wager = value.seats[i].visible_wager;
            // Rebuild unsupported fields rather than trusting a manually populated candidate.
            value.seats[i] = SeatView::unknown(i as u8 + 1);
            if stack == previous.view.seats[i].displayed_stack {
                value.seats[i].displayed_stack = stack;
            }
            if wager == previous.view.seats[i].visible_wager
                && self.wager_sources[i]
                    .as_ref()
                    .is_some_and(|s| s.qualification().is_ok())
                && self.wager_sources[i] == previous.wager_sources[i]
            {
                value.seats[i].visible_wager = wager;
            }
            if self.scene_sources[i]
                .as_ref()
                .is_some_and(|s| s.qualification().is_ok())
                && self.scene_sources[i] == previous.scene_sources[i]
            {
                crate::laya::scene::retain_agreement(
                    &mut value.seats[i],
                    &self.view.seats[i],
                    &previous.view.seats[i],
                );
                for field in crate::laya::scene::SCENE_FIELDS {
                    if ![self, previous].iter().all(|candidate| {
                        candidate.evidence.iter().any(|e| {
                            e.field == field
                                && e.seat == Some(i as u8 + 1)
                                && e.status == EvidenceStatus::Accepted
                        })
                    }) {
                        crate::laya::scene::clear_field(&mut value.seats[i], field);
                    }
                }
            }
        }
        value.capabilities = capabilities();
        for source in self.wager_sources.iter().flatten() {
            if let Some(qualified) = source.capability() {
                if let Some(capability) = value
                    .capabilities
                    .iter_mut()
                    .find(|c| c.field == qualified.field && c.seat == qualified.seat)
                {
                    *capability = qualified;
                }
            }
        }
        for source in self.scene_sources.iter().flatten() {
            for qualified in source.capabilities() {
                if let Some(capability) = value
                    .capabilities
                    .iter_mut()
                    .find(|c| c.field == qualified.field && c.seat == qualified.seat)
                {
                    *capability = qualified;
                }
            }
        }
        value.refresh_verified_fields();
        value
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum SafeAnswer {
    Choice(String),
    Noul(bool),
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct QuestionDiagnostic {
    pub question: String,
    /// Choice labels are copied only after validation against the question's vocabulary.
    pub answer: Option<SafeAnswer>,
    pub score: Option<f64>,
    pub effective_floor: Option<f64>,
    pub status: EvidenceStatus,
    pub reason: DiagnosticReason,
    pub truncated: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PassDiagnostic {
    pub pass: String,
    pub crop_bounds: Vec<[u32; 4]>,
    pub crop_dimensions: Vec<[u32; 2]>,
    pub questions: Vec<QuestionDiagnostic>,
    pub segments: Option<SegmentDiagnostic>,
    /// Measured wall time for this pass including crop/encode/transport when applicable.
    pub total_ms: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct SegmentDiagnostic {
    pub n: u32,
    pub overflow: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct PerceptionTiming {
    pub capture_ms: Option<f64>,
    pub preprocess_ms: Option<f64>,
    pub encode_ms: Option<f64>,
    pub queue_ms: Option<f64>,
    pub inference_ms: Option<f64>,
    pub assembly_ms: Option<f64>,
    pub publish_ms: Option<f64>,
    pub render_ms: Option<f64>,
}

/// Private event only. Public PartialObservationView deliberately omits these fields.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct PerceptionDiagnostics {
    pub source_current: bool,
    pub admission: DiagnosticAdmission,
    pub frame_width: u32,
    pub frame_height: u32,
    pub passes: Vec<PassDiagnostic>,
    pub fields: Vec<FieldEvidence>,
    pub timing: PerceptionTiming,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DiagnosticAdmission {
    #[default]
    Candidate,
    SourceCurrent,
    ObsoleteObservation,
    ObservationExpired,
    DecisionBudgetExpired,
}

impl PerceptionDiagnostics {
    pub(crate) fn set_admission(
        &mut self,
        admission: DiagnosticAdmission,
        view: Option<&PartialObservationView>,
    ) {
        self.admission = admission;
        self.source_current = admission == DiagnosticAdmission::SourceCurrent;
        for field in &mut self.fields {
            let accepted = view.is_some_and(|v| match field.field {
                FieldName::ScreenKind | FieldName::TableLayout | FieldName::Readable => true,
                FieldName::Role => v.role.is_some(),
                FieldName::HeroSeated => v.hero_seated.is_some(),
                FieldName::GamePhase => v.game_phase.is_some(),
                FieldName::BoardCount => v.board_count.is_some(),
                FieldName::PotSize => v.pot_size.is_some(),
                FieldName::DisplayedStack => field
                    .seat
                    .and_then(|s| v.seats.get(s as usize - 1))
                    .is_some_and(|s| s.displayed_stack.is_some()),
                FieldName::VisibleWager => field
                    .seat
                    .and_then(|s| v.seats.get(s as usize - 1))
                    .is_some_and(|s| s.visible_wager.is_some()),
                FieldName::BoardSlot => field
                    .board_slot
                    .and_then(|s| v.board_slots.get(s as usize - 1))
                    .is_some_and(Option::is_some),
                family if crate::laya::scene::SCENE_FIELDS.contains(&family) => field
                    .seat
                    .and_then(|s| v.seats.get(s as usize - 1))
                    .is_some_and(|s| crate::laya::scene::field_known(s, family)),
                _ => false,
            });
            if !self.source_current {
                field.admission_status = EvidenceStatus::Rejected;
                // Source reasons are in the enclosing typed admission metadata.
                field.admission_reason = DiagnosticReason::DependencyRejected;
            } else if accepted && field.status == EvidenceStatus::Accepted {
                field.admission_status = EvidenceStatus::Accepted;
                field.admission_reason = DiagnosticReason::Accepted;
            }
        }
    }
}

/// Versioned observation-only proposal, NEVER a trained/requestable pass manifest.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ProposedCrop {
    pub seat: u8,
    pub field: FieldName,
    pub reference_dimensions: Option<[u32; 2]>,
    pub bounds: Option<[u32; 4]>,
    pub training: TrainingStatus,
    pub acceptance_floor: Option<f64>,
}

pub fn proposed_seat_crops() -> Vec<ProposedCrop> {
    // Stage-1 pixel measurements; slot 1 has no confirmed positive individual wager.
    let wagers = [
        None,
        Some(([879, 670], [617, 218, 674, 250])),
        Some(([879, 670], [635, 427, 692, 455])),
        Some(([879, 670], [488, 450, 541, 479])),
        Some(([900, 686], [189, 440, 250, 465])),
        Some(([879, 670], [208, 222, 262, 250])),
    ];
    let mut result = Vec::new();
    for (i, wager) in wagers.into_iter().enumerate() {
        for field in [
            FieldName::VisibleWager,
            FieldName::Occupied,
            FieldName::Status,
            FieldName::Dealer,
            FieldName::SmallBlind,
            FieldName::BigBlind,
            FieldName::Badge,
            FieldName::Acting,
        ] {
            let measured = (field == FieldName::VisibleWager)
                .then_some(wager)
                .flatten();
            result.push(ProposedCrop {
                seat: i as u8 + 1,
                field,
                reference_dimensions: measured.map(|(size, _)| size),
                bounds: measured.map(|(_, bounds)| bounds),
                training: TrainingStatus::Unsupported,
                acceptance_floor: None,
            });
        }
    }
    result
}
