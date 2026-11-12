//! Synthetic CPU fixtures only. No real captures, registries, models or quality approval.
use std::cell::RefCell;
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::rc::Rc;
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use base64::Engine;
use ingest::capture::{CaptureError, CaptureSource, Frame, WindowInfo};
use ingest::discovery::{ApplicationInfo, DiscoveryConfig, DiscoverySnapshot};
use ingest::laya::client::{Answer, LayaClient, PassAnswers, Segments};
use ingest::laya::partial::assemble_partial_with_wagers;
use ingest::laya::questions::{question_set, Layout, Pass};
use ingest::laya::scene::{extend_partial, ScenePassRegistry, SCENE_FIELDS, SCENE_QUESTIONS};
use ingest::laya::wager::WagerPassRegistry;
use ingest::laya::LayaBackend;
use ingest::partial::{
    Badge, DiagnosticReason, EvidenceStatus, FieldName, PartialObservation, PerceptionDiagnostics,
    SeatStatus, TrainingStatus,
};
use ingest::runtime::{
    Analysis, Clock, Completion, InferenceFailure, InferenceJob, InferencePort, LiveEvent,
    LiveRuntime, RuntimeConfig, Ticket,
};
use ingest::screen::parse_screen_output;
use ingest::vlm::{VlmConfig, VlmError, VlmOutput};
use serde_json::{json, Value};

fn scene_registry() -> ScenePassRegistry {
    serde_json::from_value(json!({"version":1,"model_alias":"coinpoker-laya-vision",
        "passes":(1..=6).map(|seat| json!({"seat":seat,"pass":format!("p7_seat_{seat}_scene"),
            "region":{"id":format!("seat_{seat}_scene"),"reference_dimensions":[800,613],
                "bounds":[seat*80,40,seat*80+60,80]},"fitted_floor":0.99,"trained_candidate":true,
            "candidate_sha256":"1".repeat(64),"model_sha256":"2".repeat(64),
            "capability_evidence_sha256":"3".repeat(64),"held_out_approved":true,
            "human_verified":true,"provenance":"observation-only-calibrated-pass"})).collect::<Vec<_>>()
    })).unwrap()
}
fn wager_registry() -> WagerPassRegistry {
    serde_json::from_value(json!({"version":1,"model_alias":"coinpoker-laya-vision",
        "passes":(1..=6).map(|seat| json!({"seat":seat,"pass":format!("p6_seat_{seat}_wager"),
            "region":{"id":format!("seat_{seat}_wager"),"reference_dimensions":[800,613],
                "bounds":[seat*80,100,seat*80+60,130]},"fitted_floor":0.99,"trained_candidate":true,
            "candidate_sha256":"1".repeat(64),"model_sha256":"2".repeat(64),
            "capability_evidence_sha256":"3".repeat(64),"held_out_approved":true,
            "human_verified":true,"provenance":"observation-only-calibrated-pass"})).collect::<Vec<_>>()
    })).unwrap()
}
fn choice(label: &str) -> Answer {
    Answer {
        choice: Some(label.into()),
        p: 1.0,
        truncated: false,
    }
}
fn seat_number(pass: &str) -> usize {
    pass.split('_').nth(2).unwrap().parse().unwrap()
}
fn base_answers(pass: &Pass) -> PassAnswers {
    if pass.id == "p0_full" {
        let mut answers: HashMap<String, Answer> = ["ev_table_layout", "ev_readable", "ev_pot"]
            .into_iter()
            .map(|id| {
                (
                    id.into(),
                    Answer {
                        choice: None,
                        p: 1.0,
                        truncated: false,
                    },
                )
            })
            .collect();
        answers.insert("screen_kind".into(), choice("poker_table"));
        return PassAnswers {
            answers,
            acceptance_floor: Some(0.995),
            segments: None,
        };
    }
    if pass.id == "p2_board" {
        return PassAnswers {
            acceptance_floor: Some(1.0),
            ..PassAnswers::default()
        };
    }
    let text = if pass.id == "p3_pot" {
        "10.5".into()
    } else {
        format!(
            "{}.{}",
            seat_number(&pass.id),
            if pass.id.starts_with("p6") {
                "50"
            } else {
                "25"
            }
        )
    };
    PassAnswers {
        answers: text
            .chars()
            .enumerate()
            .map(|(i, c)| (format!("g{}", i + 1), choice(&c.to_string())))
            .collect(),
        acceptance_floor: Some(if pass.id.starts_with("p6") { 0.99 } else { 0.8 }),
        segments: Some(Segments {
            n: text.len() as u32,
            overflow: false,
        }),
    }
}
fn scene_answers(seat: usize) -> PassAnswers {
    let labels = [
        "occupied",
        [
            "active",
            "folded",
            "all_in",
            "sitting_out",
            "active",
            "active",
        ][seat - 1],
        [
            "none",
            "fold",
            "all_in",
            "small_blind",
            "raise",
            "big_blind",
        ][seat - 1],
        if seat == 1 {
            "dealer_here"
        } else {
            "not_dealer"
        },
        if seat == 4 {
            "small_blind_here"
        } else {
            "not_small_blind"
        },
        if seat == 6 {
            "big_blind_here"
        } else {
            "not_big_blind"
        },
        if seat == 5 { "yes" } else { "no" },
    ];
    PassAnswers {
        answers: SCENE_QUESTIONS
            .iter()
            .zip(labels)
            .map(|((_, id, _, _), label)| ((*id).into(), choice(label)))
            .collect(),
        acceptance_floor: Some(0.99),
        segments: None,
    }
}
fn assembled(
    registry: &ScenePassRegistry,
    lobby: Option<(u32, u32)>,
    change: &mut dyn FnMut(&Pass, &mut PassAnswers),
) -> (
    Option<PartialObservation>,
    PerceptionDiagnostics,
    Vec<String>,
) {
    let mut calls = Vec::new();
    let mut run = |pass: &Pass| {
        calls.push(pass.id.clone());
        let mut answers = if pass.id.starts_with("p7_") {
            scene_answers(seat_number(&pass.id))
        } else {
            base_answers(pass)
        };
        change(pass, &mut answers);
        Ok(answers)
    };
    let (mut partial, mut diagnostics, _) = assemble_partial_with_wagers(
        question_set(),
        (800, 613),
        lobby,
        None,
        &wager_registry(),
        &mut run,
    )
    .unwrap();
    extend_partial(
        &mut partial,
        &mut diagnostics,
        (800, 613),
        None,
        registry,
        &mut run,
    )
    .unwrap();
    (partial, diagnostics, calls)
}
fn candidate(registry: &ScenePassRegistry) -> PartialObservation {
    assembled(registry, None, &mut |_, _| {}).0.unwrap()
}
fn source_frame() -> Frame {
    let mut rgba = vec![64; 800 * 613 * 4];
    rgba[0] = 255;
    Frame::new(800, 613, rgba).unwrap()
}

#[test]
fn schema_is_distinct_closed_slots_with_one_whole_seat_crop_and_explicit_unknown() {
    let registry = scene_registry();
    registry
        .validate_for_model("coinpoker-laya-vision")
        .unwrap();
    let roundtrip: ScenePassRegistry =
        serde_json::from_str(&serde_json::to_string(&registry).unwrap()).unwrap();
    assert_eq!(roundtrip, registry);
    for seat in 1..=6 {
        let entry = registry.seat(seat).unwrap();
        let pass = entry.pass_descriptor().unwrap();
        assert_eq!(pass.id, format!("p7_seat_{seat}_scene"));
        assert_eq!(pass.layout, Layout::Slots);
        assert_eq!(pass.regions, [format!("seat_{seat}_scene")]);
        assert_eq!(pass.questions.len(), 7);
        assert!(pass.glyph_style.is_none() && pass.amount.is_none());
        assert!(question_set().pass(&pass.id).is_none());
        for question in &pass.questions {
            assert!(question.has_option("unknown"));
            assert_eq!(question.image, Some(0));
        }
        let [a, b, c, d] = entry.crop_bounds(800, 613).unwrap();
        assert_eq!(
            entry.crop_bounds(1600, 1226),
            Some([a * 2, b * 2, c * 2, d * 2])
        );
        assert_eq!(entry.capabilities().len(), 7);
    }
    let mut bad = registry.clone();
    bad.version = 2;
    assert!(bad.validate_for_model("coinpoker-laya-vision").is_err());
    bad = registry.clone();
    bad.passes[1].seat = 1;
    assert!(bad.validate_for_model("coinpoker-laya-vision").is_err());
    assert!(registry.validate_for_model("wrong-model").is_err());
    for proposal in ingest::partial::proposed_seat_crops()
        .iter()
        .filter(|p| SCENE_FIELDS.contains(&p.field))
    {
        assert!(proposal.bounds.is_none() && proposal.acceptance_floor.is_none());
    }
}

#[test]
fn per_seat_server_proof_and_floor_failures_preserve_every_independent_amount_and_neighbor() {
    for code in [
        "scene-capability-identity-mismatch",
        "scene-fitted-floor-mismatch",
    ] {
        let registry = scene_registry();
        let mut partial = Some(candidate(&registry));
        let mut diagnostics = PerceptionDiagnostics::default();
        extend_partial(
            &mut partial,
            &mut diagnostics,
            (800, 613),
            None,
            &registry,
            &mut |pass| {
                if pass.id == "p7_seat_2_scene" {
                    Err(VlmError::Unavailable(code.into()))
                } else {
                    Ok(scene_answers(seat_number(&pass.id)))
                }
            },
        )
        .unwrap();
        let view = partial.unwrap().view;
        let public = serde_json::to_value(&view).unwrap();
        for (_, id, _, _) in SCENE_QUESTIONS {
            assert!(public["seats"][1][id].is_null());
            assert!(!public["seats"][0][id].is_null());
            assert!(!public["seats"][2][id].is_null());
        }
        assert!(view
            .seats
            .iter()
            .all(|s| s.displayed_stack.is_some() && s.visible_wager.is_some()));
        assert_eq!(view.pot_size, Some(1050));
        assert!(diagnostics.fields.iter().any(|f| f.seat == Some(2)
            && f.field == FieldName::Badge
            && f.reason
                == if code.ends_with("identity-mismatch") {
                    DiagnosticReason::IdentityMismatch
                } else {
                    DiagnosticReason::InvalidFloor
                }));
    }
}

#[test]
fn synthetic_qualified_all_six_stacks_wagers_and_scene_fields_stay_independent() {
    let (partial, diagnostics, calls) = assembled(&scene_registry(), None, &mut |_, _| {});
    let view = partial.unwrap().view;
    assert_eq!(calls.len(), 21);
    assert_eq!(view.pot_size, Some(1050));
    assert_eq!(
        view.seats.clone().map(|s| s.status),
        [
            Some(SeatStatus::Active),
            Some(SeatStatus::Folded),
            Some(SeatStatus::AllIn),
            Some(SeatStatus::SittingOut),
            Some(SeatStatus::Active),
            Some(SeatStatus::Active)
        ]
    );
    for (i, seat) in view.seats.iter().enumerate() {
        assert_eq!(seat.seat, i as u8 + 1);
        assert_eq!(seat.displayed_stack, Some((i as u32 + 1) * 100 + 25));
        assert_eq!(seat.visible_wager, Some((i as u32 + 1) * 100 + 50));
        assert_eq!(seat.occupied, Some(true));
        assert_eq!(seat.dealer, Some(i == 0));
        assert_eq!(seat.small_blind, Some(i == 3));
        assert_eq!(seat.big_blind, Some(i == 5));
        assert_eq!(seat.acting, Some(i == 4));
        assert!(seat.badge.is_some());
        assert!(
            seat.street_contribution.is_none()
                && seat.position.is_none()
                && seat.position_group.is_none()
                && seat.occupant_epoch.is_none()
        );
        let public = serde_json::to_value(&view).unwrap();
        for (_, id, _, _) in SCENE_QUESTIONS {
            assert!(public["verified_fields"]
                .as_array()
                .unwrap()
                .contains(&json!(format!("seats.{}.{}", i + 1, id))));
            let cap = view
                .capabilities
                .iter()
                .find(|c| {
                    c.seat == Some(i as u8 + 1) && serde_json::to_value(c.field).unwrap() == id
                })
                .unwrap();
            assert_eq!(cap.training, TrainingStatus::ReadOnlyApproved);
            assert_eq!(cap.acceptance_floor, Some(0.99));
            assert!(cap.held_out_approved && cap.human_verified);
        }
    }
    assert_eq!(view.seats[0].badge, Some(Badge::None));
    assert!(!view.quality_approved);
    assert!(diagnostics
        .passes
        .iter()
        .filter(|p| p.pass.starts_with("p7_"))
        .all(|p| p.crop_dimensions == [[60, 40]]
            && p.questions.len() == 7
            && p.segments.is_none()));
    let public = serde_json::to_string(&view).unwrap();
    for private in [
        "candidate_sha256",
        "capability_evidence_sha256",
        "crop_bounds",
        "score",
        "questions",
        "hand_id",
    ] {
        assert!(!public.contains(private));
    }
}

#[test]
fn untrained_missing_bounds_floor_proof_human_or_namespace_never_request_that_seat() {
    for cause in [
        "missing",
        "bounds",
        "floor",
        "zero-floor",
        "nan-floor",
        "untrained",
        "heldout",
        "human",
        "candidate",
        "model",
        "evidence",
        "provenance",
        "region",
        "geometry",
    ] {
        let mut registry = scene_registry();
        match cause {
            "missing" => {
                registry.passes.remove(0);
            }
            "bounds" => registry.passes[0].region.as_mut().unwrap().bounds = None,
            "floor" => registry.passes[0].fitted_floor = None,
            "zero-floor" => registry.passes[0].fitted_floor = Some(0.0),
            "nan-floor" => registry.passes[0].fitted_floor = Some(f64::NAN),
            "untrained" => registry.passes[0].trained_candidate = false,
            "heldout" => registry.passes[0].held_out_approved = false,
            "human" => registry.passes[0].human_verified = false,
            "candidate" => registry.passes[0].candidate_sha256 = Some("0".repeat(64)),
            "model" => registry.passes[0].model_sha256 = None,
            "evidence" => registry.passes[0].capability_evidence_sha256 = Some("bad".into()),
            "provenance" => registry.passes[0].provenance = "it1-existing-pass".into(),
            "region" => registry.passes[0].region.as_mut().unwrap().id = "seat_2_scene".into(),
            "geometry" => {
                registry.passes[0].region.as_mut().unwrap().bounds = Some([0, 0, 900, 700])
            }
            _ => unreachable!(),
        }
        let (partial, _, calls) = assembled(&registry, None, &mut |_, _| {});
        assert!(!calls.contains(&"p7_seat_1_scene".into()), "{cause}");
        let view = partial.unwrap().view;
        assert!(
            view.seats[0].occupied.is_none()
                && view.seats[0].dealer.is_none()
                && view.seats[0].badge.is_none()
        );
        assert_eq!(view.seats[1].occupied, Some(true));
        assert_eq!(view.seats[0].displayed_stack, Some(125));
        assert!(view
            .capabilities
            .iter()
            .filter(|c| c.seat == Some(1) && SCENE_FIELDS.contains(&c.field))
            .all(|c| c.training == TrainingStatus::Unsupported && c.acceptance_floor.is_none()));
    }
    let mut registry = scene_registry();
    for entry in &mut registry.passes {
        entry.trained_candidate = false;
        entry.region.as_mut().unwrap().bounds = None;
    }
    let (_, _, calls) = assembled(&registry, None, &mut |_, _| {});
    assert!(calls.iter().all(|id| !id.starts_with("p7_")));
}

#[test]
fn unknown_missing_invalid_low_and_truncated_reject_only_their_own_field() {
    for (field, id, _, _) in SCENE_QUESTIONS {
        for cause in ["unknown", "missing", "invalid", "low", "truncated"] {
            let (partial, diagnostics, _) =
                assembled(&scene_registry(), None, &mut |pass, answers| {
                    if pass.id != "p7_seat_5_scene" {
                        return;
                    }
                    match cause {
                        "unknown" => {
                            answers.answers.insert(id.into(), choice("unknown"));
                        }
                        "missing" => {
                            answers.answers.remove(id);
                        }
                        "invalid" => {
                            answers
                                .answers
                                .insert(id.into(), choice("PRIVATE_UNRECOGNIZED_LABEL"));
                        }
                        "low" => answers.answers.get_mut(id).unwrap().p = 0.989,
                        "truncated" => answers.answers.get_mut(id).unwrap().truncated = true,
                        _ => unreachable!(),
                    }
                });
            let value = serde_json::to_value(&partial.unwrap().view).unwrap();
            assert!(value["seats"][4][id].is_null(), "{id}/{cause}");
            for (_, other, _, _) in SCENE_QUESTIONS {
                if other != id {
                    assert!(
                        !value["seats"][4][other].is_null(),
                        "{other} erased by {id}/{cause}"
                    );
                }
            }
            assert_eq!(value["seats"][4]["displayed_stack"], 525);
            assert_eq!(value["seats"][4]["visible_wager"], 550);
            let evidence = diagnostics
                .fields
                .iter()
                .find(|f| f.field == field && f.seat == Some(5))
                .unwrap();
            assert_ne!(evidence.status, EvidenceStatus::Accepted);
            assert!(!serde_json::to_string(&diagnostics)
                .unwrap()
                .contains("PRIVATE_UNRECOGNIZED_LABEL"));
        }
    }
}

#[test]
fn open_active_multiple_markers_and_actors_reject_dependencies_not_amounts() {
    let (partial, diagnostics, _) = assembled(&scene_registry(), None, &mut |pass, answers| {
        if pass.id == "p7_seat_5_scene" {
            answers.answers.insert("occupied".into(), choice("open"));
        }
        if pass.id == "p7_seat_2_scene" {
            answers
                .answers
                .insert("dealer".into(), choice("dealer_here"));
        }
        if pass.id == "p7_seat_3_scene" {
            answers
                .answers
                .insert("small_blind".into(), choice("small_blind_here"));
        }
        if pass.id == "p7_seat_4_scene" {
            answers
                .answers
                .insert("big_blind".into(), choice("big_blind_here"));
        }
    });
    let view = partial.unwrap().view;
    assert_eq!(view.seats[4].occupied, Some(false));
    assert!(
        view.seats[4].status.is_none()
            && view.seats[4].acting.is_none()
            && view.seats[4].badge.is_none()
    );
    assert!(view.seats[0].dealer.is_none() && view.seats[1].dealer.is_none());
    assert!(view.seats[2].small_blind.is_none() && view.seats[3].small_blind.is_none());
    assert!(view.seats[3].big_blind.is_none() && view.seats[5].big_blind.is_none());
    assert!(view
        .seats
        .iter()
        .all(|s| s.displayed_stack.is_some() && s.visible_wager.is_some()));
    assert_eq!(view.pot_size, Some(1050));
    assert!(diagnostics
        .fields
        .iter()
        .any(|f| f.reason == DiagnosticReason::SceneContradiction));
    let (partial, _, _) = assembled(&scene_registry(), None, &mut |pass, answers| {
        if pass.id == "p7_seat_1_scene" {
            answers.answers.insert("acting".into(), choice("yes"));
        }
    });
    let view = partial.unwrap().view;
    assert!(view.seats[0].acting.is_none() && view.seats[4].acting.is_none());
    assert_eq!(view.seats[1].acting, Some(false));
}

#[test]
fn wrong_lobby_non_table_unreadable_layout_and_deadline_never_request_scene() {
    for cause in ["lobby", "geometry", "unknown", "layout", "readability"] {
        let (partial, _, calls) = assembled(
            &scene_registry(),
            (cause == "geometry").then_some((800, 613)),
            &mut |pass, answers| {
                if pass.id != "p0_full" {
                    return;
                }
                match cause {
                    "lobby" | "unknown" => {
                        answers.answers.insert("screen_kind".into(), choice(cause));
                    }
                    "layout" => answers.answers.get_mut("ev_table_layout").unwrap().p = 0.0,
                    "readability" => answers.answers.get_mut("ev_readable").unwrap().p = 0.0,
                    _ => {}
                }
            },
        );
        assert!(partial.is_none(), "{cause}");
        assert_eq!(calls, ["p0_full"]);
    }
    let registry = scene_registry();
    let mut partial = Some(candidate(&registry));
    let mut diagnostics = PerceptionDiagnostics::default();
    let mut calls = Vec::new();
    extend_partial(
        &mut partial,
        &mut diagnostics,
        (800, 613),
        None,
        &registry,
        &mut |pass| {
            calls.push(pass.id.clone());
            if pass.id == "p7_seat_2_scene" {
                Err(VlmError::Deadline)
            } else {
                Ok(scene_answers(seat_number(&pass.id)))
            }
        },
    )
    .unwrap();
    assert!(partial.is_none());
    assert_eq!(calls, ["p7_seat_1_scene", "p7_seat_2_scene"]);
    assert_eq!(
        diagnostics.admission,
        ingest::partial::DiagnosticAdmission::DecisionBudgetExpired
    );
    assert!(diagnostics.passes[0]
        .questions
        .iter()
        .all(|q| q.status == EvidenceStatus::Accepted));
    assert!(diagnostics
        .fields
        .iter()
        .all(|f| f.admission_status == EvidenceStatus::Rejected));
}

fn read_request(stream: &mut TcpStream) -> Value {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 4096];
    let (header, length) = loop {
        let n = stream.read(&mut buffer).unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&buffer[..n]);
        if let Some(pos) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
            let header = std::str::from_utf8(&bytes[..pos]).unwrap();
            let length = header
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap();
            break (pos + 4, length);
        }
    };
    while bytes.len() < header + length {
        let n = stream.read(&mut buffer).unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&buffer[..n]);
    }
    serde_json::from_slice(&bytes[header..header + length]).unwrap()
}
fn wire_answers(pass: &Pass, result: PassAnswers) -> Value {
    let answers = result
        .answers
        .into_iter()
        .map(|(id, answer)| {
            let value = if let Some(label) = answer.choice {
                json!({"type":"choice","choice":label,
            "probabilities":{label:answer.p},"truncated":answer.truncated})
            } else {
                json!({"type":"noul","noul":answer.p,"truncated":answer.truncated})
            };
            (id, value)
        })
        .collect::<serde_json::Map<_, _>>();
    let mut value = json!({"model":"coinpoker-laya-vision","pass":pass.id,
        "acceptance_floor":result.acceptance_floor,"answers":answers});
    if let Some(segments) = result.segments {
        value["segments"] = json!({"n":segments.n,"overflow":segments.overflow});
    }
    value
}
fn fake_server(
    count: usize,
    response: impl Fn(&Value) -> Value + Send + 'static,
) -> (u16, mpsc::Receiver<Value>, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (tx, rx) = mpsc::channel();
    let handle = thread::spawn(move || {
        for _ in 0..count {
            let (mut stream, _) = listener.accept().unwrap();
            let request = read_request(&mut stream);
            let body = response(&request).to_string();
            tx.send(request).unwrap();
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
        }
    });
    (port, rx, handle)
}
fn config(port: u16) -> VlmConfig {
    VlmConfig {
        endpoint: format!("http://127.0.0.1:{port}/v1/laya/predict"),
        ..VlmConfig::default()
    }
}

#[test]
fn transport_requires_exact_echo_proof_floor_and_rejects_bad_answers_fieldwise() {
    let registry = scene_registry();
    let entry = registry.seat(5).unwrap();
    let pass = entry.pass_descriptor().unwrap();
    for cause in [
        "qualified",
        "missing-proof",
        "wrong-seat",
        "wrong-model",
        "wrong-candidate",
        "wrong-crop",
        "wrong-floor",
        "missing-floor",
        "unknown-label",
        "wrong-type",
        "missing-answer",
    ] {
        let mut response = wire_answers(&pass, scene_answers(5));
        response["scene_capability"] = registry.wire_capability(entry);
        match cause {
            "missing-proof" => {
                response.as_object_mut().unwrap().remove("scene_capability");
            }
            "wrong-seat" => response["scene_capability"]["seat"] = json!(1),
            "wrong-model" => response["scene_capability"]["model_sha256"] = json!("4".repeat(64)),
            "wrong-candidate" => {
                response["scene_capability"]["candidate_sha256"] = json!("4".repeat(64))
            }
            "wrong-crop" => response["scene_capability"]["region"]["bounds"][0] = json!(1),
            "wrong-floor" => response["acceptance_floor"] = json!(0.8),
            "missing-floor" => {
                response.as_object_mut().unwrap().remove("acceptance_floor");
            }
            "unknown-label" => {
                response["answers"]["badge"] = json!({"type":"choice","choice":"PRIVATE_NAME","probabilities":{"PRIVATE_NAME":1.0},"truncated":false})
            }
            "wrong-type" => {
                response["answers"]["badge"] = json!({"type":"noul","noul":1.0,"truncated":false})
            }
            "missing-answer" => {
                response["answers"].as_object_mut().unwrap().remove("badge");
            }
            _ => {}
        }
        let (port, requests, handle) = fake_server(1, move |_| response.clone());
        let result = LayaClient::new(&config(port))
            .unwrap()
            .predict_scene_with_deadline(
                &pass,
                vec![vec![1, 2, 3]],
                &registry,
                entry,
                Instant::now() + Duration::from_secs(5),
            );
        let ok = ["qualified", "unknown-label", "wrong-type", "missing-answer"].contains(&cause);
        assert_eq!(result.is_ok(), ok, "{cause}");
        if ok {
            let answers = result.unwrap();
            assert_eq!(
                answers.answers["occupied"].choice.as_deref(),
                Some("occupied")
            );
            if cause == "unknown-label" || cause == "wrong-type" {
                assert!(
                    answers.answers["badge"].choice.is_none()
                        && !answers.answers["badge"].p.is_finite()
                );
            }
            if cause == "missing-answer" {
                assert!(!answers.answers.contains_key("badge"));
            }
        }
        let request = requests.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(request["scene_capability"], registry.wire_capability(entry));
        assert_eq!(request["layout"], "slots");
        assert_eq!(request["questions"].as_object().unwrap().len(), 7);
        assert!(request.get("glyph_style").is_none());
        handle.join().unwrap();
    }
    let mut wrong = registry.clone();
    wrong.model_alias = "wrong-model".into();
    assert!(LayaClient::new(&config(0))
        .unwrap()
        .predict_scene_with_deadline(
            &pass,
            vec![vec![1]],
            &wrong,
            entry,
            Instant::now() + Duration::from_secs(5)
        )
        .is_err());
    let mut wrong_prompt = pass.clone();
    wrong_prompt.questions[0].instructions = "unapproved prompt".into();
    assert!(LayaClient::new(&config(0))
        .unwrap()
        .predict_scene_with_deadline(
            &wrong_prompt,
            vec![vec![1]],
            &registry,
            entry,
            Instant::now() + Duration::from_secs(5)
        )
        .is_err());
}

fn fake_response(request: &Value) -> Value {
    if let Some(batch) = request["batch"].as_array() {
        return json!({"model":"coinpoker-laya-vision","results":batch.iter().map(fake_response).collect::<Vec<_>>()});
    }
    let id = request["pass"].as_str().unwrap();
    if id.starts_with("p7_") {
        let registry = scene_registry();
        let entry = registry.seat(seat_number(id) as u8).unwrap();
        let mut response = wire_answers(
            &entry.pass_descriptor().unwrap(),
            scene_answers(entry.seat as usize),
        );
        response["scene_capability"] = request["scene_capability"].clone();
        return response;
    }
    if id.starts_with("p6_") {
        let registry = wager_registry();
        let entry = registry.seat(seat_number(id) as u8).unwrap();
        let pass = entry.pass_descriptor(question_set()).unwrap();
        let mut response = wire_answers(&pass, base_answers(&pass));
        response["wager_capability"] = request["wager_capability"].clone();
        return response;
    }
    let pass = question_set().pass(id).unwrap();
    wire_answers(pass, base_answers(pass))
}

#[test]
fn backend_default_never_requests_scene_and_explicit_fixture_encodes_distinct_seat_rois() {
    for enabled in [false, true] {
        let (port, requests, handle) = fake_server(if enabled { 16 } else { 4 }, fake_response);
        let mut backend = LayaBackend::new(config(port), None).unwrap();
        if enabled {
            backend = backend
                .with_wager_registry(wager_registry())
                .unwrap()
                .with_scene_registry(scene_registry())
                .unwrap();
        }
        let frame = source_frame();
        let result = backend
            .analyze_observation_with_deadline(&frame, Instant::now() + Duration::from_secs(5))
            .unwrap();
        let mut partial = result.partial.unwrap();
        assert!(partial.retain_source_current_fields(&frame));
        assert!(!partial.view.quality_approved);
        assert!(parse_screen_output(&result.output).unwrap().state.is_none());
        handle.join().unwrap();
        let sent: Vec<_> = requests.try_iter().collect();
        assert_eq!(
            sent.iter()
                .filter(|r| r["pass"].as_str().is_some_and(|p| p.starts_with("p7_")))
                .count(),
            if enabled { 6 } else { 0 }
        );
        for request in sent
            .iter()
            .filter(|r| r["pass"].as_str().is_some_and(|p| p.starts_with("p7_")))
        {
            let seat = seat_number(request["pass"].as_str().unwrap());
            assert_eq!(request["scene_capability"]["seat"], seat);
            assert_eq!(
                request["scene_capability"]["region"]["bounds"][0],
                seat * 80
            );
            assert_eq!(request["images_png_b64"].as_array().unwrap().len(), 1);
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(request["images_png_b64"][0].as_str().unwrap())
                .unwrap();
            let crop = image::load_from_memory(&bytes).unwrap();
            assert_eq!((crop.width(), crop.height()), (60, 40));
            assert_eq!(
                partial.view.seats[seat - 1].displayed_stack,
                Some(seat as u32 * 100 + 25)
            );
            assert_eq!(
                partial.view.seats[seat - 1].visible_wager,
                Some(seat as u32 * 100 + 50)
            );
            assert!(partial.view.seats[seat - 1].occupied.is_some());
        }
    }
}

#[test]
fn exact_whole_scene_witness_rejects_only_changed_seat_not_pot_stacks_or_wagers() {
    for seat in 1..=6 {
        let registry = scene_registry();
        let mut partial = candidate(&registry);
        partial.bind_source_frame(&source_frame()).unwrap();
        let mut latest = source_frame();
        let [a, b, _, _] = registry.seat(seat).unwrap().crop_bounds(800, 613).unwrap();
        latest.rgba[(b as usize * 800 + a as usize) * 4] += 1;
        assert!(partial.retain_source_current_fields(&latest));
        let public = serde_json::to_value(&partial.view).unwrap();
        for (_, id, _, _) in SCENE_QUESTIONS {
            assert!(public["seats"][seat as usize - 1][id].is_null());
            assert!(partial.evidence.iter().any(|f| f.seat == Some(seat)
                && f.admission_reason == DiagnosticReason::SourceRegionChanged));
        }
        for other in 1..=6 {
            assert_eq!(
                partial.view.seats[other - 1].displayed_stack,
                Some(other as u32 * 100 + 25)
            );
            assert_eq!(
                partial.view.seats[other - 1].visible_wager,
                Some(other as u32 * 100 + 50)
            );
            if other != seat as usize {
                assert_eq!(partial.view.seats[other - 1].occupied, Some(true));
            }
        }
        assert_eq!(partial.view.pot_size, Some(1050));
        assert!(!format!("{partial:?}").contains("digest"));
    }
    let mut unbound = candidate(&scene_registry());
    assert!(!unbound.retain_source_current_fields(&source_frame()));
    assert!(unbound
        .view
        .seats
        .iter()
        .all(|s| s.occupied.is_none() && s.displayed_stack.is_none()));
}

struct Time(u64);
impl Clock for Time {
    fn now_ms(&self) -> u64 {
        self.0
    }
}
#[derive(Clone)]
struct FakeSource(Rc<RefCell<Frame>>);
impl CaptureSource for FakeSource {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        let window = WindowInfo {
            hwnd: 7,
            process_id: 42,
            exe_name: "scene.synthetic".into(),
            title: Some("Synthetic table".into()),
            on_screen: true,
            width: 800,
            height: 613,
        };
        Ok(DiscoverySnapshot {
            applications: vec![ApplicationInfo {
                exe_name: window.exe_name.clone(),
                process_id: 42,
            }],
            windows: vec![window],
        })
    }
    fn select(&mut self, _: &WindowInfo) -> Result<(), CaptureError> {
        Ok(())
    }
    fn capture(&mut self) -> Result<Frame, CaptureError> {
        Ok(self.0.borrow().clone())
    }
    fn reset(&mut self) {}
}
#[derive(Default)]
struct FakeWork {
    ticket: Option<Ticket>,
    ready: Option<Analysis<()>>,
}
#[derive(Clone, Default)]
struct FakeWorker(Rc<RefCell<FakeWork>>);
impl InferencePort<()> for FakeWorker {
    fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
        self.0.borrow_mut().ticket = Some(job.ticket);
        Ok(())
    }
    fn try_complete(&mut self) -> Result<Option<Completion<()>>, InferenceFailure> {
        let mut work = self.0.borrow_mut();
        Ok(work.ready.take().map(|result| Completion {
            ticket: work.ticket.take().unwrap(),
            result: Ok(result),
        }))
    }
}
fn finish(worker: &FakeWorker, mut partial: PartialObservation) {
    partial.bind_source_frame(&source_frame()).unwrap();
    let diagnostics = PerceptionDiagnostics {
        fields: partial.evidence.clone(),
        ..PerceptionDiagnostics::default()
    };
    let observation = parse_screen_output(&VlmOutput {text:json!({"screen_kind":"poker_table",
        "evidence":{"table_layout":true,"hero_cards":false,"board_area":false,"pot":true,"action_controls":false,"readable":false},"state":null}).to_string()}).unwrap();
    worker.0.borrow_mut().ready = Some(Analysis {
        observation,
        partial: Some(partial),
        diagnostics: Some(diagnostics),
        recommendation: None,
    });
}

#[test]
fn mock_consensus_requires_same_calibration_and_current_pixels_without_action_or_lease_renewal() {
    for cause in [
        "unchanged",
        "candidate",
        "floor",
        "value",
        "pixels",
        "stale-ticket",
    ] {
        let source = FakeSource(Rc::new(RefCell::new(source_frame())));
        let worker = FakeWorker::default();
        let mut runtime = LiveRuntime::new(
            source.clone(),
            worker.clone(),
            DiscoveryConfig {
                exe_name: Some("scene.synthetic".into()),
                table_title: Some("table".into()),
                ..DiscoveryConfig::default()
            },
            RuntimeConfig::default(),
        )
        .unwrap();
        for now in [0, 100, 200, 300] {
            runtime.tick(&Time(now));
        }
        assert_eq!(runtime.active_count(), 1);
        finish(&worker, candidate(&scene_registry()));
        assert!(!runtime
            .tick(&Time(400))
            .iter()
            .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
        runtime.tick(&Time(500));
        let mut registry = scene_registry();
        if cause == "candidate" {
            registry.passes[0].candidate_sha256 = Some("4".repeat(64));
        }
        if cause == "floor" {
            registry.passes[0].fitted_floor = Some(0.999);
        }
        let second = assembled(&registry, None, &mut |pass, answers| {
            if cause == "floor" && pass.id == "p7_seat_1_scene" {
                answers.acceptance_floor = Some(0.999);
            }
            if cause == "value" && pass.id == "p7_seat_1_scene" {
                answers.answers.insert("badge".into(), choice("check"));
            }
        })
        .0
        .unwrap();
        if cause == "pixels" {
            source.0.borrow_mut().rgba[(40 * 800 + 80) * 4] += 1;
        }
        finish(&worker, second);
        if cause == "stale-ticket" {
            worker.0.borrow_mut().ticket.as_mut().unwrap().epoch += 1;
        }
        let events = runtime.tick(&Time(600));
        assert!(!events.iter().any(|e| matches!(
            e,
            LiveEvent::Recommendation { .. } | LiveEvent::Observation { .. }
        )));
        let emitted = events.iter().find_map(|e| {
            if let LiveEvent::PartialObservation {
                value,
                valid_for_ms,
                ..
            } = e
            {
                Some((value, *valid_for_ms))
            } else {
                None
            }
        });
        if cause == "stale-ticket" {
            assert!(emitted.is_none());
            continue;
        }
        let (view, lease) = emitted.unwrap();
        assert_eq!(lease, 4900);
        assert_eq!(view.seats[0].displayed_stack, Some(125));
        assert_eq!(view.seats[0].visible_wager, Some(150));
        assert_eq!(view.seats[1].occupied, Some(true));
        assert_eq!(
            view.seats[0].occupied,
            if ["candidate", "floor", "pixels"].contains(&cause) {
                None
            } else {
                Some(true)
            }
        );
        assert_eq!(
            view.seats[0].badge,
            if cause == "unchanged" {
                Some(Badge::None)
            } else {
                None
            }
        );
        for now in [700, 800, 900] {
            assert!(!runtime
                .tick(&Time(now))
                .iter()
                .any(|e| matches!(e, LiveEvent::PartialObservation { .. })));
        }
        let at_expiry = runtime.tick(&Time(5500));
        assert!(at_expiry.iter().any(|e| matches!(
            e,
            LiveEvent::ObservationInvalidated {
                reason: "observation-expired",
                ..
            }
        )));
    }
}
