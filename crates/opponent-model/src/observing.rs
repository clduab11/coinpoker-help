//! Pure, anonymous partial-observation accounting; this module has no client side effects.
//! Field calibration/human approval and current-pixel validation are independent
//! assertions supplied by the adapter, never inferred from a model-wide flag.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::betting::{
    additional_call_cost, pot_odds, BettingRound, CallContext, CallCost, PotAccounting, PotOdds,
};
use crate::classifier::Archetype;
use crate::observer::{
    Badge, Capture, ChipMovement, Evidence, GapReason, HandStart, Id, LedgerEntry, Observer,
    SeatSnapshot, Snapshot, Street, Summary, MAX_SESSION_EVENTS, PHYSICAL_SEATS,
};
use crate::position::{Position, PositionEvidence, PositionMap};

pub const MAX_FIELD_AGE_MS: u64 = 5_000;
const SEAT_FIELDS: usize = 6;
const FIELD_LEASES: usize = PHYSICAL_SEATS * SEAT_FIELDS + 5;

/// `confirmed_capture` asserts freshly validated matching context/region pixels;
/// it is NOT a new inference timestamp. Polling must never change either capture
/// or extend expiry. Untrusted evidence can be retained but cannot become known.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Reading<T> {
    pub evidence: Evidence<T>,
    pub source_capture: Capture,
    pub confirmed_capture: Capture,
    pub source_epoch: Id,
    pub hand_id: Option<Id>,
    pub street: Option<Street>,
    pub expires_at_ms: u64,
}

impl<T> Reading<T> {
    /// A newly read field, not a retained-region confirmation.
    pub fn current(frame: &Frame, evidence: Evidence<T>) -> Self {
        Self {
            evidence,
            source_capture: frame.capture,
            confirmed_capture: frame.capture,
            source_epoch: frame.source_epoch,
            hand_id: frame.hand_id.known().copied(),
            street: frame.street.known().copied(),
            expires_at_ms: frame.expires_at_ms,
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct SeatFrame {
    /// Anonymous adapter identity. trusted null means verified empty. Uncertainty
    /// retires the occupant epoch even if the same adapter ID later reappears.
    pub occupant_id: Evidence<Id>,
    pub dealt_in: Evidence<bool>,
    pub folded: Evidence<bool>,
    pub displayed_stack: Option<Reading<u64>>,
    pub visible_wager: Option<Reading<u64>>,
    pub street_commitment: Option<Reading<u64>>,
    pub live_call_credit: Option<Reading<u64>>,
    pub badge: Option<Reading<Badge>>,
    pub movement: Option<Reading<ChipMovement>>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Frame {
    pub capture: Capture,
    /// Geometry/physical-association generation, nonzero and adapter-validated.
    pub source_epoch: Id,
    pub current_capture_validated: bool,
    pub expires_at_ms: u64,
    /// Only externally evidenced IDs/boundaries; never generated from board or
    /// wager disappearance, stack drops, a payout or a capture sequence.
    pub hand_id: Evidence<Id>,
    pub street: Evidence<Street>,
    pub hand_start: Evidence<HandStart>,
    /// A corroborated street boundary BEFORE voluntary actions. Not inferred
    /// from wager disappearance. Used only to initialize reopening rights.
    pub street_start: Evidence<bool>,
    pub position: PositionEvidence,
    pub ordered: Evidence<bool>,
    pub preflop_complete: Evidence<bool>,
    /// FIXED physical slots 0..5 clockwise, not a player vector. Native public
    /// slots 1..6 must be explicitly converted by the adapter.
    pub seats: [SeatFrame; PHYSICAL_SEATS],
    pub acting_seat: Option<Reading<u8>>,
    pub legal_bring_in: Option<Reading<u64>>,
    pub current_target: Option<Reading<u64>>,
    pub full_raise_increment: Option<Reading<u64>>,
    pub pot: Option<Reading<PotAccounting>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Value<T> {
    pub value: T,
    pub source_capture: Capture,
    pub expires_at_ms: u64,
    pub hand_id: Option<Id>,
    pub street: Option<Street>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SeatView {
    pub seat: u8,
    pub occupant_epoch: Option<Id>,
    pub position: Option<Position>,
    pub folded: Option<bool>,
    pub displayed_stack: Option<Value<u64>>,
    pub visible_wager: Option<Value<u64>>,
    pub street_commitment: Option<Value<u64>>,
    pub live_call_credit: Option<Value<u64>>,
    /// Reopening rights only, NOT offered/legal UI controls or advice.
    pub may_raise: Option<bool>,
    pub profile: Archetype,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct View {
    pub capture: Option<Capture>,
    pub current_capture_validated: bool,
    pub hand_id: Option<Id>,
    pub street: Option<Street>,
    pub positions: Option<PositionMap>,
    pub seats: [SeatView; PHYSICAL_SEATS],
    pub call_cost: Option<CallCost>,
    pub pot_odds: Option<PotOdds>,
    pub gaps: Vec<GapReason>,
}

/// One current partial frame plus the existing bounded Observer's history.
/// Missing fields are not forward-filled. A retained field must be explicitly
/// re-confirmed against current pixels without renewing its original expiry.
pub struct Tracker {
    frame: Option<Frame>,
    captures: BTreeMap<Id, Capture>,
    scope: Option<(Id, Id, Id)>,
    occupant_ids: [Option<Id>; PHYSICAL_SEATS],
    occupant_epochs: [Option<Id>; PHYSICAL_SEATS],
    occupant_since: [u64; PHYSICAL_SEATS],
    next_epoch: u64,
    hand: Option<Id>,
    hands: BTreeSet<(Id, Id, Id)>,
    context_since: u64,
    positions: Option<PositionMap>,
    roster_epochs: [Option<Id>; PHYSICAL_SEATS],
    round: Option<BettingRound>,
    observer: Observer,
    gaps: Vec<GapReason>,
    last_now: u64,
    field_leases: [Option<(Capture, u64)>; FIELD_LEASES],
}

impl Default for Tracker {
    fn default() -> Self {
        Self {
            frame: None,
            captures: BTreeMap::new(),
            scope: None,
            occupant_ids: [None; PHYSICAL_SEATS],
            occupant_epochs: [None; PHYSICAL_SEATS],
            occupant_since: [0; PHYSICAL_SEATS],
            next_epoch: 1,
            hand: None,
            hands: BTreeSet::new(),
            context_since: 0,
            positions: None,
            roster_epochs: [None; PHYSICAL_SEATS],
            round: None,
            observer: Observer::default(),
            gaps: Vec::new(),
            last_now: 0,
            field_leases: [None; FIELD_LEASES],
        }
    }
}

impl Tracker {
    /// Clear current display/identity association without deleting recorded
    /// history. Source loss/geometry ambiguity is NOT a new hand boundary.
    pub fn invalidate(&mut self) {
        self.frame = None;
        self.scope = None;
        self.occupant_ids = [None; PHYSICAL_SEATS];
        self.occupant_epochs = [None; PHYSICAL_SEATS];
        self.positions = None;
        self.round = None;
    }

    pub fn history(&self) -> Summary {
        self.observer.summary()
    }

    pub fn observe(&mut self, frame: &Frame, now_ms: u64) -> View {
        self.last_now = if self.scope.is_some_and(|s| s.0 == frame.capture.session_id) {
            self.last_now.max(now_ms)
        } else {
            now_ms
        };
        let now_ms = self.last_now;
        let capture = frame.capture;
        if !valid_capture(capture) {
            self.gaps = vec![GapReason::InvalidSnapshot];
            self.observer
                .record_gap(capture, GapReason::InvalidSnapshot);
            self.invalidate();
            return self.view(now_ms);
        }
        if let Some(previous) = self.captures.get(&capture.session_id).copied() {
            if capture.sequence < previous.sequence || capture == previous {
                return self.view(now_ms);
            }
            self.gaps.clear();
            if capture.sequence == previous.sequence {
                self.gaps.push(GapReason::ConflictingCapture);
                self.observer
                    .record_gap(capture, GapReason::ConflictingCapture);
                self.invalidate();
                return self.view(now_ms);
            }
            if capture.captured_at_ms < previous.captured_at_ms || capture.ticket == previous.ticket
            {
                let reason = if capture.ticket == previous.ticket {
                    GapReason::ConflictingCapture
                } else {
                    GapReason::CaptureTime
                };
                self.gaps.push(reason);
                self.observer.record_gap(capture, reason);
                self.captures.insert(capture.session_id, capture);
                self.invalidate();
                return self.view(now_ms);
            }
            if capture.sequence != previous.sequence.saturating_add(1) {
                self.gaps.push(GapReason::CaptureSequence);
                self.occupant_ids = [None; PHYSICAL_SEATS];
                self.occupant_epochs = [None; PHYSICAL_SEATS];
                if let Some(round) = &mut self.round {
                    round.invalidate();
                }
            }
        } else if self.captures.len() >= MAX_SESSION_EVENTS {
            self.gaps = vec![GapReason::EventLimit];
            self.invalidate();
            return self.view(now_ms);
        } else {
            self.gaps.clear();
        }
        self.captures.insert(capture.session_id, capture);
        if !valid_frame(frame, now_ms) {
            self.gaps.push(GapReason::UnvalidatedSource);
            self.observer
                .record_gap(capture, GapReason::UnvalidatedSource);
            self.invalidate();
            return self.view(now_ms);
        }
        let scope = (capture.session_id, capture.table_id, frame.source_epoch);
        if self.frame.as_ref().is_some_and(|previous| {
            previous.capture.session_id == capture.session_id && now_ms >= previous.expires_at_ms
        }) {
            self.gaps.push(GapReason::UnknownIdentity);
            self.occupant_ids = [None; PHYSICAL_SEATS];
            self.occupant_epochs = [None; PHYSICAL_SEATS];
            if let Some(round) = &mut self.round {
                round.invalidate();
            }
        }
        if self.scope != Some(scope) {
            if self.scope.is_some() {
                self.gaps.push(GapReason::IdentityChanged);
            }
            self.occupant_ids = [None; PHYSICAL_SEATS];
            self.occupant_epochs = [None; PHYSICAL_SEATS];
            self.positions = None;
            self.round = None;
            self.hand = None;
            self.context_since = capture.sequence;
            self.scope = Some(scope);
            self.field_leases = [None; FIELD_LEASES];
        }
        let mut ids = BTreeSet::new();
        let identity_valid = frame.seats.iter().all(|seat| {
            seat.occupant_id
                .known()
                .is_none_or(|id| id.0 != 0 && ids.insert(*id))
        });
        for (index, seat) in frame.seats.iter().enumerate() {
            let occupant = identity_valid
                .then(|| seat.occupant_id.known().copied())
                .flatten();
            if occupant != self.occupant_ids[index] || occupant.is_none() {
                self.occupant_since[index] = capture.sequence;
                if self.occupant_epochs[index].is_some() {
                    self.gaps.push(if asserted(&seat.occupant_id) {
                        GapReason::IdentityChanged
                    } else {
                        GapReason::UnknownIdentity
                    });
                }
                self.occupant_epochs[index] = None;
                self.occupant_ids[index] = occupant;
                if occupant.is_some() {
                    self.occupant_epochs[index] = self.next_epoch.checked_add(1).map(|next| {
                        let epoch = Id(self.next_epoch);
                        self.next_epoch = next;
                        epoch
                    });
                }
            }
        }
        if !identity_valid {
            self.gaps.push(GapReason::InvalidSnapshot);
        }
        let hand = frame.hand_id.known().copied().filter(|id| id.0 != 0);
        let previous_street = self.frame.as_ref().and_then(|f| f.street.known().copied());
        let street = frame.street.known().copied();
        let context_changed = self.frame.as_ref().is_some_and(|previous| {
            previous.hand_id.known().copied() != hand || previous.street.known().copied() != street
        });
        if context_changed {
            self.context_since = capture.sequence;
            self.round = None;
        }
        let new_hand = hand.is_some() && hand != self.hand;
        if new_hand {
            self.context_since = capture.sequence;
            self.positions = None;
            self.round = None;
            let key = (capture.session_id, capture.table_id, hand.unwrap());
            if !self.hands.contains(&key) && self.hands.len() < MAX_SESSION_EVENTS {
                self.hands.insert(key);
                self.hand = hand;
                let voluntary_badge = frame.seats.iter().any(|seat| {
                    seat.badge.as_ref().and_then(|r| r.evidence.known()).is_some_and(|badge| {
                        matches!(badge, Badge::Action(action) if action.forced.known() == Some(&crate::observer::ForcedAction::Voluntary))
                    })
                });
                if street == Some(Street::Preflop) && identity_valid && !voluntary_badge {
                    let roster = std::array::from_fn(|i| frame.seats[i].dealt_in.clone());
                    let roster_has_occupants = frame.seats.iter().all(|seat| {
                        seat.dealt_in.known() == Some(&false) || seat.occupant_id.known().is_some()
                    });
                    if roster_has_occupants {
                        self.positions = PositionMap::freeze(
                            &frame.hand_id,
                            &frame.hand_start,
                            &frame.position,
                            &roster,
                        );
                        self.roster_epochs = self.occupant_epochs;
                    }
                }
            } else {
                self.gaps.push(if self.hands.contains(&key) {
                    GapReason::HandIdentityReused
                } else {
                    GapReason::EventLimit
                });
                // Preserve independent current slot readings, but withhold all
                // hand-bound semantics for reused/unavailable hand context.
            }
        }
        if hand.is_some() && self.positions.is_none() {
            self.gaps.push(GapReason::MissingEvidence);
        }
        let mut candidate = frame.clone();
        for (index, seat) in candidate.seats.iter_mut().enumerate() {
            let leases = &mut self.field_leases[index * SEAT_FIELDS..(index + 1) * SEAT_FIELDS];
            keep_original_lease(&mut seat.displayed_stack, &mut leases[0], frame);
            keep_original_lease(&mut seat.visible_wager, &mut leases[1], frame);
            keep_original_lease(&mut seat.street_commitment, &mut leases[2], frame);
            keep_original_lease(&mut seat.live_call_credit, &mut leases[3], frame);
            keep_original_lease(&mut seat.badge, &mut leases[4], frame);
            keep_original_lease(&mut seat.movement, &mut leases[5], frame);
        }
        let leases = &mut self.field_leases[PHYSICAL_SEATS * SEAT_FIELDS..];
        keep_original_lease(&mut candidate.acting_seat, &mut leases[0], frame);
        keep_original_lease(&mut candidate.legal_bring_in, &mut leases[1], frame);
        keep_original_lease(&mut candidate.current_target, &mut leases[2], frame);
        keep_original_lease(&mut candidate.full_raise_increment, &mut leases[3], frame);
        keep_original_lease(&mut candidate.pot, &mut leases[4], frame);
        let frame = &candidate;
        self.frame = Some(frame.clone());

        let history_ready = hand.is_some()
            && hand == self.hand
            && street.is_some()
            && identity_valid
            && frame.seats.iter().enumerate().all(|(index, seat)| {
                asserted(&seat.occupant_id)
                    && (seat.occupant_id.value.is_none()
                        || (seat.dealt_in.known().is_some()
                            && self.seat_read(index, &seat.badge, now_ms, true).is_some()))
            });
        if history_ready {
            let start_known = (new_hand
                && frame.hand_start.known() == Some(&HandStart::BeforeActions))
                || (previous_street != street && frame.street_start.known() == Some(&true));
            if start_known && frame.ordered.known() == Some(&true) {
                self.round = self
                    .target(now_ms)
                    .zip(self.read(&frame.full_raise_increment, now_ms, true))
                    .and_then(|(target, increment)| BettingRound::new(target, increment.value));
            }
            let snapshot = Snapshot {
                capture,
                // The existing ledger requires this bit. It is a PRIVATE
                // conjunction of current source + individually trusted fields,
                // never a model-wide quality promotion or advice admission.
                quality_approved: true,
                hand_id: frame.hand_id.clone(),
                street: frame.street.clone(),
                hand_start: frame.hand_start.clone(),
                ordered: frame.ordered.clone(),
                preflop_complete: frame.preflop_complete.clone(),
                wager: self
                    .target(now_ms)
                    .map_or_else(Evidence::default, Evidence::trusted),
                full_raise_increment: self
                    .read(&frame.full_raise_increment, now_ms, true)
                    .map_or_else(Evidence::default, |v| Evidence::trusted(v.value)),
                seats: frame
                    .seats
                    .iter()
                    .enumerate()
                    .map(|(index, seat)| SeatSnapshot {
                        seat: index as u8,
                        occupant_id: Evidence {
                            value: self.occupant_epochs[index],
                            trusted: true,
                            confidence: None,
                        },
                        dealt_in: seat.dealt_in.clone(),
                        badge: self
                            .seat_read(index, &seat.badge, now_ms, true)
                            .map_or_else(
                                || Evidence::trusted(Badge::Clear),
                                |v| Evidence::trusted(v.value),
                            ),
                        stack: self
                            .seat_read(index, &seat.displayed_stack, now_ms, false)
                            .map_or_else(Evidence::default, |v| Evidence::trusted(v.value)),
                        commitment: self
                            .seat_read(index, &seat.live_call_credit, now_ms, true)
                            .map_or_else(Evidence::default, |v| Evidence::trusted(v.value)),
                        movement: self
                            .seat_read(index, &seat.movement, now_ms, true)
                            .map_or_else(Evidence::default, |v| Evidence::trusted(v.value)),
                    })
                    .collect(),
            };
            for event in self.observer.observe(&snapshot) {
                match event.entry {
                    LedgerEntry::Gap { reason } | LedgerEntry::RecordingStopped { reason } => {
                        self.gaps.push(reason);
                        if let Some(round) = &mut self.round {
                            round.invalidate();
                        }
                    }
                    LedgerEntry::Movement { .. } => {
                        if let Some(round) = &mut self.round {
                            round.invalidate();
                        }
                    }
                    LedgerEntry::Action { action } => {
                        if let Some(round) = &mut self.round {
                            round.record_action(&action);
                        }
                    }
                    _ => {}
                }
            }
            if let Some(round) = &self.round {
                let contradictory = self
                    .target(now_ms)
                    .zip(round.target)
                    .is_some_and(|(given, tracked)| given != tracked)
                    || self
                        .read(&frame.full_raise_increment, now_ms, true)
                        .zip(round.full_raise_increment)
                        .is_some_and(|(given, tracked)| given.value != tracked);
                if contradictory {
                    self.gaps.push(GapReason::ContradictoryEvidence);
                    if let Some(round) = &mut self.round {
                        round.invalidate();
                    }
                }
            }
        } else {
            let reason = if self.gaps.contains(&GapReason::HandIdentityReused) {
                GapReason::HandIdentityReused
            } else if self.gaps.contains(&GapReason::EventLimit) {
                GapReason::EventLimit
            } else if hand.is_none() || street.is_none() {
                GapReason::UnknownHand
            } else {
                GapReason::MissingEvidence
            };
            self.gaps.push(reason);
            self.observer.record_gap(capture, reason);
            if let Some(round) = &mut self.round {
                round.invalidate();
            }
        }
        self.gaps.sort_by_key(|reason| *reason as u8);
        self.gaps.dedup();
        self.view(now_ms)
    }

    /// Reading/polling never mutates a source time, hand binding or expiry.
    /// `now_ms` uses the same monotonic capture-session clock as Capture.
    pub fn view(&self, now_ms: u64) -> View {
        let now_ms = now_ms.max(self.last_now);
        let current = self
            .frame
            .as_ref()
            .filter(|frame| valid_frame(frame, now_ms));
        let hand = current
            .and_then(|f| f.hand_id.known().copied())
            .filter(|id| id.0 != 0 && Some(*id) == self.hand);
        let street = current.and_then(|f| f.street.known().copied());
        let positions = self
            .positions
            .as_ref()
            .filter(|map| hand == Some(map.hand_id))
            .cloned();
        let seats = std::array::from_fn(|index| {
            let seat = current.map(|f| &f.seats[index]);
            let occupant_epoch = current.and(self.occupant_epochs[index]);
            SeatView {
                seat: index as u8,
                occupant_epoch,
                position: positions.as_ref().and_then(|map| {
                    (occupant_epoch.is_some() && occupant_epoch == self.roster_epochs[index])
                        .then_some(map.positions[index])
                        .flatten()
                }),
                folded: seat.and_then(|s| s.folded.known().copied()),
                displayed_stack: seat
                    .and_then(|s| self.seat_read(index, &s.displayed_stack, now_ms, false)),
                visible_wager: seat
                    .and_then(|s| self.seat_read(index, &s.visible_wager, now_ms, false)),
                street_commitment: seat
                    .and_then(|s| self.seat_read(index, &s.street_commitment, now_ms, true)),
                live_call_credit: seat
                    .and_then(|s| self.seat_read(index, &s.live_call_credit, now_ms, true)),
                may_raise: current.and_then(|frame| {
                    if hand.is_none()
                        || occupant_epoch.is_none()
                        || occupant_epoch != self.roster_epochs[index]
                        || frame.seats[index].dealt_in.known() != Some(&true)
                    {
                        return None;
                    }
                    self.target(now_ms)?;
                    self.read(&frame.full_raise_increment, now_ms, true)?;
                    if frame.seats[index].folded.known() == Some(&true) {
                        return Some(false);
                    }
                    self.round.as_ref()?.may_raise(index as u8)
                }),
                profile: Archetype::Unknown,
            }
        });
        let call_cost = current
            .filter(|_| hand.is_some() && street.is_some())
            .and_then(|frame| {
                let acting = self.read(&frame.acting_seat, now_ms, true)?.value;
                let seat = seats.get(usize::from(acting))?;
                if seat.folded == Some(true) {
                    return None;
                }
                additional_call_cost(&CallContext {
                    acting_seat: Evidence::trusted(acting),
                    legal_bring_in: Evidence::trusted(
                        self.read(&frame.legal_bring_in, now_ms, true)?.value,
                    ),
                    current_target: Evidence::trusted(
                        self.read(&frame.current_target, now_ms, true)?.value,
                    ),
                    live_credit: Evidence::trusted(seat.live_call_credit.as_ref()?.value),
                    remaining_stack: Evidence::trusted(seat.displayed_stack.as_ref()?.value),
                })
            });
        let odds = call_cost.as_ref().and_then(|call| {
            let pot = self.read(&current?.pot, now_ms, true)?;
            pot_odds(call, &Evidence::trusted(pot.value))
        });
        View {
            capture: current.map(|f| f.capture),
            current_capture_validated: current.is_some(),
            hand_id: hand,
            street,
            positions,
            seats,
            call_cost,
            pot_odds: odds,
            gaps: self.gaps.clone(),
        }
    }

    fn read<T: Clone>(
        &self,
        reading: &Option<Reading<T>>,
        now: u64,
        needs_hand: bool,
    ) -> Option<Value<T>> {
        let frame = self.frame.as_ref()?;
        let read = reading.as_ref()?;
        let hand = frame.hand_id.known().copied().filter(|id| id.0 != 0);
        let street = frame.street.known().copied();
        let source = read.source_capture;
        if !valid_frame(frame, now)
            || !valid_capture(source)
            || read.confirmed_capture != frame.capture
            || read.source_epoch != frame.source_epoch
            || source.session_id != frame.capture.session_id
            || source.table_id != frame.capture.table_id
            || source.sequence > frame.capture.sequence
            || source.captured_at_ms > frame.capture.captured_at_ms
            || read.hand_id != hand
            || read.street != street
            || (needs_hand && (hand.is_none() || hand != self.hand || street.is_none()))
            || (source.sequence < frame.capture.sequence && source.sequence < self.context_since)
            || now >= read.expires_at_ms
            || read.expires_at_ms <= source.captured_at_ms
            || read.expires_at_ms > source.captured_at_ms.saturating_add(MAX_FIELD_AGE_MS)
            || (source.sequence == frame.capture.sequence && source != frame.capture)
        {
            return None;
        }
        Some(Value {
            value: read.evidence.known()?.clone(),
            source_capture: source,
            expires_at_ms: read.expires_at_ms,
            hand_id: read.hand_id.filter(|id| Some(*id) == self.hand),
            street: read.street,
        })
    }

    fn seat_read<T: Clone>(
        &self,
        index: usize,
        reading: &Option<Reading<T>>,
        now: u64,
        needs_hand: bool,
    ) -> Option<Value<T>> {
        if reading.as_ref()?.source_capture.sequence < self.occupant_since[index] {
            return None;
        }
        self.read(reading, now, needs_hand)
    }

    fn target(&self, now: u64) -> Option<u64> {
        let frame = self.frame.as_ref()?;
        Some(
            self.read(&frame.current_target, now, true)?
                .value
                .max(self.read(&frame.legal_bring_in, now, true)?.value),
        )
    }
}

fn asserted<T>(evidence: &Evidence<T>) -> bool {
    evidence.trusted
        && evidence
            .confidence
            .is_none_or(|v| v.is_finite() && (0.0..=1.0).contains(&v))
}

fn keep_original_lease<T>(
    reading: &mut Option<Reading<T>>,
    lease: &mut Option<(Capture, u64)>,
    frame: &Frame,
) {
    let Some(read) = reading else {
        return;
    };
    if read.evidence.known().is_none()
        || !valid_capture(read.source_capture)
        || read.confirmed_capture != frame.capture
        || read.source_epoch != frame.source_epoch
        || read.source_capture.session_id != frame.capture.session_id
        || read.source_capture.table_id != frame.capture.table_id
        || read.source_capture.sequence > frame.capture.sequence
        || read.source_capture.captured_at_ms > frame.capture.captured_at_ms
        || read.expires_at_ms <= read.source_capture.captured_at_ms
        || read.expires_at_ms
            > read
                .source_capture
                .captured_at_ms
                .saturating_add(MAX_FIELD_AGE_MS)
    {
        return;
    }
    if let Some((source, expiry)) = lease {
        if read.source_capture == *source {
            read.expires_at_ms = read.expires_at_ms.min(*expiry);
        } else if read.source_capture.session_id == source.session_id
            && (read.source_capture.sequence <= source.sequence
                || read.source_capture.captured_at_ms < source.captured_at_ms)
        {
            *reading = None;
            return;
        }
    }
    *lease = Some((read.source_capture, read.expires_at_ms));
}

fn valid_capture(capture: Capture) -> bool {
    capture.session_id.0 != 0
        && capture.table_id.0 != 0
        && capture.ticket.0 != 0
        && capture.sequence != 0
}

fn valid_frame(frame: &Frame, now: u64) -> bool {
    valid_capture(frame.capture)
        && frame.current_capture_validated
        && frame.source_epoch.0 != 0
        && frame.capture.captured_at_ms <= now
        && now < frame.expires_at_ms
        && frame.expires_at_ms
            <= frame
                .capture
                .captured_at_ms
                .saturating_add(MAX_FIELD_AGE_MS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::betting::PotConvention;
    use crate::observer::{ActionBadge, ActionBasis, ActionKind, ForcedAction};
    use crate::position::ButtonPolicy;

    fn capture(sequence: u64) -> Capture {
        Capture {
            session_id: Id(1),
            table_id: Id(2),
            sequence,
            captured_at_ms: sequence * 100,
            ticket: Id(1000 + sequence),
        }
    }

    fn frame(sequence: u64) -> Frame {
        Frame {
            capture: capture(sequence),
            source_epoch: Id(1),
            current_capture_validated: true,
            expires_at_ms: sequence * 100 + 1000,
            ..Frame::default()
        }
    }

    fn hand_frame(sequence: u64) -> Frame {
        let mut f = frame(sequence);
        f.hand_id = Evidence::trusted(Id(10));
        f.street = Evidence::trusted(Street::Preflop);
        f.hand_start = Evidence::trusted(HandStart::BeforeActions);
        f.ordered = Evidence::trusted(true);
        f.position = PositionEvidence {
            button: Evidence::trusted(0),
            small_blind: Evidence::trusted(1),
            big_blind: Evidence::trusted(2),
            policy: Evidence::trusted(ButtonPolicy::Moving),
        };
        for index in 0..6 {
            f.seats[index] = SeatFrame {
                occupant_id: Evidence::trusted(Id(100 + index as u64)),
                dealt_in: Evidence::trusted(true),
                folded: Evidence::trusted(false),
                badge: Some(Reading::current(&f, Evidence::trusted(Badge::Clear))),
                displayed_stack: Some(Reading::current(&f, Evidence::trusted(1000))),
                visible_wager: Some(Reading::current(&f, Evidence::trusted(0))),
                street_commitment: Some(Reading::current(&f, Evidence::trusted(0))),
                live_call_credit: Some(Reading::current(&f, Evidence::trusted(0))),
                ..SeatFrame::default()
            };
        }
        f.current_target = Some(Reading::current(&f, Evidence::trusted(100)));
        f.legal_bring_in = Some(Reading::current(&f, Evidence::trusted(100)));
        f.full_raise_increment = Some(Reading::current(&f, Evidence::trusted(100)));
        f
    }

    fn fresh<T>(read: &mut Option<Reading<T>>, f: &Frame) {
        if let Some(read) = read {
            read.source_capture = f.capture;
            read.confirmed_capture = f.capture;
            read.source_epoch = f.source_epoch;
            read.hand_id = f.hand_id.known().copied();
            read.street = f.street.known().copied();
            read.expires_at_ms = f.expires_at_ms;
        }
    }

    fn advance(f: &mut Frame, sequence: u64) {
        f.capture = capture(sequence);
        f.expires_at_ms = f.capture.captured_at_ms + 1000;
        f.hand_start = Evidence::default();
        f.street_start = Evidence::default();
        let meta = f.clone();
        for seat in &mut f.seats {
            fresh(&mut seat.displayed_stack, &meta);
            fresh(&mut seat.visible_wager, &meta);
            fresh(&mut seat.street_commitment, &meta);
            fresh(&mut seat.live_call_credit, &meta);
            fresh(&mut seat.badge, &meta);
            fresh(&mut seat.movement, &meta);
        }
        fresh(&mut f.acting_seat, &meta);
        fresh(&mut f.legal_bring_in, &meta);
        fresh(&mut f.current_target, &meta);
        fresh(&mut f.full_raise_increment, &meta);
        fresh(&mut f.pot, &meta);
    }

    fn put_call(f: &mut Frame, seat: usize, occurrence: u64, sequence: u64, total: u64) {
        f.seats[seat].badge = Some(Reading::current(
            f,
            Evidence::trusted(Badge::Action(ActionBadge {
                occurrence: Id(occurrence),
                action_sequence: Evidence::trusted(sequence),
                kind: Evidence::trusted(ActionKind::Call),
                all_in: Evidence::trusted(false),
                forced: Evidence::trusted(ForcedAction::Voluntary),
                amount: Evidence::default(),
                full_raise: Evidence::default(),
            })),
        ));
        f.seats[seat].live_call_credit = Some(Reading::current(f, Evidence::trusted(total)));
    }

    #[test]
    fn six_stacks_and_six_wagers_are_independent_without_hand_or_occupant() {
        let mut f = frame(1);
        for i in 0..6 {
            f.seats[i].displayed_stack =
                Some(Reading::current(&f, Evidence::trusted(100 + i as u64)));
            f.seats[i].visible_wager = Some(Reading::current(&f, Evidence::trusted(10 + i as u64)));
        }
        f.seats[2]
            .displayed_stack
            .as_mut()
            .unwrap()
            .evidence
            .trusted = false;
        f.seats[4].visible_wager.as_mut().unwrap().evidence.trusted = false;
        let mut t = Tracker::default();
        let view = t.observe(&f, 100);
        for i in 0..6 {
            assert_eq!(view.seats[i].seat, i as u8);
            assert_eq!(
                view.seats[i].displayed_stack.as_ref().map(|v| v.value),
                (i != 2).then_some(100 + i as u64)
            );
            assert_eq!(
                view.seats[i].visible_wager.as_ref().map(|v| v.value),
                (i != 4).then_some(10 + i as u64)
            );
            assert!(view.seats[i].position.is_none());
            assert_eq!(view.seats[i].profile, Archetype::Unknown);
        }
        assert_eq!(view.hand_id, None);
        assert_eq!(t.history().counts.calls, 0);
        assert!(view.call_cost.is_none());
    }

    #[test]
    fn default_missing_fields_are_not_zero_and_unvalidated_capture_is_separate() {
        let mut t = Tracker::default();
        let f = frame(1);
        let view = t.observe(&f, 100);
        assert!(view.current_capture_validated);
        assert!(view
            .seats
            .iter()
            .all(|s| s.displayed_stack.is_none() && s.visible_wager.is_none()));
        let mut invalid = frame(2);
        invalid.seats[0].displayed_stack = Some(Reading::current(&invalid, Evidence::trusted(500)));
        invalid.current_capture_validated = false;
        let view = t.observe(&invalid, 200);
        assert!(!view.current_capture_validated);
        assert!(view.seats[0].displayed_stack.is_none());
        assert!(view.gaps.contains(&GapReason::UnvalidatedSource));
    }

    #[test]
    fn frozen_multiway_positions_survive_folds_without_becoming_headsup() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        let first = t.observe(&f, 100);
        advance(&mut f, 2);
        for i in 1..5 {
            f.seats[i].folded = Evidence::trusted(true);
        }
        let view = t.observe(&f, 200);
        assert_eq!(view.positions, first.positions);
        assert_eq!(view.seats[0].position, Some(Position::Button));
        assert_eq!(view.seats[5].position, Some(Position::Cutoff));
        assert_eq!(view.positions.unwrap().dealt_in, [true; 6]);
    }

    #[test]
    fn original_headsup_and_midhand_joins_do_not_use_current_occupancy() {
        let mut f = hand_frame(1);
        for i in [1, 2, 4, 5] {
            f.seats[i].occupant_id = Evidence {
                value: None,
                trusted: true,
                confidence: None,
            };
            f.seats[i].dealt_in = Evidence::trusted(false);
        }
        f.position.small_blind = Evidence::trusted(0);
        f.position.big_blind = Evidence::trusted(3);
        let mut t = Tracker::default();
        let first = t.observe(&f, 100);
        assert_eq!(first.seats[0].position, Some(Position::ButtonSmallBlind));
        assert_eq!(first.positions.unwrap().preflop_order, [0, 3]);
        advance(&mut f, 2);
        f.seats[2].occupant_id = Evidence::trusted(Id(900));
        f.seats[2].dealt_in = Evidence::trusted(true);
        let joined = t.observe(&f, 200);
        assert_eq!(joined.seats[2].position, None);
        assert_eq!(joined.seats[0].position, Some(Position::ButtonSmallBlind));
        advance(&mut f, 3);
        f.hand_id = Evidence::trusted(Id(20));
        f.hand_start = Evidence::trusted(HandStart::BeforeActions);
        f.position.small_blind = Evidence::trusted(2);
        f.position.big_blind = Evidence::trusted(3);
        let meta = f.clone();
        for s in &mut f.seats {
            fresh(&mut s.badge, &meta);
        }
        let next = t.observe(&f, 300);
        assert_eq!(next.seats[2].position, Some(Position::SmallBlind));
        assert_eq!(next.seats[0].position, Some(Position::Button));
    }

    #[test]
    fn missing_button_policy_dealtlineup_and_partial_attach_cannot_freeze_later() {
        for missing in 0..4 {
            let mut f = hand_frame(1);
            match missing {
                0 => f.position.button = Evidence::default(),
                1 => f.position.policy = Evidence::default(),
                2 => f.seats[4].dealt_in = Evidence::default(),
                _ => f.hand_start = Evidence::trusted(HandStart::Partial),
            }
            let mut t = Tracker::default();
            assert!(t.observe(&f, 100).positions.is_none());
            f = hand_frame(2);
            assert!(t.observe(&f, 200).positions.is_none());
        }
    }

    #[test]
    fn uncertain_occupant_reappearance_retires_epoch_and_never_transfers_statistics() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        let old_epoch = t.observe(&f, 100).seats[0].occupant_epoch.unwrap();
        advance(&mut f, 2);
        put_call(&mut f, 0, 1, 1, 100);
        t.observe(&f, 200);
        assert_eq!(t.history().counts.calls, 1);
        advance(&mut f, 3);
        f.seats[0].occupant_id = Evidence::default();
        assert_eq!(t.observe(&f, 300).seats[0].occupant_epoch, None);
        advance(&mut f, 4);
        f.seats[0].occupant_id = Evidence::trusted(Id(100));
        f.seats[0].badge = Some(Reading::current(&f, Evidence::trusted(Badge::Clear)));
        let view = t.observe(&f, 400);
        assert_ne!(view.seats[0].occupant_epoch, Some(old_epoch));
        assert_eq!(view.seats[0].position, None);
        assert_eq!(
            t.history()
                .occupants
                .iter()
                .find(|s| s.seat == 0)
                .unwrap()
                .actions
                .calls,
            0
        );
        assert_eq!(t.history().counts.calls, 1);
    }

    #[test]
    fn retained_field_original_expiry_cannot_be_renewed_by_polling() {
        let mut f = hand_frame(1);
        let retained = f.seats[0].displayed_stack.clone();
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        f.seats[0].displayed_stack = retained;
        f.seats[0]
            .displayed_stack
            .as_mut()
            .unwrap()
            .confirmed_capture = f.capture;
        let view = t.observe(&f, 200);
        assert_eq!(
            view.seats[0]
                .displayed_stack
                .as_ref()
                .unwrap()
                .source_capture,
            capture(1)
        );
        assert_eq!(
            view.seats[0]
                .displayed_stack
                .as_ref()
                .unwrap()
                .expires_at_ms,
            1100
        );
        assert!(t.view(1099).seats[0].displayed_stack.is_some());
        let expired = t.view(1100);
        assert!(expired.current_capture_validated);
        assert!(expired.seats[0].displayed_stack.is_none());
        assert!(expired.seats[1].displayed_stack.is_some());
        assert!(t.view(1200).capture.is_none());
    }

    #[test]
    fn retained_fields_cannot_cross_hand_street_geometry_or_occupant_boundaries() {
        for boundary in 0..4 {
            let mut f = hand_frame(1);
            let mut old = f.seats[0].displayed_stack.clone().unwrap();
            let mut t = Tracker::default();
            t.observe(&f, 100);
            advance(&mut f, 2);
            match boundary {
                0 => {
                    f.hand_id = Evidence::trusted(Id(20));
                    f.hand_start = Evidence::trusted(HandStart::BeforeActions);
                }
                1 => f.street = Evidence::trusted(Street::Flop),
                2 => {
                    f.source_epoch = Id(2);
                    f.hand_id = Evidence::trusted(Id(20));
                }
                _ => f.seats[0].occupant_id = Evidence::trusted(Id(999)),
            }
            // Even rebinding an old read to the new context cannot renew it.
            old.confirmed_capture = f.capture;
            old.hand_id = f.hand_id.known().copied();
            old.street = f.street.known().copied();
            old.source_epoch = f.source_epoch;
            f.seats[0].displayed_stack = Some(old);
            assert!(t.observe(&f, 200).seats[0].displayed_stack.is_none());
        }
    }

    #[test]
    fn call_cost_uses_live_credit_not_visible_wager_ante_or_total_commitment() {
        let mut f = hand_frame(1);
        f.acting_seat = Some(Reading::current(&f, Evidence::trusted(4)));
        f.current_target = Some(Reading::current(&f, Evidence::trusted(30)));
        f.seats[4].live_call_credit = Some(Reading::current(&f, Evidence::trusted(50)));
        f.seats[4].visible_wager = Some(Reading::current(&f, Evidence::trusted(900)));
        f.seats[4].street_commitment = Some(Reading::current(&f, Evidence::trusted(200)));
        f.seats[4].displayed_stack = Some(Reading::current(&f, Evidence::trusted(20)));
        let mut t = Tracker::default();
        let call = t.observe(&f, 100).call_cost.unwrap();
        assert_eq!(call.seat, 4);
        assert_eq!(call.uncapped, 50);
        assert_eq!(call.payable, 20);
        advance(&mut f, 2);
        f.seats[4].live_call_credit = None;
        assert!(t.observe(&f, 200).call_cost.is_none());
    }

    #[test]
    fn current_pot_odds_requires_matching_eligible_sidepot_and_convention() {
        let mut f = hand_frame(1);
        f.acting_seat = Some(Reading::current(&f, Evidence::trusted(0)));
        f.pot = Some(Reading::current(
            &f,
            Evidence::trusted(PotAccounting {
                displayed: 500,
                convention: PotConvention::Unknown,
                outstanding: Some(200),
                ineligible: Some(100),
                pending_returns: Some(0),
                eligible_for: Some(0),
                eligible_call: Some(100),
            }),
        ));
        let mut t = Tracker::default();
        assert!(t.observe(&f, 100).pot_odds.is_none());
        advance(&mut f, 2);
        f.pot
            .as_mut()
            .unwrap()
            .evidence
            .value
            .as_mut()
            .unwrap()
            .convention = PotConvention::IncludesOutstanding;
        let odds = t.observe(&f, 200).pot_odds.unwrap();
        assert_eq!(odds.seat, 0);
        assert_eq!(odds.required_equity, 0.2);
        f.pot.as_mut().unwrap().expires_at_ms = 250;
        advance(&mut f, 3);
        f.pot.as_mut().unwrap().expires_at_ms = 350;
        t.observe(&f, 300);
        assert!(t.view(350).pot_odds.is_none());
        assert!(t.view(350).call_cost.is_some());
    }

    #[test]
    fn stack_drops_wager_disappearance_refunds_and_animations_never_create_actions() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        f.seats[0].displayed_stack = Some(Reading::current(&f, Evidence::trusted(900)));
        f.seats[0].visible_wager = None;
        let view = t.observe(&f, 200);
        assert_eq!(t.history().counts.calls, 0);
        assert_eq!(view.seats[0].live_call_credit.as_ref().unwrap().value, 0);
        assert!(view.gaps.contains(&GapReason::ChipMovement));
        advance(&mut f, 3);
        f.seats[0].displayed_stack = Some(Reading::current(&f, Evidence::trusted(950)));
        f.seats[0].movement = Some(Reading::current(
            &f,
            Evidence::trusted(ChipMovement::Refund),
        ));
        t.observe(&f, 300);
        assert!(t.history().events.iter().any(|e| matches!(
            e.entry,
            LedgerEntry::Movement {
                movement: ChipMovement::Refund,
                ..
            }
        )));
        assert_eq!(t.history().counts.calls, 0);
        assert_eq!(t.history().counts.raises, 0);
    }

    #[test]
    fn street_reset_requires_street_evidence_and_new_explicit_credit_not_disappearing_wagers() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        f.seats[0].visible_wager = None;
        assert_eq!(t.observe(&f, 200).street, Some(Street::Preflop));
        advance(&mut f, 3);
        f.street = Evidence::trusted(Street::Flop);
        f.street_start = Evidence::trusted(true);
        f.preflop_complete = Evidence::trusted(true);
        let meta = f.clone();
        for s in &mut f.seats {
            fresh(&mut s.badge, &meta);
        }
        // Old street-bound credits are withheld, not silently reset to zero.
        let view = t.observe(&f, 300);
        assert!(view.seats[0].live_call_credit.is_none());
        advance(&mut f, 4);
        f.seats[0].live_call_credit = Some(Reading::current(&f, Evidence::trusted(0)));
        assert_eq!(
            t.observe(&f, 400).seats[0]
                .live_call_credit
                .as_ref()
                .unwrap()
                .value,
            0
        );
        assert_eq!(t.history().counts.calls, 0);
    }

    #[test]
    fn badges_persist_flicker_and_renew_with_existing_ledger_provenance() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        put_call(&mut f, 0, 1, 1, 100);
        t.observe(&f, 200);
        let same = t.observe(&f, 200);
        assert_eq!(t.history().counts.calls, 1);
        advance(&mut f, 3);
        t.observe(&f, 300);
        advance(&mut f, 4);
        f.seats[0].badge = Some(Reading::current(&f, Evidence::trusted(Badge::Clear)));
        t.observe(&f, 400);
        advance(&mut f, 5);
        put_call(&mut f, 0, 1, 1, 100);
        t.observe(&f, 500);
        assert_eq!(t.history().counts.calls, 1);
        assert!(same.seats[0].occupant_epoch.is_some());
        assert!(t.history().events.iter().any(|e| matches!(&e.entry,
            LedgerEntry::Action { action } if action.basis == ActionBasis::Badge && action.trusted)));
        advance(&mut f, 6);
        put_call(&mut f, 3, 1, 2, 100);
        t.observe(&f, 600);
        assert_eq!(t.history().counts.calls, 2);
    }

    #[test]
    fn stale_conflicting_sequence_time_and_reused_hand_fail_closed() {
        let mut t = Tracker::default();
        let f = hand_frame(1);
        t.observe(&f, 100);
        let mut later = hand_frame(2);
        later.hand_start = Evidence::default();
        later.seats[0].displayed_stack = Some(Reading::current(&later, Evidence::trusted(500)));
        t.observe(&later, 200);
        assert_eq!(
            t.observe(&f, 200).seats[0]
                .displayed_stack
                .as_ref()
                .unwrap()
                .value,
            500
        );
        let mut conflict = later.clone();
        conflict.capture.ticket = Id(9999);
        assert!(!t.observe(&conflict, 200).current_capture_validated);
        assert!(!t.observe(&later, 200).current_capture_validated);
        let mut reverse = hand_frame(3);
        reverse.capture.captured_at_ms = 50;
        assert!(!t.observe(&reverse, 300).current_capture_validated);
        let mut new = hand_frame(4);
        new.hand_id = Evidence::trusted(Id(20));
        t.observe(&new, 400);
        let reused = hand_frame(5);
        let view = t.observe(&reused, 500);
        assert!(view.current_capture_validated);
        assert!(view.hand_id.is_none());
        assert!(view.call_cost.is_none());
        assert!(view.seats[0].displayed_stack.is_some());
        assert!(t.view(500).gaps.contains(&GapReason::HandIdentityReused));
    }

    #[test]
    fn one_bad_field_never_flips_other_fields_and_forged_retention_is_rejected() {
        let mut f = hand_frame(1);
        f.seats[0].displayed_stack.as_mut().unwrap().source_epoch = Id(99);
        f.seats[1].visible_wager.as_mut().unwrap().expires_at_ms = 5101;
        f.seats[2].live_call_credit.as_mut().unwrap().hand_id = Some(Id(88));
        let mut t = Tracker::default();
        let view = t.observe(&f, 100);
        assert!(view.current_capture_validated);
        assert!(view.seats[0].displayed_stack.is_none());
        assert!(view.seats[0].visible_wager.is_some());
        assert!(view.seats[1].visible_wager.is_none());
        assert!(view.seats[1].displayed_stack.is_some());
        assert!(view.seats[2].live_call_credit.is_none());
        assert!(view.seats[2].displayed_stack.is_some());
        advance(&mut f, 2);
        let retained = f.seats[3].displayed_stack.as_mut().unwrap();
        retained.source_capture = capture(1);
        retained.confirmed_capture = capture(1);
        assert!(t.observe(&f, 200).seats[3].displayed_stack.is_none());
    }

    #[test]
    fn retained_badge_and_movement_cannot_attach_to_a_new_occupant_epoch() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        put_call(&mut f, 0, 1, 1, 100);
        let mut old_badge = f.seats[0].badge.clone().unwrap();
        let mut old_movement = Reading::current(&f, Evidence::trusted(ChipMovement::Refund));
        t.observe(&f, 200);
        advance(&mut f, 3);
        f.seats[0].occupant_id = Evidence::trusted(Id(999));
        old_badge.confirmed_capture = f.capture;
        old_movement.confirmed_capture = f.capture;
        f.seats[0].badge = Some(old_badge);
        f.seats[0].movement = Some(old_movement);
        t.observe(&f, 300);
        assert_eq!(t.history().counts.calls, 1);
        assert!(t.history().events.iter().all(|event| !matches!(
            event.entry,
            LedgerEntry::Movement {
                movement: ChipMovement::Refund,
                ..
            }
        )));
        assert!(t
            .history()
            .occupants
            .iter()
            .all(|seat| seat.occupant_id != t.view(300).seats[0].occupant_epoch.unwrap()));
    }

    #[test]
    fn reopening_views_require_dealt_occupants_and_current_target_increment() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        assert_eq!(t.observe(&f, 100).seats[0].may_raise, Some(true));
        advance(&mut f, 2);
        f.full_raise_increment.as_mut().unwrap().expires_at_ms = 250;
        t.observe(&f, 200);
        assert_eq!(t.view(249).seats[0].may_raise, Some(true));
        assert_eq!(t.view(250).seats[0].may_raise, None);
        let mut heads_up = hand_frame(1);
        for i in 2..6 {
            heads_up.seats[i].occupant_id = Evidence {
                value: None,
                trusted: true,
                confidence: None,
            };
            heads_up.seats[i].dealt_in = Evidence::trusted(false);
        }
        heads_up.position.small_blind = Evidence::trusted(0);
        heads_up.position.big_blind = Evidence::trusted(1);
        let mut hu = Tracker::default();
        let view = hu.observe(&heads_up, 100);
        assert_eq!(view.seats[0].may_raise, Some(true));
        assert!(view.seats[2..].iter().all(|s| s.may_raise.is_none()));
    }

    #[test]
    fn uncorroborated_street_boundary_never_carries_previous_reopening_rights() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        assert_eq!(t.observe(&f, 100).seats[0].may_raise, Some(true));
        f.street = Evidence::trusted(Street::Flop);
        advance(&mut f, 2);
        f.preflop_complete = Evidence::trusted(true);
        let view = t.observe(&f, 200);
        assert_eq!(view.street, Some(Street::Flop));
        assert_eq!(view.seats[0].may_raise, None);
    }

    #[test]
    fn new_capture_session_resets_its_clock_but_retains_prior_history() {
        let mut t = Tracker::default();
        let mut old = frame(100);
        old.capture.captured_at_ms = 500_000;
        old.expires_at_ms = 501_000;
        old.seats[0].displayed_stack = Some(Reading::current(&old, Evidence::trusted(500)));
        t.observe(&old, 500_000);
        let mut new = frame(1);
        new.capture.session_id = Id(200);
        new.seats[0].displayed_stack = Some(Reading::current(&new, Evidence::trusted(700)));
        let view = t.observe(&new, 100);
        assert!(view.current_capture_validated);
        assert_eq!(view.seats[0].displayed_stack.as_ref().unwrap().value, 700);
        assert!(t
            .history()
            .events
            .iter()
            .any(|e| e.capture.session_id == Id(1)));
        assert!(t
            .history()
            .events
            .iter()
            .any(|e| e.capture.session_id == Id(200)));
    }

    #[test]
    fn expired_identity_interval_and_duplicate_id_reject_statistics_transfer() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        let old = t.observe(&f, 100).seats[0].occupant_epoch;
        advance(&mut f, 2);
        f.capture.captured_at_ms = 1200;
        f.expires_at_ms = 2200;
        let view = t.observe(&f, 1200);
        assert_ne!(view.seats[0].occupant_epoch, old);
        assert_eq!(view.seats[0].position, None);
        let mut duplicate = hand_frame(3);
        duplicate.capture.captured_at_ms = 1300;
        duplicate.expires_at_ms = 2300;
        duplicate.seats[2].occupant_id = Evidence::trusted(Id(100));
        let view = t.observe(&duplicate, 1300);
        assert!(view.seats.iter().all(|s| s.occupant_epoch.is_none()));
        assert!(view.gaps.contains(&GapReason::InvalidSnapshot));
    }

    #[test]
    fn supplemental_context_keys_are_bounded_without_discarding_ledger_prefix() {
        let captures = (1..=MAX_SESSION_EVENTS as u64)
            .map(|id| {
                (
                    Id(id),
                    Capture {
                        session_id: Id(id),
                        ..capture(1)
                    },
                )
            })
            .collect();
        let mut t = Tracker {
            captures,
            ..Tracker::default()
        };
        let mut f = frame(1);
        f.capture.session_id = Id(MAX_SESSION_EVENTS as u64 + 1);
        let view = t.observe(&f, 100);
        assert!(!view.current_capture_validated);
        assert_eq!(view.gaps, [GapReason::EventLimit]);
        assert_eq!(t.captures.len(), MAX_SESSION_EVENTS);
    }

    #[test]
    fn observer_actions_drive_reopening_without_replacing_full_increment_on_short_allins() {
        let mut f = hand_frame(1);
        let mut t = Tracker::default();
        t.observe(&f, 100);
        for (sequence, slot, total, all_in, full, kind) in [
            (2, 0, 300, false, Some(true), ActionKind::Raise),
            (3, 1, 300, false, None, ActionKind::Call),
            (4, 2, 350, true, Some(false), ActionKind::Raise),
            (5, 3, 400, true, Some(false), ActionKind::Raise),
            (6, 4, 500, true, Some(false), ActionKind::Raise),
        ] {
            advance(&mut f, sequence);
            f.seats[slot].badge = Some(Reading::current(
                &f,
                Evidence::trusted(Badge::Action(ActionBadge {
                    occurrence: Id(1),
                    action_sequence: Evidence::trusted(sequence - 1),
                    kind: Evidence::trusted(kind),
                    all_in: Evidence::trusted(all_in),
                    full_raise: full.map_or_else(Evidence::default, Evidence::trusted),
                    forced: Evidence::trusted(ForcedAction::Voluntary),
                    amount: Evidence::default(),
                })),
            ));
            f.seats[slot].live_call_credit = Some(Reading::current(&f, Evidence::trusted(total)));
            f.current_target = Some(Reading::current(&f, Evidence::trusted(total)));
            f.full_raise_increment = Some(Reading::current(&f, Evidence::trusted(200)));
            let view = t.observe(&f, sequence * 100);
            if sequence == 4 || sequence == 5 {
                assert_eq!(view.seats[0].may_raise, Some(false));
                assert_eq!(view.seats[1].may_raise, Some(false));
            }
            if sequence == 6 {
                assert_eq!(view.seats[0].may_raise, Some(true));
                assert_eq!(view.seats[1].may_raise, Some(true));
                assert_eq!(view.seats[2].may_raise, Some(false));
            }
            assert_eq!(t.round.as_ref().unwrap().full_raise_increment, Some(200));
        }
        assert_eq!(t.history().counts.raises, 4);
        assert_eq!(t.history().counts.incomplete_raises, 3);
        advance(&mut f, 7);
        f.full_raise_increment = Some(Reading::current(&f, Evidence::trusted(50)));
        let view = t.observe(&f, 700);
        assert!(view.gaps.contains(&GapReason::ContradictoryEvidence));
        assert_eq!(view.seats[0].may_raise, None);
    }

    #[test]
    fn short_bb_nominal_target_is_also_the_ledger_and_reopening_baseline() {
        let mut f = hand_frame(1);
        f.current_target = Some(Reading::current(&f, Evidence::trusted(30)));
        let mut t = Tracker::default();
        assert_eq!(t.observe(&f, 100).seats[0].may_raise, Some(true));
        assert_eq!(t.round.as_ref().unwrap().target, Some(100));
        advance(&mut f, 2);
        f.current_target = Some(Reading::current(&f, Evidence::trusted(200)));
        f.seats[0].live_call_credit = Some(Reading::current(&f, Evidence::trusted(200)));
        f.seats[0].badge = Some(Reading::current(
            &f,
            Evidence::trusted(Badge::Action(ActionBadge {
                occurrence: Id(1),
                action_sequence: Evidence::trusted(1),
                kind: Evidence::trusted(ActionKind::Raise),
                all_in: Evidence::trusted(false),
                full_raise: Evidence::trusted(true),
                forced: Evidence::trusted(ForcedAction::Voluntary),
                amount: Evidence::default(),
            })),
        ));
        t.observe(&f, 200);
        assert_eq!(t.round.as_ref().unwrap().full_raise_increment, Some(100));
        assert_eq!(t.history().counts.raises, 1);
    }

    #[test]
    fn newer_confirmation_cannot_extend_original_lease_or_roll_back_a_field_source() {
        let mut f = hand_frame(1);
        let mut old = f.seats[0].displayed_stack.clone().unwrap();
        let mut t = Tracker::default();
        t.observe(&f, 100);
        advance(&mut f, 2);
        old.confirmed_capture = f.capture;
        old.expires_at_ms = 5100;
        f.seats[0].displayed_stack = Some(old.clone());
        assert_eq!(
            t.observe(&f, 200).seats[0]
                .displayed_stack
                .as_ref()
                .unwrap()
                .expires_at_ms,
            1100
        );
        assert!(t.view(1100).seats[0].displayed_stack.is_none());
        assert!(t.view(1100).seats[1].displayed_stack.is_some());
        let mut rollback = Tracker::default();
        let mut f = hand_frame(1);
        rollback.observe(&f, 100);
        advance(&mut f, 2);
        f.seats[0].displayed_stack = Some(Reading::current(&f, Evidence::trusted(800)));
        rollback.observe(&f, 200);
        advance(&mut f, 3);
        old.confirmed_capture = f.capture;
        f.seats[0].displayed_stack = Some(old);
        let view = rollback.observe(&f, 300);
        assert!(view.seats[0].displayed_stack.is_none());
        assert!(view.seats[1].displayed_stack.is_some());
    }
}
