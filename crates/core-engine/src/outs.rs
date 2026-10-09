//! Outs-based equity heuristics and the odds worth memorizing.
//!
//! Deterministic approximations for after-the-flop draw equity:
//! the rule of two and four, exact turn/river combinatorics, and
//! the reference draw table from the project's poker reference
//! sheet ("Odds worth knowing — after the flop").

/// Rule of two: approximate equity with one card to come, in percent.
pub fn rule_of_two(outs: u8) -> f64 {
    f64::from(outs) * 2.0
}

/// Rule of four: approximate equity with two cards to come, in percent.
pub fn rule_of_four(outs: u8) -> f64 {
    f64::from(outs) * 4.0
}

/// Exact equity with one card to come after the flop (47 unseen cards).
pub fn exact_next_card(outs: u8) -> f64 {
    (f64::from(outs) / 47.0) * 100.0
}

/// Exact equity with two cards to come after the flop (turn and river).
///
/// `1 - C(47-outs, 2) / C(47, 2)`, i.e. the complement of missing
/// with both remaining community cards.
pub fn exact_turn_and_river(outs: u8) -> f64 {
    let outs = f64::from(outs);
    let unseen = 47.0;
    let miss_one = (unseen - outs) / unseen;
    let miss_two = (unseen - outs - 1.0) / (unseen - 1.0);
    (1.0 - miss_one * miss_two) * 100.0
}

/// A memorized draw with its out count and the printed reference
/// percentages from the reference sheet.
pub struct MemorizedDraw {
    /// Draw name as printed on the sheet.
    pub name: &'static str,
    /// Number of outs.
    pub outs: u8,
    /// Printed next-card percentage (one card to come).
    pub printed_next_card_pct: u8,
    /// Printed two-card percentage (turn and river to come).
    pub printed_two_card_pct: u8,
    /// Transcription-suspect printed values, kept verbatim from the
    /// sheet pending human verification.
    pub suspect: Option<&'static str>,
}

/// The "odds worth memorizing" table, after the flop.
///
/// Printed percentages are the sheet's rounded values. The 8-out
/// (open-ended straight draw) two-card entry prints 32%, which is
/// the rule-of-four value; the exact value is 31.45%. Flagged as
/// suspect rather than silently corrected.
pub const MEMORIZED_DRAWS: [MemorizedDraw; 5] = [
    MemorizedDraw {
        name: "Flush draw",
        outs: 9,
        printed_next_card_pct: 19,
        printed_two_card_pct: 35,
        suspect: None,
    },
    MemorizedDraw {
        name: "Open-ended straight draw",
        outs: 8,
        printed_next_card_pct: 17,
        printed_two_card_pct: 32,
        suspect: Some("printed 32% two-card is the rule-of-four value; exact is 31.45%"),
    },
    MemorizedDraw {
        name: "Two overcards",
        outs: 6,
        printed_next_card_pct: 13,
        printed_two_card_pct: 24,
        suspect: None,
    },
    MemorizedDraw {
        name: "Gutshot straight draw",
        outs: 4,
        printed_next_card_pct: 9,
        printed_two_card_pct: 17,
        suspect: None,
    },
    MemorizedDraw {
        name: "Pocket pair to a set",
        outs: 2,
        printed_next_card_pct: 4,
        printed_two_card_pct: 8,
        suspect: None,
    },
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rule_of_two_and_four_scale_with_outs() {
        assert!((rule_of_two(9) - 18.0).abs() < 1e-9);
        assert!((rule_of_four(9) - 36.0).abs() < 1e-9);
        assert!((rule_of_two(0) - 0.0).abs() < 1e-9);
    }

    #[test]
    fn exact_next_card_matches_outs_over_47() {
        assert!((exact_next_card(9) - 900.0 / 47.0).abs() < 1e-9);
        assert!((exact_next_card(1) - 100.0 / 47.0).abs() < 1e-9);
    }

    #[test]
    fn exact_two_card_equity_is_the_complement_of_missing_both() {
        // 9 outs: 1 - (38/47) * (37/46) = 34.97%.
        let expected = (1.0 - (38.0 / 47.0) * (37.0 / 46.0)) * 100.0;
        assert!((exact_turn_and_river(9) - expected).abs() < 1e-9);
        assert!((exact_turn_and_river(0) - 0.0).abs() < 1e-9);
        assert!((exact_turn_and_river(47) - 100.0).abs() < 1e-9);
    }

    #[test]
    fn printed_percentages_track_the_exact_values() {
        // The sheet rounds loosely; the gutshot two-card entry prints
        // 17% where the linear approximation is 8/47 = 17.02% and the
        // exact compound value is 16.47%. Every printed value must sit
        // within one percentage point of the exact value.
        for draw in MEMORIZED_DRAWS {
            let exact_next = exact_next_card(draw.outs);
            let exact_two = exact_turn_and_river(draw.outs);
            assert!(
                (f64::from(draw.printed_next_card_pct) - exact_next).abs() < 1.0,
                "{} next-card: printed {} vs exact {:.2}",
                draw.name,
                draw.printed_next_card_pct,
                exact_next
            );
            assert!(
                (f64::from(draw.printed_two_card_pct) - exact_two).abs() < 1.0,
                "{} two-card: printed {} vs exact {:.2}",
                draw.name,
                draw.printed_two_card_pct,
                exact_two
            );
        }
    }

    #[test]
    fn the_eight_out_two_card_entry_is_flagged_suspect() {
        let oesd = MEMORIZED_DRAWS
            .iter()
            .find(|draw| draw.outs == 8)
            .expect("open-ended straight draw present");
        assert!(oesd.suspect.is_some());
        assert!((exact_turn_and_river(8) - 31.45).abs() < 0.01);
    }

    #[test]
    fn the_table_covers_the_five_reference_draws() {
        assert_eq!(MEMORIZED_DRAWS.len(), 5);
        let outs: Vec<u8> = MEMORIZED_DRAWS.iter().map(|draw| draw.outs).collect();
        assert_eq!(outs, vec![9, 8, 6, 4, 2]);
    }
}
