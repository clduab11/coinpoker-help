//! Seating positions and betting rounds from `poker-info-sheet.pdf`.
//!
//! The reference sheet (PokerNews "Poker Cheat Sheet", 15 pages, kept
//! untracked at the repository root; SHA-256
//! `5ce3a3f811b0a9cd0291e906162c1a5014b43700c4e4f9437574b14a06bd7de6`)
//! drives the Laya perception logic. The vision model reports only what is
//! visible — the dealer-button seat, which seats are occupied, the hero's
//! seat, and the board cards — and these rules derive the hero's position
//! and the betting round. The model is never trusted to name a position or
//! a street on its own; its direct answers are cross-checks only.
//!
//! Rules used, by sheet page:
//!
//! - p.3: every hand has four betting rounds — preflop, the flop, the turn,
//!   and the river. The small blind sits to the immediate left of the
//!   dealer and cards are dealt clockwise starting with the small blind, so
//!   "left" means the next seat clockwise.
//! - p.3-4: the flop reveals three community cards, the turn the fourth,
//!   and the river the fifth and final card.
//! - p.6: nine-handed names UTG, UTG+1, MP1, MP2, HJ, CO, BTN, SB, BB. The
//!   small blind sits directly left of the dealer button, the big blind
//!   directly left of the small blind, and UTG directly left of the big
//!   blind. The cutoff sits immediately right of the button and the hijack
//!   immediately right of the cutoff.
//! - p.7: "the more players that are left to act after you, the tighter you
//!   should play" — so seats before the hijack never open wider than UTG.
//!
//! The sheet names positions for a full nine-handed table only. With fewer
//! players the anchored definitions still hold, in this precedence: button,
//! blinds, UTG, cutoff, hijack. Any remaining seats after UTG take UTG+1,
//! MP1 and MP2 in the diagram's order. Six players therefore give UTG, HJ,
//! CO, BTN, SB, BB — the six-handed names of [`crate::ranges`]. The sheet
//! does not define heads-up blind posting, so a two-player table yields no
//! position rather than a guess.
//!
//! The p.6 text and diagram disagree on group sizes: the text counts two
//! early and two middle seats after UTG plus a hijack, ten seats in all.
//! The diagram's labels are the canonical names here.

use std::fmt;

use thiserror::Error;

use crate::ranges::Position6max;

/// Seats on the largest table the sheet describes (p.6, nine-handed).
pub const MAX_SEATS: usize = 9;

/// Seat positions named on the sheet's nine-handed diagram (p.6).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum TablePosition {
    /// Dealer or button — acts last every hand after the flop.
    Btn,
    /// Small blind — directly left of the button.
    Sb,
    /// Big blind — directly left of the small blind.
    Bb,
    /// Under the gun — directly left of the big blind, first to act preflop.
    Utg,
    /// The seat after UTG.
    Utg1,
    /// First middle seat.
    Mp1,
    /// Second middle seat.
    Mp2,
    /// Hijack — immediately right of the cutoff.
    Hj,
    /// Cutoff — immediately right of the button.
    Co,
}

impl TablePosition {
    /// Nine-handed seating clockwise from the dealer button (p.6 diagram).
    pub const NINE_HANDED: [TablePosition; MAX_SEATS] = [
        TablePosition::Btn,
        TablePosition::Sb,
        TablePosition::Bb,
        TablePosition::Utg,
        TablePosition::Utg1,
        TablePosition::Mp1,
        TablePosition::Mp2,
        TablePosition::Hj,
        TablePosition::Co,
    ];

    /// The position's label exactly as printed on the sheet's diagram.
    pub const fn label(self) -> &'static str {
        match self {
            TablePosition::Btn => "BTN",
            TablePosition::Sb => "SB",
            TablePosition::Bb => "BB",
            TablePosition::Utg => "UTG",
            TablePosition::Utg1 => "UTG+1",
            TablePosition::Mp1 => "MP1",
            TablePosition::Mp2 => "MP2",
            TablePosition::Hj => "HJ",
            TablePosition::Co => "CO",
        }
    }

    /// Parse a diagram label such as `UTG+1`; unknown labels give `None`.
    pub fn from_label(label: &str) -> Option<Self> {
        Self::NINE_HANDED
            .iter()
            .copied()
            .find(|position| position.label() == label)
    }

    /// The six-handed seat whose opening range this position uses.
    ///
    /// UTG+1, MP1 and MP2 open the tier-1 base range like UTG (p.7: the
    /// more players left to act, the tighter the range).
    pub const fn opening_seat(self) -> Position6max {
        match self {
            TablePosition::Utg | TablePosition::Utg1 | TablePosition::Mp1 | TablePosition::Mp2 => {
                Position6max::Utg
            }
            TablePosition::Hj => Position6max::Hj,
            TablePosition::Co => Position6max::Co,
            TablePosition::Btn => Position6max::Btn,
            TablePosition::Sb => Position6max::Sb,
            TablePosition::Bb => Position6max::Bb,
        }
    }
}

impl fmt::Display for TablePosition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.label())
    }
}

/// Why a seat layout cannot be named. Every error means "position unknown".
#[derive(Debug, Error, Clone, Copy, PartialEq, Eq)]
pub enum SeatingError {
    /// A seat number is outside the nine-seat table.
    #[error("seat {seat} is outside 1..=9")]
    SeatOutOfRange { seat: usize },
    /// A seat number appears more than once.
    #[error("seat {seat} is listed more than once")]
    DuplicateSeat { seat: usize },
    /// The dealer button sits at a seat that is not occupied.
    #[error("the dealer button seat {seat} is not occupied")]
    ButtonNotOccupied { seat: usize },
    /// The sheet names positions for three to nine players only.
    #[error("the sheet names positions for 3 to 9 players, not {players}")]
    UnsupportedPlayerCount { players: usize },
}

/// Name every occupied seat, clockwise from the dealer button.
///
/// Seats are numbered 1..=9 clockwise, the numbering the Laya seat
/// questions use. `button_seat` must be one of `occupied_seats`. Returns
/// `(seat, position)` pairs in clockwise order starting at the button.
pub fn assign_positions(
    button_seat: usize,
    occupied_seats: &[usize],
) -> Result<Vec<(usize, TablePosition)>, SeatingError> {
    let mut seats = occupied_seats.to_vec();
    seats.sort_unstable();
    for (index, &seat) in seats.iter().enumerate() {
        if !(1..=MAX_SEATS).contains(&seat) {
            return Err(SeatingError::SeatOutOfRange { seat });
        }
        if index > 0 && seats[index - 1] == seat {
            return Err(SeatingError::DuplicateSeat { seat });
        }
    }
    if !(1..=MAX_SEATS).contains(&button_seat) {
        return Err(SeatingError::SeatOutOfRange { seat: button_seat });
    }
    let button_index = seats
        .iter()
        .position(|&seat| seat == button_seat)
        .ok_or(SeatingError::ButtonNotOccupied { seat: button_seat })?;
    let players = seats.len();
    if !(3..=MAX_SEATS).contains(&players) {
        return Err(SeatingError::UnsupportedPlayerCount { players });
    }
    seats.rotate_left(button_index);
    Ok(seats
        .into_iter()
        .zip(names_clockwise_from_button(players))
        .collect())
}

/// The position of one seat, or `None` when that seat is not occupied.
pub fn seat_position(
    seat: usize,
    button_seat: usize,
    occupied_seats: &[usize],
) -> Result<Option<TablePosition>, SeatingError> {
    Ok(assign_positions(button_seat, occupied_seats)?
        .into_iter()
        .find(|&(candidate, _)| candidate == seat)
        .map(|(_, position)| position))
}

/// Position names for `players` seats, clockwise from the button.
fn names_clockwise_from_button(players: usize) -> Vec<TablePosition> {
    let mut names = vec![TablePosition::Btn, TablePosition::Sb, TablePosition::Bb];
    if players >= 4 {
        names.push(TablePosition::Utg);
    }
    let middle_seats = players.saturating_sub(6);
    names.extend(
        [TablePosition::Utg1, TablePosition::Mp1, TablePosition::Mp2]
            .into_iter()
            .take(middle_seats),
    );
    if players >= 6 {
        names.push(TablePosition::Hj);
    }
    if players >= 5 {
        names.push(TablePosition::Co);
    }
    names
}

/// The four betting rounds of every hand (p.3).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Street {
    /// Hole cards only; no community cards.
    Preflop,
    /// Three community cards.
    Flop,
    /// The fourth community card.
    Turn,
    /// The fifth and final community card.
    River,
}

impl Street {
    /// The four rounds in order.
    pub const ALL: [Street; 4] = [Street::Preflop, Street::Flop, Street::Turn, Street::River];

    /// Community cards visible during the round (p.3-4).
    pub const fn board_cards(self) -> usize {
        match self {
            Street::Preflop => 0,
            Street::Flop => 3,
            Street::Turn => 4,
            Street::River => 5,
        }
    }

    /// The round implied by a visible board count.
    ///
    /// One, two or more than five cards is never a legal board and gives
    /// `None`. Five cards cannot distinguish the river from the showdown
    /// (p.5); that distinction stays with the observed screen.
    pub fn from_board_count(count: usize) -> Option<Street> {
        Street::ALL
            .into_iter()
            .find(|street| street.board_cards() == count)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(button_seat: usize, occupied: &[usize]) -> Vec<(usize, &'static str)> {
        assign_positions(button_seat, occupied)
            .expect("valid layout")
            .into_iter()
            .map(|(seat, position)| (seat, position.label()))
            .collect()
    }

    #[test]
    fn full_table_matches_the_sheet_diagram() {
        let all: Vec<usize> = (1..=9).collect();
        assert_eq!(
            names(2, &all),
            vec![
                (2, "BTN"),
                (3, "SB"),
                (4, "BB"),
                (5, "UTG"),
                (6, "UTG+1"),
                (7, "MP1"),
                (8, "MP2"),
                (9, "HJ"),
                (1, "CO"),
            ]
        );
    }

    #[test]
    fn six_players_get_the_six_handed_names() {
        let layout = assign_positions(4, &[1, 2, 4, 5, 7, 8]).expect("valid");
        let labels: Vec<&str> = layout
            .iter()
            .map(|(_, position)| position.label())
            .collect();
        assert_eq!(labels, vec!["BTN", "SB", "BB", "UTG", "HJ", "CO"]);
        for (_, position) in layout {
            assert_eq!(position.opening_seat().to_string(), position.label());
        }
    }

    #[test]
    fn anchored_seats_hold_at_every_supported_size() {
        for players in 3..=MAX_SEATS {
            let occupied: Vec<usize> = (1..=players).collect();
            let layout = assign_positions(1, &occupied).expect("valid");
            let positions: Vec<TablePosition> = layout.iter().map(|&(_, p)| p).collect();
            assert_eq!(positions.len(), players);
            assert_eq!(
                &positions[..3],
                &[TablePosition::Btn, TablePosition::Sb, TablePosition::Bb]
            );
            for (index, position) in positions.iter().enumerate() {
                assert!(
                    !positions[index + 1..].contains(position),
                    "{players} players: {position} assigned twice"
                );
            }
            if players >= 4 {
                assert_eq!(positions[3], TablePosition::Utg, "UTG is left of BB");
            }
            if players >= 5 {
                assert_eq!(
                    positions[players - 1],
                    TablePosition::Co,
                    "CO is right of BTN"
                );
            }
            if players >= 6 {
                assert_eq!(
                    positions[players - 2],
                    TablePosition::Hj,
                    "HJ is right of CO"
                );
            }
        }
    }

    #[test]
    fn empty_seats_are_skipped_and_numbering_wraps() {
        assert_eq!(
            names(9, &[1, 3, 4, 7, 9]),
            vec![(9, "BTN"), (1, "SB"), (3, "BB"), (4, "UTG"), (7, "CO")]
        );
        assert_eq!(names(7, &[7, 3, 1]), vec![(7, "BTN"), (1, "SB"), (3, "BB")]);
    }

    #[test]
    fn layouts_the_sheet_does_not_define_are_errors() {
        assert_eq!(
            assign_positions(1, &[1, 5]),
            Err(SeatingError::UnsupportedPlayerCount { players: 2 })
        );
        assert_eq!(
            assign_positions(2, &[1, 3, 5]),
            Err(SeatingError::ButtonNotOccupied { seat: 2 })
        );
        assert_eq!(
            assign_positions(1, &[0, 1, 2]),
            Err(SeatingError::SeatOutOfRange { seat: 0 })
        );
        assert_eq!(
            assign_positions(1, &[1, 2, 10]),
            Err(SeatingError::SeatOutOfRange { seat: 10 })
        );
        assert_eq!(
            assign_positions(10, &[1, 2, 3]),
            Err(SeatingError::SeatOutOfRange { seat: 10 })
        );
        assert_eq!(
            assign_positions(1, &[1, 2, 2, 3]),
            Err(SeatingError::DuplicateSeat { seat: 2 })
        );
    }

    #[test]
    fn seat_position_reports_unoccupied_seats_as_none() {
        let occupied = [1, 2, 3, 4, 5, 6];
        assert_eq!(seat_position(4, 1, &occupied), Ok(Some(TablePosition::Utg)));
        assert_eq!(seat_position(8, 1, &occupied), Ok(None));
        assert_eq!(
            seat_position(1, 1, &[1, 2]),
            Err(SeatingError::UnsupportedPlayerCount { players: 2 })
        );
    }

    #[test]
    fn labels_round_trip() {
        for position in TablePosition::NINE_HANDED {
            assert_eq!(TablePosition::from_label(position.label()), Some(position));
            assert_eq!(position.to_string(), position.label());
        }
        assert_eq!(TablePosition::from_label("MP3"), None);
        assert_eq!(TablePosition::from_label("utg"), None);
    }

    #[test]
    fn seats_before_the_hijack_open_the_base_range() {
        for position in [
            TablePosition::Utg,
            TablePosition::Utg1,
            TablePosition::Mp1,
            TablePosition::Mp2,
        ] {
            assert_eq!(position.opening_seat(), Position6max::Utg);
        }
        assert_eq!(TablePosition::Bb.opening_seat(), Position6max::Bb);
    }

    #[test]
    fn board_count_determines_the_street() {
        assert_eq!(Street::from_board_count(0), Some(Street::Preflop));
        assert_eq!(Street::from_board_count(3), Some(Street::Flop));
        assert_eq!(Street::from_board_count(4), Some(Street::Turn));
        assert_eq!(Street::from_board_count(5), Some(Street::River));
        for illegal in [1, 2, 6] {
            assert_eq!(Street::from_board_count(illegal), None);
        }
        for street in Street::ALL {
            assert_eq!(Street::from_board_count(street.board_cards()), Some(street));
        }
    }
}
