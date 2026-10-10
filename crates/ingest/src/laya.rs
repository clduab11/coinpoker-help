//! Laya Vision backend: closed-vocabulary questions about region crops, answered
//! by the loopback `scripts/laya-server.py`, assembled into the screen envelope.
//!
//! - `geometry`  — content rect and region boxes (identical to `scripts/laya_prep.py`)
//! - `questions` — the vendored question set (`assets/laya/question-set.json`)
//! - `client`    — the `/v1/laya/predict` wire format
//! - `assembly`  — pure, deterministic envelope assembly (rules R1-R19)
//!
//! The analysis prompt is ignored: Laya never sees free-form instructions.

pub mod assembly;
pub mod client;
pub mod geometry;
pub mod partial;
pub mod questions;
pub mod scene;
pub mod wager;

pub use assembly::assemble;
pub use client::{Answer, LayaClient, PassAnswers, Segments};
pub use questions::{question_set, Pass, QuestionSet};

use crate::capture::Frame;
use crate::vlm::{encode_png, remaining_budget, VlmBackend, VlmConfig, VlmError, VlmOutput};
use questions::Layout;
use std::time::Instant;
use wager::WagerPassRegistry;

pub struct LayaAnalysis {
    pub output: VlmOutput,
    pub partial: Option<crate::partial::PartialObservation>,
    pub diagnostics: crate::partial::PerceptionDiagnostics,
}

/// The live perception backend. Construction performs no network I/O.
pub struct LayaBackend {
    client: LayaClient,
    lobby: Option<(u32, u32)>,
    threshold: Option<f32>,
    wager_registry: Option<WagerPassRegistry>,
    scene_registry: Option<scene::ScenePassRegistry>,
}

impl LayaBackend {
    pub fn new(config: VlmConfig, lobby_size: Option<(u32, u32)>) -> Result<Self, VlmError> {
        if config
            .threshold
            .is_some_and(|t| !(t.is_finite() && (0.0..=1.0).contains(&t)))
        {
            return Err(VlmError::Unavailable(
                "Laya threshold must be within 0..=1".into(),
            ));
        }
        Ok(Self {
            client: LayaClient::new(&config)?,
            lobby: lobby_size,
            threshold: config.threshold,
            wager_registry: None,
            scene_registry: None,
        })
    }

    /// Explicit future candidate opt-in; no automatic it1, CLI or environment activation.
    pub fn with_wager_registry(mut self, registry: WagerPassRegistry) -> Result<Self, VlmError> {
        registry.validate_for_model(self.client.model())?;
        self.wager_registry = Some(registry);
        Ok(self)
    }

    /// Explicit future candidate opt-in. Construction never loads a registry or a model.
    pub fn with_scene_registry(
        mut self,
        registry: scene::ScenePassRegistry,
    ) -> Result<Self, VlmError> {
        registry.validate_for_model(self.client.model())?;
        self.scene_registry = Some(registry);
        Ok(self)
    }

    /// The validated endpoint this backend targets.
    pub fn endpoint(&self) -> &str {
        self.client.endpoint()
    }

    /// Separate observing path. Strict assembly runs against the exact same answers,
    /// without a second model request or a relaxed GameState/action gate.
    pub fn analyze_observation_with_deadline(
        &self,
        frame: &Frame,
        deadline: Instant,
    ) -> Result<LayaAnalysis, VlmError> {
        remaining_budget(deadline, Instant::now())?;
        let image = frame
            .to_rgba_image()
            .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
        let size = (image.width(), image.height());
        let mut batch_answers = std::collections::HashMap::new();
        let mut batch_attempted = false;
        let mut serial_stacks = false;
        let mut pass_times = std::collections::HashMap::new();
        let mut run = |pass: &Pass| -> Result<PassAnswers, VlmError> {
            remaining_budget(deadline, Instant::now())?;
            if pass.id.starts_with("p7_seat_") {
                let registry = self
                    .scene_registry
                    .as_ref()
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let entry = registry
                    .passes
                    .iter()
                    .find(|entry| entry.pass == pass.id)
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let [a, b, c, d] = entry
                    .crop_bounds(size.0, size.1)
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let started = Instant::now();
                let crop = image::imageops::crop_imm(&image, a, b, c - a, d - b).to_image();
                let result = self.client.predict_scene_with_deadline(
                    pass,
                    vec![encode_png(&crop)?],
                    registry,
                    entry,
                    deadline,
                );
                pass_times.insert(pass.id.clone(), started.elapsed().as_secs_f64() * 1000.0);
                return result;
            }
            if pass.id.starts_with("p6_seat_") {
                let registry = self
                    .wager_registry
                    .as_ref()
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let entry = registry
                    .passes
                    .iter()
                    .find(|entry| entry.pass == pass.id)
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let [a, b, c, d] = entry
                    .crop_bounds(size.0, size.1)
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))?;
                let started = Instant::now();
                let crop = image::imageops::crop_imm(&image, a, b, c - a, d - b).to_image();
                let result = self.client.predict_wager_with_deadline(
                    pass,
                    vec![encode_png(&crop)?],
                    registry,
                    entry,
                    deadline,
                );
                pass_times.insert(pass.id.clone(), started.elapsed().as_secs_f64() * 1000.0);
                return result;
            }
            if pass.id.starts_with("p5_seat_") && !batch_attempted {
                batch_attempted = true;
                let mut passes = Vec::new();
                for seat in 1..=6 {
                    let stack_pass = question_set()
                        .pass(&format!("p5_seat_{seat}_stack"))
                        .unwrap();
                    if let Some(images) = pass_images(&image, stack_pass)? {
                        passes.push((stack_pass, images));
                    }
                }
                if !passes.is_empty() {
                    match self.client.predict_batch_with_deadline(&passes, deadline) {
                        Ok(results) => {
                            for ((pass, _), result) in passes.into_iter().zip(results) {
                                batch_answers.insert(pass.id.clone(), result);
                            }
                        }
                        Err(VlmError::Server { status: 404, .. }) => serial_stacks = true,
                        Err(VlmError::Deadline) => return Err(VlmError::Deadline),
                        Err(_) => {
                            // Busy/failed batches are never retried through the serial endpoint.
                            for (pass, _) in passes {
                                batch_answers.insert(
                                    pass.id.clone(),
                                    Err(VlmError::Unavailable(
                                        "trained stack batch unavailable".into(),
                                    )),
                                );
                            }
                        }
                    }
                }
            }
            if pass.id.starts_with("p5_seat_") && !serial_stacks {
                return batch_answers
                    .remove(&pass.id)
                    .unwrap_or_else(|| Ok(PassAnswers::default()));
            }
            let started = Instant::now();
            let result = match pass_images(&image, pass)? {
                Some(images) => self.client.predict_with_deadline(pass, images, deadline),
                None => Ok(PassAnswers::default()),
            };
            pass_times.insert(pass.id.clone(), started.elapsed().as_secs_f64() * 1000.0);
            result
        };
        let (mut partial, mut diagnostics, cache) = match &self.wager_registry {
            Some(registry) => partial::assemble_partial_with_wagers(
                question_set(),
                size,
                self.lobby,
                self.threshold,
                registry,
                &mut run,
            )?,
            None => partial::assemble_partial(
                question_set(),
                size,
                self.lobby,
                self.threshold,
                &mut run,
            )?,
        };
        if let Some(registry) = &self.scene_registry {
            scene::extend_partial(
                &mut partial,
                &mut diagnostics,
                size,
                self.threshold,
                registry,
                &mut run,
            )?;
        }
        for pass in &mut diagnostics.passes {
            pass.total_ms = pass_times.get(&pass.pass).copied();
        }
        let assembly_started = Instant::now();
        let text = assemble(
            question_set(),
            size,
            self.lobby,
            self.threshold,
            &mut |pass| {
                cache
                    .get(&pass.id)
                    .cloned()
                    .ok_or(VlmError::Parse(crate::vlm::VlmResponseError::Schema))
            },
        )
        .unwrap_or_else(|_| {
            // A malformed individual pass does not erase independent read-only amounts.
            // The strict result remains unreadable and cannot become an actionable state.
            let kind = cache
                .get("p0_full")
                .and_then(|p| p.answers.get("screen_kind"))
                .and_then(|a| a.choice.as_deref())
                .filter(|kind| {
                    ["poker_table", "lobby", "other_coin_poker_window", "unknown"].contains(kind)
                })
                .unwrap_or("unknown");
            serde_json::json!({"screen_kind":kind,"evidence":{"table_layout":false,
                "hero_cards":false,"board_area":false,"pot":false,
                "action_controls":false,"readable":false},"state":null})
            .to_string()
        });
        diagnostics.timing.assembly_ms = Some(assembly_started.elapsed().as_secs_f64() * 1000.0);
        let mut text = if diagnostics.admission
            == crate::partial::DiagnosticAdmission::DecisionBudgetExpired
            || remaining_budget(deadline, Instant::now()).is_err()
        {
            diagnostics.set_admission(
                crate::partial::DiagnosticAdmission::DecisionBudgetExpired,
                None,
            );
            partial = None;
            serde_json::json!({"screen_kind":"unknown","evidence":{"table_layout":false,
                "hero_cards":false,"board_area":false,"pot":false,"action_controls":false,
                "readable":false},"state":null})
            .to_string()
        } else {
            text
        };
        if let Some(candidate) = &mut partial {
            candidate
                .bind_source_frame(frame)
                .map_err(|_| VlmError::Unavailable("source-witness-unavailable".into()))?;
        }
        if remaining_budget(deadline, Instant::now()).is_err() {
            diagnostics.set_admission(
                crate::partial::DiagnosticAdmission::DecisionBudgetExpired,
                None,
            );
            partial = None;
            text = serde_json::json!({"screen_kind":"unknown","evidence":{"table_layout":false,
                "hero_cards":false,"board_area":false,"pot":false,"action_controls":false,
                "readable":false},"state":null})
            .to_string();
        }
        Ok(LayaAnalysis {
            output: VlmOutput { text },
            partial,
            diagnostics,
        })
    }

    fn analyze_until(
        &self,
        frame: &Frame,
        deadline: Option<Instant>,
    ) -> Result<VlmOutput, VlmError> {
        if let Some(deadline) = deadline {
            remaining_budget(deadline, Instant::now())?;
        }
        let image = frame
            .to_rgba_image()
            .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
        let size = (image.width(), image.height());
        let mut run = |pass: &Pass| -> Result<PassAnswers, VlmError> {
            if let Some(deadline) = deadline {
                remaining_budget(deadline, Instant::now())?;
            }
            match pass_images(&image, pass)? {
                Some(images) => match deadline {
                    Some(deadline) => self.client.predict_with_deadline(pass, images, deadline),
                    None => self.client.predict(pass, images),
                },
                None => Ok(PassAnswers::default()),
            }
        };
        let text = assemble(question_set(), size, self.lobby, self.threshold, &mut run)?;
        if let Some(deadline) = deadline {
            remaining_budget(deadline, Instant::now())?;
        }
        Ok(VlmOutput { text })
    }
}

/// Version of the vendored question set.
pub fn question_set_version() -> &'static str {
    &question_set().version
}

/// Whether the vendored question set's thresholds are calibrated.
pub fn calibrated() -> bool {
    question_set().thresholds.calibrated
}

/// PNG images for a pass in region order; `None` when a crop is too small, in
/// which case the pass is not sent and trained-pass assembly fails closed.
fn pass_images(frame: &image::RgbaImage, pass: &Pass) -> Result<Option<Vec<Vec<u8>>>, VlmError> {
    if pass.layout == Layout::Full {
        return Ok(Some(vec![encode_png(frame)?]));
    }
    let mut images = Vec::with_capacity(pass.regions.len());
    for region in &pass.regions {
        let Some(crop) = geometry::crop(frame, region) else {
            return Ok(None);
        };
        images.push(encode_png(&crop)?);
    }
    Ok(Some(images))
}

impl VlmBackend for LayaBackend {
    fn analyze(&self, frame: &Frame, _prompt: &str) -> Result<VlmOutput, VlmError> {
        self.analyze_until(frame, None)
    }

    fn analyze_with_deadline(
        &self,
        frame: &Frame,
        _prompt: &str,
        deadline: Instant,
    ) -> Result<VlmOutput, VlmError> {
        self.analyze_until(frame, Some(deadline))
    }
}

#[cfg(test)]
mod tests {
    use super::client::tests::read_http_request;
    use super::*;
    use crate::screen::{parse_screen_output, ScreenKind};
    use base64::Engine;
    use serde_json::{json, Value};
    use std::io::Write;
    use std::net::TcpListener;
    use std::sync::mpsc::{self, Receiver};
    use std::thread;

    fn assert_send_static<T: Send + 'static>() {}

    #[test]
    fn backend_is_send_and_constructs_without_io() {
        assert_send_static::<LayaBackend>();
        let backend = LayaBackend::new(
            VlmConfig {
                endpoint: "http://127.0.0.1:0/v1/laya/predict".into(),
                ..VlmConfig::default()
            },
            None,
        )
        .expect("loopback endpoint");
        assert_eq!(backend.endpoint(), "http://127.0.0.1:0/v1/laya/predict");
        assert!(matches!(
            LayaBackend::new(
                VlmConfig {
                    endpoint: "https://example.com/v1/laya/predict".into(),
                    ..VlmConfig::default()
                },
                None
            ),
            Err(VlmError::InvalidEndpoint(_))
        ));
        assert!(LayaBackend::new(
            VlmConfig {
                threshold: Some(f32::NAN),
                ..VlmConfig::default()
            },
            None
        )
        .is_err());
        assert_eq!(question_set_version(), "0.4.0");
        assert!(!calibrated());
    }

    /// Answers each connection by the request's pass id; reports requests.
    fn scripted_server(
        respond: impl Fn(&Value) -> Value + Send + 'static,
    ) -> (u16, Receiver<Value>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { return };
                let request: Value =
                    serde_json::from_slice(&read_http_request(&mut stream)).unwrap_or(Value::Null);
                let body = respond(&request).to_string();
                let _ = tx.send(request);
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        (port, rx)
    }

    fn choice(label: &str) -> Value {
        json!({"type": "choice", "choice": label, "probabilities": {label: 0.97},
            "confidence": 0.97, "truncated": false})
    }

    fn noul(p: f64) -> Value {
        json!({"type": "noul", "noul": p, "confidence": 0.97, "truncated": false})
    }

    fn unseated_flop(request: &Value) -> Value {
        let pass_id = request["pass"].as_str().unwrap_or_default();
        let (answers, segments) = match pass_id {
            "p0_full" => (
                json!({
                    "screen_kind": choice("poker_table"), "ev_table_layout": noul(0.99),
                    "ev_hero_cards": noul(0.01), "ev_board_area": noul(0.99), "ev_pot": noul(0.99),
                    "ev_action_controls": noul(0.01), "ev_seat_controls": noul(0.99),
                    "ev_readable": noul(0.99), "game_phase": choice("flop"),
                    "action_on_hero": noul(0.01), "hero_seat_index": choice("not_seated")
                }),
                Value::Null,
            ),
            "p2_board" => {
                let mut answers = serde_json::Map::new();
                for (k, (rank, suit)) in [
                    ("Q", "diamonds"),
                    ("7", "clubs"),
                    ("2", "spades"),
                    ("no_card", "no_card"),
                    ("no_card", "no_card"),
                ]
                .into_iter()
                .enumerate()
                {
                    answers.insert(format!("board_{}_rank", k + 1), choice(rank));
                    answers.insert(format!("board_{}_suit", k + 1), choice(suit));
                }
                (Value::Object(answers), Value::Null)
            }
            "p3_pot" => (
                json!({"g1": choice("2"), "g2": choice("."), "g3": choice("5")}),
                json!({"n": 3, "overflow": false}),
            ),
            _ => (json!({}), Value::Null),
        };
        // Explicit synthetic floor for backend transport tests, not the fitted model floor.
        let mut response = json!({"model": "coinpoker-laya-vision", "pass": pass_id,
            "acceptance_floor": 0.8,
            "answers": answers, "timing_ms": {}});
        if !segments.is_null() {
            response["segments"] = segments;
        }
        response
    }

    fn backend(port: u16, lobby: Option<(u32, u32)>) -> LayaBackend {
        LayaBackend::new(
            VlmConfig {
                endpoint: format!("http://127.0.0.1:{port}/v1/laya/predict"),
                ..VlmConfig::default()
            },
            lobby,
        )
        .unwrap()
    }

    fn frame(width: u32, height: u32) -> Frame {
        let rgba = (0..width * height)
            .flat_map(|i| [(i % 251) as u8, 40, 90, 255])
            .collect();
        Frame::new(width, height, rgba).unwrap()
    }

    #[test]
    fn analyze_runs_crops_through_the_server_and_assembles_an_envelope() {
        let (port, requests) = scripted_server(unseated_flop);
        let output = backend(port, Some((1280, 1032)))
            .analyze(&frame(800, 613), "ignored prompt")
            .expect("analysis");
        let observation = parse_screen_output(&output).expect("valid envelope");
        assert_eq!(observation.screen_kind, ScreenKind::PokerTable);
        let state = observation.state.expect("observation-only state");
        assert_eq!(state.board.len(), 3);
        assert_eq!(state.pot_size, 250);
        assert!(!state.action_required);

        let sent: Vec<Value> = requests.try_iter().collect();
        let passes: Vec<&str> = sent.iter().map(|r| r["pass"].as_str().unwrap()).collect();
        assert_eq!(passes, ["p0_full", "p2_board", "p3_pot"]);
        let image_sizes: Vec<Vec<(u32, u32)>> = sent
            .iter()
            .map(|request| {
                request["images_png_b64"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|b64| {
                        let png = base64::Engine::decode(
                            &base64::engine::general_purpose::STANDARD,
                            b64.as_str().unwrap(),
                        )
                        .unwrap();
                        let image = image::load_from_memory(&png).unwrap();
                        (image.width(), image.height())
                    })
                    .collect()
            })
            .collect();
        assert_eq!(image_sizes[0], [(800, 613)]);
        let slot_sizes: Vec<(u32, u32)> = (1..=5)
            .map(|k| {
                let (a, b, c, d) =
                    geometry::region_px(&format!("board_slot_{k}"), 800, 613).unwrap();
                (c - a, d - b)
            })
            .collect();
        assert_eq!(image_sizes[1], slot_sizes);
        assert_eq!(image_sizes[1][0], (61, 85));
        assert_eq!(image_sizes[2], [(192, 25)]);
        assert!(sent
            .iter()
            .all(|r| !r.to_string().contains("ignored prompt")));
    }

    #[test]
    fn lobby_sized_frames_stop_after_classification() {
        let (port, requests) = scripted_server(unseated_flop);
        let output = backend(port, Some((800, 613)))
            .analyze(&frame(800, 613), "")
            .unwrap();
        let observation = parse_screen_output(&output).unwrap();
        assert!(!observation.evidence.readable && observation.state.is_none());
        assert_eq!(requests.try_iter().count(), 1);
    }

    #[test]
    fn frames_too_small_to_crop_fail_closed_without_crop_requests() {
        let (port, requests) = scripted_server(unseated_flop);
        let error = backend(port, None)
            .analyze(&frame(60, 60), "")
            .expect_err("unattempted trained pass has no acceptance floor");
        assert!(matches!(
            error,
            VlmError::Parse(crate::vlm::VlmResponseError::Schema)
        ));
        let passes: Vec<String> = requests
            .try_iter()
            .map(|r| r["pass"].as_str().unwrap().to_string())
            .collect();
        assert_eq!(passes, ["p0_full"]);
    }

    #[test]
    fn malformed_frames_are_encoding_errors() {
        let backend = backend(1, None);
        let error = backend
            .analyze(
                &Frame {
                    width: 2,
                    height: 2,
                    rgba: vec![0; 15],
                },
                "",
            )
            .unwrap_err();
        assert!(matches!(error, VlmError::ImageEncoding(_)));
    }

    #[test]
    fn exhausted_total_budget_never_encodes_or_sends_a_pass() {
        let malformed = Frame {
            width: 2,
            height: 2,
            rgba: vec![0; 15],
        };
        let error = backend(0, None)
            .analyze_with_deadline(&malformed, "", Instant::now())
            .unwrap_err();
        assert!(matches!(error, VlmError::Deadline));
    }

    #[test]
    fn combined_observing_analysis_batches_existing_stack_passes_without_relaxing_strict_state() {
        let (port, requests) = scripted_server(|request| {
            if let Some(batch) = request["batch"].as_array() {
                return json!({"model":"coinpoker-laya-vision", "results":batch.iter().map(|r|
                    json!({"model":"coinpoker-laya-vision", "pass":r["pass"],
                        "acceptance_floor":0.8,"answers":{"g1":choice("1")},
                        "segments":{"n":1,"overflow":false}})).collect::<Vec<_>>()});
            }
            let mut response = unseated_flop(request);
            if request["pass"] == "p0_full" {
                response["acceptance_floor"] = json!(0.995);
                for answer in response["answers"].as_object_mut().unwrap().values_mut() {
                    if let Some(p) = answer.get_mut("noul") {
                        *p = json!(if p.as_f64().unwrap() > 0.5 { 1.0 } else { 0.0 });
                    } else {
                        let label = answer["choice"].as_str().unwrap().to_string();
                        answer["probabilities"][label] = json!(1.0);
                    }
                }
                // Exact role blocker from Stage 1 must not stop independent crops.
                response["answers"]["hero_seat_index"]["probabilities"]["not_seated"] =
                    json!(0.9925);
            }
            response
        });
        let result = backend(port, None)
            .analyze_observation_with_deadline(
                &frame(800, 613),
                Instant::now() + std::time::Duration::from_secs(5),
            )
            .unwrap();
        assert!(parse_screen_output(&result.output).unwrap().state.is_none());
        let mut candidate = result.partial.unwrap();
        assert!(
            candidate.retain_source_current_fields(&frame(800, 613)),
            "backend must bind the original real input Frame"
        );
        let view = candidate.view;
        assert_eq!(view.role, None);
        assert_eq!(view.game_phase, None);
        assert_eq!(view.pot_size, Some(250));
        assert!(view
            .seats
            .iter()
            .all(|seat| seat.displayed_stack == Some(100)));
        let sent: Vec<Value> = requests.try_iter().collect();
        assert_eq!(
            sent.len(),
            4,
            "p0, board, pot, one compatible six-stack batch"
        );
        assert_eq!(sent[3]["batch"].as_array().unwrap().len(), 6);
        for (i, request) in sent[3]["batch"].as_array().unwrap().iter().enumerate() {
            assert_eq!(request["pass"], format!("p5_seat_{}_stack", i + 1));
            assert_eq!(
                request["note"],
                question_set()
                    .pass(&format!("p5_seat_{}_stack", i + 1))
                    .unwrap()
                    .note
            );
        }
        assert!(
            result
                .diagnostics
                .passes
                .iter()
                .filter(|p| p.pass.starts_with("p5_"))
                .all(|p| p.total_ms.is_none()),
            "batch wall time is not fabricated into independent inference timings"
        );
    }

    #[test]
    fn explicit_synthetic_registry_wires_separate_wager_crops_but_never_action_or_call_cost() {
        let registry = wager::tests::registry();
        let (port, requests) = scripted_server(|request| {
            if let Some(batch) = request["batch"].as_array() {
                return json!({"model":"coinpoker-laya-vision","results":batch.iter().map(|r|
                    json!({"model":"coinpoker-laya-vision","pass":r["pass"],"acceptance_floor":0.8,
                        "answers":{"g1":choice("1")},"segments":{"n":1,"overflow":false}})).collect::<Vec<_>>()});
            }
            if request["pass"].as_str().unwrap().starts_with("p6_") {
                return json!({"model":"coinpoker-laya-vision","pass":request["pass"],
                    "wager_capability":request["wager_capability"],"acceptance_floor":0.99,
                    "answers":{"g1":{"type":"choice","choice":"7","probabilities":{"7":1.0},"truncated":false}},
                    "segments":{"n":1,"overflow":false}});
            }
            let mut reply = unseated_flop(request);
            if request["pass"] == "p0_full" {
                reply["acceptance_floor"] = json!(0.995);
                for id in ["ev_table_layout", "ev_readable", "ev_pot"] {
                    reply["answers"][id]["noul"] = json!(1.0);
                }
                reply["answers"]["screen_kind"]["probabilities"]["poker_table"] = json!(1.0);
            }
            reply
        });
        let result = backend(port, None)
            .with_wager_registry(registry)
            .unwrap()
            .analyze_observation_with_deadline(
                &frame(800, 613),
                Instant::now() + std::time::Duration::from_secs(5),
            )
            .unwrap();
        let view = result.partial.unwrap().view;
        assert!(view.seats.iter().all(|s| s.displayed_stack == Some(100)
            && s.visible_wager == Some(700)
            && s.street_contribution.is_none()));
        assert!(!view.quality_approved);
        assert!(parse_screen_output(&result.output).unwrap().state.is_none());
        let sent: Vec<Value> = requests.try_iter().collect();
        assert_eq!(sent.len(), 10);
        for request in &sent[4..] {
            assert!(request["pass"].as_str().unwrap().starts_with("p6_"));
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(request["images_png_b64"][0].as_str().unwrap())
                .unwrap();
            let crop = image::load_from_memory(&bytes).unwrap();
            assert_eq!((crop.width(), crop.height()), (60, 30));
        }
    }
}
