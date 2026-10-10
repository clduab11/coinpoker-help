//! Pure watched-history infrastructure, independent of hero cards and advice.
//!
//! Callers must validate the source, freshness, field evidence and physical seat
//! mapping before asserting trust. Sequence continuity alone is not proof that a
//! sampled source saw every action. The current real model is not validated for
//! this contract. No names, pixels, persistence, ranges or classifier admission
//! belong here. Counts are observed lower bounds, not complete hand histories.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::classifier::Archetype;

pub const MAX_EVENT_VIEW: usize = 200;
pub const MAX_SESSION_EVENTS: usize = 10_000;
pub const PHYSICAL_SEATS: usize = 6;

/// Locally assigned, nonzero opaque identifier. Never derive it from a name.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Id(pub u64);

/// Unknown is the default. `trusted` asserts validated, source-current evidence;
/// confidence is descriptive, never a substitute for capability approval.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, bound(deserialize = "T: Deserialize<'de>"))]
pub struct Evidence<T> {
    pub value: Option<T>,
    pub trusted: bool,
    pub confidence: Option<f64>,
}

impl<T> Default for Evidence<T> {
    fn default() -> Self {
        Self {
            value: None,
            trusted: false,
            confidence: None,
        }
    }
}

impl<T> Evidence<T> {
    pub fn trusted(value: T) -> Self {
        Self {
            value: Some(value),
            trusted: true,
            confidence: None,
        }
    }

    pub fn known(&self) -> Option<&T> {
        self.valid().then_some(self.value.as_ref()).flatten()
    }

    fn valid(&self) -> bool {
        self.trusted
            && self
                .confidence
                .is_none_or(|v| v.is_finite() && (0.0..=1.0).contains(&v))
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Capture {
    pub session_id: Id,
    pub table_id: Id,
    /// Strictly increasing within a capture session, including target changes.
    pub sequence: u64,
    /// Monotonic milliseconds in this capture session, not wall-clock time.
    pub captured_at_ms: u64,
    pub ticket: Id,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Street {
    Preflop,
    Flop,
    Turn,
    River,
    Showdown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HandStart {
    /// A validated readable hand ID or corroborated deal, before voluntary play.
    BeforeActions,
    Partial,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionKind {
    Fold,
    Check,
    Call,
    Bet,
    Raise,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ForcedAction {
    Voluntary,
    SmallBlind,
    BigBlind,
    Ante,
    Straddle,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChipMovement {
    Refund,
    TopUp,
    Payout,
    PotCollection,
    Ambiguous,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ActionBadge {
    /// Stable through persistence/flicker; a renewed identical action gets a NEW
    /// ID. IDs are unique per occupant and hand, not hashes of badge text.
    pub occurrence: Id,
    /// Trusted one-based action order in the hand, INCLUDING forced actions.
    /// Omission is not an inferred seat order or a complete aggressive prefix.
    pub action_sequence: Evidence<u64>,
    pub kind: Evidence<ActionKind>,
    pub all_in: Evidence<bool>,
    pub full_raise: Evidence<bool>,
    pub forced: Evidence<ForcedAction>,
    /// Incremental amount in caller-validated, consistent integer chip units.
    pub amount: Evidence<u64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "state", content = "action", rename_all = "snake_case")]
pub enum Badge {
    Clear,
    Action(ActionBadge),
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct SeatSnapshot {
    /// Physical slot 0..5, NEVER an index into an OCR player vector.
    pub seat: u8,
    /// trusted + null means verified empty; untrusted means identity unknown.
    pub occupant_id: Evidence<Id>,
    /// Eligibility must be established at the trusted start of preflop.
    pub dealt_in: Evidence<bool>,
    pub badge: Evidence<Badge>,
    pub stack: Evidence<u64>,
    pub commitment: Evidence<u64>,
    pub movement: Evidence<ChipMovement>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Snapshot {
    pub capture: Capture,
    pub quality_approved: bool,
    /// A caller-assigned opaque ID backed by a validated hand boundary. Board
    /// disappearance, payout and commitment clearing alone cannot establish it.
    pub hand_id: Evidence<Id>,
    pub street: Evidence<Street>,
    pub hand_start: Evidence<HandStart>,
    /// True asserts all intervening transitions were accounted for. Multiple
    /// newly changed badges are still ambiguous here, regardless of seat order.
    pub ordered: Evidence<bool>,
    /// Corroborated end of preflop, not merely an empty/changed board.
    pub preflop_complete: Evidence<bool>,
    pub seats: Vec<SeatSnapshot>,
    /// Current highest street commitment and last FULL raise increment. These
    /// establish the next snapshot's prior wager, not this snapshot's action.
    pub wager: Evidence<u64>,
    pub full_raise_increment: Evidence<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GapReason {
    UnvalidatedSource,
    MissingEvidence,
    InvalidSnapshot,
    CaptureSequence,
    ConflictingCapture,
    CaptureTime,
    IdentityChanged,
    UnknownIdentity,
    UnknownHand,
    HandIdentityReused,
    PartialHand,
    OrderAmbiguous,
    SimultaneousActions,
    ActionSequence,
    UnknownAction,
    ContradictoryEvidence,
    ChipMovement,
    StreetTransition,
    EventLimit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionBasis {
    Badge,
    Commitment,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionRecord {
    pub seat: u8,
    pub occupant_id: Id,
    pub occurrence: Id,
    pub action_sequence: Option<u64>,
    pub kind: Option<ActionKind>,
    pub all_in: Option<bool>,
    pub full_raise: Option<bool>,
    pub forced: Option<ForcedAction>,
    pub amount: Option<u64>,
    pub stack: Option<u64>,
    pub commitment: Option<u64>,
    pub trusted: bool,
    pub kind_confidence: Option<f64>,
    pub basis: ActionBasis,
    /// 2 = opening preflop aggression; 3/4 require the whole ordered FULL
    /// aggressive prefix. Short raises have no ordinal and break that prefix.
    pub preflop_raise_ordinal: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum LedgerEntry {
    HandStarted {
        partial: bool,
    },
    Action {
        action: ActionRecord,
    },
    Gap {
        reason: GapReason,
    },
    Movement {
        seat: u8,
        occupant_id: Id,
        movement: ChipMovement,
    },
    HandOutcome {
        seat: u8,
        occupant_id: Id,
        vpip: bool,
        pfr: bool,
    },
    RecordingStopped {
        reason: GapReason,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LedgerEvent {
    pub event_sequence: u64,
    pub capture: Capture,
    pub hand_id: Option<Id>,
    pub street: Option<Street>,
    #[serde(flatten)]
    pub entry: LedgerEntry,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Limits {
    pub event_view: usize,
    pub session_events: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            event_view: MAX_EVENT_VIEW,
            session_events: MAX_SESSION_EVENTS,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct ActionCounts {
    pub folds: u64,
    pub checks: u64,
    pub calls: u64,
    pub bets: u64,
    pub raises: u64,
    pub all_ins: u64,
    pub incomplete_raises: u64,
    pub three_bets: u64,
    pub four_bets: u64,
}

impl ActionCounts {
    fn add(&mut self, action: &ActionRecord) {
        if !action.trusted || action.forced != Some(ForcedAction::Voluntary) {
            return;
        }
        match action.kind {
            Some(ActionKind::Fold) => self.folds += 1,
            Some(ActionKind::Check) => self.checks += 1,
            Some(ActionKind::Call) => self.calls += 1,
            Some(ActionKind::Bet) => self.bets += 1,
            Some(ActionKind::Raise) => self.raises += 1,
            None => return,
        }
        if action.all_in == Some(true) {
            self.all_ins += 1;
        }
        if action.full_raise == Some(false)
            && matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise))
        {
            self.incomplete_raises += 1;
        }
        if action.preflop_raise_ordinal == Some(3) {
            self.three_bets += 1;
        }
        if action.preflop_raise_ordinal == Some(4) {
            self.four_bets += 1;
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OccupantSummary {
    pub seat: u8,
    pub occupant_id: Id,
    pub actions: ActionCounts,
    pub eligible_hands: u64,
    pub vpip_hands: u64,
    pub pfr_hands: u64,
    pub vpip: Option<f64>,
    pub pfr: Option<f64>,
    /// Infrastructure never grants admission to history-conditioned advice.
    pub profile: Archetype,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Coverage {
    pub complete: bool,
    pub ordered_prefix: bool,
    pub recording: bool,
    pub accepted_captures: u64,
    pub unvalidated_captures: u64,
    pub partial_hands: u64,
    pub event_limit: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Summary {
    pub session_id: Option<Id>,
    pub table_id: Option<Id>,
    pub hand_id: Option<Id>,
    pub counts: ActionCounts,
    pub gaps: u64,
    pub coverage: Coverage,
    /// Only the current table's physical occupants, not an unbounded profile list.
    pub occupants: Vec<OccupantSummary>,
    pub events: Vec<LedgerEvent>,
}

#[derive(Debug, Clone, Default)]
struct Stats {
    actions: ActionCounts,
    hands: u64,
    vpip: u64,
    pfr: u64,
}

#[derive(Debug, Clone)]
struct SeatState {
    occupant: Id,
    dealt_in: Option<bool>,
    stack: Option<u64>,
    commitment: Option<u64>,
    eligible: bool,
    voluntary: bool,
    raised: bool,
    settled: bool,
}

type OccupantKey = (Id, Id, Id);
type HandKey = (Id, Id, Id);
type BadgeKey = (Id, Id, Id, Id, Id);

/// In-memory prefix-preserving ledger. A disk writer has its own byte limit.
/// Create a new instance for a new recording; session/target changes inside an
/// instance retain evidence but never merge occupant identities across scopes.
pub struct Observer {
    limits: Limits,
    ledger: Vec<LedgerEvent>,
    captures: BTreeMap<Id, Capture>,
    last_rejected: Option<Capture>,
    current: Option<Capture>,
    hand: Option<Id>,
    street: Option<Street>,
    hands: BTreeSet<HandKey>,
    badges: BTreeMap<BadgeKey, usize>,
    stats: BTreeMap<OccupantKey, Stats>,
    seats: [Option<SeatState>; PHYSICAL_SEATS],
    ordered: bool,
    aggressive_prefix: bool,
    next_action: u64,
    aggressions: u32,
    wager: Option<u64>,
    full_increment: Option<u64>,
    counts: ActionCounts,
    gaps: u64,
    complete: bool,
    recording: bool,
    accepted_captures: u64,
    unvalidated_captures: u64,
    partial_hands: u64,
}

impl Default for Observer {
    fn default() -> Self {
        Self::new(Limits::default())
    }
}

impl Observer {
    pub fn new(limits: Limits) -> Self {
        Self {
            limits: Limits {
                event_view: limits.event_view.min(MAX_EVENT_VIEW),
                session_events: limits.session_events.clamp(1, MAX_SESSION_EVENTS),
            },
            ledger: Vec::new(),
            captures: BTreeMap::new(),
            last_rejected: None,
            current: None,
            hand: None,
            street: None,
            hands: BTreeSet::new(),
            badges: BTreeMap::new(),
            stats: BTreeMap::new(),
            seats: std::array::from_fn(|_| None),
            ordered: false,
            aggressive_prefix: false,
            next_action: 1,
            aggressions: 0,
            wager: None,
            full_increment: None,
            counts: ActionCounts::default(),
            gaps: 0,
            complete: true,
            recording: true,
            accepted_captures: 0,
            unvalidated_captures: 0,
            partial_hands: 0,
        }
    }

    /// Full bounded recorded prefix, suitable for an independent private writer.
    pub fn events(&self) -> &[LedgerEvent] {
        &self.ledger
    }

    /// Explicit integration path when capture/quality/seat/action evidence is
    /// unavailable. It consumes the capture sequence just like `observe`.
    pub fn record_gap(&mut self, capture: Capture, reason: GapReason) -> Vec<LedgerEvent> {
        let start = self.ledger.len();
        if self.admit_capture(capture) {
            if reason == GapReason::UnvalidatedSource {
                self.unvalidated_captures += 1;
            }
            self.gap(capture, reason);
        }
        self.ledger[start..].to_vec()
    }

    /// Returns only newly recorded events. Repeated/older captures are no-ops;
    /// quality approval defaults false even if every field claims high confidence.
    pub fn observe(&mut self, snapshot: &Snapshot) -> Vec<LedgerEvent> {
        let start = self.ledger.len();
        self.observe_snapshot(snapshot);
        self.ledger[start..].to_vec()
    }

    fn observe_snapshot(&mut self, snapshot: &Snapshot) {
        let capture = snapshot.capture;
        if !self.admit_capture(capture) {
            return;
        }
        if !snapshot.quality_approved {
            self.unvalidated_captures += 1;
            self.gap(capture, GapReason::UnvalidatedSource);
            return;
        }
        let mut physical = [None; PHYSICAL_SEATS];
        let mut occupants = BTreeSet::new();
        if snapshot.seats.len() > PHYSICAL_SEATS {
            self.gap(capture, GapReason::InvalidSnapshot);
            return;
        }
        for seat in &snapshot.seats {
            let index = usize::from(seat.seat);
            if index >= PHYSICAL_SEATS
                || physical[index].is_some()
                || seat
                    .occupant_id
                    .known()
                    .is_some_and(|id| id.0 == 0 || !occupants.insert(*id))
                || (seat.occupant_id.valid()
                    && seat.occupant_id.value.is_none()
                    && (seat.dealt_in.known() == Some(&true)
                        || matches!(seat.badge.known(), Some(Badge::Action(_)))))
            {
                self.gap(capture, GapReason::InvalidSnapshot);
                return;
            }
            physical[index] = Some(seat);
        }
        let (Some(hand), Some(street)) = (
            snapshot.hand_id.known().copied().filter(|id| id.0 != 0),
            snapshot.street.known().copied(),
        ) else {
            self.gap(capture, GapReason::UnknownHand);
            return;
        };

        let new_hand = self.hand != Some(hand);
        let roster_known = physical.iter().all(|seat| {
            seat.is_some_and(|seat| {
                seat.occupant_id.valid()
                    && (seat.occupant_id.value.is_none() || seat.dealt_in.known().is_some())
            })
        });
        if new_hand {
            let key = (capture.session_id, capture.table_id, hand);
            if self.hands.contains(&key) {
                self.gap(capture, GapReason::HandIdentityReused);
                return;
            }
            let before_actions = snapshot.hand_start.known() == Some(&HandStart::BeforeActions)
                && street == Street::Preflop
                && snapshot.ordered.known() == Some(&true)
                && roster_known
                && snapshot.seats.iter().all(|seat| match seat.badge.known() {
                    Some(Badge::Clear) => true,
                    Some(Badge::Action(action)) => action
                        .forced
                        .known()
                        .is_some_and(|forced| *forced != ForcedAction::Voluntary),
                    None => seat.occupant_id.valid() && seat.occupant_id.value.is_none(),
                });
            self.hand = Some(hand);
            self.street = Some(street);
            self.seats = std::array::from_fn(|_| None);
            self.ordered = before_actions;
            self.aggressive_prefix = before_actions;
            self.next_action = 1;
            self.aggressions = 0;
            self.wager = snapshot.wager.known().copied();
            self.full_increment = snapshot
                .full_raise_increment
                .known()
                .copied()
                .filter(|v| *v != 0);
            if !self.append(
                capture,
                LedgerEntry::HandStarted {
                    partial: !before_actions,
                },
            ) {
                return;
            }
            self.hands.insert(key);
            if !before_actions {
                self.partial_hands += 1;
                self.gap(capture, GapReason::PartialHand);
            }
        }
        if !roster_known {
            self.gap(capture, GapReason::MissingEvidence);
        }
        if snapshot.ordered.known() != Some(&true) {
            self.gap(capture, GapReason::OrderAmbiguous);
        }
        if !self.recording {
            return;
        }

        let mut changed = Vec::new();
        for (index, seat) in physical.iter().enumerate() {
            let Some(seat) = seat else {
                if self.seats[index].is_some() {
                    self.gap(capture, GapReason::UnknownIdentity);
                }
                self.seats[index] = None;
                continue;
            };
            if !seat.occupant_id.valid() {
                self.gap(capture, GapReason::UnknownIdentity);
                self.seats[index] = None;
                continue;
            }
            let Some(occupant) = seat.occupant_id.known().copied() else {
                if self.seats[index].is_some() {
                    self.gap(capture, GapReason::IdentityChanged);
                }
                self.seats[index] = None;
                continue;
            };
            if self.seats[index]
                .as_ref()
                .is_some_and(|s| s.occupant != occupant)
            {
                self.gap(capture, GapReason::IdentityChanged);
                self.seats[index] = None;
            }
            if self.seats[index].is_none() {
                // A replacement/mid-hand arrival never inherits the old seat's
                // hand eligibility, even when its numeric slot is unchanged.
                if !new_hand {
                    self.gap(capture, GapReason::IdentityChanged);
                }
                self.seats[index] = Some(SeatState {
                    occupant,
                    dealt_in: seat.dealt_in.known().copied(),
                    stack: None,
                    commitment: None,
                    eligible: new_hand && self.ordered && seat.dealt_in.known() == Some(&true),
                    voluntary: false,
                    raised: false,
                    settled: false,
                });
            }
            if self.seats[index]
                .as_ref()
                .and_then(|state| state.dealt_in)
                .zip(seat.dealt_in.known().copied())
                .is_some_and(|(old, now)| old != now)
            {
                self.gap(capture, GapReason::ContradictoryEvidence);
            }
            match seat.badge.known() {
                Some(Badge::Action(badge)) if badge.occurrence.0 != 0 => {
                    let key = (
                        capture.session_id,
                        capture.table_id,
                        hand,
                        occupant,
                        badge.occurrence,
                    );
                    if let Some(event_index) = self.badges.get(&key) {
                        let LedgerEntry::Action { action: previous } =
                            &self.ledger[*event_index].entry
                        else {
                            unreachable!("badge indices reference recorded actions")
                        };
                        let changed_evidence = previous
                            .action_sequence
                            .zip(badge.action_sequence.known().copied())
                            .is_some_and(|(old, now)| old != now)
                            || previous
                                .kind
                                .zip(badge.kind.known().copied())
                                .is_some_and(|(old, now)| old != now)
                            || previous
                                .forced
                                .zip(badge.forced.known().copied())
                                .is_some_and(|(old, now)| old != now)
                            || previous
                                .full_raise
                                .zip(badge.full_raise.known().copied())
                                .is_some_and(|(old, now)| old != now)
                            || previous
                                .all_in
                                .zip(badge.all_in.known().copied())
                                .is_some_and(|(old, now)| old != now);
                        if changed_evidence {
                            self.gap(capture, GapReason::ContradictoryEvidence);
                        }
                    } else {
                        changed.push((index, *seat, badge));
                    }
                }
                Some(Badge::Clear) => {}
                _ => self.gap(capture, GapReason::UnknownAction),
            }
        }
        if changed.len() > 1 {
            self.gap(capture, GapReason::SimultaneousActions);
        }
        let single_change = changed.len() == 1;

        let previous_street = self.street;
        let street_changed = previous_street != Some(street);
        if !new_hand
            && !street_changed
            && changed.is_empty()
            && self
                .wager
                .zip(snapshot.wager.known().copied())
                .is_some_and(|(old, now)| old != now)
        {
            self.gap(capture, GapReason::ChipMovement);
        }
        if street_changed {
            let sequential = matches!(
                (previous_street, street),
                (Some(Street::Preflop), Street::Flop)
                    | (Some(Street::Flop), Street::Turn)
                    | (Some(Street::Turn), Street::River)
                    | (Some(Street::River), Street::Showdown)
            );
            if !sequential || !changed.is_empty() {
                self.gap(capture, GapReason::StreetTransition);
            }
            if previous_street == Some(Street::Preflop) {
                if snapshot.preflop_complete.known() != Some(&true) {
                    self.gap(capture, GapReason::MissingEvidence);
                }
            }
        }

        for (index, seat) in physical.iter().enumerate() {
            let Some(seat) = seat else {
                continue;
            };
            let Some(previous) = self.seats[index].as_ref().cloned() else {
                continue;
            };
            let has_new_badge = changed.iter().any(|(i, _, _)| *i == index);
            let stack = seat.stack.known().copied();
            let commitment = seat.commitment.known().copied();
            let unexpected_delta = !new_hand
                && (stack
                    .zip(previous.stack)
                    .is_some_and(|(now, old)| now > old || (now < old && !has_new_badge))
                    || (!street_changed
                        && commitment
                            .zip(previous.commitment)
                            .is_some_and(|(now, old)| now < old || (now > old && !has_new_badge))));
            if let Some(movement) = seat
                .movement
                .known()
                .copied()
                .or(unexpected_delta.then_some(ChipMovement::Ambiguous))
            {
                if self.append(
                    capture,
                    LedgerEntry::Movement {
                        seat: index as u8,
                        occupant_id: previous.occupant,
                        movement,
                    },
                ) {
                    self.gap(capture, GapReason::ChipMovement);
                }
            }
        }
        if street_changed {
            if previous_street == Some(Street::Preflop)
                && snapshot.preflop_complete.known() == Some(&true)
            {
                self.settle_all(capture);
            }
            self.street = Some(street);
            self.wager = None;
            self.full_increment = None;
            self.aggressive_prefix = false;
        }
        for (index, seat, badge) in changed {
            if !self.recording {
                return;
            }
            // A skipped action can change the wager/minimum increment. Break
            // those baselines BEFORE inferring an all-in subtype or amount.
            if badge.action_sequence.known().copied() != Some(self.next_action) {
                self.gap(capture, GapReason::ActionSequence);
            } else {
                self.next_action = self.next_action.saturating_add(1);
            }
            let Some(previous) = self.seats[index].as_ref().cloned() else {
                continue;
            };
            let mut action = self.reconcile(seat, badge, &previous, new_hand || street_changed);
            if single_change
                && action.forced == Some(ForcedAction::Voluntary)
                && matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise))
                && (self
                    .wager
                    .zip(snapshot.wager.known().copied())
                    .is_some_and(|(old, now)| now <= old)
                    || action
                        .commitment
                        .zip(snapshot.wager.known().copied())
                        .is_some_and(|(total, now)| total != now))
            {
                action.kind = None;
                action.full_raise = None;
                action.trusted = false;
                action.kind_confidence = None;
                action.basis = ActionBasis::Unknown;
            }
            if action.kind.is_none() && badge.kind.known().is_some() {
                self.gap(capture, GapReason::ContradictoryEvidence);
            }
            self.observe_action(capture, index, action);
        }
        if !self.recording {
            return;
        }
        if self.street == Some(Street::Preflop) && snapshot.preflop_complete.known() == Some(&true)
        {
            self.settle_all(capture);
        }
        if !self.recording {
            return;
        }
        for (index, seat) in physical.iter().enumerate() {
            if let (Some(state), Some(seat)) = (self.seats[index].as_mut(), seat) {
                // Missing fields break amount continuity instead of carrying
                // stale amounts forward to manufacture a future chip delta.
                state.stack = seat.stack.known().copied();
                state.commitment = seat.commitment.known().copied();
                state.dealt_in = seat.dealt_in.known().copied();
            }
        }
        self.wager = snapshot.wager.known().copied();
        self.full_increment = snapshot
            .full_raise_increment
            .known()
            .copied()
            .filter(|v| *v != 0);
    }

    fn reconcile(
        &self,
        seat: &SeatSnapshot,
        badge: &ActionBadge,
        previous: &SeatState,
        boundary: bool,
    ) -> ActionRecord {
        let mut action = ActionRecord {
            seat: seat.seat,
            occupant_id: previous.occupant,
            occurrence: badge.occurrence,
            action_sequence: badge.action_sequence.known().copied().filter(|v| *v != 0),
            kind: badge.kind.known().copied(),
            all_in: badge.all_in.known().copied(),
            full_raise: badge.full_raise.known().copied(),
            forced: badge.forced.known().copied(),
            amount: badge.amount.known().copied(),
            stack: seat.stack.known().copied(),
            commitment: seat.commitment.known().copied(),
            trusted: false,
            kind_confidence: if badge.kind.known().is_some() {
                badge.kind.confidence
            } else {
                None
            },
            basis: if badge.kind.known().is_some() {
                ActionBasis::Badge
            } else {
                ActionBasis::Unknown
            },
            preflop_raise_ordinal: None,
        };
        if seat.movement.known().is_some() {
            return action;
        }
        let delta = if boundary || action.forced != Some(ForcedAction::Voluntary) {
            None
        } else {
            action.commitment.zip(previous.commitment)
        };
        let mut contradiction = delta.is_some_and(|(now, old)| now < old)
            || seat.dealt_in.known() == Some(&false)
            || (self.street == Some(Street::Preflop) && previous.settled);
        if let Some((now, old)) = delta.filter(|(now, old)| now >= old) {
            if action.amount.is_some_and(|amount| amount != now - old) {
                contradiction = true;
            }
            if action.amount.is_none() {
                action.amount = Some(now - old);
            }
            if action.forced == Some(ForcedAction::Voluntary) {
                if let Some(wager) = self.wager {
                    if action.kind.is_none() && action.all_in == Some(true) && now > old {
                        action.kind = Some(if now <= wager {
                            ActionKind::Call
                        } else if wager == 0 {
                            ActionKind::Bet
                        } else {
                            ActionKind::Raise
                        });
                        action.basis = ActionBasis::Commitment;
                    }
                    match action.kind {
                        Some(ActionKind::Call) => {
                            contradiction |= now <= old
                                || now > wager
                                || (now < wager && action.all_in != Some(true));
                        }
                        Some(ActionKind::Bet | ActionKind::Raise) => {
                            contradiction |= now <= wager
                                || now <= old
                                || (action.kind == Some(ActionKind::Bet) && wager != 0);
                            if let Some(increment) = self.full_increment {
                                let full = now.saturating_sub(wager) >= increment;
                                contradiction |=
                                    action.full_raise.is_some_and(|claim| claim != full)
                                        || (!full && action.all_in != Some(true));
                                action.full_raise = Some(full);
                            }
                        }
                        Some(ActionKind::Check) => contradiction |= now != old || old < wager,
                        Some(ActionKind::Fold) => contradiction |= now != old,
                        None => {}
                    }
                }
            }
        }
        contradiction |= action.full_raise == Some(true)
            && !matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise));
        contradiction |= action.all_in == Some(true)
            && matches!(action.kind, Some(ActionKind::Fold | ActionKind::Check));
        contradiction |= action.full_raise == Some(false)
            && matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise))
            && action.all_in != Some(true);
        if contradiction {
            action.kind = None;
            action.full_raise = None;
            action.basis = ActionBasis::Unknown;
            action.kind_confidence = None;
        }
        action.trusted = !contradiction
            && action.forced.is_some()
            && (action.kind.is_some() || action.forced != Some(ForcedAction::Voluntary));
        action
    }

    fn observe_action(&mut self, capture: Capture, index: usize, mut action: ActionRecord) {
        if !action.trusted {
            self.gap(capture, GapReason::UnknownAction);
        }
        let voluntary = action.trusted && action.forced == Some(ForcedAction::Voluntary);
        let aggressive =
            voluntary && matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise));
        if aggressive {
            if self.street == Some(Street::Preflop)
                && self.ordered
                && self.aggressive_prefix
                && action.full_raise == Some(true)
            {
                self.aggressions += 1;
                action.preflop_raise_ordinal = Some(self.aggressions + 1);
            } else {
                self.aggressive_prefix = false;
            }
            if action.full_raise.is_none() {
                self.aggressive_prefix = false;
            }
        }
        let key = (
            capture.session_id,
            capture.table_id,
            self.hand.unwrap(),
            action.occupant_id,
            action.occurrence,
        );
        let event_index = self.ledger.len();
        if !self.append(
            capture,
            LedgerEntry::Action {
                action: action.clone(),
            },
        ) {
            return;
        }
        self.badges.insert(key, event_index);
        self.counts.add(&action);
        if voluntary {
            self.stats
                .entry((capture.session_id, capture.table_id, action.occupant_id))
                .or_default()
                .actions
                .add(&action);
            if self.street == Some(Street::Preflop) {
                if let Some(state) = self.seats[index].as_mut() {
                    state.voluntary |= matches!(
                        action.kind,
                        Some(ActionKind::Call | ActionKind::Bet | ActionKind::Raise)
                    );
                    state.raised |= aggressive;
                }
                if action.kind == Some(ActionKind::Fold) {
                    self.settle(capture, index);
                }
            }
        }
        if action.trusted {
            if let Some(commitment) = action.commitment {
                if matches!(action.kind, Some(ActionKind::Bet | ActionKind::Raise))
                    || matches!(
                        action.forced,
                        Some(
                            ForcedAction::SmallBlind
                                | ForcedAction::BigBlind
                                | ForcedAction::Straddle
                        )
                    )
                {
                    if action.full_raise == Some(true) && voluntary {
                        self.full_increment = self
                            .wager
                            .map(|w| commitment.saturating_sub(w))
                            .filter(|v| *v != 0);
                    }
                    self.wager = Some(self.wager.map_or(commitment, |w| w.max(commitment)));
                }
            }
        }
    }

    fn settle_all(&mut self, capture: Capture) {
        for index in 0..PHYSICAL_SEATS {
            self.settle(capture, index);
        }
    }

    fn settle(&mut self, capture: Capture, index: usize) {
        if !self.ordered || !self.recording {
            return;
        }
        let Some(state) = self.seats[index].as_ref() else {
            return;
        };
        if !state.eligible || state.settled {
            return;
        }
        let (occupant_id, vpip, pfr) = (state.occupant, state.voluntary, state.raised);
        if !self.append(
            capture,
            LedgerEntry::HandOutcome {
                seat: index as u8,
                occupant_id,
                vpip,
                pfr,
            },
        ) {
            return;
        }
        let stats = self
            .stats
            .entry((capture.session_id, capture.table_id, occupant_id))
            .or_default();
        stats.hands += 1;
        stats.vpip += u64::from(vpip);
        stats.pfr += u64::from(pfr);
        self.seats[index].as_mut().unwrap().settled = true;
    }

    pub fn summary(&self) -> Summary {
        let occupants = self
            .seats
            .iter()
            .enumerate()
            .filter_map(|(seat, state)| {
                let state = state.as_ref()?;
                let capture = self.current?;
                let stats = self
                    .stats
                    .get(&(capture.session_id, capture.table_id, state.occupant))
                    .cloned()
                    .unwrap_or_default();
                Some(OccupantSummary {
                    seat: seat as u8,
                    occupant_id: state.occupant,
                    actions: stats.actions,
                    eligible_hands: stats.hands,
                    vpip_hands: stats.vpip,
                    pfr_hands: stats.pfr,
                    vpip: (stats.hands != 0).then(|| stats.vpip as f64 / stats.hands as f64),
                    pfr: (stats.hands != 0).then(|| stats.pfr as f64 / stats.hands as f64),
                    profile: Archetype::Unknown,
                })
            })
            .collect();
        Summary {
            session_id: self.current.map(|c| c.session_id),
            table_id: self.current.map(|c| c.table_id),
            hand_id: self.hand,
            counts: self.counts.clone(),
            gaps: self.gaps,
            coverage: Coverage {
                complete: self.complete && self.hand.is_some() && self.recording,
                ordered_prefix: self.ordered && self.aggressive_prefix && self.recording,
                recording: self.recording,
                accepted_captures: self.accepted_captures,
                unvalidated_captures: self.unvalidated_captures,
                partial_hands: self.partial_hands,
                event_limit: self.limits.session_events,
            },
            occupants,
            events: self.ledger[self.ledger.len().saturating_sub(self.limits.event_view)..]
                .to_vec(),
        }
    }

    fn append(&mut self, capture: Capture, entry: LedgerEntry) -> bool {
        if !self.recording {
            return false;
        }
        // Reserve the final slot for an explicit stop rather than silently
        // dropping evidence while continuing to count or claiming continuity.
        let stopping = self.ledger.len() + 1 >= self.limits.session_events;
        let same_target = self.current.is_some_and(|current| {
            current.session_id == capture.session_id && current.table_id == capture.table_id
        });
        self.ledger.push(LedgerEvent {
            event_sequence: self.ledger.len() as u64 + 1,
            capture,
            hand_id: if same_target { self.hand } else { None },
            street: if same_target { self.street } else { None },
            entry: if stopping {
                LedgerEntry::RecordingStopped {
                    reason: GapReason::EventLimit,
                }
            } else {
                entry
            },
        });
        if stopping {
            self.recording = false;
            self.complete = false;
            self.ordered = false;
            self.aggressive_prefix = false;
            self.gaps += 1;
        }
        !stopping
    }

    fn gap(&mut self, capture: Capture, reason: GapReason) {
        self.complete = false;
        self.ordered = false;
        self.aggressive_prefix = false;
        self.wager = None;
        self.full_increment = None;
        for seat in self.seats.iter_mut().flatten() {
            seat.stack = None;
            seat.commitment = None;
        }
        if self.append(capture, LedgerEntry::Gap { reason }) {
            self.gaps += 1;
        }
    }

    fn admit_capture(&mut self, capture: Capture) -> bool {
        if !self.recording {
            return false;
        }
        if capture.session_id.0 == 0
            || capture.table_id.0 == 0
            || capture.ticket.0 == 0
            || capture.sequence == 0
        {
            if self.last_rejected != Some(capture) {
                self.last_rejected = Some(capture);
                self.gap(capture, GapReason::InvalidSnapshot);
            }
            return false;
        }
        if let Some(previous) = self.captures.get(&capture.session_id).copied() {
            // Older captures and repeated ticket sequences never reactivate a
            // hand/table. A same-sequence conflict interrupts continuity once.
            if capture.sequence < previous.sequence {
                return false;
            }
            if capture.sequence == previous.sequence {
                if capture != previous && self.last_rejected != Some(capture) {
                    self.last_rejected = Some(capture);
                    self.gap(capture, GapReason::ConflictingCapture);
                }
                return false;
            }
            if capture.sequence != previous.sequence.saturating_add(1) {
                self.gap(capture, GapReason::CaptureSequence);
            }
            if capture.captured_at_ms < previous.captured_at_ms {
                self.gap(capture, GapReason::CaptureTime);
                self.captures.insert(capture.session_id, capture);
                return false;
            }
            if capture.ticket == previous.ticket {
                self.gap(capture, GapReason::ConflictingCapture);
                self.captures.insert(capture.session_id, capture);
                return false;
            }
        }
        if self
            .current
            .is_some_and(|c| c.session_id != capture.session_id || c.table_id != capture.table_id)
        {
            self.gap(capture, GapReason::IdentityChanged);
            self.hand = None;
            self.street = None;
            self.seats = std::array::from_fn(|_| None);
        }
        if !self.recording {
            return false;
        }
        self.captures.insert(capture.session_id, capture);
        self.current = Some(capture);
        self.accepted_captures += 1;
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capture(sequence: u64) -> Capture {
        Capture {
            session_id: Id(1),
            table_id: Id(2),
            sequence,
            captured_at_ms: sequence * 10,
            ticket: Id(sequence + 1000),
        }
    }

    fn snapshot(sequence: u64) -> Snapshot {
        Snapshot {
            capture: capture(sequence),
            quality_approved: true,
            hand_id: Evidence::trusted(Id(10)),
            street: Evidence::trusted(Street::Preflop),
            hand_start: Evidence::trusted(HandStart::BeforeActions),
            ordered: Evidence::trusted(true),
            preflop_complete: Evidence::default(),
            wager: Evidence::default(),
            full_raise_increment: Evidence::default(),
            seats: (0..PHYSICAL_SEATS as u8)
                .map(|seat| SeatSnapshot {
                    seat,
                    occupant_id: Evidence {
                        value: match seat {
                            0 => Some(Id(100)),
                            3 => Some(Id(200)),
                            _ => None,
                        },
                        trusted: true,
                        confidence: None,
                    },
                    dealt_in: Evidence::trusted(seat == 0 || seat == 3),
                    badge: Evidence::trusted(Badge::Clear),
                    ..SeatSnapshot::default()
                })
                .collect(),
        }
    }

    fn next(snapshot: &mut Snapshot, sequence: u64) {
        snapshot.capture = capture(sequence);
        snapshot.hand_start = Evidence::default();
        snapshot.preflop_complete = Evidence::default();
        for seat in &mut snapshot.seats {
            seat.movement = Evidence::default();
        }
    }

    fn seat(snapshot: &mut Snapshot, physical: u8) -> &mut SeatSnapshot {
        snapshot
            .seats
            .iter_mut()
            .find(|seat| seat.seat == physical)
            .unwrap()
    }

    fn badge(kind: ActionKind, occurrence: u64, sequence: u64) -> ActionBadge {
        ActionBadge {
            occurrence: Id(occurrence),
            action_sequence: Evidence::trusted(sequence),
            kind: Evidence::trusted(kind),
            all_in: Evidence::trusted(false),
            full_raise: if matches!(kind, ActionKind::Raise | ActionKind::Bet) {
                Evidence::trusted(true)
            } else {
                Evidence::default()
            },
            forced: Evidence::trusted(ForcedAction::Voluntary),
            amount: Evidence::default(),
        }
    }

    fn put(snapshot: &mut Snapshot, physical: u8, action: ActionBadge) {
        seat(snapshot, physical).badge = Evidence::trusted(Badge::Action(action));
    }

    fn actions(observer: &Observer) -> Vec<&ActionRecord> {
        observer
            .events()
            .iter()
            .filter_map(|event| match &event.entry {
                LedgerEntry::Action { action } => Some(action),
                _ => None,
            })
            .collect()
    }

    fn has_gap(observer: &Observer, reason: GapReason) -> bool {
        observer
            .events()
            .iter()
            .any(|event| event.entry == LedgerEntry::Gap { reason })
    }

    #[test]
    fn unapproved_source_never_admits_actions_or_outcomes() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.quality_approved = false;
        s.preflop_complete = Evidence::trusted(true);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        let events = observer.observe(&s);
        assert_eq!(events.len(), 1);
        assert!(has_gap(&observer, GapReason::UnvalidatedSource));
        assert!(actions(&observer).is_empty());
        assert_eq!(observer.summary().counts, ActionCounts::default());
        assert_eq!(observer.summary().coverage.unvalidated_captures, 1);
        assert!(!observer.summary().coverage.complete);
        assert!(observer.summary().occupants.is_empty());
    }

    #[test]
    fn default_evidence_and_nullable_amounts_do_not_mean_zero_or_false() {
        assert_eq!(Evidence::<bool>::default().known(), None);
        assert_eq!(Evidence::<u64>::default().known(), None);
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        let mut action = badge(ActionKind::Call, 1, 1);
        action.all_in = Evidence::default();
        action.amount = Evidence {
            value: Some(0),
            trusted: false,
            confidence: Some(1.0),
        };
        put(&mut s, 0, action);
        observer.observe(&s);
        let action = actions(&observer)[0];
        assert_eq!(action.amount, None);
        assert_eq!(action.stack, None);
        assert_eq!(action.commitment, None);
        assert_eq!(action.all_in, None);
        assert_eq!(action.full_raise, None);
        assert_eq!(observer.summary().occupants[0].vpip, None);
    }

    #[test]
    fn duplicate_persistent_flickering_and_renewed_badges_are_distinct() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Check, 1, 1));
        observer.observe(&s);
        let prefix = observer.events().to_vec();
        assert!(observer.observe(&s).is_empty());
        assert_eq!(observer.events(), prefix);
        next(&mut s, 3);
        observer.observe(&s);
        next(&mut s, 4);
        seat(&mut s, 0).badge = Evidence::trusted(Badge::Clear);
        observer.observe(&s);
        next(&mut s, 5);
        put(&mut s, 0, badge(ActionKind::Check, 1, 1));
        observer.observe(&s);
        assert_eq!(observer.summary().counts.checks, 1);
        next(&mut s, 6);
        put(&mut s, 0, badge(ActionKind::Check, 2, 2));
        observer.observe(&s);
        assert_eq!(observer.summary().counts.checks, 2);
        assert_eq!(actions(&observer).len(), 2);
    }

    #[test]
    fn reused_occurrence_with_changed_order_or_kind_is_a_gap_not_a_false_outcome() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Call, 1, 1));
        observer.observe(&s);
        next(&mut s, 3);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 2));
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::ContradictoryEvidence));
        assert_eq!(actions(&observer).len(), 1);
        assert_eq!(observer.summary().counts.calls, 1);
        assert_eq!(observer.summary().counts.raises, 0);
        assert_eq!(observer.summary().occupants[0].pfr, None);
    }

    #[test]
    fn identical_raise_badges_are_not_permanently_collapsed() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        next(&mut s, 3);
        put(&mut s, 3, badge(ActionKind::Raise, 1, 2));
        observer.observe(&s);
        next(&mut s, 4);
        put(&mut s, 0, badge(ActionKind::Raise, 2, 3));
        observer.observe(&s);
        assert_eq!(observer.summary().counts.raises, 3);
        assert_eq!(observer.summary().occupants[0].actions.raises, 2);
        assert_eq!(actions(&observer)[2].preflop_raise_ordinal, Some(4));
    }

    #[test]
    fn full_ordered_prefix_establishes_three_and_four_bets() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.seats.reverse(); // Physical slot, not vector index, identifies the actor.
        observer.observe(&s);
        for (capture_sequence, physical, occurrence, order) in
            [(2, 3, 1, 1), (3, 0, 1, 2), (4, 3, 2, 3)]
        {
            next(&mut s, capture_sequence);
            put(
                &mut s,
                physical,
                badge(ActionKind::Raise, occurrence, order),
            );
            observer.observe(&s);
        }
        let actions = actions(&observer);
        assert_eq!(
            actions
                .iter()
                .map(|a| a.preflop_raise_ordinal)
                .collect::<Vec<_>>(),
            vec![Some(2), Some(3), Some(4)]
        );
        assert_eq!(actions[0].seat, 3);
        assert_eq!(actions[0].occupant_id, Id(200));
        assert_eq!(observer.summary().counts.three_bets, 1);
        assert_eq!(observer.summary().counts.four_bets, 1);
    }

    #[test]
    fn forced_blinds_and_antes_are_excluded_and_short_all_in_is_a_call() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.wager = Evidence::trusted(100);
        s.full_raise_increment = Evidence::trusted(100);
        seat(&mut s, 0).commitment = Evidence::trusted(0);
        seat(&mut s, 3).commitment = Evidence::trusted(0);
        observer.observe(&s);
        next(&mut s, 2);
        let mut blind = badge(ActionKind::Call, 1, 1);
        blind.kind = Evidence::default(); // Posting a blind is not a voluntary call.
        blind.forced = Evidence::trusted(ForcedAction::BigBlind);
        put(&mut s, 3, blind);
        seat(&mut s, 3).commitment = Evidence::trusted(100);
        observer.observe(&s);
        next(&mut s, 3);
        let mut ante = badge(ActionKind::Call, 2, 2);
        ante.kind = Evidence::default();
        ante.forced = Evidence::trusted(ForcedAction::Ante);
        put(&mut s, 3, ante);
        observer.observe(&s);
        next(&mut s, 4);
        let mut all_in = badge(ActionKind::Call, 1, 3);
        all_in.kind = Evidence::default();
        all_in.all_in = Evidence::trusted(true);
        put(&mut s, 0, all_in);
        seat(&mut s, 0).commitment = Evidence::trusted(50);
        observer.observe(&s);
        let summary = observer.summary();
        assert_eq!(summary.counts.calls, 1);
        assert_eq!(summary.counts.raises, 0);
        assert_eq!(summary.counts.all_ins, 1);
        assert!(summary.coverage.ordered_prefix);
        let action = actions(&observer)[2];
        assert_eq!(action.kind, Some(ActionKind::Call));
        assert_eq!(action.basis, ActionBasis::Commitment);
        assert_eq!(action.amount, Some(50));
        assert_eq!(action.preflop_raise_ordinal, None);
    }

    #[test]
    fn short_all_in_raise_does_not_reopen_a_full_aggressive_prefix() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.wager = Evidence::trusted(100);
        s.full_raise_increment = Evidence::trusted(100);
        seat(&mut s, 0).commitment = Evidence::trusted(0);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 3, badge(ActionKind::Raise, 1, 1));
        s.wager = Evidence::trusted(300);
        s.full_raise_increment = Evidence::trusted(200);
        observer.observe(&s);
        next(&mut s, 3);
        let mut short = badge(ActionKind::Raise, 1, 2);
        short.all_in = Evidence::trusted(true);
        short.full_raise = Evidence::trusted(false);
        put(&mut s, 0, short);
        seat(&mut s, 0).commitment = Evidence::trusted(350);
        s.wager = Evidence::trusted(350);
        observer.observe(&s);
        next(&mut s, 4);
        put(&mut s, 3, badge(ActionKind::Raise, 2, 3));
        s.wager = Evidence::trusted(700);
        s.full_raise_increment = Evidence::trusted(350);
        observer.observe(&s);
        assert_eq!(observer.summary().counts.raises, 3);
        assert_eq!(observer.summary().counts.incomplete_raises, 1);
        assert_eq!(observer.summary().counts.three_bets, 0);
        assert_eq!(actions(&observer)[1].full_raise, Some(false));
        assert_eq!(actions(&observer)[2].preflop_raise_ordinal, None);
    }

    #[test]
    fn unknown_all_in_subtype_and_missing_full_raise_stay_unknown() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        let mut unknown = badge(ActionKind::Raise, 1, 1);
        unknown.kind = Evidence::default();
        unknown.all_in = Evidence::trusted(true);
        unknown.full_raise = Evidence::default();
        put(&mut s, 0, unknown);
        observer.observe(&s);
        assert_eq!(actions(&observer)[0].kind, None);
        assert_eq!(actions(&observer)[0].all_in, Some(true));
        assert_eq!(observer.summary().counts.raises, 0);
        next(&mut s, 3);
        let mut raise = badge(ActionKind::Raise, 2, 2);
        raise.full_raise = Evidence::default();
        put(&mut s, 0, raise);
        observer.observe(&s);
        assert_eq!(actions(&observer)[1].full_raise, None);
        assert_eq!(actions(&observer)[1].preflop_raise_ordinal, None);
    }

    #[test]
    fn capture_and_action_sequence_gaps_prevent_invented_ordinals() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        next(&mut s, 4);
        put(&mut s, 3, badge(ActionKind::Raise, 1, 3));
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::CaptureSequence));
        assert!(has_gap(&observer, GapReason::ActionSequence));
        assert_eq!(actions(&observer)[1].preflop_raise_ordinal, None);
        assert_eq!(observer.summary().counts.raises, 2);
        let prefix = observer.events().to_vec();
        s.capture = capture(3);
        assert!(observer.observe(&s).is_empty());
        assert_eq!(observer.events(), prefix);
    }

    #[test]
    fn missed_action_clears_prior_wager_before_all_in_subtype_reconciliation() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.wager = Evidence::trusted(100);
        s.full_raise_increment = Evidence::trusted(100);
        seat(&mut s, 0).commitment = Evidence::trusted(0);
        observer.observe(&s);
        next(&mut s, 2);
        let mut all_in = badge(ActionKind::Call, 1, 3); // Two intervening actions are missing.
        all_in.kind = Evidence::default();
        all_in.all_in = Evidence::trusted(true);
        put(&mut s, 0, all_in);
        seat(&mut s, 0).commitment = Evidence::trusted(150);
        s.wager = Evidence::trusted(200);
        observer.observe(&s);
        let action = actions(&observer)[0];
        assert!(has_gap(&observer, GapReason::ActionSequence));
        assert_eq!(action.kind, None); // 150 > old 100 does NOT prove a raise to 150.
        assert_eq!(action.full_raise, None);
        assert_eq!(action.amount, None);
        assert_eq!(observer.summary().counts.raises, 0);
        assert_eq!(observer.summary().counts.calls, 0);
    }

    #[test]
    fn simultaneous_badges_are_not_ordered_by_seat_or_claimed_sequence() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        put(&mut s, 3, badge(ActionKind::Raise, 1, 2));
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::SimultaneousActions));
        assert!(actions(&observer)
            .iter()
            .all(|action| action.preflop_raise_ordinal.is_none()));
        assert_eq!(observer.summary().counts.three_bets, 0);
    }

    #[test]
    fn explicit_gap_and_unknown_order_break_continuity() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        let events = observer.record_gap(capture(2), GapReason::MissingEvidence);
        assert_eq!(events.len(), 1);
        assert!(observer
            .record_gap(capture(2), GapReason::MissingEvidence)
            .is_empty());
        next(&mut s, 3);
        s.ordered = Evidence::default();
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        assert_eq!(actions(&observer)[0].preflop_raise_ordinal, None);
        assert!(has_gap(&observer, GapReason::OrderAmbiguous));
        assert!(!observer.summary().coverage.ordered_prefix);
    }

    #[test]
    fn identity_changes_preserve_history_without_merging_occupants() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Fold, 1, 1));
        observer.observe(&s);
        assert_eq!(observer.summary().occupants[0].eligible_hands, 1);
        next(&mut s, 3);
        seat(&mut s, 0).occupant_id = Evidence::trusted(Id(300));
        seat(&mut s, 0).badge = Evidence::trusted(Badge::Clear);
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::IdentityChanged));
        assert_eq!(observer.summary().occupants[0].occupant_id, Id(300));
        assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
        next(&mut s, 4);
        s.capture.table_id = Id(3);
        s.hand_start = Evidence::trusted(HandStart::BeforeActions);
        observer.observe(&s);
        assert_eq!(observer.summary().counts.folds, 1);
        assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
        next(&mut s, 1);
        s.capture.session_id = Id(4);
        s.hand_start = Evidence::trusted(HandStart::BeforeActions);
        observer.observe(&s);
        assert_eq!(observer.summary().session_id, Some(Id(4)));
        assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
        assert_eq!(observer.summary().counts.folds, 1);
    }

    #[test]
    fn partial_hand_has_lower_bounds_but_no_false_negative_denominator() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.hand_start = Evidence::trusted(HandStart::Partial);
        put(&mut s, 0, badge(ActionKind::Call, 1, 1));
        observer.observe(&s);
        next(&mut s, 2);
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        let summary = observer.summary();
        assert_eq!(summary.counts.calls, 1);
        assert_eq!(summary.coverage.partial_hands, 1);
        assert_eq!(summary.occupants[0].eligible_hands, 0);
        assert_eq!(summary.occupants[0].vpip, None);
        assert_eq!(summary.occupants[0].pfr, None);
        assert_eq!(summary.occupants[0].profile, Archetype::Unknown);
    }

    #[test]
    fn established_eligible_outcomes_are_counted_once_and_survive_later_gaps() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Call, 1, 1));
        observer.observe(&s);
        next(&mut s, 3);
        put(&mut s, 3, badge(ActionKind::Fold, 1, 2));
        observer.observe(&s);
        next(&mut s, 4);
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        next(&mut s, 5);
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        let summary = observer.summary();
        assert_eq!(summary.occupants[0].eligible_hands, 1);
        assert_eq!(summary.occupants[0].vpip, Some(1.0));
        assert_eq!(summary.occupants[0].pfr, Some(0.0));
        assert_eq!(summary.occupants[1].vpip, Some(0.0));
        observer.record_gap(capture(6), GapReason::MissingEvidence);
        assert_eq!(observer.summary().occupants[0].eligible_hands, 1);
        assert_eq!(observer.summary().occupants[0].profile, Archetype::Unknown);
    }

    #[test]
    fn full_raise_outcomes_do_not_automatically_enable_profiles_after_twenty_hands() {
        let mut observer = Observer::default();
        for hand in 0..22 {
            let mut s = snapshot(hand * 3 + 1);
            s.hand_id = Evidence::trusted(Id(hand + 10));
            observer.observe(&s);
            next(&mut s, hand * 3 + 2);
            put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
            observer.observe(&s);
            next(&mut s, hand * 3 + 3);
            put(&mut s, 3, badge(ActionKind::Fold, 1, 2));
            s.preflop_complete = Evidence::trusted(true);
            observer.observe(&s);
        }
        let summary = observer.summary();
        assert_eq!(summary.occupants[0].eligible_hands, 22);
        assert_eq!(summary.occupants[0].vpip, Some(1.0));
        assert_eq!(summary.occupants[0].pfr, Some(1.0));
        assert_eq!(summary.occupants[0].profile, Archetype::Unknown);
    }

    #[test]
    fn unknown_badges_and_unknown_eligibility_cannot_become_false_outcomes() {
        for unknown_badge in [true, false] {
            let mut observer = Observer::default();
            let mut s = snapshot(1);
            if unknown_badge {
                seat(&mut s, 0).badge = Evidence::default();
            } else {
                seat(&mut s, 0).dealt_in = Evidence::default();
            }
            observer.observe(&s);
            next(&mut s, 2);
            s.preflop_complete = Evidence::trusted(true);
            observer.observe(&s);
            assert_eq!(observer.summary().occupants[0].vpip, None);
            assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
        }
    }

    #[test]
    fn contradictory_dealt_in_status_cannot_finalize_other_players_as_false() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        seat(&mut s, 0).dealt_in = Evidence::trusted(false);
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::ContradictoryEvidence));
        assert!(observer
            .summary()
            .occupants
            .iter()
            .all(|p| p.eligible_hands == 0));
    }

    #[test]
    fn fold_or_check_cannot_simultaneously_be_an_all_in_action() {
        for kind in [ActionKind::Fold, ActionKind::Check] {
            let mut observer = Observer::default();
            let mut s = snapshot(1);
            observer.observe(&s);
            next(&mut s, 2);
            let mut contradictory = badge(kind, 1, 1);
            contradictory.all_in = Evidence::trusted(true);
            put(&mut s, 0, contradictory);
            observer.observe(&s);
            assert_eq!(actions(&observer)[0].kind, None);
            assert_eq!(observer.summary().counts, ActionCounts::default());
            assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
        }
    }

    #[test]
    fn hand_boundaries_require_identity_and_reset_prefix_and_badge_scope() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        next(&mut s, 3);
        s.hand_id = Evidence::default();
        s.wager = Evidence::trusted(0);
        observer.observe(&s);
        assert_eq!(observer.summary().hand_id, Some(Id(10)));
        assert!(has_gap(&observer, GapReason::UnknownHand));
        next(&mut s, 4);
        s.hand_id = Evidence::trusted(Id(11));
        s.hand_start = Evidence::trusted(HandStart::BeforeActions);
        // The prior hand's cleared wager is not evidence of this deal's wager.
        s.wager = Evidence::default();
        seat(&mut s, 0).badge = Evidence::trusted(Badge::Clear);
        observer.observe(&s);
        assert!(observer.summary().coverage.ordered_prefix);
        next(&mut s, 5);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        assert_eq!(actions(&observer).len(), 2);
        assert_eq!(actions(&observer)[1].kind, Some(ActionKind::Raise));
        assert!(actions(&observer)[1].trusted);
        assert_eq!(actions(&observer)[1].preflop_raise_ordinal, Some(2));
        next(&mut s, 6);
        s.hand_id = Evidence::trusted(Id(10));
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::HandIdentityReused));
        assert_eq!(observer.summary().hand_id, Some(Id(11)));
    }

    #[test]
    fn street_transition_with_new_actions_or_payout_cannot_close_known_preflop() {
        for payout in [false, true] {
            let mut observer = Observer::default();
            let mut s = snapshot(1);
            observer.observe(&s);
            next(&mut s, 2);
            s.street = Evidence::trusted(Street::Flop);
            s.preflop_complete = Evidence::trusted(true);
            if payout {
                seat(&mut s, 0).movement = Evidence::trusted(ChipMovement::Payout);
            } else {
                put(&mut s, 0, badge(ActionKind::Bet, 1, 1));
            }
            observer.observe(&s);
            assert_eq!(observer.summary().occupants[0].eligible_hands, 0);
            assert!(!observer.summary().coverage.complete);
        }
    }

    #[test]
    fn corroborated_preflop_end_allows_known_outcomes_without_using_board_clearing() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        next(&mut s, 3);
        put(&mut s, 3, badge(ActionKind::Call, 1, 2));
        observer.observe(&s);
        next(&mut s, 4);
        s.street = Evidence::trusted(Street::Flop);
        s.preflop_complete = Evidence::trusted(true);
        observer.observe(&s);
        assert_eq!(observer.summary().occupants[0].eligible_hands, 1);
        assert_eq!(observer.summary().occupants[0].pfr, Some(1.0));
        assert_eq!(observer.summary().hand_id, Some(Id(10)));
    }

    #[test]
    fn refunds_topups_payout_and_collection_are_markers_not_actions_or_new_hands() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        for (sequence, movement) in [
            (2, ChipMovement::Refund),
            (3, ChipMovement::TopUp),
            (4, ChipMovement::Payout),
            (5, ChipMovement::PotCollection),
        ] {
            next(&mut s, sequence);
            seat(&mut s, 0).movement = Evidence::trusted(movement);
            observer.observe(&s);
        }
        assert_eq!(observer.summary().hand_id, Some(Id(10)));
        assert!(actions(&observer).is_empty());
        assert_eq!(
            observer
                .events()
                .iter()
                .filter(|e| matches!(e.entry, LedgerEntry::Movement { .. }))
                .count(),
            4
        );
        assert!(has_gap(&observer, GapReason::ChipMovement));
    }

    #[test]
    fn unexplained_chip_deltas_and_contradictory_calls_remain_ambiguous() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.wager = Evidence::trusted(100);
        seat(&mut s, 0).stack = Evidence::trusted(1000);
        seat(&mut s, 0).commitment = Evidence::trusted(0);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Call, 1, 1));
        seat(&mut s, 0).commitment = Evidence::trusted(200);
        observer.observe(&s);
        assert_eq!(actions(&observer)[0].kind, None);
        assert_eq!(observer.summary().counts.calls, 0);
        assert!(has_gap(&observer, GapReason::ContradictoryEvidence));
        next(&mut s, 3);
        seat(&mut s, 0).badge = Evidence::trusted(Badge::Clear);
        seat(&mut s, 0).stack = Evidence::trusted(1200);
        observer.observe(&s);
        assert!(observer.events().iter().any(|e| matches!(
            e.entry,
            LedgerEntry::Movement {
                movement: ChipMovement::Ambiguous,
                ..
            }
        )));
        assert!(!observer.summary().coverage.complete);
    }

    #[test]
    fn contradictory_wager_and_unexplained_wager_clearing_interrupt_continuity() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        s.wager = Evidence::trusted(100);
        observer.observe(&s);
        next(&mut s, 2);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        assert_eq!(actions(&observer)[0].kind, None);
        assert!(has_gap(&observer, GapReason::ContradictoryEvidence));
        next(&mut s, 3);
        seat(&mut s, 0).badge = Evidence::trusted(Badge::Clear);
        s.wager = Evidence::trusted(0);
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::ChipMovement));
        assert_eq!(observer.summary().hand_id, Some(Id(10)));
        assert_eq!(observer.summary().counts.raises, 0);
    }

    #[test]
    fn missing_commitment_and_gaps_do_not_supply_a_zero_baseline() {
        for explicit_gap in [false, true] {
            let mut observer = Observer::default();
            let mut s = snapshot(1);
            if explicit_gap {
                seat(&mut s, 0).commitment = Evidence::trusted(0);
            }
            observer.observe(&s);
            if explicit_gap {
                observer.record_gap(capture(2), GapReason::MissingEvidence);
            }
            next(&mut s, if explicit_gap { 3 } else { 2 });
            let mut unknown = badge(ActionKind::Call, 1, 1);
            unknown.kind = Evidence::default();
            unknown.all_in = Evidence::trusted(true);
            put(&mut s, 0, unknown);
            seat(&mut s, 0).commitment = Evidence::trusted(50);
            observer.observe(&s);
            assert_eq!(actions(&observer)[0].kind, None);
            assert_eq!(actions(&observer)[0].amount, None);
            assert_eq!(observer.summary().counts.calls, 0);
        }
    }

    #[test]
    fn conflicting_capture_and_reversed_time_do_not_admit_actions() {
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        s.capture.ticket = Id(999);
        put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::ConflictingCapture));
        assert!(observer.observe(&s).is_empty());
        next(&mut s, 2);
        s.capture.captured_at_ms = 0;
        observer.observe(&s);
        assert!(has_gap(&observer, GapReason::CaptureTime));
        assert!(actions(&observer).is_empty());
    }

    #[test]
    fn malformed_seat_mapping_and_nonfinite_confidence_fail_closed() {
        for malformed in 0..4 {
            let mut observer = Observer::default();
            let mut s = snapshot(1);
            match malformed {
                0 => s.seats[1].seat = 0,
                1 => s.seats[1].seat = 6,
                2 => s.seats[3].occupant_id = Evidence::trusted(Id(100)),
                _ => s.hand_id.confidence = Some(f64::NAN),
            }
            put(&mut s, 0, badge(ActionKind::Raise, 1, 1));
            observer.observe(&s);
            assert!(actions(&observer).is_empty());
            assert!(!observer.summary().coverage.complete);
        }
        let mut observer = Observer::default();
        let mut s = snapshot(1);
        observer.observe(&s);
        next(&mut s, 2);
        let mut bad = badge(ActionKind::Call, 1, 1);
        bad.kind.confidence = Some(f64::INFINITY);
        put(&mut s, 0, bad);
        observer.observe(&s);
        assert_eq!(actions(&observer)[0].kind, None);
        assert_eq!(actions(&observer)[0].kind_confidence, None);
    }

    #[test]
    fn event_limit_preserves_prefix_and_freezes_counts_with_an_explicit_stop() {
        let mut observer = Observer::new(Limits {
            event_view: 2,
            session_events: 4,
        });
        let mut s = snapshot(1);
        observer.observe(&s);
        for sequence in 2..=8 {
            next(&mut s, sequence);
            put(
                &mut s,
                0,
                badge(ActionKind::Check, sequence - 1, sequence - 1),
            );
            observer.observe(&s);
        }
        assert_eq!(observer.events().len(), 4);
        assert!(matches!(
            observer.events()[0].entry,
            LedgerEntry::HandStarted { partial: false }
        ));
        assert_eq!(
            observer.events()[3].entry,
            LedgerEntry::RecordingStopped {
                reason: GapReason::EventLimit
            }
        );
        assert_eq!(observer.summary().counts.checks, 2);
        assert_eq!(observer.summary().events.len(), 2);
        assert!(!observer.summary().coverage.recording);
        assert!(!observer.summary().coverage.complete);
        assert!(observer
            .record_gap(capture(9), GapReason::MissingEvidence)
            .is_empty());
    }

    #[test]
    fn default_and_custom_limits_bound_event_view_and_all_retained_keys() {
        let mut observer = Observer::new(Limits {
            event_view: usize::MAX,
            session_events: usize::MAX,
        });
        for sequence in 1..=MAX_SESSION_EVENTS as u64 + 10 {
            observer.record_gap(capture(sequence), GapReason::UnvalidatedSource);
        }
        assert_eq!(observer.events().len(), MAX_SESSION_EVENTS);
        assert_eq!(observer.summary().events.len(), MAX_EVENT_VIEW);
        assert_eq!(observer.summary().coverage.event_limit, MAX_SESSION_EVENTS);
        assert!(!observer.summary().coverage.recording);
        assert_eq!(observer.captures.len(), 1);
        assert!(observer.stats.is_empty());
        assert!(observer.badges.is_empty());
        assert_eq!(Limits::default().event_view, MAX_EVENT_VIEW);
        assert_eq!(Limits::default().session_events, MAX_SESSION_EVENTS);
    }

    #[test]
    fn public_dtos_are_serializable_and_default_snapshot_is_untrusted() {
        fn serializable<T: Serialize + for<'de> Deserialize<'de>>() {}
        serializable::<Snapshot>();
        serializable::<Summary>();
        serializable::<LedgerEvent>();
        assert!(!Snapshot::default().quality_approved);
        assert_eq!(Snapshot::default().hand_id.known(), None);
        assert_eq!(Observer::default().summary().hand_id, None);
    }
}
