//! Independent Laya field assembly. Incomplete evidence is not an actionable GameState.

use std::collections::HashMap;

use super::assembly::parse_amount;
use super::client::PassAnswers;
use super::geometry;
use super::questions::{Calibration, Pass, QuestionSet, QuestionType};
use crate::parser::{Card, GamePhase};
use crate::partial::{
    DiagnosticReason as Reason, EvidenceStatus as Status, FieldEvidence, FieldName,
    PartialObservation, PartialObservationView, PassDiagnostic, PerceptionDiagnostics,
    QuestionDiagnostic, SafeAnswer, SegmentDiagnostic, UNSUPPORTED_SEAT_FIELDS,
};
use crate::runtime::ObservationRole;
use crate::vlm::VlmError;

const RANKS: [&str; 13] = [
    "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A",
];
const SUITS: [&str; 4] = ["spades", "hearts", "diamonds", "clubs"];

pub(super) struct Reading<'a> {
    pub(super) pass: &'a Pass,
    pub(super) answers: PassAnswers,
    pub(super) floor: Option<f64>,
    pub(super) failure: Option<Reason>,
}
impl Reading<'_> {
    pub(super) fn diagnostic(&self, id: &str) -> QuestionDiagnostic {
        let question = self.pass.question(id).expect("only vendored question IDs");
        let answer = self.answers.answers.get(id);
        let score = answer
            .filter(|a| a.p.is_finite() && (0.0..=1.0).contains(&a.p))
            .map(|a| a.p);
        let safe_answer = answer.and_then(|a| match question.kind {
            QuestionType::Choice => a
                .choice
                .as_ref()
                .filter(|label| question.has_option(label))
                .map(|label| SafeAnswer::Choice(label.clone())),
            QuestionType::Noul if a.choice.is_none() => score.map(|p| SafeAnswer::Noul(p >= 0.5)),
            _ => None,
        });
        let reason = if let Some(failure) = self.failure {
            failure
        } else if answer.is_none() {
            Reason::MissingAnswer
        } else if answer.is_some_and(|a| a.truncated) {
            Reason::Truncated
        } else if let (Some(p), Some(_)) = (score, safe_answer.as_ref()) {
            if let Some(floor) = self.floor {
                let confident = if question.kind == QuestionType::Noul {
                    p >= floor || p <= 1.0 - floor
                } else {
                    p >= floor
                };
                if confident {
                    Reason::Accepted
                } else {
                    Reason::BelowFloor
                }
            } else {
                Reason::InvalidFloor
            }
        } else {
            Reason::InvalidAnswer
        };
        let status = match reason {
            Reason::Accepted => Status::Accepted,
            Reason::MissingAnswer
            | Reason::PassUnavailable
            | Reason::CropTooSmall
            | Reason::DecisionDeadline => Status::Unknown,
            _ => Status::Rejected,
        };
        QuestionDiagnostic {
            question: id.into(),
            answer: safe_answer,
            score,
            effective_floor: self.floor,
            status,
            reason,
            truncated: answer.is_some_and(|a| a.truncated),
        }
    }
    pub(super) fn choice(&self, id: &str) -> Option<&str> {
        (self.diagnostic(id).status == Status::Accepted)
            .then(|| self.answers.answers.get(id)?.choice.as_deref())
            .flatten()
    }
    fn noul(&self, id: &str) -> Option<bool> {
        (self.diagnostic(id).status == Status::Accepted)
            .then(|| {
                self.answers
                    .answers
                    .get(id)
                    .map(|a| a.p >= self.floor.unwrap())
            })
            .flatten()
    }
}

pub(super) fn record(
    fields: &mut Vec<FieldEvidence>,
    field: FieldName,
    seat: Option<u8>,
    board_slot: Option<u8>,
    status: Status,
    reason: Reason,
) {
    fields.push(FieldEvidence {
        field,
        seat,
        board_slot,
        status,
        reason,
        admission_status: if status == Status::Accepted {
            Status::Unknown
        } else {
            status
        },
        admission_reason: if status == Status::Accepted {
            Reason::AwaitingConsensus
        } else {
            reason
        },
    });
}

fn run_reading<'a>(
    qs: &'a QuestionSet,
    id: &str,
    frame: (u32, u32),
    threshold: Option<f32>,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
    diagnostics: &mut PerceptionDiagnostics,
    cache: &mut HashMap<String, PassAnswers>,
) -> Result<Reading<'a>, VlmError> {
    let pass = qs.pass(id).expect("existing vendored pass");
    let min = geometry::regions().geometry.min_crop_px;
    let bounds: Vec<[u32; 4]> = if pass.regions.is_empty() {
        vec![[0, 0, frame.0, frame.1]]
    } else {
        pass.regions
            .iter()
            .filter_map(|name| geometry::region_px(name, frame.0, frame.1))
            .map(|(a, b, c, d)| [a, b, c, d])
            .collect()
    };
    let crop_dimensions: Vec<[u32; 2]> = bounds
        .iter()
        .map(|[a, b, c, d]| [c.saturating_sub(*a), d.saturating_sub(*b)])
        .collect();
    let crop_ok = !bounds.is_empty() && crop_dimensions.iter().all(|[w, h]| *w >= min && *h >= min);
    let (answers, failure) = if diagnostics.admission
        == crate::partial::DiagnosticAdmission::DecisionBudgetExpired
    {
        (PassAnswers::default(), Some(Reason::DecisionDeadline))
    } else if pass.calibration == Calibration::UntrainedProvisional {
        (PassAnswers::default(), Some(Reason::Unsupported))
    } else if !crop_ok {
        (PassAnswers::default(), Some(Reason::CropTooSmall))
    } else {
        match run(pass) {
            Ok(answers) => (answers, None),
            Err(VlmError::Deadline) => {
                diagnostics.admission = crate::partial::DiagnosticAdmission::DecisionBudgetExpired;
                (PassAnswers::default(), Some(Reason::DecisionDeadline))
            }
            Err(_) => (PassAnswers::default(), Some(Reason::PassUnavailable)),
        }
    };
    // It1 fitted floors are immutable. A server omission/invalid value cannot relax them.
    let pinned = if id == "p0_full" {
        0.995
    } else if id == "p2_board" {
        1.0
    } else {
        0.8
    };
    let floor = answers
        .acceptance_floor
        .filter(|t| t.is_finite() && (0.0..=1.0).contains(t))
        .map(|t| {
            t.max(pass.threshold)
                .max(pinned)
                .max(threshold.map_or(0.0, f64::from))
        });
    cache.insert(id.into(), answers.clone());
    let reading = Reading {
        pass,
        answers,
        floor,
        failure,
    };
    diagnostics.passes.push(PassDiagnostic {
        pass: id.into(),
        crop_bounds: bounds,
        crop_dimensions,
        questions: pass
            .questions
            .iter()
            .map(|q| reading.diagnostic(&q.id))
            .collect(),
        segments: reading.answers.segments.map(|s| SegmentDiagnostic {
            n: s.n,
            overflow: s.overflow,
        }),
        total_ms: None,
    });
    Ok(reading)
}

fn amount(reading: &Reading<'_>, max_glyphs: u32) -> (Option<(u32, String)>, Status, Reason) {
    if let Some(reason) = reading.failure {
        return (None, Status::Unknown, reason);
    }
    if reading.floor.is_none() {
        return (None, Status::Rejected, Reason::InvalidFloor);
    }
    let Some(segments) = reading.answers.segments else {
        return (None, Status::Unknown, Reason::MissingSegments);
    };
    if segments.overflow || segments.n > max_glyphs {
        return (None, Status::Rejected, Reason::SegmentationOverflow);
    }
    if segments.n == 0 {
        return (None, Status::Unknown, Reason::EmptySegmentation);
    }
    let mut text = String::new();
    for k in 1..=segments.n {
        let id = format!("g{k}");
        let Some(glyph) = reading.choice(&id) else {
            let d = reading.diagnostic(&id);
            return (None, d.status, d.reason);
        };
        if glyph == "not_a_character" {
            return (None, Status::Rejected, Reason::InvalidAmount);
        }
        text.push_str(glyph);
    }
    match parse_amount(&text) {
        Some(value) => (Some((value, text)), Status::Accepted, Reason::Accepted),
        None => (None, Status::Rejected, Reason::InvalidAmount),
    }
}

/// All trained amount paths are tried after the core gate even when role/board fails.
/// No new/untrained question, pass or crop is sent to the model.
pub type PartialAssembly = (
    Option<PartialObservation>,
    PerceptionDiagnostics,
    HashMap<String, PassAnswers>,
);

pub fn assemble_partial(
    qs: &QuestionSet,
    frame: (u32, u32),
    lobby: Option<(u32, u32)>,
    threshold: Option<f32>,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
) -> Result<PartialAssembly, VlmError> {
    let mut diagnostics = PerceptionDiagnostics {
        frame_width: frame.0,
        frame_height: frame.1,
        ..PerceptionDiagnostics::default()
    };
    let mut cache = HashMap::new();
    let p0 = run_reading(
        qs,
        "p0_full",
        frame,
        threshold,
        run,
        &mut diagnostics,
        &mut cache,
    )?;
    let mut core = true;
    for (field, id, expected) in [
        (FieldName::ScreenKind, "screen_kind", true),
        (FieldName::TableLayout, "ev_table_layout", true),
        (FieldName::Readable, "ev_readable", true),
    ] {
        let d = p0.diagnostic(id);
        let matches = if field == FieldName::ScreenKind {
            p0.choice(id) == Some("poker_table")
        } else {
            p0.noul(id) == Some(expected)
        };
        let (status, reason) = if matches {
            (Status::Accepted, Reason::Accepted)
        } else if d.status == Status::Accepted {
            (
                Status::Rejected,
                match field {
                    FieldName::Readable => Reason::Occluded,
                    FieldName::TableLayout => Reason::Unsupported,
                    _ => Reason::NonTable,
                },
            )
        } else {
            (d.status, d.reason)
        };
        record(&mut diagnostics.fields, field, None, None, status, reason);
        core &= matches;
    }
    if lobby == Some(frame) {
        record(
            &mut diagnostics.fields,
            FieldName::ScreenKind,
            None,
            None,
            Status::Rejected,
            Reason::LobbyGeometry,
        );
        core = false;
    }
    if !core {
        return Ok((None, diagnostics, cache));
    }

    let mut view = PartialObservationView::default();
    let mut fields = diagnostics.fields.clone();
    let unseated = p0.choice("hero_seat_index") == Some("not_seated")
        && p0.noul("action_on_hero") == Some(false)
        && p0.noul("ev_seat_controls") == Some(true)
        && p0.noul("ev_hero_cards") == Some(false)
        && p0.noul("ev_action_controls") == Some(false);
    if unseated {
        view.role = Some(ObservationRole::Observing);
        view.hero_seated = Some(false);
    }
    let contradictory = p0.choice("hero_seat_index") == Some("not_seated")
        && (p0.noul("action_on_hero") == Some(true)
            || p0.noul("ev_hero_cards") == Some(true)
            || p0.noul("ev_action_controls") == Some(true));
    for field in [FieldName::Role, FieldName::HeroSeated] {
        record(
            &mut fields,
            field,
            None,
            None,
            if unseated {
                Status::Accepted
            } else if contradictory {
                Status::Rejected
            } else {
                Status::Unknown
            },
            if unseated {
                Reason::Accepted
            } else if contradictory {
                Reason::RoleContradiction
            } else {
                [
                    "hero_seat_index",
                    "action_on_hero",
                    "ev_seat_controls",
                    "ev_hero_cards",
                    "ev_action_controls",
                ]
                .iter()
                .map(|id| p0.diagnostic(id))
                .find(|d| d.status != Status::Accepted)
                .map_or(Reason::Unsupported, |d| d.reason)
            },
        );
    }

    let board = run_reading(
        qs,
        "p2_board",
        frame,
        threshold,
        run,
        &mut diagnostics,
        &mut cache,
    )?;
    let mut presence = [None; 5];
    let board_allowed = p0.noul("ev_board_area") == Some(true);
    for (i, present) in presence.iter_mut().enumerate() {
        let rank_id = format!("board_{}_rank", i + 1);
        let suit_id = format!("board_{}_suit", i + 1);
        let rank = board.choice(&rank_id);
        let suit = board.choice(&suit_id);
        let occluded = rank == Some("unreadable") || suit == Some("unreadable");
        let contradiction = (rank == Some("no_card") && suit.is_some_and(|s| SUITS.contains(&s)))
            || (suit == Some("no_card") && rank.is_some_and(|r| RANKS.contains(&r)));
        let card = if board_allowed && !contradiction && !occluded {
            if rank == Some("no_card") && suit == Some("no_card") {
                *present = Some(false);
            } else if rank.is_some_and(|r| RANKS.contains(&r))
                || suit.is_some_and(|s| SUITS.contains(&s))
            {
                *present = Some(true);
            }
            match (rank, suit) {
                (Some(rank), Some(suit)) if RANKS.contains(&rank) && SUITS.contains(&suit) => {
                    Some(Card {
                        rank: rank.into(),
                        suit: suit.into(),
                    })
                }
                _ => None,
            }
        } else {
            None
        };
        let reason = if !board_allowed {
            let d = p0.diagnostic("ev_board_area");
            if d.status == Status::Accepted {
                Reason::Occluded
            } else {
                d.reason
            }
        } else if occluded {
            Reason::Occluded
        } else if contradiction {
            Reason::InvalidAnswer
        } else if card.is_some() || *present == Some(false) {
            Reason::Accepted
        } else {
            let rank_d = board.diagnostic(&rank_id);
            if rank_d.status != Status::Accepted {
                rank_d.reason
            } else {
                board.diagnostic(&suit_id).reason
            }
        };
        let status = if reason == Reason::Accepted {
            Status::Accepted
        } else if matches!(
            reason,
            Reason::MissingAnswer
                | Reason::DependencyUnknown
                | Reason::CropTooSmall
                | Reason::PassUnavailable
                | Reason::DecisionDeadline
        ) {
            Status::Unknown
        } else {
            Status::Rejected
        };
        view.board_slots[i] = card;
        record(
            &mut fields,
            FieldName::BoardSlot,
            None,
            Some(i as u8 + 1),
            status,
            reason,
        );
    }
    // Duplicate identities reject the conflicting cards; amount fields survive.
    for i in 0..5 {
        if view.board_slots[i].is_some()
            && (0..5).any(|j| i != j && view.board_slots[j] == view.board_slots[i])
        {
            for evidence in fields
                .iter_mut()
                .filter(|f| f.field == FieldName::BoardSlot && f.board_slot == Some(i as u8 + 1))
            {
                evidence.status = Status::Rejected;
                evidence.reason = Reason::DuplicateCard;
            }
        }
    }
    for field in fields
        .iter()
        .filter(|f| f.field == FieldName::BoardSlot && f.reason == Reason::DuplicateCard)
    {
        view.board_slots[field.board_slot.unwrap() as usize - 1] = None;
    }
    let count = presence.iter().take_while(|p| **p == Some(true)).count();
    let (count_status, count_reason) = if presence.iter().any(Option::is_none) {
        (Status::Unknown, Reason::BoardPresenceUnknown)
    } else if presence[count..].contains(&Some(true)) {
        (Status::Rejected, Reason::BoardNoncontiguous)
    } else if !matches!(count, 0 | 3 | 4 | 5) {
        (Status::Rejected, Reason::BoardCountInvalid)
    } else {
        view.board_count = Some(count as u8);
        (Status::Accepted, Reason::Accepted)
    };
    record(
        &mut fields,
        FieldName::BoardCount,
        None,
        None,
        count_status,
        count_reason,
    );
    let phase = match p0.choice("game_phase") {
        Some("preflop") => Some(GamePhase::Preflop),
        Some("flop") => Some(GamePhase::Flop),
        Some("turn") => Some(GamePhase::Turn),
        Some("river") => Some(GamePhase::River),
        Some("showdown") => Some(GamePhase::Showdown),
        _ => None,
    };
    let (phase_status, phase_reason) = match (phase, view.board_count) {
        (Some(phase), Some(count)) if phase.expected_board_cards() == usize::from(count) => {
            view.game_phase = Some(phase);
            (Status::Accepted, Reason::Accepted)
        }
        (Some(_), Some(_)) => (Status::Rejected, Reason::PhaseBoardMismatch),
        (Some(_), None) => (Status::Unknown, Reason::BoardPresenceUnknown),
        _ => {
            let d = p0.diagnostic("game_phase");
            (d.status, d.reason)
        }
    };
    record(
        &mut fields,
        FieldName::GamePhase,
        None,
        None,
        phase_status,
        phase_reason,
    );

    let pot = run_reading(
        qs,
        "p3_pot",
        frame,
        threshold,
        run,
        &mut diagnostics,
        &mut cache,
    )?;
    let (pot_amount, mut status, mut reason) = amount(&pot, qs.max_glyphs);
    if p0.noul("ev_pot") == Some(true) {
        if let Some((value, text)) = pot_amount {
            view.pot_size = Some(value);
            view.pot_size_text = Some(text);
        }
    } else {
        (status, reason) = if p0.noul("ev_pot") == Some(false) {
            (Status::Rejected, Reason::DependencyRejected)
        } else {
            let d = p0.diagnostic("ev_pot");
            (d.status, d.reason)
        };
    }
    record(&mut fields, FieldName::PotSize, None, None, status, reason);
    for seat in 1..=6 {
        let id = format!("p5_seat_{seat}_stack");
        let reading = run_reading(qs, &id, frame, threshold, run, &mut diagnostics, &mut cache)?;
        let (stack, status, reason) = amount(&reading, qs.max_glyphs);
        if let Some((value, text)) = stack {
            view.seats[seat as usize - 1].displayed_stack = Some(value);
            view.seats[seat as usize - 1].displayed_stack_text = Some(text);
        }
        record(
            &mut fields,
            FieldName::DisplayedStack,
            Some(seat),
            None,
            status,
            reason,
        );
        for field in UNSUPPORTED_SEAT_FIELDS {
            record(
                &mut fields,
                field,
                Some(seat),
                None,
                Status::Unknown,
                Reason::Unsupported,
            );
        }
    }
    view.refresh_verified_fields();
    diagnostics.fields = fields.clone();
    let expired =
        diagnostics.admission == crate::partial::DiagnosticAdmission::DecisionBudgetExpired;
    if expired {
        diagnostics.set_admission(
            crate::partial::DiagnosticAdmission::DecisionBudgetExpired,
            None,
        );
    }
    Ok((
        (!expired).then_some(PartialObservation {
            view,
            evidence: fields,
            frame_width: frame.0,
            frame_height: frame.1,
            core_accepted: true,
            wager_sources: std::array::from_fn(|_| None),
            scene_sources: std::array::from_fn(|_| None),
            source_witness: None,
        }),
        diagnostics,
        cache,
    ))
}

/// Opt-in extension of the same table core and amount reader, not a second state pipeline.
pub fn assemble_partial_with_wagers(
    qs: &QuestionSet,
    frame: (u32, u32),
    lobby: Option<(u32, u32)>,
    threshold: Option<f32>,
    registry: &super::wager::WagerPassRegistry,
    run: &mut dyn FnMut(&Pass) -> Result<PassAnswers, VlmError>,
) -> Result<PartialAssembly, VlmError> {
    // Model binding is checked by Backend opt-in and again by the transport adapter.
    registry.validate_namespace()?;
    let (mut partial, mut diagnostics, cache) = assemble_partial(qs, frame, lobby, threshold, run)?;
    let Some(candidate) = partial.as_mut() else {
        return Ok((partial, diagnostics, cache));
    };
    for seat in 1..=6 {
        candidate
            .evidence
            .retain(|f| !(f.field == FieldName::VisibleWager && f.seat == Some(seat)));
        let Some(entry) = registry.seat(seat) else {
            record(
                &mut candidate.evidence,
                FieldName::VisibleWager,
                Some(seat),
                None,
                Status::Unknown,
                Reason::Unsupported,
            );
            continue;
        };
        if let Err(reason) = entry.qualification() {
            record(
                &mut candidate.evidence,
                FieldName::VisibleWager,
                Some(seat),
                None,
                Status::Unknown,
                reason,
            );
            continue;
        }
        let pass = entry
            .pass_descriptor(qs)
            .expect("qualified closed glyph descriptor");
        let bounds = entry
            .crop_bounds(frame.0, frame.1)
            .expect("qualified reference dimensions");
        let [a, b, c, d] = bounds;
        let min = geometry::regions().geometry.min_crop_px;
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
                    diagnostics.admission =
                        crate::partial::DiagnosticAdmission::DecisionBudgetExpired;
                    (PassAnswers::default(), Some(Reason::DecisionDeadline))
                }
                Err(VlmError::Unavailable(code))
                    if code == "wager-capability-identity-mismatch" =>
                {
                    (PassAnswers::default(), Some(Reason::IdentityMismatch))
                }
                Err(VlmError::Unavailable(code)) if code == "wager-fitted-floor-mismatch" => {
                    (PassAnswers::default(), Some(Reason::InvalidFloor))
                }
                Err(_) => (PassAnswers::default(), Some(Reason::PassUnavailable)),
            }
        };
        let floor = answers
            .acceptance_floor
            .filter(|f| f.is_finite() && *f <= 1.0 && *f >= entry.fitted_floor.unwrap())
            .map(|f| f.max(threshold.map_or(0.0, f64::from)));
        let reading = Reading {
            pass: &pass,
            answers,
            floor,
            failure,
        };
        let (value, status, reason) = amount(&reading, qs.max_glyphs);
        diagnostics.passes.push(PassDiagnostic {
            pass: pass.id.clone(),
            crop_bounds: vec![bounds],
            crop_dimensions: vec![[c.saturating_sub(a), d.saturating_sub(b)]],
            questions: pass
                .questions
                .iter()
                .map(|q| reading.diagnostic(&q.id))
                .collect(),
            segments: reading.answers.segments.map(|s| SegmentDiagnostic {
                n: s.n,
                overflow: s.overflow,
            }),
            total_ms: None,
        });
        if let Some((value, text)) = value {
            candidate.view.seats[seat as usize - 1].visible_wager = Some(value);
            candidate.view.seats[seat as usize - 1].visible_wager_text = Some(text);
        }
        candidate.wager_sources[seat as usize - 1] = Some(entry.clone());
        if let Some(capability) = candidate
            .view
            .capabilities
            .iter_mut()
            .find(|c| c.field == FieldName::VisibleWager && c.seat == Some(seat))
        {
            *capability = entry.capability().unwrap();
        }
        record(
            &mut candidate.evidence,
            FieldName::VisibleWager,
            Some(seat),
            None,
            status,
            reason,
        );
        if diagnostics.admission == crate::partial::DiagnosticAdmission::DecisionBudgetExpired {
            diagnostics.fields.clone_from(&candidate.evidence);
            diagnostics.set_admission(
                crate::partial::DiagnosticAdmission::DecisionBudgetExpired,
                None,
            );
            return Ok((None, diagnostics, cache));
        }
    }
    candidate.view.refresh_verified_fields();
    diagnostics.fields.clone_from(&candidate.evidence);
    Ok((partial, diagnostics, cache))
}
