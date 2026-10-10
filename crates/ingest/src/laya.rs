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
pub mod questions;

pub use assembly::assemble;
pub use client::{Answer, LayaClient, PassAnswers, Segments};
pub use questions::{question_set, Pass, QuestionSet};

use crate::capture::Frame;
use crate::vlm::{encode_png, remaining_budget, VlmBackend, VlmConfig, VlmError, VlmOutput};
use questions::Layout;
use std::time::Instant;

/// The live perception backend. Construction performs no network I/O.
pub struct LayaBackend {
    client: LayaClient,
    lobby: Option<(u32, u32)>,
    threshold: Option<f32>,
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
        })
    }

    /// The validated endpoint this backend targets.
    pub fn endpoint(&self) -> &str {
        self.client.endpoint()
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
/// which case the pass is not sent and all its answers are low confidence.
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
        let mut response = json!({"model": "coinpoker-laya-vision", "pass": pass_id,
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
    fn frames_too_small_to_crop_degrade_without_crop_requests() {
        let (port, requests) = scripted_server(unseated_flop);
        let output = backend(port, None).analyze(&frame(60, 60), "").unwrap();
        let observation = parse_screen_output(&output).unwrap();
        assert_eq!(observation.screen_kind, ScreenKind::PokerTable);
        assert!(!observation.evidence.readable && observation.state.is_none());
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
}
