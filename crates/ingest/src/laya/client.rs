//! Loopback client for `scripts/laya-server.py` (`POST /v1/laya/predict`).
//!
//! Request: `{model, pass, note, layout, glyph_style?, images_png_b64, questions:
//! {qid: {type, instructions, criteria?}}}`. Response: `{model, pass, answers:
//! {qid: {type, choice?, probabilities?, noul?, confidence, truncated}},
//! segments?: {n, overflow}, timing_ms}`. Neither request nor response content
//! ever enters an error value.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Map, Value};

use super::questions::{Pass, QuestionType};
use crate::vlm::{
    base64_png, http_agent, read_bounded, remaining_budget, validate_endpoint, VlmConfig, VlmError,
    VlmResponseError,
};

const MAX_RESPONSE: u64 = 1_048_576;

/// One answer: the chosen label (choice questions) and its probability, or
/// `P(true)` for a noul question.
#[derive(Debug, Clone, PartialEq)]
pub struct Answer {
    pub choice: Option<String>,
    pub p: f32,
    pub truncated: bool,
}

/// Glyph segmentation reported by the server for `glyphs` passes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
pub struct Segments {
    pub n: u32,
    pub overflow: bool,
}

/// Answers of one pass, keyed by question id.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PassAnswers {
    pub answers: HashMap<String, Answer>,
    pub segments: Option<Segments>,
}

pub struct LayaClient {
    endpoint: String,
    model: String,
    agent: ureq::Agent,
    timeout: Duration,
}

#[derive(Deserialize)]
struct WireResponse {
    model: String,
    #[serde(rename = "pass")]
    pass_id: String,
    answers: HashMap<String, WireAnswer>,
    #[serde(default)]
    segments: Option<Segments>,
}

#[derive(Deserialize)]
struct WireAnswer {
    #[serde(rename = "type")]
    kind: QuestionType,
    #[serde(default)]
    choice: Option<String>,
    #[serde(default)]
    probabilities: Option<HashMap<String, f64>>,
    #[serde(default)]
    noul: Option<f64>,
    truncated: bool,
}

fn schema() -> VlmError {
    VlmError::Parse(VlmResponseError::Schema)
}

fn probability(value: f64) -> Result<f32, VlmError> {
    if value.is_finite() && (0.0..=1.0).contains(&value) {
        Ok(value as f32)
    } else {
        Err(schema())
    }
}

impl LayaClient {
    /// Validate the endpoint (loopback only) and build the agent; no network I/O.
    pub fn new(config: &VlmConfig) -> Result<Self, VlmError> {
        let endpoint = validate_endpoint(&config.endpoint)?;
        Ok(Self {
            endpoint: endpoint.into(),
            model: config.model.clone(),
            agent: http_agent(config.timeout_secs),
            timeout: Duration::from_secs(config.timeout_secs),
        })
    }

    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }

    fn request_body(&self, pass: &Pass, images: &[Vec<u8>]) -> Value {
        let mut questions = Map::new();
        for question in &pass.questions {
            let mut entry = Map::new();
            entry.insert("type".into(), json!(question.kind.as_str()));
            entry.insert("instructions".into(), json!(question.instructions));
            if let Some(criteria) = question.wire_criteria() {
                entry.insert("criteria".into(), criteria);
            }
            questions.insert(question.id.clone(), Value::Object(entry));
        }
        let mut body = Map::new();
        body.insert("model".into(), json!(self.model));
        body.insert("pass".into(), json!(pass.id));
        body.insert("note".into(), json!(pass.note));
        body.insert("layout".into(), json!(pass.layout.as_str()));
        if let Some(style) = &pass.glyph_style {
            body.insert("glyph_style".into(), json!(style));
        }
        body.insert(
            "images_png_b64".into(),
            Value::Array(images.iter().map(|png| json!(base64_png(png))).collect()),
        );
        body.insert("questions".into(), Value::Object(questions));
        Value::Object(body)
    }

    /// Ask every question of `pass` about the PNG `images` (in region order).
    pub fn predict(&self, pass: &Pass, images: Vec<Vec<u8>>) -> Result<PassAnswers, VlmError> {
        self.predict_until(pass, images, None)
    }

    pub fn predict_with_deadline(
        &self,
        pass: &Pass,
        images: Vec<Vec<u8>>,
        deadline: Instant,
    ) -> Result<PassAnswers, VlmError> {
        self.predict_until(pass, images, Some(deadline))
    }

    fn request_timeout(
        &self,
        deadline: Option<Instant>,
        now: Instant,
    ) -> Result<Duration, VlmError> {
        match deadline {
            Some(deadline) => Ok(self.timeout.min(remaining_budget(deadline, now)?)),
            None => Ok(self.timeout),
        }
    }

    fn predict_until(
        &self,
        pass: &Pass,
        images: Vec<Vec<u8>>,
        deadline: Option<Instant>,
    ) -> Result<PassAnswers, VlmError> {
        self.request_timeout(deadline, Instant::now())?;
        let body = self.request_body(pass, &images);
        drop(images);
        let timeout = self.request_timeout(deadline, Instant::now())?;
        // Servers can echo requests (including screenshots) in error bodies:
        // never retain them, and never follow redirects.
        // ureq 2.12 Request::timeout overrides the agent's overall timeout,
        // including reading the response body, not just the connection phase.
        let response = match self
            .agent
            .post(&self.endpoint)
            .timeout(timeout)
            .send_json(body)
        {
            Ok(response) => response,
            Err(ureq::Error::Status(status, _)) => {
                return Err(VlmError::Server {
                    status,
                    body: String::new(),
                })
            }
            Err(_) => {
                if let Some(deadline) = deadline {
                    remaining_budget(deadline, Instant::now())?;
                }
                return Err(VlmError::Request(
                    "connection or request timeout; check the local Laya server".into(),
                ));
            }
        };
        // With redirects disabled, ureq returns 3xx responses directly.
        let status = response.status();
        if !(200..300).contains(&status) {
            return Err(VlmError::Server {
                status,
                body: String::new(),
            });
        }
        let bytes = read_bounded(response, MAX_RESPONSE);
        if let Some(deadline) = deadline {
            remaining_budget(deadline, Instant::now())?;
        }
        let bytes = bytes?;
        let text =
            std::str::from_utf8(&bytes).map_err(|_| VlmError::Parse(VlmResponseError::Encoding))?;
        let result = self.parse_response(pass, text);
        if let Some(deadline) = deadline {
            remaining_budget(deadline, Instant::now())?;
        }
        result
    }

    fn parse_response(&self, pass: &Pass, text: &str) -> Result<PassAnswers, VlmError> {
        let wire: WireResponse = serde_json::from_str(text).map_err(|_| schema())?;
        if wire.model != self.model || wire.pass_id != pass.id {
            return Err(schema());
        }
        let mut answers = HashMap::with_capacity(wire.answers.len());
        for (id, answer) in wire.answers {
            let question = pass.question(&id).ok_or_else(schema)?;
            if question.kind != answer.kind {
                return Err(schema());
            }
            let parsed = match answer.kind {
                QuestionType::Choice => {
                    let probabilities = answer.probabilities.ok_or_else(schema)?;
                    for (label, p) in &probabilities {
                        probability(*p)?;
                        if !question.has_option(label) {
                            return Err(schema());
                        }
                    }
                    let choice = answer.choice.ok_or_else(schema)?;
                    let p = probability(*probabilities.get(&choice).ok_or_else(schema)?)?;
                    Answer {
                        choice: Some(choice),
                        p,
                        truncated: answer.truncated,
                    }
                }
                QuestionType::Noul => Answer {
                    choice: None,
                    p: probability(answer.noul.ok_or_else(schema)?)?,
                    truncated: answer.truncated,
                },
            };
            answers.insert(id, parsed);
        }
        Ok(PassAnswers {
            answers,
            segments: wire.segments,
        })
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use crate::laya::questions::pass;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::sync::mpsc::{self, Receiver};
    use std::thread;
    use std::time::{Duration, Instant};

    pub(crate) fn read_http_request(stream: &mut TcpStream) -> Vec<u8> {
        let mut buf = [0u8; 8192];
        let mut data: Vec<u8> = Vec::new();
        let header_end = loop {
            let n = stream.read(&mut buf).expect("read request");
            if n == 0 {
                return Vec::new();
            }
            data.extend_from_slice(&buf[..n]);
            if let Some(pos) = data.windows(4).position(|w| w == b"\r\n\r\n") {
                break pos + 4;
            }
        };
        let headers = String::from_utf8_lossy(&data[..header_end]);
        let content_length = headers
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(|v| v.trim().parse::<usize>().unwrap_or(0))
            })
            .unwrap_or(0);
        while data.len() < header_end + content_length {
            let n = stream.read(&mut buf).expect("read body");
            if n == 0 {
                break;
            }
            data.extend_from_slice(&buf[..n]);
        }
        data[header_end..data.len().min(header_end + content_length)].to_vec()
    }

    fn mock_server(status_line: &'static str, body: String) -> (u16, Receiver<Vec<u8>>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        let (request_tx, request_rx) = mpsc::channel();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let request_body = read_http_request(&mut stream);
            let _ = request_tx.send(request_body);
            let response = format!(
                "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(response.as_bytes());
        });
        (port, request_rx)
    }

    fn client(port: u16, timeout_secs: u64) -> LayaClient {
        LayaClient::new(&VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/laya/predict"),
            timeout_secs,
            ..VlmConfig::default()
        })
        .expect("loopback endpoint")
    }

    fn png() -> Vec<u8> {
        crate::vlm::encode_png(&image::RgbaImage::from_pixel(
            4,
            4,
            image::Rgba([9, 8, 7, 255]),
        ))
        .unwrap()
    }

    fn p0_response(model: &str, pass_id: &str) -> String {
        json!({
            "model": model, "pass": pass_id,
            "answers": {
                "screen_kind": {"type": "choice", "choice": "lobby",
                    "probabilities": {"lobby": 0.97, "poker_table": 0.01,
                        "other_coin_poker_window": 0.01, "unknown": 0.01},
                    "confidence": 0.97, "truncated": false},
                "ev_pot": {"type": "noul", "noul": 0.12, "confidence": 0.88, "truncated": false}
            },
            "timing_ms": {"decode": 1.0, "prep": 0.0, "predict": 20.0}
        })
        .to_string()
    }

    #[test]
    fn happy_path_sends_the_wire_format_and_parses_answers() {
        let (port, request_rx) =
            mock_server("200 OK", p0_response("coinpoker-laya-vision", "p0_full"));
        let p0 = pass("p0_full").unwrap();
        let answers = client(port, 5).predict(p0, vec![png()]).expect("answers");
        let screen = &answers.answers["screen_kind"];
        assert_eq!(screen.choice.as_deref(), Some("lobby"));
        assert!((screen.p - 0.97).abs() < 1e-6);
        assert!(!screen.truncated);
        let pot = &answers.answers["ev_pot"];
        assert_eq!(pot.choice, None);
        assert!((pot.p - 0.12).abs() < 1e-6);
        assert_eq!(answers.segments, None);

        let request: Value = serde_json::from_slice(&request_rx.recv().unwrap()).unwrap();
        assert_eq!(request["model"], "coinpoker-laya-vision");
        assert_eq!(request["pass"], "p0_full");
        assert_eq!(request["layout"], "full");
        assert_eq!(request["note"], p0.note.as_str());
        assert!(request.get("glyph_style").is_none());
        let images = request["images_png_b64"].as_array().unwrap();
        assert_eq!(images.len(), 1);
        let bytes = base64::Engine::decode(
            &base64::engine::general_purpose::STANDARD,
            images[0].as_str().unwrap(),
        )
        .unwrap();
        assert_eq!(bytes, png());
        let questions = request["questions"].as_object().unwrap();
        assert_eq!(questions.len(), 16);
        assert_eq!(questions["ev_pot"]["type"], "noul");
        assert!(questions["ev_pot"].get("criteria").is_none());
        assert_eq!(
            questions["screen_kind"]["criteria"],
            p0.question("screen_kind").unwrap().wire_criteria().unwrap()
        );
        assert_eq!(
            questions["screen_kind"]["criteria"][0],
            json!(["lobby", "CoinPoker lobby or game listing"])
        );
    }

    #[test]
    fn glyph_pass_sends_style_all_glyph_questions_and_reads_segments() {
        let body = json!({
            "model": "coinpoker-laya-vision", "pass": "p3_pot",
            "answers": {"g1": {"type": "choice", "choice": "7",
                "probabilities": {"7": 0.99}, "confidence": 0.99, "truncated": false}},
            "segments": {"n": 1, "overflow": false}, "timing_ms": {}
        });
        let (port, request_rx) = mock_server("200 OK", body.to_string());
        let answers = client(port, 5)
            .predict(pass("p3_pot").unwrap(), vec![png()])
            .expect("answers");
        assert_eq!(
            answers.segments,
            Some(Segments {
                n: 1,
                overflow: false
            })
        );
        let request: Value = serde_json::from_slice(&request_rx.recv().unwrap()).unwrap();
        assert_eq!(request["layout"], "glyphs");
        assert_eq!(request["glyph_style"], "white");
        let questions = request["questions"].as_object().unwrap();
        let mut ids: Vec<&String> = questions.keys().collect();
        ids.sort();
        assert_eq!(ids, ["g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]);
    }

    #[test]
    fn non_loopback_endpoints_are_rejected_without_io() {
        for endpoint in [
            "http://192.168.1.2/v1/laya/predict",
            "https://example.com/v1/laya/predict",
            "http://localhost.evil.com/",
        ] {
            assert!(matches!(
                LayaClient::new(&VlmConfig {
                    endpoint: endpoint.into(),
                    ..VlmConfig::default()
                }),
                Err(VlmError::InvalidEndpoint(_))
            ));
        }
        // Port zero is never listening; construction still does no I/O.
        assert!(LayaClient::new(&VlmConfig {
            endpoint: "http://127.0.0.1:0/v1/laya/predict".into(),
            ..VlmConfig::default()
        })
        .is_ok());
    }

    #[test]
    fn redirects_are_surfaced_instead_of_followed() {
        let target = TcpListener::bind("127.0.0.1:0").expect("bind");
        let target_port = target.local_addr().unwrap().port();
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = read_http_request(&mut stream);
            let response = format!(
                "HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{target_port}/x\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            );
            let _ = stream.write_all(response.as_bytes());
        });
        let error = client(port, 2)
            .predict(pass("p0_full").unwrap(), vec![png()])
            .expect_err("redirect must not be followed");
        assert!(
            matches!(error, VlmError::Server { status: 302, .. }),
            "{error:?}"
        );
        target.set_nonblocking(true).unwrap();
        assert!(target.accept().is_err(), "redirect target was contacted");
    }

    #[test]
    fn oversized_bodies_are_rejected() {
        let body = format!("{{\"pad\":\"{}\"}}", "x".repeat(1_100_000));
        let (port, _request) = mock_server("200 OK", body);
        let error = client(port, 5)
            .predict(pass("p0_full").unwrap(), vec![png()])
            .unwrap_err();
        assert!(
            matches!(error, VlmError::Parse(VlmResponseError::Size)),
            "{error:?}"
        );
    }

    #[test]
    fn timeout_is_bounded_without_a_sleeping_mock() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        let (release, blocked) = mpsc::sync_channel::<()>(1);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_http_request(&mut stream);
            let _ = blocked.recv_timeout(Duration::from_secs(10));
        });
        let start = Instant::now();
        let result = client(port, 1).predict(pass("p0_full").unwrap(), vec![png()]);
        assert!(matches!(result, Err(VlmError::Request(_))), "{result:?}");
        assert!(start.elapsed() < Duration::from_secs(5));
        let _ = release.send(());
        server.join().unwrap();
    }

    #[test]
    fn each_pass_receives_only_the_remaining_total_or_request_budget() {
        let client = client(0, 2);
        let start = Instant::now();
        let deadline = start + Duration::from_millis(5_000);
        assert_eq!(
            client.request_timeout(Some(deadline), start).unwrap(),
            Duration::from_secs(2)
        );
        assert_eq!(
            client
                .request_timeout(Some(deadline), start + Duration::from_millis(3_500))
                .unwrap(),
            Duration::from_millis(1_500)
        );
        assert_eq!(
            client
                .request_timeout(Some(deadline), start + Duration::from_millis(4_999))
                .unwrap(),
            Duration::from_millis(1)
        );
        assert!(matches!(
            client.request_timeout(Some(deadline), deadline),
            Err(VlmError::Deadline)
        ));
    }

    #[test]
    fn expired_budget_sends_no_http_request() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let port = listener.local_addr().unwrap().port();
        let error = client(port, 5)
            .predict_with_deadline(pass("p0_full").unwrap(), vec![png()], Instant::now())
            .unwrap_err();
        assert!(matches!(error, VlmError::Deadline));
        assert!(listener.accept().is_err());
    }

    #[test]
    fn remaining_deadline_bounds_response_body_not_only_headers() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let client = client(port, 5);
        let images = vec![png()];
        let (release, blocked) = mpsc::sync_channel::<()>(1);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_http_request(&mut stream);
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n")
                .unwrap();
            let _ = blocked.recv_timeout(Duration::from_secs(10));
        });
        let start = Instant::now();
        let result = client.predict_with_deadline(
            pass("p0_full").unwrap(),
            images,
            start + Duration::from_millis(250),
        );
        let _ = release.send(());
        server.join().unwrap();
        assert!(matches!(result, Err(VlmError::Deadline)), "{result:?}");
        assert!(start.elapsed() < Duration::from_secs(3));
    }

    #[test]
    fn errors_never_contain_request_or_response_payloads() {
        let image = png();
        let payload = base64_png(&image);
        for (status, body) in [
            ("500 Internal Server Error", payload.clone()),
            ("200 OK", format!("{{\"echo\":\"{payload}\"")),
            (
                "200 OK",
                json!({"model": payload, "pass": "p0_full", "answers": {}}).to_string(),
            ),
        ] {
            let (port, _request) = mock_server(status, body);
            let error = client(port, 5)
                .predict(pass("p0_full").unwrap(), vec![image.clone()])
                .unwrap_err();
            let text = format!("{error:?} {error}");
            assert!(!text.contains(&payload), "{text}");
            assert!(!text.contains("PNG"));
        }
    }

    #[test]
    fn not_found_maps_to_unsupported_model_api() {
        let (port, _request) = mock_server("404 Not Found", "{\"error\":\"unknown-model\"}".into());
        let error = client(port, 5)
            .predict(pass("p0_full").unwrap(), vec![png()])
            .unwrap_err();
        assert!(matches!(error, VlmError::Server { status: 404, .. }));
        assert_eq!(error.code(), "unsupported-model-api");
    }

    #[test]
    fn mismatched_or_invalid_responses_are_schema_errors() {
        let bad_probability = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "answers": {"ev_pot": {"type": "noul", "noul": 1.5, "truncated": false}}
        });
        let unknown_label = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "answers": {"screen_kind": {"type": "choice", "choice": "casino",
                "probabilities": {"casino": 0.9}, "truncated": false}}
        });
        let wrong_type = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "answers": {"screen_kind": {"type": "noul", "noul": 0.9, "truncated": false}}
        });
        let unknown_question = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "answers": {"g1": {"type": "noul", "noul": 0.9, "truncated": false}}
        });
        for body in [
            p0_response("another-model", "p0_full"),
            p0_response("coinpoker-laya-vision", "p2_board"),
            bad_probability.to_string(),
            unknown_label.to_string(),
            wrong_type.to_string(),
            unknown_question.to_string(),
            "not json".to_string(),
        ] {
            let (port, _request) = mock_server("200 OK", body);
            let error = client(port, 5)
                .predict(pass("p0_full").unwrap(), vec![png()])
                .unwrap_err();
            assert!(
                matches!(error, VlmError::Parse(VlmResponseError::Schema)),
                "{error:?}"
            );
        }
    }

    #[test]
    fn non_utf8_bodies_are_encoding_errors() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let _ = read_http_request(&mut stream);
            let mut response =
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n".to_vec();
            response.extend_from_slice(&[0xff, 0xfe]);
            let _ = stream.write_all(&response);
        });
        let error = client(port, 5)
            .predict(pass("p0_full").unwrap(), vec![png()])
            .unwrap_err();
        assert!(matches!(error, VlmError::Parse(VlmResponseError::Encoding)));
    }
}
