//! Synthetic closed answers only: no captures, model, GPU, or quality claims.
use std::collections::HashMap;

use ingest::laya::client::{Answer, PassAnswers, Segments};
use ingest::laya::partial::assemble_partial;
use ingest::laya::questions::{question_set, Pass};
use ingest::partial::{DiagnosticReason, EvidenceStatus, FieldName, TrainingStatus};
use ingest::vlm::VlmError;

fn choice(label: &str, p: f64) -> Answer {
    Answer {
        choice: Some(label.into()),
        p,
        truncated: false,
    }
}
fn flag(value: bool) -> Answer {
    Answer {
        choice: None,
        p: if value { 1.0 } else { 0.0 },
        truncated: false,
    }
}
fn scripts() -> HashMap<String, PassAnswers> {
    let mut passes = HashMap::new();
    let p0 = PassAnswers {
        acceptance_floor: Some(0.995),
        answers: [
            ("screen_kind", choice("poker_table", 1.0)),
            ("ev_table_layout", flag(true)),
            ("ev_readable", flag(true)),
            ("ev_board_area", flag(true)),
            ("ev_pot", flag(true)),
            ("ev_seat_controls", flag(true)),
            ("ev_hero_cards", flag(false)),
            ("ev_action_controls", flag(false)),
            ("action_on_hero", flag(false)),
            ("hero_seat_index", choice("not_seated", 1.0)),
            ("game_phase", choice("flop", 1.0)),
        ]
        .into_iter()
        .map(|(id, a)| (id.into(), a))
        .collect(),
        segments: None,
    };
    passes.insert("p0_full".into(), p0);
    let mut answers = HashMap::new();
    for (i, (rank, suit)) in [
        ("A", "spades"),
        ("K", "hearts"),
        ("Q", "clubs"),
        ("no_card", "no_card"),
        ("no_card", "no_card"),
    ]
    .into_iter()
    .enumerate()
    {
        answers.insert(format!("board_{}_rank", i + 1), choice(rank, 1.0));
        answers.insert(format!("board_{}_suit", i + 1), choice(suit, 1.0));
    }
    passes.insert(
        "p2_board".into(),
        PassAnswers {
            answers,
            acceptance_floor: Some(1.0),
            segments: None,
        },
    );
    passes.insert("p3_pot".into(), amount("10.5"));
    for seat in 1..=6 {
        passes.insert(
            format!("p5_seat_{seat}_stack"),
            amount(&format!("{seat}.25")),
        );
    }
    passes
}
fn amount(text: &str) -> PassAnswers {
    PassAnswers {
        answers: text
            .chars()
            .enumerate()
            .map(|(i, c)| (format!("g{}", i + 1), choice(&c.to_string(), 1.0)))
            .collect(),
        acceptance_floor: Some(0.8),
        segments: Some(Segments {
            n: text.len() as u32,
            overflow: false,
        }),
    }
}
fn assemble(
    passes: &HashMap<String, PassAnswers>,
    lobby: Option<(u32, u32)>,
) -> (
    Option<ingest::partial::PartialObservation>,
    ingest::partial::PerceptionDiagnostics,
    Vec<String>,
) {
    let mut calls = Vec::new();
    let (partial, diagnostics, _) = assemble_partial(
        question_set(),
        (800, 613),
        lobby,
        None,
        &mut |pass: &Pass| {
            calls.push(pass.id.clone());
            Ok(passes.get(&pass.id).unwrap().clone())
        },
    )
    .unwrap();
    (partial, diagnostics, calls)
}

#[test]
fn rejected_role_and_all_cards_preserve_independent_pot_and_six_stacks() {
    let mut passes = scripts();
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .get_mut("hero_seat_index")
        .unwrap()
        .p = 0.9925;
    for a in passes.get_mut("p2_board").unwrap().answers.values_mut() {
        a.p = 0.99999999;
    }
    let (partial, diagnostics, calls) = assemble(&passes, None);
    let partial = partial.unwrap();
    assert!(partial.core_accepted());
    assert_eq!(partial.view.role, None);
    assert_eq!(partial.view.hero_seated, None);
    assert_eq!(partial.view.game_phase, None);
    assert_eq!(partial.view.board_count, None);
    assert!(partial.view.board_slots.iter().all(Option::is_none));
    assert_eq!(partial.view.pot_size, Some(1050));
    assert_eq!(
        calls,
        [
            "p0_full",
            "p2_board",
            "p3_pot",
            "p5_seat_1_stack",
            "p5_seat_2_stack",
            "p5_seat_3_stack",
            "p5_seat_4_stack",
            "p5_seat_5_stack",
            "p5_seat_6_stack"
        ]
    );
    for (i, seat) in partial.view.seats.iter().enumerate() {
        assert_eq!(seat.seat, i as u8 + 1);
        assert_eq!(seat.displayed_stack, Some((i as u32 + 1) * 100 + 25));
        assert!(seat.occupied.is_none() && seat.visible_wager.is_none());
        assert!(seat.status.is_none() && seat.dealer.is_none() && seat.acting.is_none());
        assert!(seat.badge.is_none() && seat.street_contribution.is_none());
    }
    assert!(!partial.view.quality_approved);
    assert_eq!(diagnostics.passes[2].crop_bounds, [[320, 222, 512, 247]]);
    assert_eq!(diagnostics.passes[2].crop_dimensions, [[192, 25]]);
    assert!(diagnostics.timing.inference_ms.is_none() && diagnostics.timing.render_ms.is_none());
    let public = serde_json::to_string(&partial.view).unwrap();
    for private in ["crop_bounds", "questions", "score", "diagnostics", "name"] {
        assert!(!public.contains(private));
    }
}

#[test]
fn phase_requires_presence_count_but_not_every_card_identity() {
    let mut passes = scripts();
    passes
        .get_mut("p2_board")
        .unwrap()
        .answers
        .get_mut("board_1_suit")
        .unwrap()
        .p = 0.99999999;
    let view = assemble(&passes, None).0.unwrap().view;
    assert_eq!(view.board_count, Some(3));
    assert_eq!(view.game_phase, Some(ingest::parser::GamePhase::Flop));
    assert!(view.board_slots[0].is_none());
    assert!(view.board_slots[1].is_some());

    let board = passes.get_mut("p2_board").unwrap();
    for (i, rank, suit) in [(4, "J", "diamonds"), (5, "T", "spades")] {
        board
            .answers
            .insert(format!("board_{i}_rank"), choice(rank, 1.0));
        board
            .answers
            .insert(format!("board_{i}_suit"), choice(suit, 1.0));
    }
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .insert("game_phase".into(), choice("turn", 0.9976));
    let (partial, diagnostics, _) = assemble(&passes, None);
    let view = partial.unwrap().view;
    assert_eq!(view.board_count, Some(5));
    assert_eq!(
        view.game_phase, None,
        "confident wrong turn on five cards must fail"
    );
    assert_eq!(view.pot_size, Some(1050));
    assert!(diagnostics
        .fields
        .iter()
        .any(|f| f.field == FieldName::GamePhase
            && f.status == EvidenceStatus::Rejected
            && f.reason == DiagnosticReason::PhaseBoardMismatch));
}

#[test]
fn independent_field_failures_and_empty_segmentation_are_never_zero_or_open_seats() {
    let mut passes = scripts();
    passes.get_mut("p5_seat_1_stack").unwrap().segments = Some(Segments {
        n: 0,
        overflow: false,
    });
    passes
        .get_mut("p5_seat_2_stack")
        .unwrap()
        .answers
        .get_mut("g1")
        .unwrap()
        .truncated = true;
    passes.get_mut("p5_seat_3_stack").unwrap().acceptance_floor = None;
    passes.insert("p5_seat_4_stack".into(), amount("0"));
    passes.insert("p5_seat_5_stack".into(), amount("1..8"));
    let (partial, diagnostics, _) = assemble(&passes, None);
    let seats = partial.unwrap().view.seats;
    assert_eq!(
        seats.map(|s| s.displayed_stack),
        [None, None, None, Some(0), None, Some(625)]
    );
    for (seat, reason) in [
        (1, DiagnosticReason::EmptySegmentation),
        (2, DiagnosticReason::Truncated),
        (3, DiagnosticReason::InvalidFloor),
        (5, DiagnosticReason::InvalidAmount),
    ] {
        assert!(diagnostics
            .fields
            .iter()
            .any(|f| f.field == FieldName::DisplayedStack
                && f.seat == Some(seat)
                && f.reason == reason));
    }
}

#[test]
fn floor_overrides_never_lower_and_untrained_wager_proposals_have_no_floor() {
    let mut passes = scripts();
    for id in ["p0_full", "p2_board", "p3_pot", "p5_seat_1_stack"] {
        passes.get_mut(id).unwrap().acceptance_floor = Some(0.2);
    }
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .get_mut("screen_kind")
        .unwrap()
        .p = 0.99499999;
    assert!(assemble(&passes, None).0.is_none());
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .get_mut("screen_kind")
        .unwrap()
        .p = 0.995;
    passes
        .get_mut("p3_pot")
        .unwrap()
        .answers
        .get_mut("g1")
        .unwrap()
        .p = 0.79999999;
    passes
        .get_mut("p5_seat_1_stack")
        .unwrap()
        .answers
        .get_mut("g1")
        .unwrap()
        .p = 0.79999999;
    let view = assemble(&passes, None).0.unwrap().view;
    assert_eq!(view.pot_size, None);
    assert_eq!(view.seats[0].displayed_stack, None);
    for capability in view
        .capabilities
        .iter()
        .filter(|c| c.field == FieldName::VisibleWager)
    {
        assert_eq!(capability.training, TrainingStatus::Unsupported);
        assert_eq!(capability.acceptance_floor, None);
        assert!(!capability.held_out_approved && !capability.human_verified);
    }
    let proposals = ingest::partial::proposed_seat_crops();
    for seat in 1..=6 {
        let crop = proposals
            .iter()
            .find(|c| c.seat == seat && c.field == FieldName::VisibleWager)
            .unwrap();
        assert_eq!(crop.training, TrainingStatus::Unsupported);
        assert_eq!(crop.acceptance_floor, None);
        assert_eq!(crop.bounds.is_none(), seat == 1);
    }
}

#[test]
fn non_table_unreadable_layout_lobby_and_transition_core_never_run_amount_passes() {
    for bad in [
        "lobby",
        "unknown",
        "other_coin_poker_window",
        "layout",
        "readability",
        "geometry",
    ] {
        let mut passes = scripts();
        let p0 = passes.get_mut("p0_full").unwrap();
        match bad {
            "layout" => {
                p0.answers.insert("ev_table_layout".into(), flag(false));
            }
            "readability" => {
                p0.answers.insert("ev_readable".into(), flag(false));
            }
            "geometry" => {}
            kind => {
                p0.answers.insert("screen_kind".into(), choice(kind, 1.0));
            }
        }
        let (partial, _, calls) = assemble(&passes, (bad == "geometry").then_some((800, 613)));
        assert!(partial.is_none(), "{bad}");
        assert_eq!(calls, ["p0_full"]);
    }
}

#[test]
fn a_board_transport_failure_still_attempts_amounts_but_deadline_aborts_all() {
    let passes = scripts();
    let mut calls = Vec::new();
    let result = assemble_partial(question_set(), (800, 613), None, None, &mut |pass| {
        calls.push(pass.id.clone());
        if pass.id == "p2_board" {
            Err(VlmError::Request("private error body".into()))
        } else {
            Ok(passes.get(&pass.id).unwrap().clone())
        }
    })
    .unwrap();
    assert_eq!(result.0.unwrap().view.pot_size, Some(1050));
    assert_eq!(calls.len(), 9);
    assert!(!serde_json::to_string(&result.1)
        .unwrap()
        .contains("private error body"));
    let result = assemble_partial(question_set(), (800, 613), None, None, &mut |pass| {
        if pass.id == "p3_pot" {
            Err(VlmError::Deadline)
        } else {
            Ok(passes.get(&pass.id).unwrap().clone())
        }
    });
    let (partial, diagnostics, _) = result.unwrap();
    assert!(partial.is_none());
    assert_eq!(
        diagnostics.admission,
        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired
    );
    assert!(diagnostics
        .passes
        .iter()
        .any(|pass| pass.pass == "p0_full" && pass.questions.iter().any(|q| q.score == Some(1.0))));
}

pub(crate) fn synthetic_wager_registry() -> ingest::laya::wager::WagerPassRegistry {
    use ingest::laya::wager::{WagerPassConfig, WagerPassRegistry, WagerRegion};
    WagerPassRegistry {
        version: 1,
        model_alias: "coinpoker-laya-vision".into(),
        passes: (1..=6)
            .map(|seat| WagerPassConfig {
                seat,
                pass: format!("p6_seat_{seat}_wager"),
                region: Some(WagerRegion {
                    id: format!("seat_{seat}_wager"),
                    reference_dimensions: [800, 613],
                    bounds: Some([100, 100, 160, 130]),
                }),
                fitted_floor: Some(0.99),
                trained_candidate: true,
                candidate_sha256: Some("1".repeat(64)),
                model_sha256: Some("2".repeat(64)),
                capability_evidence_sha256: Some("3".repeat(64)),
                held_out_approved: true,
                human_verified: true,
                provenance: "observation-only-calibrated-pass".into(),
            })
            .collect(),
    }
}

fn assemble_wagers(
    passes: &HashMap<String, PassAnswers>,
    registry: &ingest::laya::wager::WagerPassRegistry,
    lobby: Option<(u32, u32)>,
) -> (
    Option<ingest::partial::PartialObservation>,
    ingest::partial::PerceptionDiagnostics,
    Vec<String>,
) {
    let mut calls = Vec::new();
    let (value, diagnostics, _) = ingest::laya::partial::assemble_partial_with_wagers(
        question_set(),
        (800, 613),
        lobby,
        None,
        registry,
        &mut |pass| {
            calls.push(pass.id.clone());
            if pass.id.starts_with("p6_") {
                let seat = pass.id.chars().nth(8).unwrap().to_digit(10).unwrap();
                let mut reading = amount(&format!("{}.75", seat + 10));
                reading.acceptance_floor = Some(0.99);
                Ok(reading)
            } else {
                Ok(passes.get(&pass.id).unwrap().clone())
            }
        },
    )
    .unwrap();
    (value, diagnostics, calls)
}

#[test]
fn synthetic_qualified_wagers_are_separate_from_all_six_stacks_cards_and_street_commitments() {
    let mut passes = scripts();
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .get_mut("hero_seat_index")
        .unwrap()
        .p = 0.9;
    for answer in passes.get_mut("p2_board").unwrap().answers.values_mut() {
        answer.p = 0.9;
    }
    let registry = synthetic_wager_registry();
    let (value, diagnostics, calls) = assemble_wagers(&passes, &registry, None);
    let value = value.unwrap();
    assert_eq!(calls.len(), 15);
    assert_eq!(
        &calls[9..],
        [
            "p6_seat_1_wager",
            "p6_seat_2_wager",
            "p6_seat_3_wager",
            "p6_seat_4_wager",
            "p6_seat_5_wager",
            "p6_seat_6_wager"
        ]
    );
    for (i, seat) in value.view.seats.iter().enumerate() {
        assert_eq!(seat.displayed_stack, Some((i as u32 + 1) * 100 + 25));
        assert_eq!(seat.visible_wager, Some((i as u32 + 11) * 100 + 75));
        assert_eq!(seat.street_contribution, None);
        let capability = value
            .view
            .capabilities
            .iter()
            .find(|c| c.field == FieldName::VisibleWager && c.seat == Some(seat.seat))
            .unwrap();
        assert_eq!(capability.training, TrainingStatus::ReadOnlyApproved);
        assert_eq!(capability.acceptance_floor, Some(0.99));
        assert!(capability.held_out_approved && capability.human_verified);
        assert!(serde_json::to_string(&value.view.verified_fields)
            .unwrap()
            .contains(&format!("seats.{}.visible_wager", i + 1)));
    }
    assert!(value.view.game_phase.is_none() && value.view.role.is_none());
    assert!(!value.view.quality_approved);
    assert!(diagnostics
        .passes
        .iter()
        .filter(|p| p.pass.starts_with("p6_"))
        .all(|p| p
            .questions
            .iter()
            .filter(|q| q.status == EvidenceStatus::Accepted)
            .all(|q| q.effective_floor == Some(0.99))));
    let public = serde_json::to_string(&value.view).unwrap();
    assert!(!public.contains("sha256") && !public.contains("score"));
}

#[test]
fn every_unqualified_wager_seat_is_not_requested_and_remains_unknown_without_borrowing_p3_floor() {
    let mut registry = synthetic_wager_registry();
    registry.passes[0].region.as_mut().unwrap().bounds = None;
    registry.passes[1].fitted_floor = None;
    registry.passes[2].held_out_approved = false;
    registry.passes[3].human_verified = false;
    registry.passes[4].trained_candidate = false;
    registry.passes[5].region.as_mut().unwrap().id = "pot".into();
    let (value, diagnostics, calls) = assemble_wagers(&scripts(), &registry, None);
    assert_eq!(calls.len(), 9);
    let value = value.unwrap();
    assert!(value
        .view
        .seats
        .iter()
        .all(|s| s.visible_wager.is_none() && s.displayed_stack.is_some()));
    assert!(value
        .view
        .capabilities
        .iter()
        .filter(|c| c.field == FieldName::VisibleWager)
        .all(|c| c.training == TrainingStatus::Unsupported && c.acceptance_floor.is_none()));
    for (seat, reason) in [
        (1, DiagnosticReason::UnknownRegion),
        (2, DiagnosticReason::InvalidFloor),
        (3, DiagnosticReason::UnapprovedCapability),
        (4, DiagnosticReason::UnapprovedCapability),
        (5, DiagnosticReason::UnapprovedCapability),
        (6, DiagnosticReason::UnknownRegion),
    ] {
        assert!(diagnostics
            .fields
            .iter()
            .any(|f| f.field == FieldName::VisibleWager
                && f.seat == Some(seat)
                && f.reason == reason));
    }
}

#[test]
fn missing_slot_one_does_not_block_other_qualified_wagers_and_lobby_blocks_all() {
    let mut registry = synthetic_wager_registry();
    registry.passes[0].region.as_mut().unwrap().bounds = None;
    let (value, _, calls) = assemble_wagers(&scripts(), &registry, None);
    assert_eq!(calls.len(), 14);
    assert!(value.as_ref().unwrap().view.seats[0]
        .visible_wager
        .is_none());
    assert!(value.unwrap().view.seats[1..]
        .iter()
        .all(|s| s.visible_wager.is_some()));
    let (value, _, calls) = assemble_wagers(&scripts(), &registry, Some((800, 613)));
    assert!(value.is_none());
    assert_eq!(calls, ["p0_full"]);
    let mut non_table = scripts();
    non_table
        .get_mut("p0_full")
        .unwrap()
        .answers
        .insert("screen_kind".into(), choice("unknown", 1.0));
    assert_eq!(assemble_wagers(&non_table, &registry, None).2, ["p0_full"]);
}

#[test]
fn wager_registry_rejects_bad_floors_identity_provenance_versions_and_unknown_regions() {
    use ingest::laya::wager::WagerPassRegistry;
    for floor in [
        None,
        Some(f64::NAN),
        Some(f64::INFINITY),
        Some(-0.1),
        Some(0.0),
        Some(1.1),
    ] {
        let mut registry = synthetic_wager_registry();
        registry.passes[0].fitted_floor = floor;
        assert_eq!(
            registry.passes[0].qualification(),
            Err(DiagnosticReason::InvalidFloor)
        );
    }
    for key in ["candidate", "model", "evidence", "provenance", "bounds"] {
        let mut registry = synthetic_wager_registry();
        match key {
            "candidate" => registry.passes[0].candidate_sha256 = Some("0".repeat(64)),
            "model" => registry.passes[0].model_sha256 = None,
            "evidence" => {
                registry.passes[0].capability_evidence_sha256 = Some("PRIVATE-NAME".into())
            }
            "provenance" => registry.passes[0].provenance = "it1-existing-pass".into(),
            _ => registry.passes[0].region.as_mut().unwrap().bounds = Some([100, 100, 900, 130]),
        }
        assert!(registry.passes[0].qualification().is_err());
    }
    let mut registry = synthetic_wager_registry();
    assert!(registry.validate_for_model("wrong-model").is_err());
    registry.version = 2;
    assert!(registry
        .validate_for_model("coinpoker-laya-vision")
        .is_err());
    let mut raw = serde_json::to_value(synthetic_wager_registry()).unwrap();
    raw["quality_approved"] = true.into();
    assert!(serde_json::from_value::<WagerPassRegistry>(raw).is_err());
    let mut registry = synthetic_wager_registry();
    registry.passes[1] = registry.passes[0].clone();
    assert!(registry
        .validate_for_model("coinpoker-laya-vision")
        .is_err());
}

#[test]
fn qualified_wager_scores_still_require_their_own_floor_valid_segmentation_and_deadline() {
    let passes = scripts();
    let registry = synthetic_wager_registry();
    let (value, diagnostics, _) = ingest::laya::partial::assemble_partial_with_wagers(
        question_set(),
        (800, 613),
        None,
        None,
        &registry,
        &mut |pass| {
            if !pass.id.starts_with("p6_") {
                return Ok(passes[&pass.id].clone());
            }
            let mut reading = amount("1");
            reading.acceptance_floor = Some(0.99);
            match pass.id.as_str() {
                "p6_seat_1_wager" => reading.answers.get_mut("g1").unwrap().p = 0.98,
                "p6_seat_2_wager" => reading.acceptance_floor = Some(0.8),
                "p6_seat_3_wager" => {
                    reading.segments = Some(Segments {
                        n: 0,
                        overflow: false,
                    })
                }
                "p6_seat_4_wager" => reading.answers.get_mut("g1").unwrap().truncated = true,
                "p6_seat_5_wager" => {
                    return Err(VlmError::Unavailable(
                        "wager-capability-identity-mismatch".into(),
                    ))
                }
                _ => {}
            }
            Ok(reading)
        },
    )
    .unwrap();
    let value = value.unwrap();
    assert_eq!(
        value.view.seats.map(|s| s.visible_wager),
        [None, None, None, None, None, Some(100)]
    );
    assert!(diagnostics
        .fields
        .iter()
        .any(|f| f.field == FieldName::VisibleWager
            && f.seat == Some(5)
            && f.reason == DiagnosticReason::IdentityMismatch));
    let result = ingest::laya::partial::assemble_partial_with_wagers(
        question_set(),
        (800, 613),
        None,
        None,
        &registry,
        &mut |pass| {
            if pass.id.starts_with("p6_") {
                Err(VlmError::Deadline)
            } else {
                Ok(passes[&pass.id].clone())
            }
        },
    )
    .unwrap();
    assert!(result.0.is_none());
    assert_eq!(
        result.1.admission,
        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired
    );
    assert!(result
        .1
        .passes
        .iter()
        .any(|p| p.pass == "p3_pot" && p.segments.is_some()));
}

#[test]
fn a_later_wager_deadline_keeps_prior_safe_field_traces_but_admits_nothing_and_stops_requests() {
    let passes = scripts();
    let registry = synthetic_wager_registry();
    let mut calls = Vec::new();
    let (partial, diagnostics, _) = ingest::laya::partial::assemble_partial_with_wagers(
        question_set(),
        (800, 613),
        None,
        None,
        &registry,
        &mut |pass| {
            calls.push(pass.id.clone());
            if pass.id == "p6_seat_2_wager" {
                return Err(VlmError::Deadline);
            }
            if pass.id.starts_with("p6_") {
                let mut reading = amount("1");
                reading.acceptance_floor = Some(0.99);
                Ok(reading)
            } else {
                Ok(passes[&pass.id].clone())
            }
        },
    )
    .unwrap();
    assert!(partial.is_none());
    assert_eq!(calls.len(), 11);
    assert_eq!(calls.last().unwrap(), "p6_seat_2_wager");
    assert!(!diagnostics.source_current);
    assert_eq!(
        diagnostics.admission,
        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired
    );
    assert!(diagnostics
        .fields
        .iter()
        .any(|f| f.field == FieldName::VisibleWager
            && f.seat == Some(1)
            && f.status == EvidenceStatus::Accepted
            && f.admission_status == EvidenceStatus::Rejected));
    assert!(diagnostics
        .fields
        .iter()
        .any(|f| f.field == FieldName::VisibleWager
            && f.seat == Some(2)
            && f.status == EvidenceStatus::Unknown
            && f.reason == DiagnosticReason::DecisionDeadline));
    assert!(diagnostics
        .passes
        .iter()
        .find(|p| p.pass == "p6_seat_1_wager")
        .unwrap()
        .questions
        .iter()
        .any(|q| q.question == "g1" && q.score == Some(1.0)));
}

#[test]
fn source_region_witnesses_bind_original_zero_frame_once_and_never_enter_public_or_diagnostics_json(
) {
    use ingest::capture::Frame;
    use ingest::partial::SourceWitnessError;
    let zero = Frame::new(800, 613, vec![0; 800 * 613 * 4]).unwrap();
    let (candidate, diagnostics, _) = assemble(&scripts(), None);
    let mut missing = candidate.clone().unwrap();
    assert!(!missing.retain_source_current_fields(&zero));
    assert!(missing.view.verified_fields.is_empty());
    let mut candidate = candidate.unwrap();
    let wrong = Frame::new(801, 613, vec![0; 801 * 613 * 4]).unwrap();
    assert_eq!(
        candidate.bind_source_frame(&wrong),
        Err(SourceWitnessError::GeometryMismatch)
    );
    candidate.bind_source_frame(&zero).unwrap();
    assert_eq!(
        candidate.bind_source_frame(&zero),
        Err(SourceWitnessError::AlreadyBound)
    );
    let original = candidate.view.clone();
    assert!(candidate.retain_source_current_fields(&zero));
    assert_eq!(candidate.view, original);
    let public = serde_json::to_string(&candidate.view).unwrap();
    let private = serde_json::to_string(&diagnostics).unwrap();
    assert!(
        !format!("{candidate:?}").contains("digest"),
        "witness Debug must redact fingerprints too"
    );
    for forbidden in ["source_witness", "digest", "rgba", "source_pixels"] {
        assert!(!public.contains(forbidden) && !private.contains(forbidden));
    }
}

#[test]
fn current_activity_witnesses_are_independent_and_never_tolerate_changed_field_pixels() {
    use ingest::capture::Frame;
    use ingest::laya::geometry::TABLE_READOUT_REGIONS;
    let original = Frame::new(800, 613, vec![64; 800 * 613 * 4]).unwrap();
    let mut candidate = assemble(&scripts(), None).0.unwrap();
    assert!(candidate.table_content_witness(&original).is_none());
    candidate.bind_source_frame(&original).unwrap();
    let baseline = candidate.table_content_witness(&original).unwrap();
    let mut cosmetic = original.clone();
    cosmetic.rgba[0] = 255;
    let witness = candidate.table_content_witness(&cosmetic).unwrap();
    assert!((0..12).all(|index| witness.same_region(&baseline, index)));
    candidate.retain_source_current_fields(&cosmetic);
    assert!(candidate.view.role.is_none() && candidate.view.game_phase.is_none());
    assert_eq!(candidate.view.pot_size, Some(1050));
    for (changed, region) in TABLE_READOUT_REGIONS.into_iter().enumerate() {
        let mut latest = original.clone();
        let (x, y, _, _) = ingest::laya::geometry::region_px(region, 800, 613).unwrap();
        latest.rgba[(y * 800 + x) as usize * 4] += 1;
        let witness = candidate.table_content_witness(&latest).unwrap();
        assert!(!witness.has_current_region(changed));
        assert!(!witness.same_region(&baseline, changed));
        assert!((0..12)
            .filter(|index| *index != changed)
            .all(|index| witness.same_region(&baseline, index)));
    }
    let different = Frame::new(800, 613, vec![65; 800 * 613 * 4]).unwrap();
    assert!(candidate.table_content_witness(&different).is_none());
    let resized = Frame::new(801, 613, vec![64; 801 * 613 * 4]).unwrap();
    assert!(candidate.table_content_witness(&resized).is_none());
}

#[test]
fn original_and_current_occlusion_masks_reject_equal_crop_hashes_independently() {
    use ingest::capture::{Frame, FrameReadability};
    let clear = Frame::new(800, 613, vec![64; 800 * 613 * 4]).unwrap();
    let (a, b, c, d) = ingest::laya::geometry::region_px("seat_1_stack", 800, 613).unwrap();
    let mut covered = clear.clone();
    covered.visibility.readability = FrameReadability::Regional;
    covered.visibility.occluded_regions = vec![[a, b, c, d]];
    assert_eq!(clear.rgba, covered.rgba);
    for (original, latest) in [(&covered, &covered), (&covered, &clear), (&clear, &covered)] {
        let mut candidate = assemble(&scripts(), None).0.unwrap();
        candidate.bind_source_frame(original).unwrap();
        let witness = candidate.table_content_witness(latest).unwrap();
        assert!(!witness.has_current_region(6));
        assert!(witness.has_current_region(5) && witness.has_current_region(7));
        assert!(candidate.retain_source_current_fields(latest));
        assert!(candidate.view.seats[0].displayed_stack.is_none());
        assert!(candidate.view.seats[0].displayed_stack_text.is_none());
        assert!(candidate.view.seats[0].occupied.is_none());
        assert!(candidate.view.role.is_none() && candidate.view.hero_seated.is_none());
        assert_eq!(candidate.view.pot_size, Some(1050));
        assert!(candidate.view.seats[1].displayed_stack.is_some());
        assert!(candidate
            .evidence
            .iter()
            .any(|field| field.field == FieldName::DisplayedStack
                && field.seat == Some(1)
                && field.admission_reason == DiagnosticReason::Occluded));
        assert!(candidate.retain_source_current_fields(&clear));
        assert!(
            candidate.view.seats[0].displayed_stack.is_none(),
            "no re-authoring the covered original"
        );
    }
}

#[test]
fn queued_original_capture_receipt_is_carried_without_latest_frame_substitution_or_lease_renewal() {
    use ingest::capture::Frame;
    use ingest::recorder::{CaptureStamp, PrivateRecorder, RecorderConfig};
    use std::fs;
    use std::time::{Duration, SystemTime, UNIX_EPOCH};
    let root = std::env::temp_dir().join(format!(
        "coinpoker-original-receipt-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    fs::create_dir(&root).unwrap();
    let mut recorder =
        PrivateRecorder::new(&root, RecorderConfig::default(), SystemTime::now()).unwrap();
    let session = recorder
        .session_path()
        .file_name()
        .unwrap()
        .to_str()
        .unwrap()
        .to_owned();
    let stamp = |ms| CaptureStamp {
        source_utc: UNIX_EPOCH + Duration::from_millis(1_791_642_000_000 + ms),
        captured_at_monotonic_ms: ms,
        generation: None,
        source_id: Some(u64::MAX),
    };
    let mut original = Frame::new(800, 613, vec![64; 800 * 613 * 4]).unwrap();
    let first = recorder.live_frame(&original, stamp(100), 11).unwrap();
    original.original_capture = Some(first.original_capture(session.clone()));
    let mut candidate = assemble(&scripts(), None).0.unwrap();
    candidate.bind_source_frame(&original).unwrap();
    let bound = candidate.view.original_capture.clone().unwrap();
    let mut latest = original.clone();
    latest.original_capture = Some(
        recorder
            .live_frame(&latest, stamp(200), 12)
            .unwrap()
            .original_capture(session),
    );
    assert!(candidate.retain_source_current_fields(&latest));
    assert_eq!(candidate.view.original_capture.as_ref(), Some(&bound));
    assert_eq!(bound.captured_at_monotonic_ms, 100);
    assert_eq!(bound.frame_index, 11);
    assert_eq!(
        bound.sha256,
        latest.original_capture.as_ref().unwrap().sha256
    );
    assert_eq!(
        bound.native_source_id.as_deref(),
        Some("18446744073709551615")
    );
    let mut next = assemble(&scripts(), None).0.unwrap();
    next.bind_source_frame(&latest).unwrap();
    assert_eq!(next.view.original_capture, latest.original_capture);
    let wire = serde_json::to_value(next.view).unwrap();
    assert_eq!(wire["original_capture"]["frame_index"], 12);
    assert_eq!(wire["original_capture"]["captured_at_monotonic_ms"], 200);
    assert_eq!(
        wire["original_capture"]["native_source_id"],
        "18446744073709551615"
    );
    for private in ["filename", "hwnd", "window_class", "exe_name", "title"] {
        assert!(wire["original_capture"].get(private).is_none());
    }
    latest.original_capture.as_mut().unwrap().width += 1;
    assert!(latest.validate().is_err());
}

#[test]
fn covered_board_is_unknown_not_gameplay_clear_and_global_unreadable_stays_rejected() {
    use ingest::capture::{Frame, FrameReadability};
    let mut frame = Frame::new(800, 613, vec![64; 800 * 613 * 4]).unwrap();
    frame.visibility.readability = FrameReadability::Regional;
    let (a, b, c, d) = ingest::laya::geometry::region_px("board_slot_1", 800, 613).unwrap();
    frame.visibility.occluded_regions = vec![[a, b, c, d]];
    let mut candidate = assemble(&scripts(), None).0.unwrap();
    candidate.bind_source_frame(&frame).unwrap();
    assert!(candidate.retain_source_current_fields(&frame));
    assert!(candidate.view.board_slots[0].is_none() && candidate.view.board_count.is_none());
    assert!(candidate.view.game_phase.is_none() && candidate.view.board_slots[1].is_some());
    assert_eq!(candidate.view.pot_size, Some(1050));
    let mut passes = scripts();
    passes
        .get_mut("p0_full")
        .unwrap()
        .answers
        .insert("ev_readable".into(), flag(false));
    let (candidate, _, calls) = assemble(&passes, None);
    assert!(candidate.is_none_or(|candidate| !candidate.core_accepted()));
    assert_eq!(calls, ["p0_full"]);
}

#[test]
fn board_source_region_change_clears_only_changed_slot_and_dependent_count_phase() {
    use ingest::capture::Frame;
    let zero = Frame::new(800, 613, vec![0; 800 * 613 * 4]).unwrap();
    let mut candidate = assemble(&scripts(), None).0.unwrap();
    candidate.bind_source_frame(&zero).unwrap();
    let mut latest = zero.clone();
    let (a, b, _, _) = ingest::laya::geometry::region_px("board_slot_1", 800, 613).unwrap();
    latest.rgba[(b * 800 + a) as usize * 4] = 1;
    assert!(candidate.retain_source_current_fields(&latest));
    assert!(candidate.view.board_slots[0].is_none());
    assert!(candidate.view.board_slots[1].is_some() && candidate.view.board_slots[2].is_some());
    assert!(candidate.view.board_count.is_none() && candidate.view.game_phase.is_none());
    assert_eq!(candidate.view.pot_size, Some(1050));
    assert!(candidate
        .view
        .seats
        .iter()
        .all(|s| s.displayed_stack.is_some()));
    assert!(candidate
        .evidence
        .iter()
        .any(|f| f.field == FieldName::BoardSlot
            && f.status == EvidenceStatus::Accepted
            && f.admission_status == EvidenceStatus::Rejected
            && f.admission_reason == DiagnosticReason::SourceRegionChanged));
    // A later pixel reversal cannot re-author an already withheld original field.
    assert!(candidate.retain_source_current_fields(&zero));
    assert!(candidate.view.board_count.is_none() && candidate.view.board_slots[0].is_none());
    assert!(candidate.view.board_slots[1].is_some() && candidate.view.board_slots[2].is_some());
}

#[test]
fn literal_amount_glyphs_survive_without_currency_or_decimal_normalization() {
    let mut passes = scripts();
    passes.insert("p3_pot".into(), amount("1,234.5"));
    passes.insert("p5_seat_1_stack".into(), amount("0007"));
    passes.insert("p5_seat_2_stack".into(), amount("0"));
    passes.insert("p5_seat_3_stack".into(), amount("1..2"));
    let mut candidate = assemble(&passes, None).0.unwrap();
    assert_eq!(candidate.view.pot_size, Some(123450));
    assert_eq!(candidate.view.pot_size_text.as_deref(), Some("1,234.5"));
    assert_eq!(candidate.view.seats[0].displayed_stack, Some(700));
    assert_eq!(
        candidate.view.seats[0].displayed_stack_text.as_deref(),
        Some("0007")
    );
    assert_eq!(
        candidate.view.seats[1].displayed_stack_text.as_deref(),
        Some("0")
    );
    assert!(candidate.view.seats[2].displayed_stack_text.is_none());
    let original = ingest::capture::Frame::new(800, 613, vec![0; 800 * 613 * 4]).unwrap();
    candidate.bind_source_frame(&original).unwrap();
    let mut changed = original.clone();
    let (a, b, _, _) = ingest::laya::geometry::region_px("pot", 800, 613).unwrap();
    changed.rgba[(b * 800 + a) as usize * 4] = 1;
    assert!(candidate.retain_source_current_fields(&changed));
    assert!(candidate.view.pot_size.is_none() && candidate.view.pot_size_text.is_none());
    assert_eq!(
        candidate.view.seats[0].displayed_stack_text.as_deref(),
        Some("0007")
    );
}

#[test]
fn confident_unreadable_card_is_occluded_not_an_accepted_identity_or_presence() {
    let mut passes = scripts();
    passes
        .get_mut("p2_board")
        .unwrap()
        .answers
        .insert("board_1_suit".into(), choice("unreadable", 1.0));
    let (candidate, diagnostic, _) = assemble(&passes, None);
    let view = candidate.unwrap().view;
    assert!(
        view.board_slots[0].is_none() && view.board_count.is_none() && view.game_phase.is_none()
    );
    assert!(view.board_slots[1].is_some());
    assert_eq!(view.pot_size_text.as_deref(), Some("10.5"));
    assert!(diagnostic
        .fields
        .iter()
        .any(|field| field.field == FieldName::BoardSlot
            && field.board_slot == Some(1)
            && field.status == EvidenceStatus::Rejected
            && field.reason == DiagnosticReason::Occluded));
}
