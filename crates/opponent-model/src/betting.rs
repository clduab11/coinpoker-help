//! Chip accounting. Integer units must be validated by the caller.
//! Visible wagers, stacks, dead money and total contributions are not live credit.

use serde::{Deserialize, Serialize};

use crate::observer::{ActionKind, ActionRecord, Evidence, ForcedAction, PHYSICAL_SEATS};

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct CallContext {
    pub acting_seat: Evidence<u8>,
    /// Nominal bring-in, even when the BB posted a smaller all-in amount.
    pub legal_bring_in: Evidence<u64>,
    pub current_target: Evidence<u64>,
    /// EXCLUDES antes, dead blinds and money already swept from this street.
    pub live_credit: Evidence<u64>,
    pub remaining_stack: Evidence<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallCost {
    pub seat: u8,
    pub target: u64,
    pub live_credit: u64,
    pub uncapped: u64,
    pub payable: u64,
}

pub fn additional_call_cost(context: &CallContext) -> Option<CallCost> {
    let seat = *context.acting_seat.known()?;
    if usize::from(seat) >= PHYSICAL_SEATS {
        return None;
    }
    let target = (*context.legal_bring_in.known()?).max(*context.current_target.known()?);
    let credit = *context.live_credit.known()?;
    let uncapped = target.checked_sub(credit)?;
    Some(CallCost {
        seat,
        target,
        live_credit: credit,
        uncapped,
        payable: uncapped.min(*context.remaining_stack.known()?),
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PotConvention {
    IncludesOutstanding,
    ExcludesOutstanding,
    Unknown,
}

/// Accounting must be established FOR this seat and its capped call, including
/// side-pot eligibility, known refunds and rake. None never means zero.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PotAccounting {
    pub displayed: u64,
    pub convention: PotConvention,
    pub outstanding: Option<u64>,
    pub ineligible: Option<u64>,
    pub pending_returns: Option<u64>,
    pub eligible_for: Option<u8>,
    pub eligible_call: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PotOdds {
    pub seat: u8,
    pub eligible_pot: u64,
    pub call_cost: u64,
    pub required_equity: f64,
}

pub fn pot_odds(call: &CallCost, accounting: &Evidence<PotAccounting>) -> Option<PotOdds> {
    let pot = accounting.known()?;
    if pot.eligible_for != Some(call.seat) || pot.eligible_call != Some(call.payable) {
        return None;
    }
    let gross = match pot.convention {
        PotConvention::IncludesOutstanding => pot.displayed,
        PotConvention::ExcludesOutstanding => pot.displayed.checked_add(pot.outstanding?)?,
        PotConvention::Unknown => return None,
    };
    let eligible = gross
        .checked_sub(pot.ineligible?)?
        .checked_sub(pot.pending_returns?)?;
    let denominator = eligible.checked_add(call.payable)?;
    (denominator != 0).then_some(PotOdds {
        seat: call.seat,
        eligible_pot: eligible,
        call_cost: call.payable,
        required_equity: call.payable as f64 / denominator as f64,
    })
}

/// A supplemental per-player reopening ledger, not an action extractor. Feed
/// only the existing Observer's ordered, trusted records. A gap invalidates it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BettingRound {
    pub target: Option<u64>,
    pub full_raise_increment: Option<u64>,
    acted_at: [Option<u64>; PHYSICAL_SEATS],
    can_act: [Option<bool>; PHYSICAL_SEATS],
    complete_start: bool,
}

impl BettingRound {
    pub fn new(target: u64, full_raise_increment: u64) -> Option<Self> {
        (full_raise_increment != 0).then_some(Self {
            target: Some(target),
            full_raise_increment: Some(full_raise_increment),
            acted_at: [None; PHYSICAL_SEATS],
            can_act: [Some(true); PHYSICAL_SEATS],
            complete_start: true,
        })
    }

    pub fn invalidate(&mut self) {
        self.target = None;
        self.full_raise_increment = None;
        self.acted_at = [None; PHYSICAL_SEATS];
        self.can_act = [None; PHYSICAL_SEATS];
        self.complete_start = false;
    }

    pub fn may_raise(&self, seat: u8) -> Option<bool> {
        let index = usize::from(seat);
        if index >= PHYSICAL_SEATS || !self.complete_start {
            return None;
        }
        if !self.can_act[index]? {
            return Some(false);
        }
        Some(match self.acted_at[index] {
            None => true,
            Some(last) => self.target?.checked_sub(last)? >= self.full_raise_increment?,
        })
    }

    pub fn record_action(&mut self, action: &ActionRecord) -> bool {
        let index = usize::from(action.seat);
        let valid = (|| {
            if index >= PHYSICAL_SEATS || !action.trusted || !self.complete_start {
                return None;
            }
            let forced = action.forced?;
            if forced != ForcedAction::Voluntary {
                // Antes/dead money never raise the target or grant call credit.
                if matches!(
                    forced,
                    ForcedAction::SmallBlind | ForcedAction::BigBlind | ForcedAction::Straddle
                ) {
                    self.target = Some(self.target?.max(action.commitment?));
                    self.can_act[index] = action.all_in.map(|all_in| !all_in);
                }
                return Some(());
            }
            if self.can_act[index] != Some(true) {
                return None;
            }
            let target = self.target?;
            match action.kind? {
                ActionKind::Fold => self.can_act[index] = Some(false),
                ActionKind::Check => {
                    if action.commitment? != target {
                        return None;
                    }
                }
                ActionKind::Call => {
                    let total = action.commitment?;
                    if total > target || (total < target && action.all_in != Some(true)) {
                        return None;
                    }
                }
                ActionKind::Bet | ActionKind::Raise => {
                    let total = action.commitment?;
                    let increase = total.checked_sub(target).filter(|v| *v != 0)?;
                    let full = increase >= self.full_raise_increment?;
                    if action.full_raise != Some(full)
                        || (!full && action.all_in != Some(true))
                        || self.may_raise(action.seat) != Some(true)
                        || (action.kind == Some(ActionKind::Bet) && target != 0)
                    {
                        return None;
                    }
                    if full {
                        self.full_raise_increment = Some(increase);
                    }
                    self.target = Some(total);
                }
            }
            self.acted_at[index] = self.target;
            if action.kind != Some(ActionKind::Fold) {
                self.can_act[index] = action.all_in.map(|all_in| !all_in);
            }
            Some(())
        })()
        .is_some();
        if !valid {
            self.invalidate();
        }
        valid
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::observer::{ActionBasis, Id};

    fn action(
        seat: u8,
        kind: ActionKind,
        total: u64,
        all_in: bool,
        full: Option<bool>,
    ) -> ActionRecord {
        ActionRecord {
            seat,
            occupant_id: Id(u64::from(seat) + 1),
            occurrence: Id(1),
            action_sequence: Some(1),
            kind: Some(kind),
            all_in: Some(all_in),
            full_raise: full,
            forced: Some(ForcedAction::Voluntary),
            amount: None,
            stack: None,
            commitment: Some(total),
            trusted: true,
            kind_confidence: None,
            basis: ActionBasis::Badge,
            preflop_raise_ordinal: None,
        }
    }

    #[test]
    fn call_requires_every_validated_field_and_never_defaults_to_zero() {
        let c = CallContext {
            acting_seat: Evidence::trusted(5),
            legal_bring_in: Evidence::trusted(100),
            current_target: Evidence::trusted(300),
            live_credit: Evidence::trusted(100),
            remaining_stack: Evidence::trusted(500),
        };
        assert_eq!(additional_call_cost(&c).unwrap().payable, 200);
        for field in 0..5 {
            let mut unknown = c.clone();
            match field {
                0 => unknown.acting_seat = Evidence::default(),
                1 => unknown.legal_bring_in = Evidence::default(),
                2 => unknown.current_target = Evidence::default(),
                3 => unknown.live_credit = Evidence::default(),
                _ => unknown.remaining_stack = Evidence::default(),
            }
            assert!(additional_call_cost(&unknown).is_none());
        }
        let mut bad = c;
        bad.acting_seat = Evidence::trusted(6);
        assert!(additional_call_cost(&bad).is_none());
        bad.acting_seat = Evidence::trusted(5);
        bad.live_credit = Evidence::trusted(301);
        assert!(additional_call_cost(&bad).is_none());
        bad.live_credit = Evidence::trusted(300);
        assert_eq!(additional_call_cost(&bad).unwrap().payable, 0);
        bad.current_target.confidence = Some(f64::NAN);
        assert!(additional_call_cost(&bad).is_none());
    }

    #[test]
    fn short_big_blind_nominal_bringin_and_stack_cap_not_ante_credit() {
        let c = CallContext {
            acting_seat: Evidence::trusted(1),
            legal_bring_in: Evidence::trusted(100),
            current_target: Evidence::trusted(30),
            live_credit: Evidence::trusted(50),
            remaining_stack: Evidence::trusted(20),
        };
        assert_eq!(
            additional_call_cost(&c),
            Some(CallCost {
                seat: 1,
                target: 100,
                live_credit: 50,
                uncapped: 50,
                payable: 20
            })
        );
        let mut round = BettingRound::new(100, 100).unwrap();
        let mut ante = action(4, ActionKind::Bet, 999, false, None);
        ante.forced = Some(ForcedAction::Ante);
        assert!(round.record_action(&ante));
        assert_eq!(round.target, Some(100));
        assert_eq!(round.may_raise(4), Some(true));
    }

    #[test]
    fn full_raises_short_and_cumulative_allins_preserve_increment_and_individual_rights() {
        let mut r = BettingRound::new(100, 100).unwrap();
        assert!(r.record_action(&action(0, ActionKind::Raise, 300, false, Some(true))));
        assert_eq!(r.full_raise_increment, Some(200));
        assert!(r.record_action(&action(1, ActionKind::Call, 300, false, None)));
        assert!(r.record_action(&action(2, ActionKind::Raise, 350, true, Some(false))));
        assert_eq!(r.may_raise(0), Some(false));
        assert_eq!(r.may_raise(1), Some(false));
        assert_eq!(r.may_raise(5), Some(true));
        assert!(r.record_action(&action(3, ActionKind::Raise, 400, true, Some(false))));
        assert_eq!(r.may_raise(0), Some(false));
        assert!(r.record_action(&action(4, ActionKind::Raise, 500, true, Some(false))));
        assert_eq!(r.full_raise_increment, Some(200));
        assert_eq!(r.may_raise(0), Some(true));
        assert_eq!(r.may_raise(1), Some(true));
        assert_eq!(r.may_raise(2), Some(false));
        assert!(r.record_action(&action(0, ActionKind::Raise, 700, false, Some(true))));
        assert_eq!(r.full_raise_increment, Some(200));
        assert_eq!(r.may_raise(0), Some(false));
        assert_eq!(r.may_raise(1), Some(true));
    }

    #[test]
    fn cumulative_short_reopens_only_seats_facing_a_full_increment_since_last_action() {
        let mut r = BettingRound::new(100, 100).unwrap();
        assert!(r.record_action(&action(0, ActionKind::Call, 100, false, None)));
        assert!(r.record_action(&action(1, ActionKind::Raise, 150, true, Some(false))));
        assert!(r.record_action(&action(2, ActionKind::Call, 150, false, None)));
        assert!(r.record_action(&action(3, ActionKind::Raise, 200, true, Some(false))));
        assert_eq!(r.may_raise(0), Some(true));
        assert_eq!(r.may_raise(2), Some(false));
        assert_eq!(r.full_raise_increment, Some(100));
        assert!(r.record_action(&action(2, ActionKind::Call, 200, false, None)));
        assert_eq!(r.may_raise(2), Some(false));
    }

    #[test]
    fn folds_allin_calls_illegal_reopens_unknown_actions_and_street_reset() {
        let mut r = BettingRound::new(100, 100).unwrap();
        assert!(r.record_action(&action(0, ActionKind::Fold, 0, false, None)));
        assert_eq!(r.may_raise(0), Some(false));
        assert!(r.record_action(&action(1, ActionKind::Call, 40, true, None)));
        assert_eq!(r.may_raise(1), Some(false));
        assert!(r.record_action(&action(2, ActionKind::Call, 100, false, None)));
        assert!(!r.record_action(&action(2, ActionKind::Raise, 200, false, Some(true))));
        assert_eq!(r.may_raise(3), None);
        assert_eq!(r.full_raise_increment, None);
        assert!(BettingRound::new(0, 0).is_none());
        let mut flop = BettingRound::new(0, 100).unwrap();
        assert!(flop.record_action(&action(2, ActionKind::Check, 0, false, None)));
        assert!(flop.record_action(&action(3, ActionKind::Bet, 200, false, Some(true))));
        assert_eq!(flop.may_raise(2), Some(true));
        assert_eq!(flop.full_raise_increment, Some(200));
        let mut invalid = action(4, ActionKind::Call, 200, false, None);
        invalid.trusted = false;
        assert!(!flop.record_action(&invalid));
        assert_eq!(flop.may_raise(4), None);
    }

    #[test]
    fn pot_odds_known_convention_sidepot_eligibility_returns_and_seat_label() {
        let call = CallCost {
            seat: 3,
            target: 100,
            live_credit: 50,
            uncapped: 50,
            payable: 50,
        };
        let mut p = PotAccounting {
            displayed: 500,
            convention: PotConvention::IncludesOutstanding,
            outstanding: Some(200),
            ineligible: Some(100),
            pending_returns: Some(50),
            eligible_for: Some(3),
            eligible_call: Some(50),
        };
        let odds = pot_odds(&call, &Evidence::trusted(p.clone())).unwrap();
        assert_eq!(odds.seat, 3);
        assert_eq!(odds.eligible_pot, 350);
        assert_eq!(odds.required_equity, 0.125);
        p.displayed = 300;
        p.convention = PotConvention::ExcludesOutstanding;
        assert_eq!(pot_odds(&call, &Evidence::trusted(p.clone())), Some(odds));
        for field in 0..6 {
            let mut unknown = p.clone();
            match field {
                0 => unknown.convention = PotConvention::Unknown,
                1 => unknown.outstanding = None,
                2 => unknown.ineligible = None,
                3 => unknown.pending_returns = None,
                4 => unknown.eligible_for = Some(4),
                _ => unknown.eligible_call = Some(20),
            }
            assert!(pot_odds(&call, &Evidence::trusted(unknown)).is_none());
        }
        p.pending_returns = Some(501);
        assert!(pot_odds(&call, &Evidence::trusted(p.clone())).is_none());
        p.displayed = u64::MAX;
        assert!(pot_odds(&call, &Evidence::trusted(p)).is_none());
    }

    #[test]
    fn unknown_allin_status_is_not_false_and_short_bb_allin_cannot_act() {
        let mut r = BettingRound::new(100, 100).unwrap();
        let mut blind = action(1, ActionKind::Call, 30, true, None);
        blind.forced = Some(ForcedAction::BigBlind);
        assert!(r.record_action(&blind));
        assert_eq!(r.target, Some(100));
        assert_eq!(r.may_raise(1), Some(false));
        let mut call = action(2, ActionKind::Call, 100, false, None);
        call.all_in = None;
        assert!(r.record_action(&call));
        assert_eq!(r.may_raise(2), None);
        assert!(r.record_action(&action(3, ActionKind::Raise, 200, false, Some(true))));
        assert_eq!(r.may_raise(2), None);
    }
}
