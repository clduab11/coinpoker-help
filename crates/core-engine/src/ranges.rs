//! Six-handed preflop opening ranges and hand-notation parsing.
//!
//! Deterministic lookup tables transcribed from the reference card
//! "Before the flop, six-handed" (`screenshot-2.png`, repository root).
//! The card prints three cumulative tiers, each with the cumulative
//! share of all 1326 starting combinations it covers:
//!
//! 1. From any seat (14%) — the base range every opening seat shares.
//! 2. Add from the hijack and cutoff (26%).
//! 3. Add on the small blind and button (43%).
//!
//! The big blind is already invested and never opens preflop.
//!
//! # Seating convention
//!
//! Six-handed seating is UTG, HJ, CO, BTN, SB, BB. The card's tiers
//! name the hijack, cutoff, small blind, and button explicitly, which
//! fixes the six-seat convention used here. Nine-handed tables use the
//! position names of `poker-info-sheet.pdf`; [`crate::table_rules`]
//! maps them onto these six (UTG+1, MP1, and MP2 open the tier-1 base
//! range, same as UTG).
//!
//! # Provenance and verification
//!
//! A first machine transcription dropped the card's dash ranges
//! (`A9s-A6s` read as only `A9s` and `A6s`) and misread several tokens;
//! it covered 8.7% of combinations where the card prints 14%. The
//! tokens below were re-read from the card at 3x magnification and are
//! checked by the printed percentages: exact coverage is 190, 338 and
//! 574 combinations (14.33%, 25.49%, 43.29%) against the printed 14%,
//! 26% and 43%. The card rounds 25.49% up to 26%, as its odds table
//! also rounds loosely; tests accept one percentage point.

use std::fmt;

use thiserror::Error;

use crate::equity::Rank;

/// Every rank in ascending order.
const ALL_RANKS: [Rank; 13] = [
    Rank::Two,
    Rank::Three,
    Rank::Four,
    Rank::Five,
    Rank::Six,
    Rank::Seven,
    Rank::Eight,
    Rank::Nine,
    Rank::Ten,
    Rank::Jack,
    Rank::Queen,
    Rank::King,
    Rank::Ace,
];

fn rank_notation(rank: Rank) -> char {
    match rank {
        Rank::Two => '2',
        Rank::Three => '3',
        Rank::Four => '4',
        Rank::Five => '5',
        Rank::Six => '6',
        Rank::Seven => '7',
        Rank::Eight => '8',
        Rank::Nine => '9',
        Rank::Ten => 'T',
        Rank::Jack => 'J',
        Rank::Queen => 'Q',
        Rank::King => 'K',
        Rank::Ace => 'A',
    }
}

/// Six-handed seating positions, in preflop action order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Position6max {
    /// Under the gun — first to act preflop; opens the base range.
    Utg,
    /// Hijack.
    Hj,
    /// Cutoff.
    Co,
    /// Button.
    Btn,
    /// Small blind.
    Sb,
    /// Big blind — already invested, never opens preflop.
    Bb,
}

impl Position6max {
    /// All six positions in preflop action order.
    pub const ALL: [Position6max; 6] = [
        Position6max::Utg,
        Position6max::Hj,
        Position6max::Co,
        Position6max::Btn,
        Position6max::Sb,
        Position6max::Bb,
    ];
}

impl fmt::Display for Position6max {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            Position6max::Utg => "UTG",
            Position6max::Hj => "HJ",
            Position6max::Co => "CO",
            Position6max::Btn => "BTN",
            Position6max::Sb => "SB",
            Position6max::Bb => "BB",
        };
        f.write_str(label)
    }
}

/// A class of starting hands sharing ranks and suitedness, e.g. `AJs`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum HoleClass {
    /// A pocket pair, e.g. `AA`.
    Pair(Rank),
    /// Two suited cards, high rank first, e.g. `AJs`.
    Suited(Rank, Rank),
    /// Two offsuit cards, high rank first, e.g. `ATo`.
    Offsuit(Rank, Rank),
}

impl HoleClass {
    /// Number of distinct two-card combinations in the class:
    /// 6 for a pair, 4 suited, 12 offsuit (1326 over all 169 classes).
    pub const fn combos(self) -> u32 {
        match self {
            HoleClass::Pair(_) => 6,
            HoleClass::Suited(..) => 4,
            HoleClass::Offsuit(..) => 12,
        }
    }

    /// Classify two hole cards given in any order.
    pub fn from_ranks(a: Rank, b: Rank, suited: bool) -> Self {
        if a == b {
            return HoleClass::Pair(a);
        }
        let (high, low) = if a > b { (a, b) } else { (b, a) };
        if suited {
            HoleClass::Suited(high, low)
        } else {
            HoleClass::Offsuit(high, low)
        }
    }
}

impl fmt::Display for HoleClass {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HoleClass::Pair(rank) => write!(f, "{}{}", rank_notation(*rank), rank_notation(*rank)),
            HoleClass::Suited(high, low) => {
                write!(f, "{}{}s", rank_notation(*high), rank_notation(*low))
            }
            HoleClass::Offsuit(high, low) => {
                write!(f, "{}{}o", rank_notation(*high), rank_notation(*low))
            }
        }
    }
}

/// Errors produced by the notation parser.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum RangeError {
    /// The token is not valid hand notation.
    #[error("invalid hand notation: `{token}`")]
    InvalidToken { token: String },
    /// A character is not a valid card rank.
    #[error("invalid rank character: `{character}`")]
    InvalidRank { character: char },
    /// Two different ranks were given without a suited/offsuit suffix.
    #[error("pair notation must repeat one rank: `{token}`")]
    InvalidPair { token: String },
    /// The first rank does not outrank the second.
    #[error("high card must outrank low card: `{token}`")]
    HighCardNotHigher { token: String },
}

fn parse_rank(character: char) -> Option<Rank> {
    ALL_RANKS
        .iter()
        .copied()
        .find(|rank| rank_notation(*rank) == character.to_ascii_uppercase())
}

/// Expand one notation token into the hand classes it covers.
///
/// Supported grammar, as printed on the reference sheet:
///
/// - `77` — exactly the pocket pair; `77+` — the pair and every
///   stronger pair up through `AA`.
/// - `AJs` — exactly that suited hand; `AJs+` — the hand and every
///   stronger suited hand sharing the high card (`AJs`, `AQs`, `AKs`).
/// - `ATo` — exactly that offsuit hand; `ATo+` — the hand and every
///   stronger offsuit hand sharing the high card.
/// - `A5s-A2s` / `A7o-A2o` — every hand sharing the high card and
///   suitedness from the right-hand kicker up to the left-hand kicker,
///   inclusive (`A5s`, `A4s`, `A3s`, `A2s`).
pub fn expand_notation(token: &str) -> Result<Vec<HoleClass>, RangeError> {
    let token = token.trim();
    let invalid = || RangeError::InvalidToken {
        token: token.to_string(),
    };

    if let Some((upper, lower)) = token.split_once('-') {
        return expand_dash_range(token, upper, lower);
    }

    let (body, plus) = match token.strip_suffix('+') {
        Some(rest) => (rest, true),
        None => (token, false),
    };

    let characters: Vec<char> = body.chars().collect();
    match characters.len() {
        2 => {
            let high = parse_rank(characters[0]).ok_or(RangeError::InvalidRank {
                character: characters[0],
            })?;
            let low = parse_rank(characters[1]).ok_or(RangeError::InvalidRank {
                character: characters[1],
            })?;
            if high != low {
                return Err(RangeError::InvalidPair {
                    token: token.to_string(),
                });
            }
            let low_index = rank_index(high);
            if plus {
                Ok(ALL_RANKS[low_index..]
                    .iter()
                    .copied()
                    .map(HoleClass::Pair)
                    .collect())
            } else {
                Ok(vec![HoleClass::Pair(high)])
            }
        }
        3 => {
            let high = parse_rank(characters[0]).ok_or(RangeError::InvalidRank {
                character: characters[0],
            })?;
            let low = parse_rank(characters[1]).ok_or(RangeError::InvalidRank {
                character: characters[1],
            })?;
            if high <= low {
                return Err(RangeError::HighCardNotHigher {
                    token: token.to_string(),
                });
            }
            let suited = match characters[2] {
                's' | 'S' => true,
                'o' | 'O' => false,
                other => {
                    return Err(RangeError::InvalidRank { character: other });
                }
            };
            if !plus {
                let class = if suited {
                    HoleClass::Suited(high, low)
                } else {
                    HoleClass::Offsuit(high, low)
                };
                return Ok(vec![class]);
            }
            let low_index = rank_index(low);
            let high_index = rank_index(high);
            Ok(ALL_RANKS[low_index..high_index]
                .iter()
                .copied()
                .map(|card_low| {
                    if suited {
                        HoleClass::Suited(high, card_low)
                    } else {
                        HoleClass::Offsuit(high, card_low)
                    }
                })
                .collect())
        }
        _ => Err(invalid()),
    }
}

/// Expand `XYs-XZs` / `XYo-XZo`: both ends single non-pair hands with
/// the same high card and suitedness, the left kicker above the right.
fn expand_dash_range(token: &str, upper: &str, lower: &str) -> Result<Vec<HoleClass>, RangeError> {
    let invalid = || RangeError::InvalidToken {
        token: token.to_string(),
    };
    if upper.ends_with('+') || lower.ends_with('+') || lower.contains('-') {
        return Err(invalid());
    }
    let single = |part: &str| -> Result<HoleClass, RangeError> {
        match expand_notation(part)?.as_slice() {
            [class] => Ok(*class),
            _ => Err(invalid()),
        }
    };
    let (high, start, end, suited) = match (single(upper)?, single(lower)?) {
        (HoleClass::Suited(high, start), HoleClass::Suited(other, end)) if high == other => {
            (high, start, end, true)
        }
        (HoleClass::Offsuit(high, start), HoleClass::Offsuit(other, end)) if high == other => {
            (high, start, end, false)
        }
        _ => return Err(invalid()),
    };
    if start <= end {
        return Err(invalid());
    }
    Ok(ALL_RANKS[rank_index(end)..=rank_index(start)]
        .iter()
        .copied()
        .map(|low| {
            if suited {
                HoleClass::Suited(high, low)
            } else {
                HoleClass::Offsuit(high, low)
            }
        })
        .collect())
}

fn rank_index(rank: Rank) -> usize {
    ALL_RANKS
        .iter()
        .position(|&candidate| candidate == rank)
        .expect("rank comes from ALL_RANKS")
}

/// One printed tier of the six-handed opening ranges.
pub struct RangeTier {
    /// Tier heading exactly as printed on the sheet.
    pub heading: &'static str,
    /// Positions that open this tier's hands. Tier one is the base
    /// range shared by every opening seat; later tiers are additive,
    /// so a position opens every tier that lists it.
    pub added_by: &'static [Position6max],
    /// Cumulative share of all 1326 combinations, as printed (percent).
    pub printed_percent: u8,
    /// Notation tokens exactly as printed on the sheet.
    pub notation: &'static [&'static str],
}

/// The three cumulative opening tiers, transcribed from the sheet.
pub const RANGE_TIERS: [RangeTier; 3] = [
    RangeTier {
        heading: "From any seat",
        added_by: &[
            Position6max::Utg,
            Position6max::Hj,
            Position6max::Co,
            Position6max::Btn,
            Position6max::Sb,
        ],
        printed_percent: 14,
        notation: &[
            "22+", "ATs+", "A5s-A2s", "KTs+", "QTs+", "JTs", "T9s", "98s", "AJo+", "KQo",
        ],
    },
    RangeTier {
        heading: "Add from the hijack and cutoff",
        added_by: &[
            Position6max::Hj,
            Position6max::Co,
            Position6max::Sb,
            Position6max::Btn,
        ],
        printed_percent: 26,
        notation: &[
            "A9s-A6s", "K9s-K5s", "Q9s", "Q8s", "J9s", "J8s", "T8s", "97s", "87s", "76s", "65s",
            "54s", "ATo", "A9o", "A8o", "KJo", "KTo", "QJo",
        ],
    },
    RangeTier {
        heading: "Add on the small blind and button",
        added_by: &[Position6max::Sb, Position6max::Btn],
        printed_percent: 43,
        notation: &[
            "K4s-K2s", "Q7s-Q4s", "J7s", "J6s", "T7s", "T6s", "96s", "95s", "86s", "85s", "75s",
            "64s", "A7o-A2o", "K9o", "K8o", "QTo", "Q9o", "JTo", "J9o", "T9o", "98o",
        ],
    },
];

/// The cumulative opening range for one six-handed position.
///
/// Every opening seat shares tier one; later tiers are added on top.
/// The big blind opens nothing. Malformed tokens are skipped — the
/// test suite guarantees every constant token parses.
pub fn open_range(position: Position6max) -> Vec<HoleClass> {
    let mut hands: Vec<HoleClass> = Vec::new();
    for tier in &RANGE_TIERS {
        if !tier.added_by.contains(&position) {
            continue;
        }
        for token in tier.notation {
            if let Ok(classes) = expand_notation(token) {
                for class in classes {
                    if !hands.contains(&class) {
                        hands.push(class);
                    }
                }
            }
        }
    }
    hands.sort();
    hands
}

/// Whether the reference sheet says the position opens the hand class.
pub fn is_openable(position: Position6max, class: HoleClass) -> bool {
    open_range(position).contains(&class)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn classes(tokens: &[&str]) -> Vec<HoleClass> {
        tokens
            .iter()
            .flat_map(|token| expand_notation(token).expect("token parses"))
            .collect()
    }

    #[test]
    fn expands_pair_plus_through_aces() {
        let expanded = expand_notation("77+").expect("parses");
        assert_eq!(expanded.len(), 8);
        assert_eq!(expanded[0], HoleClass::Pair(Rank::Seven));
        assert_eq!(expanded[7], HoleClass::Pair(Rank::Ace));
    }

    #[test]
    fn expands_suited_plus_up_to_below_the_high_card() {
        let expanded = expand_notation("AJs+").expect("parses");
        assert_eq!(
            expanded,
            vec![
                HoleClass::Suited(Rank::Ace, Rank::Jack),
                HoleClass::Suited(Rank::Ace, Rank::Queen),
                HoleClass::Suited(Rank::Ace, Rank::King),
            ]
        );
    }

    #[test]
    fn expands_offsuit_plus() {
        let expanded = expand_notation("ATo+").expect("parses");
        assert_eq!(
            expanded,
            vec![
                HoleClass::Offsuit(Rank::Ace, Rank::Ten),
                HoleClass::Offsuit(Rank::Ace, Rank::Jack),
                HoleClass::Offsuit(Rank::Ace, Rank::Queen),
                HoleClass::Offsuit(Rank::Ace, Rank::King),
            ]
        );
    }

    #[test]
    fn expands_single_hand_tokens() {
        assert_eq!(
            expand_notation("KQs").expect("parses"),
            vec![HoleClass::Suited(Rank::King, Rank::Queen)]
        );
        assert_eq!(
            expand_notation("98s").expect("parses"),
            vec![HoleClass::Suited(Rank::Nine, Rank::Eight)]
        );
        assert_eq!(
            expand_notation("A2o").expect("parses"),
            vec![HoleClass::Offsuit(Rank::Ace, Rank::Two)]
        );
    }

    #[test]
    fn expands_dash_ranges_inclusively() {
        assert_eq!(
            expand_notation("A5s-A2s").expect("parses"),
            vec![
                HoleClass::Suited(Rank::Ace, Rank::Two),
                HoleClass::Suited(Rank::Ace, Rank::Three),
                HoleClass::Suited(Rank::Ace, Rank::Four),
                HoleClass::Suited(Rank::Ace, Rank::Five),
            ]
        );
        let offsuit = expand_notation("A7o-A2o").expect("parses");
        assert_eq!(offsuit.len(), 6);
        assert!(offsuit
            .iter()
            .all(|class| matches!(class, HoleClass::Offsuit(Rank::Ace, _))));
        assert_eq!(expand_notation("K9s-K5s").expect("parses").len(), 5);
    }

    #[test]
    fn rejects_malformed_dash_ranges() {
        for token in [
            "A2s-A5s",
            "A5s-A5s",
            "A5s-K2s",
            "A5s-A2o",
            "77-22",
            "A5s+-A2s",
            "A5s-A3s-A2s",
            "-A2s",
        ] {
            assert!(
                matches!(expand_notation(token), Err(RangeError::InvalidToken { .. })),
                "{token} must be rejected"
            );
        }
    }

    #[test]
    fn rejects_malformed_tokens() {
        assert!(matches!(
            expand_notation("JAs"),
            Err(RangeError::HighCardNotHigher { .. })
        ));
        assert!(matches!(
            expand_notation("AK"),
            Err(RangeError::InvalidPair { .. })
        ));
        assert!(matches!(
            expand_notation("AJx"),
            Err(RangeError::InvalidRank { .. })
        ));
        assert!(matches!(
            expand_notation(""),
            Err(RangeError::InvalidToken { .. })
        ));
        assert!(matches!(
            expand_notation("toolong"),
            Err(RangeError::InvalidToken { .. })
        ));
    }

    #[test]
    fn every_constant_token_parses() {
        for tier in &RANGE_TIERS {
            for token in tier.notation {
                assert!(
                    expand_notation(token).is_ok(),
                    "tier `{}` token `{token}` must parse",
                    tier.heading
                );
            }
        }
    }

    #[test]
    fn display_round_trips_notation() {
        for tier in &RANGE_TIERS {
            for token in tier.notation {
                if token.ends_with('+') || token.contains('-') {
                    continue;
                }
                let classes = classes(&[token]);
                for class in classes {
                    assert_eq!(class.to_string(), *token, "token {token}");
                }
            }
        }
    }

    #[test]
    fn from_ranks_orders_high_and_low() {
        assert_eq!(
            HoleClass::from_ranks(Rank::Jack, Rank::Ace, true),
            HoleClass::Suited(Rank::Ace, Rank::Jack)
        );
        assert_eq!(
            HoleClass::from_ranks(Rank::Nine, Rank::King, false),
            HoleClass::Offsuit(Rank::King, Rank::Nine)
        );
        assert_eq!(
            HoleClass::from_ranks(Rank::Queen, Rank::Queen, true),
            HoleClass::Pair(Rank::Queen)
        );
    }

    #[test]
    fn utg_opens_only_the_base_range() {
        let range = open_range(Position6max::Utg);
        assert_eq!(range.len(), 33);
        for class in classes(&[
            "AA", "22", "ATs", "A2s", "KTs", "QJs", "JTs", "T9s", "98s", "AJo", "KQo",
        ]) {
            assert!(range.contains(&class), "{class} must be in the UTG range");
        }
        for class in classes(&["A9s", "K9s", "ATo", "KJo", "QJo", "A2o", "87s"]) {
            assert!(
                !range.contains(&class),
                "{class} must not be in the UTG range"
            );
        }
    }

    #[test]
    fn hijack_and_cutoff_add_tier_two() {
        let range = open_range(Position6max::Hj);
        assert_eq!(range.len(), 58);
        for class in classes(&["A9s", "A6s", "K5s", "97s", "54s", "ATo", "A8o", "QJo"]) {
            assert!(range.contains(&class), "{class} must be in the HJ range");
        }
        for class in classes(&["K4s", "Q7s", "A7o", "QTo", "98o"]) {
            assert!(
                !range.contains(&class),
                "{class} must not be in the HJ range"
            );
        }
        assert_eq!(open_range(Position6max::Co), range);
    }

    #[test]
    fn button_and_small_blind_add_tier_three() {
        for position in [Position6max::Sb, Position6max::Btn] {
            let range = open_range(position);
            assert_eq!(range.len(), 89, "{position}");
            for class in classes(&[
                "K2s", "Q4s", "J7s", "64s", "A2o", "A7o", "K9o", "QTo", "JTo", "98o",
            ]) {
                assert!(
                    range.contains(&class),
                    "{class} must be in the {position} range"
                );
            }
            for class in classes(&["Q3s", "J5s", "53s", "K7o", "T8o", "87o"]) {
                assert!(
                    !range.contains(&class),
                    "{class} must not be in the {position} range"
                );
            }
        }
        assert_eq!(open_range(Position6max::Sb), open_range(Position6max::Btn));
    }

    #[test]
    fn printed_percentages_match_exact_combinatorics() {
        let all_classes: u32 = ALL_RANKS
            .iter()
            .flat_map(|&high| {
                ALL_RANKS.iter().flat_map(move |&low| {
                    if high == low {
                        vec![HoleClass::Pair(high)]
                    } else if high > low {
                        vec![HoleClass::Suited(high, low), HoleClass::Offsuit(high, low)]
                    } else {
                        Vec::new()
                    }
                })
            })
            .map(HoleClass::combos)
            .sum();
        assert_eq!(all_classes, 1326);

        let expected_combos = [190, 338, 574];
        let widest_opener = [Position6max::Utg, Position6max::Hj, Position6max::Btn];
        for ((tier, position), expected) in
            RANGE_TIERS.iter().zip(widest_opener).zip(expected_combos)
        {
            let combos: u32 = open_range(position)
                .into_iter()
                .map(HoleClass::combos)
                .sum();
            assert_eq!(combos, expected, "{}", tier.heading);
            let exact = 100.0 * f64::from(combos) / 1326.0;
            assert!(
                (exact - f64::from(tier.printed_percent)).abs() <= 1.0,
                "{}: exact {exact:.2}% vs printed {}%",
                tier.heading,
                tier.printed_percent
            );
        }
    }

    #[test]
    fn tiers_are_disjoint() {
        let mut seen: Vec<HoleClass> = Vec::new();
        for tier in &RANGE_TIERS {
            for class in classes(tier.notation) {
                assert!(
                    !seen.contains(&class),
                    "{class} printed in more than one tier ({})",
                    tier.heading
                );
                seen.push(class);
            }
        }
        assert_eq!(seen.len(), 89);
    }

    #[test]
    fn big_blind_never_opens() {
        assert!(open_range(Position6max::Bb).is_empty());
    }

    #[test]
    fn ranges_are_cumulative() {
        let utg = open_range(Position6max::Utg);
        let hj = open_range(Position6max::Hj);
        let btn = open_range(Position6max::Btn);
        for class in &utg {
            assert!(hj.contains(class), "HJ must contain UTG's {class}");
            assert!(btn.contains(class), "BTN must contain UTG's {class}");
        }
        for class in &hj {
            assert!(btn.contains(class), "BTN must contain HJ's {class}");
        }
    }

    #[test]
    fn is_openable_matches_range_membership() {
        let aces = HoleClass::Pair(Rank::Ace);
        assert!(is_openable(Position6max::Utg, aces));
        assert!(!is_openable(Position6max::Bb, aces));
        let ace_nine_suited = HoleClass::Suited(Rank::Ace, Rank::Nine);
        assert!(is_openable(Position6max::Co, ace_nine_suited));
        assert!(!is_openable(Position6max::Utg, ace_nine_suited));
    }

    #[test]
    fn display_labels_positions() {
        assert_eq!(Position6max::Utg.to_string(), "UTG");
        assert_eq!(Position6max::Bb.to_string(), "BB");
        assert_eq!(Position6max::ALL.len(), 6);
    }
}
