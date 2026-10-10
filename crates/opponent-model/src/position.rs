//! Six physical slots, clockwise: top, upper right, lower right, bottom,
//! lower left, upper left. Nine-handed terminology is reference-only.
//! General rules do not establish the client's dead/moving-button policy.

use serde::{Deserialize, Serialize};

use crate::observer::{Evidence, HandStart, Id, PHYSICAL_SEATS};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ButtonPolicy {
    Moving,
    Dead,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct PositionEvidence {
    pub button: Evidence<u8>,
    pub small_blind: Evidence<u8>,
    pub big_blind: Evidence<u8>,
    pub policy: Evidence<ButtonPolicy>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Position {
    UtgLojack,
    Hijack,
    Cutoff,
    Button,
    SmallBlind,
    BigBlind,
    ButtonSmallBlind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PositionGroup {
    Early,
    Middle,
    Late,
    SmallBlind,
    BigBlind,
}

impl Position {
    pub fn group(self) -> PositionGroup {
        match self {
            Self::UtgLojack => PositionGroup::Early,
            Self::Hijack => PositionGroup::Middle,
            Self::Cutoff | Self::Button => PositionGroup::Late,
            Self::SmallBlind | Self::ButtonSmallBlind => PositionGroup::SmallBlind,
            Self::BigBlind => PositionGroup::BigBlind,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PositionMap {
    pub hand_id: Id,
    pub dealt_in: [bool; PHYSICAL_SEATS],
    pub positions: [Option<Position>; PHYSICAL_SEATS],
    pub preflop_order: Vec<u8>,
    pub postflop_order: Vec<u8>,
}

impl PositionMap {
    /// Freeze once, before voluntary actions. Occupancy/survivors are NOT a
    /// substitute for the original dealt-in roster. An empty dead button (or
    /// missing/dead SB) needs client-specific rules: deliberately unsupported.
    pub fn freeze(
        hand_id: &Evidence<Id>,
        start: &Evidence<HandStart>,
        evidence: &PositionEvidence,
        roster: &[Evidence<bool>; PHYSICAL_SEATS],
    ) -> Option<Self> {
        let hand_id = *hand_id.known().filter(|id| id.0 != 0)?;
        if start.known() != Some(&HandStart::BeforeActions) {
            return None;
        }
        let button = usize::from(*evidence.button.known()?);
        let sb = *evidence.small_blind.known()?;
        let bb = *evidence.big_blind.known()?;
        evidence.policy.known()?;
        let mut dealt_in = [false; PHYSICAL_SEATS];
        for (slot, dealt) in roster.iter().enumerate() {
            dealt_in[slot] = *dealt.known()?;
        }
        if button >= PHYSICAL_SEATS || !dealt_in[button] {
            return None;
        }
        let clockwise: Vec<u8> = (0..PHYSICAL_SEATS)
            .map(|offset| (button + offset) % PHYSICAL_SEATS)
            .filter(|slot| dealt_in[*slot])
            .map(|slot| slot as u8)
            .collect();
        let count = clockwise.len();
        if !(2..=PHYSICAL_SEATS).contains(&count) {
            return None;
        }
        let heads_up = count == 2;
        if sb != clockwise[usize::from(!heads_up)] || bb != clockwise[if heads_up { 1 } else { 2 }]
        {
            return None;
        }
        let mut positions = [None; PHYSICAL_SEATS];
        if heads_up {
            positions[button] = Some(Position::ButtonSmallBlind);
            positions[usize::from(bb)] = Some(Position::BigBlind);
        } else {
            positions[button] = Some(Position::Button);
            positions[usize::from(sb)] = Some(Position::SmallBlind);
            positions[usize::from(bb)] = Some(Position::BigBlind);
            let names = [Position::UtgLojack, Position::Hijack, Position::Cutoff];
            for (seat, name) in clockwise[3..].iter().zip(&names[6 - count..]) {
                positions[usize::from(*seat)] = Some(*name);
            }
        }
        let rotate = |offset| {
            clockwise[offset..]
                .iter()
                .chain(&clockwise[..offset])
                .copied()
                .collect()
        };
        Some(Self {
            hand_id,
            dealt_in,
            positions,
            preflop_order: rotate(if heads_up { 0 } else { 3 % count }),
            postflop_order: rotate(1),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map(mask: u8, button: u8, policy: ButtonPolicy) -> Option<PositionMap> {
        let slots: Vec<u8> = (0..6)
            .map(|i| (button + i) % 6)
            .filter(|i| mask & (1 << i) != 0)
            .collect();
        let evidence = PositionEvidence {
            button: Evidence::trusted(button),
            small_blind: Evidence::trusted(slots[usize::from(slots.len() != 2)]),
            big_blind: Evidence::trusted(slots[if slots.len() == 2 { 1 } else { 2 }]),
            policy: Evidence::trusted(policy),
        };
        PositionMap::freeze(
            &Evidence::trusted(Id(1)),
            &Evidence::trusted(HandStart::BeforeActions),
            &evidence,
            &std::array::from_fn(|i| Evidence::trusted(mask & (1 << i) != 0)),
        )
    }

    #[test]
    fn every_dealer_every_two_to_six_dealt_roster_both_explicit_policies() {
        for policy in [ButtonPolicy::Moving, ButtonPolicy::Dead] {
            for mask in 0u8..64 {
                if mask.count_ones() < 2 {
                    continue;
                }
                for button in 0..6 {
                    if mask & (1 << button) == 0 {
                        continue;
                    }
                    let map = map(mask, button, policy).unwrap();
                    assert_eq!(
                        map.positions.iter().flatten().count(),
                        mask.count_ones() as usize
                    );
                    assert_eq!(map.preflop_order.len(), mask.count_ones() as usize);
                    assert_eq!(map.postflop_order.len(), mask.count_ones() as usize);
                    for i in 0..6 {
                        assert_eq!(map.positions[i].is_some(), mask & (1 << i) != 0);
                    }
                    if mask.count_ones() == 2 {
                        assert_eq!(
                            map.positions[usize::from(button)],
                            Some(Position::ButtonSmallBlind)
                        );
                        assert_eq!(map.preflop_order[0], button);
                        assert_eq!(map.postflop_order[1], button);
                    } else {
                        assert_eq!(map.positions[usize::from(button)], Some(Position::Button));
                        assert_eq!(
                            map.preflop_order[map.preflop_order.len() - 1],
                            map.postflop_order[1]
                        );
                        assert_eq!(map.postflop_order.last(), Some(&button));
                    }
                }
            }
        }
    }

    #[test]
    fn sixmax_names_and_chosen_groups_are_exact_clockwise_slots() {
        let map = map(63, 0, ButtonPolicy::Moving).unwrap();
        assert_eq!(
            map.positions,
            [
                Some(Position::Button),
                Some(Position::SmallBlind),
                Some(Position::BigBlind),
                Some(Position::UtgLojack),
                Some(Position::Hijack),
                Some(Position::Cutoff)
            ]
        );
        assert_eq!(map.preflop_order, [3, 4, 5, 0, 1, 2]);
        assert_eq!(map.postflop_order, [1, 2, 3, 4, 5, 0]);
        assert_eq!(Position::UtgLojack.group(), PositionGroup::Early);
        assert_eq!(Position::Hijack.group(), PositionGroup::Middle);
        assert_eq!(Position::Cutoff.group(), PositionGroup::Late);
        assert_eq!(Position::Button.group(), PositionGroup::Late);
        assert_eq!(Position::SmallBlind.group(), PositionGroup::SmallBlind);
        assert_eq!(Position::BigBlind.group(), PositionGroup::BigBlind);
    }

    #[test]
    fn missing_button_blinds_policy_roster_and_empty_dead_button_stay_unknown() {
        let hand = Evidence::trusted(Id(1));
        let start = Evidence::trusted(HandStart::BeforeActions);
        let roster = std::array::from_fn(|_| Evidence::trusted(true));
        let good = PositionEvidence {
            button: Evidence::trusted(0),
            small_blind: Evidence::trusted(1),
            big_blind: Evidence::trusted(2),
            policy: Evidence::trusted(ButtonPolicy::Moving),
        };
        for field in 0..4 {
            let mut e = good.clone();
            match field {
                0 => e.button = Evidence::default(),
                1 => e.small_blind = Evidence::default(),
                2 => e.big_blind = Evidence::default(),
                _ => e.policy = Evidence::default(),
            }
            assert!(PositionMap::freeze(&hand, &start, &e, &roster).is_none());
        }
        let mut partial = roster.clone();
        partial[4] = Evidence::default();
        assert!(PositionMap::freeze(&hand, &start, &good, &partial).is_none());
        let mut empty_button = roster.clone();
        empty_button[0] = Evidence::trusted(false);
        let mut dead = good.clone();
        dead.policy = Evidence::trusted(ButtonPolicy::Dead);
        assert!(PositionMap::freeze(&hand, &start, &dead, &empty_button).is_none());
        assert!(PositionMap::freeze(
            &hand,
            &Evidence::trusted(HandStart::Partial),
            &good,
            &roster
        )
        .is_none());
        let mut wrong = good;
        wrong.button = Evidence::trusted(9);
        assert!(PositionMap::freeze(&hand, &start, &wrong, &roster).is_none());
        wrong.button = Evidence::trusted(0);
        wrong.big_blind = Evidence::trusted(5);
        assert!(PositionMap::freeze(&hand, &start, &wrong, &roster).is_none());
    }
}
