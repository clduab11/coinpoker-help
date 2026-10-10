//! Deterministic envelope assembly from Laya answers (question set 0.4.0,
//! `assembly_rules` R1-R19). Pure: every model call goes through `run`.
//!
//! Confidence: with `t = max(pass.threshold, acceptance_floor, override)`, a
//! choice is accepted iff its probability is `>= t` and it is not truncated; a
//! noul is true iff `P(true) >= t`, false iff `P(true) <= 1 - t`, otherwise (or
//! when truncated or missing) it is low confidence and `on_low_confidence`
//! applies. Assembly never repairs: every early exit is a `poker_table` with
//! `readable=false` and `state: null`, and the final envelope must pass the
//! unchanged [`parse_screen_output`] or it degrades the same way (R6).

use serde_json::{json, Value};

use super::client::{Answer, PassAnswers};
use super::questions::{Calibration, Pass, QuestionSet, QuestionType};
use crate::screen::parse_screen_output;
use crate::vlm::{VlmError, VlmOutput, VlmResponseError};

const RANKS: [&str; 13] = [
    "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A",
];
const SUITS: [&str; 4] = ["spades", "hearts", "diamonds", "clubs"];
const NO_CARD: &str = "no_card";
const NOT_A_CHARACTER: &str = "not_a_character";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Evidence {
    table_layout: bool,
    hero_cards: bool,
    board_area: bool,
    pot: bool,
    action_controls: bool,
    readable: bool,
}

impl Evidence {
    fn to_json(self) -> Value {
        json!({
            "table_layout": self.table_layout,
            "hero_cards": self.hero_cards,
            "board_area": self.board_area,
            "pot": self.pot,
            "action_controls": self.action_controls,
            "readable": self.readable,
        })
    }
}

/// One pass's answers read against its effective threshold.
struct Reading<'a> {
    pass: &'a Pass,
    answers: PassAnswers,
    threshold: f64,
}

impl Reading<'_> {
    fn answer(&self, id: &str) -> Option<&Answer> {
        self.pass.question(id)?;
        self.answers.answers.get(id)
    }

    /// The confidently chosen label, if any.
    fn choice(&self, id: &str) -> Option<&str> {
        let answer = self.answer(id)?;
        if answer.truncated || !answer.p.is_finite() || answer.p < self.threshold {
            return None;
        }
        answer.choice.as_deref()
    }

    /// A confident noul value, if any.
    fn noul(&self, id: &str) -> Option<bool> {
        let answer = self.answer(id)?;
        if answer.truncated || !answer.p.is_finite() {
            None
        } else if answer.p >= self.threshold {
            Some(true)
        } else if answer.p <= 1.0 - self.threshold {
            Some(false)
        } else {
            None
        }
    }

    /// The confident choice, else the question's `on_low_confidence` label.
    fn choice_or_fallback(&self, id: &str) -> &str {
        match self.choice(id) {
            Some(label) => label,
            None => self
                .pass
                .question(id)
                .map_or("unknown", |q| q.on_low_confidence.as_str()),
        }
    }

    /// The confident noul, else the question's `on_low_confidence` boolean.
    fn flag(&self, id: &str) -> bool {
        self.noul(id).unwrap_or_else(|| {
            self.pass
                .question(id)
                .is_some_and(|q| q.kind == QuestionType::Noul && q.on_low_confidence == "true")
        })
    }
}

fn threshold(pass: &Pass, acceptance_floor: f64, threshold_override: Option<f32>) -> f64 {
    let base = pass.threshold.max(acceptance_floor);
    match threshold_override {
        Some(value) if f64::from(value) > base => f64::from(value),
        _ => base,
    }
}

fn run_pass<'a>(
    qs: &'a QuestionSet,
    id: &str,
    threshold_override: Option<f32>,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
) -> Result<Reading<'a>, VlmError> {
    let pass = qs
        .pass(id)
        .ok_or_else(|| VlmError::Unavailable("vendored question set lacks a pass".into()))?;
    // Untrained passes are never asked; all their answers are low confidence.
    let (answers, acceptance_floor) = if pass.calibration == Calibration::UntrainedProvisional {
        (PassAnswers::default(), pass.threshold)
    } else {
        let answers = run(pass)?;
        let acceptance_floor = answers
            .acceptance_floor
            .filter(|floor| floor.is_finite() && (0.0..=1.0).contains(floor))
            .ok_or(VlmError::Parse(VlmResponseError::Schema))?;
        (answers, acceptance_floor)
    };
    Ok(Reading {
        pass,
        threshold: threshold(pass, acceptance_floor, threshold_override),
        answers,
    })
}

fn envelope(kind: &str, evidence: Evidence, state: Value) -> String {
    json!({"screen_kind": kind, "evidence": evidence.to_json(), "state": state}).to_string()
}

/// R6: the validator is the gate; failures degrade, never repair.
fn finish(kind: &str, evidence: Evidence, state: Value) -> String {
    let text = envelope(kind, evidence, state);
    if parse_screen_output(&VlmOutput { text: text.clone() }).is_ok() {
        return text;
    }
    unreadable(kind, evidence)
}

fn unreadable(kind: &str, evidence: Evidence) -> String {
    envelope(
        kind,
        Evidence {
            readable: false,
            ..evidence
        },
        Value::Null,
    )
}

fn table_null(evidence: Evidence) -> Result<String, VlmError> {
    Ok(unreadable("poker_table", evidence))
}

/// Parse a displayed chip amount into hundredths (R5):
/// `^(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$`, `,` stripped, exact integer math.
pub fn parse_amount(text: &str) -> Option<u32> {
    let digits = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    let (integer, fraction) = match text.split_once('.') {
        Some((integer, fraction)) => (integer, Some(fraction)),
        None => (text, None),
    };
    if let Some(fraction) = fraction {
        if !(1..=2).contains(&fraction.len()) || !digits(fraction) {
            return None;
        }
    }
    if integer.contains(',') {
        let mut groups = integer.split(',');
        let first = groups.next()?;
        if !(1..=3).contains(&first.len()) || !digits(first) {
            return None;
        }
        if !groups.all(|group| group.len() == 3 && digits(group)) {
            return None;
        }
    } else if !digits(integer) {
        return None;
    }
    let mut value: u64 = 0;
    for byte in integer.bytes().filter(u8::is_ascii_digit) {
        value = value.checked_mul(10)?.checked_add(u64::from(byte - b'0'))?;
    }
    let cents = match fraction {
        None => 0,
        Some(f) if f.len() == 1 => u64::from(f.as_bytes()[0] - b'0') * 10,
        Some(f) => u64::from(f.as_bytes()[0] - b'0') * 10 + u64::from(f.as_bytes()[1] - b'0'),
    };
    u32::try_from(value.checked_mul(100)?.checked_add(cents)?).ok()
}

/// Assemble the screen envelope JSON text accepted by [`parse_screen_output`].
///
/// `frame` and `lobby` are `(width, height)`; `run` performs one pass and its
/// errors abort assembly unchanged.
pub fn assemble(
    qs: &QuestionSet,
    frame: (u32, u32),
    lobby: Option<(u32, u32)>,
    threshold_override: Option<f32>,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
) -> Result<String, VlmError> {
    // 1-2. Whole-window classification and evidence.
    let p0 = run_pass(qs, "p0_full", threshold_override, run)?;
    let kind = p0.choice_or_fallback("screen_kind").to_string();
    let evidence = Evidence {
        table_layout: p0.flag("ev_table_layout"),
        hero_cards: p0.flag("ev_hero_cards"),
        board_area: p0.flag("ev_board_area"),
        pot: p0.flag("ev_pot"),
        action_controls: p0.flag("ev_action_controls"),
        readable: p0.flag("ev_readable"),
    };
    // R1: non-table screens never carry a state.
    if kind != "poker_table" {
        return Ok(finish(&kind, evidence, Value::Null));
    }
    // R18: a lobby-sized frame never gets a table pass.
    if lobby == Some(frame) {
        return table_null(evidence);
    }
    // R17: observation only until calibrated (no actionable path in 0.4.0).
    if p0.noul("action_on_hero") == Some(true) {
        return table_null(evidence);
    }
    // R15: only a confidently unseated hero continues (the low-confidence
    // `not_seated` fallback does not count). The seated path needs untrained
    // passes (p1, p3_to_call, p3_hero_chips), so it is null under R17 in 0.4.0.
    let unseated = p0.choice("hero_seat_index") == Some("not_seated")
        && p0.noul("action_on_hero") == Some(false)
        && p0.noul("ev_seat_controls") == Some(true);
    if !unseated {
        return table_null(evidence);
    }
    // State evidence gate.
    let confident = |id: &str| p0.noul(id) == Some(true);
    if !(confident("ev_table_layout")
        && confident("ev_board_area")
        && confident("ev_pot")
        && confident("ev_readable"))
        || confident("ev_action_controls")
        || confident("ev_hero_cards")
    {
        return table_null(evidence);
    }

    // 7. R4 board.
    let board_pass = run_pass(qs, "p2_board", threshold_override, run)?;
    let mut slots = Vec::with_capacity(5);
    for k in 1..=5 {
        let rank = board_pass.choice(&format!("board_{k}_rank"));
        let suit = board_pass.choice(&format!("board_{k}_suit"));
        match (rank, suit) {
            (Some(NO_CARD), Some(NO_CARD)) => slots.push(None),
            (Some(rank), Some(suit)) if RANKS.contains(&rank) && SUITS.contains(&suit) => {
                slots.push(Some(json!({"rank": rank, "suit": suit})))
            }
            _ => return table_null(evidence),
        }
    }
    let count = slots.iter().take_while(|slot| slot.is_some()).count();
    if slots[count..].iter().any(Option::is_some) || !matches!(count, 0 | 3 | 4 | 5) {
        return table_null(evidence);
    }
    let board: Vec<Value> = slots.into_iter().flatten().collect();

    // 8. R12 strict street cross-check.
    let Some(phase) = p0.choice("game_phase") else {
        return table_null(evidence);
    };
    let street_matches = match count {
        0 => phase == "preflop",
        3 => phase == "flop",
        4 => phase == "turn",
        _ => matches!(phase, "river" | "showdown"),
    };
    if !street_matches {
        return table_null(evidence);
    }

    // 9. R5 pot amount.
    let pot = run_pass(qs, "p3_pot", threshold_override, run)?;
    let Some(segments) = pot.answers.segments else {
        return table_null(evidence);
    };
    if segments.overflow || segments.n == 0 || segments.n > qs.max_glyphs {
        return table_null(evidence);
    }
    let mut text = String::new();
    for k in 1..=segments.n {
        match pot.choice(&format!("g{k}")) {
            Some(glyph) if glyph != NOT_A_CHARACTER => text.push_str(glyph),
            _ => return table_null(evidence),
        }
    }
    let Some(pot_size) = parse_amount(&text) else {
        return table_null(evidence);
    };

    // 10. Observation-only state (R15/R16: no players for non-actionable states).
    let state = json!({
        "game_phase": phase,
        "hero_cards": [],
        "board": board,
        "pot_size": pot_size,
        "to_call": 0,
        "hero_chips": 0,
        "min_raise_to": null,
        "max_raise_to": null,
        "players": [],
        "action_required": false,
        "available_actions": [],
    });
    let evidence = Evidence {
        readable: true,
        hero_cards: false,
        ..evidence
    };
    Ok(finish("poker_table", evidence, state))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::laya::client::Segments;
    use crate::laya::questions::question_set;
    use crate::laya::questions::Layout;
    use crate::screen::ScreenKind;
    use std::collections::HashMap;

    fn choice(label: &str, p: f64) -> Answer {
        Answer {
            choice: Some(label.to_string()),
            p,
            truncated: false,
        }
    }

    fn noul(p: f64) -> Answer {
        Answer {
            choice: None,
            p,
            truncated: false,
        }
    }

    /// An unseated, readable flop with synthetic .8 floors, not fitted floors.
    fn p0(overrides: &[(&str, Answer)]) -> PassAnswers {
        let mut answers: HashMap<String, Answer> = [
            ("screen_kind", choice("poker_table", 0.99)),
            ("ev_table_layout", noul(0.99)),
            ("ev_hero_cards", noul(0.01)),
            ("ev_board_area", noul(0.99)),
            ("ev_pot", noul(0.99)),
            ("ev_action_controls", noul(0.01)),
            ("ev_seat_controls", noul(0.99)),
            ("ev_readable", noul(0.99)),
            ("game_phase", choice("flop", 0.99)),
            ("action_on_hero", noul(0.01)),
            ("act_fold", noul(0.01)),
            ("act_check", noul(0.01)),
            ("act_call", noul(0.01)),
            ("act_raise", noul(0.01)),
            ("act_allin", noul(0.01)),
            ("hero_seat_index", choice("not_seated", 0.99)),
        ]
        .into_iter()
        .map(|(id, answer)| (id.to_string(), answer))
        .collect();
        for (id, answer) in overrides {
            answers.insert(id.to_string(), answer.clone());
        }
        PassAnswers {
            answers,
            segments: None,
            acceptance_floor: Some(0.8),
        }
    }

    fn board(cards: &[(&str, &str)]) -> PassAnswers {
        let mut answers = HashMap::new();
        for k in 1..=5 {
            let (rank, suit) = cards.get(k - 1).copied().unwrap_or((NO_CARD, NO_CARD));
            answers.insert(format!("board_{k}_rank"), choice(rank, 0.99));
            answers.insert(format!("board_{k}_suit"), choice(suit, 0.99));
        }
        PassAnswers {
            answers,
            segments: None,
            acceptance_floor: Some(0.8),
        }
    }

    fn pot_glyphs(glyphs: &[&str]) -> PassAnswers {
        let answers = glyphs
            .iter()
            .enumerate()
            .map(|(i, glyph)| (format!("g{}", i + 1), choice(glyph, 0.99)))
            .collect();
        PassAnswers {
            answers,
            acceptance_floor: Some(0.8),
            segments: Some(Segments {
                n: glyphs.len() as u32,
                overflow: false,
            }),
        }
    }

    fn pot(text: &str) -> PassAnswers {
        let glyphs: Vec<String> = text.chars().map(String::from).collect();
        pot_glyphs(&glyphs.iter().map(String::as_str).collect::<Vec<_>>())
    }

    const FLOP: [(&str, &str); 3] = [("A", "spades"), ("T", "hearts"), ("7", "clubs")];

    struct Outcome {
        envelope: Value,
        calls: Vec<String>,
    }

    fn assemble_script(
        passes: Vec<(&str, PassAnswers)>,
        frame: (u32, u32),
        lobby: Option<(u32, u32)>,
        threshold_override: Option<f32>,
    ) -> Outcome {
        let passes: HashMap<String, PassAnswers> = passes
            .into_iter()
            .map(|(id, answers)| (id.to_string(), answers))
            .collect();
        let mut calls = Vec::new();
        let text = assemble(
            question_set(),
            frame,
            lobby,
            threshold_override,
            &mut |pass: &Pass| {
                calls.push(pass.id.clone());
                Ok(passes
                    .get(&pass.id)
                    .expect("explicit scripted pass")
                    .clone())
            },
        )
        .expect("scripted passes never fail");
        let observation = parse_screen_output(&VlmOutput { text: text.clone() })
            .expect("every assembled envelope parses");
        let envelope: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(observation.state.is_some(), !envelope["state"].is_null());
        Outcome { envelope, calls }
    }

    fn run_table(passes: Vec<(&str, PassAnswers)>) -> Outcome {
        assemble_script(passes, (800, 613), Some((1280, 1032)), None)
    }

    fn assert_table_null(outcome: &Outcome) {
        assert_eq!(outcome.envelope["screen_kind"], "poker_table");
        assert_eq!(outcome.envelope["evidence"]["readable"], false);
        assert!(outcome.envelope["state"].is_null());
    }

    fn flop_passes(p0_overrides: &[(&str, Answer)]) -> Vec<(&'static str, PassAnswers)> {
        vec![
            ("p0_full", p0(p0_overrides)),
            ("p2_board", board(&FLOP)),
            ("p3_pot", pot("1,234.5")),
        ]
    }

    fn fitted_floor_passes() -> Vec<(&'static str, PassAnswers)> {
        let mut passes = flop_passes(&[]);
        // Synthetic answers isolate the immutable it1 per-pass acceptance boundaries.
        for (id, answers) in &mut passes {
            let floor = match *id {
                "p0_full" => 0.995,
                "p2_board" => 1.0,
                "p3_pot" => 0.8,
                _ => unreachable!(),
            };
            answers.acceptance_floor = Some(floor);
            for answer in answers.answers.values_mut() {
                answer.p = if *id != "p0_full" {
                    1.0
                } else if answer.choice.is_none() && answer.p < 0.5 {
                    1.0 - floor
                } else {
                    floor
                };
            }
        }
        passes
    }

    #[test]
    fn acceptance_floor_is_required_and_validated_for_every_trained_pass() {
        for pass in &question_set().passes {
            if pass.calibration == Calibration::UntrainedProvisional {
                continue;
            }
            for acceptance_floor in [
                None,
                Some(-0.00000001),
                Some(1.00000001),
                Some(f64::NAN),
                Some(f64::INFINITY),
                Some(f64::NEG_INFINITY),
            ] {
                let result = run_pass(question_set(), &pass.id, None, &mut |_| {
                    Ok(PassAnswers {
                        acceptance_floor,
                        ..PassAnswers::default()
                    })
                });
                assert!(matches!(
                    result,
                    Err(VlmError::Parse(VlmResponseError::Schema))
                ));
            }
        }
        let p0 = question_set().pass("p0_full").unwrap();
        assert_eq!(threshold(p0, 0.995, Some(0.8)), 0.995);
        assert_eq!(threshold(p0, 0.995, Some(0.99)), 0.995);
        assert_eq!(threshold(p0, 0.2, None), p0.threshold);
        assert_eq!(threshold(p0, 0.8, Some(0.9)), f64::from(0.9_f32));
    }

    #[test]
    fn acceptance_floor_p0_boundary_and_low_overrides_enforce_both_polarities() {
        for threshold_override in [None, Some(0.8), Some(0.99)] {
            for (id, p, accepted) in [
                ("screen_kind", 0.995, true),
                ("screen_kind", 0.99499999, false),
                ("ev_table_layout", 0.995, true),
                ("ev_table_layout", 0.99499999, false),
                ("action_on_hero", 1.0 - 0.995, true),
                ("action_on_hero", 0.00500001, false),
            ] {
                let mut passes = fitted_floor_passes();
                passes[0].1.answers.get_mut(id).unwrap().p = p;
                let outcome = assemble_script(passes, (800, 613), None, threshold_override);
                assert_eq!(!outcome.envelope["state"].is_null(), accepted, "{id}: {p}");
                if !accepted {
                    assert_eq!(outcome.calls, ["p0_full"]);
                }
            }
        }
    }

    #[test]
    fn acceptance_floor_board_one_checks_every_card_and_no_card_slot() {
        for cards in [&FLOP[..], &[][..]] {
            let mut passes = fitted_floor_passes();
            if cards.is_empty() {
                passes[0].1.answers.get_mut("game_phase").unwrap().choice = Some("preflop".into());
            }
            passes[1].1 = board(cards);
            passes[1].1.acceptance_floor = Some(1.0);
            for answer in passes[1].1.answers.values_mut() {
                answer.p = 1.0;
            }
            for threshold_override in [None, Some(0.8), Some(0.99)] {
                let outcome = assemble_script(passes.clone(), (800, 613), None, threshold_override);
                assert!(!outcome.envelope["state"].is_null());
                for id in passes[1].1.answers.keys() {
                    for invalid in ["below_floor", "truncated", "missing"] {
                        let mut bad = passes.clone();
                        let answers = &mut bad[1].1.answers;
                        match invalid {
                            "below_floor" => answers.get_mut(id).unwrap().p = 0.99999999,
                            "truncated" => answers.get_mut(id).unwrap().truncated = true,
                            _ => {
                                answers.remove(id);
                            }
                        }
                        let outcome = assemble_script(bad, (800, 613), None, threshold_override);
                        assert_table_null(&outcome);
                        assert_eq!(outcome.calls, ["p0_full", "p2_board"]);
                    }
                }
            }
        }
    }

    #[test]
    fn acceptance_floor_keeps_noul_fallbacks_and_truncation_at_exact_boundaries() {
        let pass = question_set().pass("p0_full").unwrap();
        for floor in [0.995, 1.0] {
            for id in ["ev_pot", "action_on_hero"] {
                for (p, expected) in [
                    (floor, Some(true)),
                    (1.0 - floor, Some(false)),
                    (floor - 0.00000001, None),
                    (1.0 - floor + 0.00000001, None),
                ] {
                    let mut answers = p0(&[(id, noul(p))]);
                    answers.acceptance_floor = Some(floor);
                    let mut reading = run_pass(question_set(), &pass.id, Some(0.8), &mut |_| {
                        Ok(answers.clone())
                    })
                    .unwrap();
                    let fallback = pass.question(id).unwrap().on_low_confidence == "true";
                    assert_eq!(reading.noul(id), expected);
                    assert_eq!(reading.flag(id), expected.unwrap_or(fallback));
                    reading.answers.answers.get_mut(id).unwrap().truncated = true;
                    assert_eq!(reading.noul(id), None);
                    assert_eq!(reading.flag(id), fallback);
                    reading.answers.answers.remove(id);
                    assert_eq!(reading.noul(id), None);
                    assert_eq!(reading.flag(id), fallback);
                }
            }
        }
    }

    #[test]
    fn r1_non_table_screens_have_a_null_state_and_run_one_pass() {
        for label in ["lobby", "other_coin_poker_window", "unknown"] {
            let outcome = run_table(flop_passes(&[("screen_kind", choice(label, 0.95))]));
            assert_eq!(outcome.envelope["screen_kind"], label);
            assert!(outcome.envelope["state"].is_null());
            assert_eq!(outcome.envelope["evidence"]["readable"], true);
            assert_eq!(outcome.calls, ["p0_full"]);
        }
        // A low-confidence classification falls back to `unknown`.
        let outcome = run_table(flop_passes(&[("screen_kind", choice("poker_table", 0.6))]));
        assert_eq!(outcome.envelope["screen_kind"], "unknown");
        assert_eq!(outcome.calls, ["p0_full"]);
    }

    #[test]
    fn r18_lobby_sized_frames_never_get_a_table_pass() {
        let outcome = assemble_script(flop_passes(&[]), (800, 613), Some((800, 613)), None);
        assert_table_null(&outcome);
        assert_eq!(outcome.envelope["evidence"]["table_layout"], true);
        assert_eq!(outcome.calls, ["p0_full"]);
    }

    #[test]
    fn r15_unseated_flop_produces_an_observation_only_state() {
        let outcome = run_table(flop_passes(&[]));
        assert_eq!(outcome.calls, ["p0_full", "p2_board", "p3_pot"]);
        assert_eq!(
            outcome.envelope,
            json!({
                "screen_kind": "poker_table",
                "evidence": {"table_layout": true, "hero_cards": false, "board_area": true,
                    "pot": true, "action_controls": false, "readable": true},
                "state": {"game_phase": "flop", "hero_cards": [],
                    "board": [{"rank": "A", "suit": "spades"}, {"rank": "T", "suit": "hearts"},
                        {"rank": "7", "suit": "clubs"}],
                    "pot_size": 123450, "to_call": 0, "hero_chips": 0,
                    "min_raise_to": null, "max_raise_to": null, "players": [],
                    "action_required": false, "available_actions": []}
            })
        );
    }

    #[test]
    fn r15_preflop_unseated_equals_the_inter_hand_marker_shape() {
        let outcome = run_table(vec![
            ("p0_full", p0(&[("game_phase", choice("preflop", 0.9))])),
            ("p2_board", board(&[])),
            ("p3_pot", pot("150")),
        ]);
        let observation = parse_screen_output(&VlmOutput {
            text: outcome.envelope.to_string(),
        })
        .unwrap();
        assert_eq!(observation.screen_kind, ScreenKind::PokerTable);
        assert!(observation.evidence.readable && observation.evidence.pot);
        let state = observation.state.expect("marker state");
        assert_eq!(state.game_phase, crate::parser::GamePhase::Preflop);
        assert!(state.hero_cards.is_empty() && state.board.is_empty());
        assert!(!state.action_required && state.available_actions.is_empty());
        assert_eq!(
            (state.pot_size, state.to_call, state.hero_chips),
            (15000, 0, 0)
        );
        assert!(state.players.is_empty());
        assert_eq!((state.min_raise_to, state.max_raise_to), (None, None));
    }

    #[test]
    fn r15_low_confidence_not_seated_fallback_does_not_count() {
        for overrides in [
            vec![("hero_seat_index", choice("not_seated", 0.5))],
            vec![("hero_seat_index", choice("seat_4", 0.95))],
            vec![("ev_seat_controls", noul(0.5))],
            vec![("ev_seat_controls", noul(0.05))],
            vec![("action_on_hero", noul(0.5))],
        ] {
            let outcome = run_table(flop_passes(&overrides));
            assert_table_null(&outcome);
            assert_eq!(outcome.calls, ["p0_full"]);
        }
    }

    #[test]
    fn r17_action_on_hero_is_observation_only() {
        let outcome = run_table(flop_passes(&[
            ("action_on_hero", noul(0.99)),
            ("hero_seat_index", choice("seat_4", 0.99)),
            ("ev_action_controls", noul(0.99)),
            ("ev_hero_cards", noul(0.99)),
        ]));
        assert_table_null(&outcome);
        assert_eq!(outcome.envelope["evidence"]["action_controls"], true);
        assert_eq!(outcome.calls, ["p0_full"]);
    }

    #[test]
    fn state_evidence_gate_requires_confident_table_evidence() {
        for overrides in [
            vec![("ev_table_layout", noul(0.5))],
            vec![("ev_board_area", noul(0.01))],
            vec![("ev_pot", noul(0.7))],
            vec![("ev_readable", noul(0.2))],
            vec![("ev_action_controls", noul(0.99))],
            vec![("ev_hero_cards", noul(0.99))],
        ] {
            let outcome = run_table(flop_passes(&overrides));
            assert_table_null(&outcome);
            assert_eq!(outcome.calls, ["p0_full"]);
        }
    }

    #[test]
    fn r4_board_slots_are_strict() {
        let bad_boards: Vec<PassAnswers> = vec![
            // a gap: card, card, absent, card
            board(&[
                ("A", "spades"),
                ("K", "hearts"),
                (NO_CARD, NO_CARD),
                ("2", "clubs"),
            ]),
            board(&[("A", "spades"), ("unreadable", "hearts"), ("2", "clubs")]),
            board(&[("A", "spades"), ("K", NO_CARD), ("2", "clubs")]),
            board(&[("A", "spades"), ("K", "hearts"), ("2", "unreadable")]),
            board(&[("A", "spades")]),
            board(&[("A", "spades"), ("K", "hearts")]),
            {
                let mut low = board(&FLOP);
                low.answers.insert("board_2_rank".into(), choice("T", 0.6));
                low
            },
            {
                let mut truncated = board(&FLOP);
                truncated.answers.get_mut("board_1_suit").unwrap().truncated = true;
                truncated
            },
            {
                let mut missing = board(&FLOP);
                missing.answers.remove("board_5_rank");
                missing
            },
        ];
        for bad in bad_boards {
            let outcome = run_table(vec![
                ("p0_full", p0(&[])),
                ("p2_board", bad),
                ("p3_pot", pot("100")),
            ]);
            assert_table_null(&outcome);
            assert_eq!(outcome.calls, ["p0_full", "p2_board"]);
        }
        let turn = [
            ("A", "spades"),
            ("T", "hearts"),
            ("7", "clubs"),
            ("2", "diamonds"),
        ];
        let outcome = run_table(vec![
            ("p0_full", p0(&[("game_phase", choice("turn", 0.99))])),
            ("p2_board", board(&turn)),
            ("p3_pot", pot("100")),
        ]);
        assert_eq!(outcome.envelope["state"]["board"][3]["rank"], "2");
        assert_eq!(outcome.envelope["state"]["board"][1]["rank"], "T");
    }

    #[test]
    fn r12_game_phase_must_be_confident_and_match_the_street() {
        let river = [
            ("A", "spades"),
            ("T", "hearts"),
            ("7", "clubs"),
            ("2", "diamonds"),
            ("9", "spades"),
        ];
        for (phase, cards, expected) in [
            (choice("flop", 0.6), &FLOP[..], None),
            (choice("preflop", 0.99), &FLOP[..], None),
            (choice("turn", 0.99), &FLOP[..], None),
            (choice("flop", 0.99), &[][..], None),
            (choice("turn", 0.99), &river[..], None),
            (choice("river", 0.99), &river[..], Some("river")),
            (choice("showdown", 0.99), &river[..], Some("showdown")),
        ] {
            let outcome = run_table(vec![
                ("p0_full", p0(&[("game_phase", phase)])),
                ("p2_board", board(cards)),
                ("p3_pot", pot("100")),
            ]);
            match expected {
                Some(phase) => assert_eq!(outcome.envelope["state"]["game_phase"], phase),
                None => {
                    assert_table_null(&outcome);
                    assert_eq!(outcome.calls, ["p0_full", "p2_board"]);
                }
            }
        }
    }

    #[test]
    fn r5_amounts_are_read_exactly_or_not_at_all() {
        for (text, expected) in [
            ("0", Some(0)),
            ("1.05", Some(105)),
            ("1,234.5", Some(123450)),
        ] {
            let outcome = run_table(vec![
                ("p0_full", p0(&[])),
                ("p2_board", board(&FLOP)),
                ("p3_pot", pot(text)),
            ]);
            assert_eq!(
                outcome.envelope["state"]["pot_size"],
                json!(expected.unwrap())
            );
        }
        let mut overflow = pot("100");
        overflow.segments = Some(Segments {
            n: 9,
            overflow: true,
        });
        let mut empty = pot("");
        empty.segments = Some(Segments {
            n: 0,
            overflow: false,
        });
        let mut missing_segments = pot("100");
        missing_segments.segments = None;
        let mut low = pot("100");
        low.answers.insert("g2".into(), choice("0", 0.5));
        let mut too_many = pot("100");
        too_many.segments = Some(Segments {
            n: 4,
            overflow: false,
        });
        for bad in [
            overflow,
            empty,
            missing_segments,
            low,
            too_many,
            pot_glyphs(&["1", NOT_A_CHARACTER, "0"]),
            pot("1..2"),
            pot(",12"),
            pot("12,34"),
            pot("1.234"),
            pot("99999999"),
        ] {
            let outcome = run_table(vec![
                ("p0_full", p0(&[])),
                ("p2_board", board(&FLOP)),
                ("p3_pot", bad),
            ]);
            assert_table_null(&outcome);
            assert_eq!(outcome.calls, ["p0_full", "p2_board", "p3_pot"]);
        }
    }

    #[test]
    fn amount_parser_follows_the_r5_pattern() {
        for (text, expected) in [
            ("0", Some(0)),
            ("007", Some(700)),
            ("1.05", Some(105)),
            ("1.5", Some(150)),
            ("1,234.5", Some(123450)),
            ("1,234,567.89", Some(123456789)),
            ("42949672.95", Some(u32::MAX)),
            ("42949672.96", None),
            ("1..2", None),
            (",12", None),
            ("1234,567", None),
            ("1,23", None),
            ("1.", None),
            (".5", None),
            ("1.234", None),
            ("", None),
            ("1,234.", None),
            ("12a", None),
        ] {
            assert_eq!(parse_amount(text), expected, "{text:?}");
        }
    }

    #[test]
    fn threshold_override_only_raises_pass_thresholds() {
        let at = |p: f64| {
            let mut passes = flop_passes(&[]);
            for (_, answers) in &mut passes {
                for answer in answers.answers.values_mut() {
                    // Keep noul polarity: confident true -> p, confident false -> 1 - p.
                    answer.p = if answer.choice.is_none() && answer.p < 0.5 {
                        1.0 - p
                    } else {
                        p
                    };
                }
            }
            passes
        };
        let readable = |outcome: &Outcome| !outcome.envelope["state"].is_null();
        assert!(readable(&assemble_script(at(0.85), (800, 613), None, None)));
        assert!(readable(&assemble_script(
            at(0.85),
            (800, 613),
            None,
            Some(0.80)
        )));
        assert!(!readable(&assemble_script(
            at(0.85),
            (800, 613),
            None,
            Some(0.9)
        )));
        assert!(!readable(&assemble_script(
            at(0.75),
            (800, 613),
            None,
            None
        )));
        assert!(!readable(&assemble_script(
            at(0.75),
            (800, 613),
            None,
            Some(0.5)
        )));
    }

    #[test]
    fn r6_validator_failures_degrade_without_repair() {
        let duplicate = [("A", "spades"), ("A", "spades"), ("7", "clubs")];
        let outcome = run_table(vec![
            ("p0_full", p0(&[])),
            ("p2_board", board(&duplicate)),
            ("p3_pot", pot("100")),
        ]);
        assert_table_null(&outcome);
        assert_eq!(outcome.envelope["evidence"]["pot"], true);
        assert_eq!(outcome.calls, ["p0_full", "p2_board", "p3_pot"]);
    }

    #[test]
    fn untrained_passes_are_never_run_and_errors_abort() {
        let mut seen = Vec::new();
        let result = assemble(
            question_set(),
            (800, 613),
            None,
            None,
            &mut |pass: &Pass| {
                seen.push(pass.id.clone());
                match pass.id.as_str() {
                    "p0_full" => Ok(p0(&[])),
                    _ => Err(VlmError::Request("synthetic".into())),
                }
            },
        );
        assert!(matches!(result, Err(VlmError::Request(_))));
        assert_eq!(seen, ["p0_full", "p2_board"]);
        for pass in &question_set().passes {
            if pass.calibration == Calibration::UntrainedProvisional {
                let reading = run_pass(question_set(), &pass.id, None, &mut |_: &Pass| -> Result<
                    PassAnswers,
                    VlmError,
                > {
                    panic!("untrained pass must not run")
                })
                .unwrap();
                assert!(reading.answers.answers.is_empty());
                assert_eq!(reading.answers.acceptance_floor, None);
            }
        }
    }

    struct XorShift(u64);

    impl XorShift {
        fn next(&mut self) -> u64 {
            let mut x = self.0;
            x ^= x << 13;
            x ^= x >> 7;
            x ^= x << 17;
            self.0 = x;
            x
        }
        fn unit(&mut self) -> f64 {
            (self.next() >> 40) as f64 / (1u64 << 24) as f64
        }
        fn below(&mut self, n: usize) -> usize {
            (self.next() % n as u64) as usize
        }
        fn chance(&mut self, p: f64) -> bool {
            self.unit() < p
        }
        fn pick<'a>(&mut self, items: &[&'a str]) -> &'a str {
            items[self.below(items.len())]
        }
        fn probability(&mut self) -> f64 {
            match self.below(4) {
                0 => self.unit(),
                1 => 0.8 + 0.2 * self.unit(),
                2 => 0.2 * self.unit(),
                _ => 0.95,
            }
        }
    }

    fn random_pass(
        rng: &mut XorShift,
        pass: &Pass,
        steered: bool,
        board_count: usize,
        street: &str,
    ) -> PassAnswers {
        let preferred: HashMap<&str, (Option<&str>, f64)> = [
            ("screen_kind", (Some("poker_table"), 0.99)),
            ("ev_table_layout", (None, 0.99)),
            ("ev_hero_cards", (None, 0.01)),
            ("ev_board_area", (None, 0.99)),
            ("ev_pot", (None, 0.99)),
            ("ev_action_controls", (None, 0.01)),
            ("ev_seat_controls", (None, 0.99)),
            ("ev_readable", (None, 0.99)),
            ("game_phase", (Some(street), 0.99)),
            ("action_on_hero", (None, 0.01)),
            ("hero_seat_index", (Some("not_seated"), 0.99)),
        ]
        .into();
        let mut answers = HashMap::new();
        let glyph_count = 1 + rng.below(8);
        for question in &pass.questions {
            if rng.chance(0.03) {
                continue;
            }
            let options = question.options();
            let mut answer = match question.kind {
                QuestionType::Choice => choice(rng.pick(&options), rng.probability()),
                QuestionType::Noul => noul(rng.probability()),
            };
            if steered && rng.chance(0.93) {
                if let Some((label, p)) = preferred.get(question.id.as_str()) {
                    answer = Answer {
                        choice: label.map(str::to_string),
                        p: *p,
                        truncated: false,
                    };
                } else if let Some(rest) = question.id.strip_prefix("board_") {
                    let slot: usize = rest[..1].parse().unwrap();
                    let label = if slot > board_count {
                        NO_CARD
                    } else if rest.ends_with("rank") {
                        rng.pick(&RANKS)
                    } else {
                        rng.pick(&SUITS)
                    };
                    answer = choice(label, 0.97);
                } else if pass.layout == Layout::Glyphs {
                    let glyph = if rng.chance(0.85) {
                        rng.pick(&["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"])
                    } else {
                        rng.pick(&[",", ".", NOT_A_CHARACTER])
                    };
                    answer = choice(glyph, 0.97);
                }
            }
            answer.truncated = rng.chance(0.02);
            answers.insert(question.id.clone(), answer);
        }
        let segments = if pass.layout == Layout::Glyphs {
            if steered && rng.chance(0.9) {
                Some(Segments {
                    n: glyph_count as u32,
                    overflow: false,
                })
            } else if rng.chance(0.8) {
                Some(Segments {
                    n: rng.below(11) as u32,
                    overflow: rng.chance(0.2),
                })
            } else {
                None
            }
        } else if rng.chance(0.05) {
            Some(Segments {
                n: rng.below(9) as u32,
                overflow: rng.chance(0.5),
            })
        } else {
            None
        };
        PassAnswers {
            answers,
            segments,
            acceptance_floor: Some(0.8),
        }
    }

    #[test]
    fn seeded_random_answer_maps_always_produce_parseable_envelopes() {
        let mut rng = XorShift(0x9E37_79B9_7F4A_7C15);
        let mut states = 0;
        let mut kinds: HashMap<String, usize> = HashMap::new();
        for iteration in 0..1000 {
            let steered = iteration % 2 == 0;
            let board_count = [0, 3, 4, 5, 2][rng.below(5)];
            let street = match board_count {
                _ if rng.chance(0.15) => "turn",
                0 => "preflop",
                3 => "flop",
                4 => "turn",
                _ => ["river", "showdown"][rng.below(2)],
            };
            let frame = if rng.chance(0.05) {
                (1280, 1032)
            } else {
                (800 + rng.below(500) as u32, 600 + rng.below(400) as u32)
            };
            let threshold = rng.chance(0.2).then(|| (0.8 + 0.19 * rng.unit()) as f32);
            let mut rng_inner = XorShift(rng.next() | 1);
            let text = assemble(
                question_set(),
                frame,
                Some((1280, 1032)),
                threshold,
                &mut |pass: &Pass| {
                    Ok(random_pass(
                        &mut rng_inner,
                        pass,
                        steered,
                        board_count,
                        street,
                    ))
                },
            )
            .expect("scripted passes never fail");
            let observation = parse_screen_output(&VlmOutput { text })
                .unwrap_or_else(|error| panic!("iteration {iteration}: {error}"));
            states += usize::from(observation.state.is_some());
            *kinds
                .entry(format!("{:?}", observation.screen_kind))
                .or_default() += 1;
        }
        assert!(states >= 20, "only {states} random states reached assembly");
        assert!(kinds.len() >= 3, "{kinds:?}");
    }
}
