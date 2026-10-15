//! Loopback client for `scripts/laya-server.py` (`POST /v1/laya/predict`).
//!
//! Request: `{model, pass, note, layout, glyph_style?, images_png_b64, questions:
//! {qid: {type, instructions, criteria?}}}`. Response: `{model, pass, answers:
//! {qid: {type, choice?, probabilities?, noul?, confidence, truncated}}, acceptance_floor,
//! segments?: {n, overflow}, timing_ms}`. Neither request nor response content
//! ever enters an error value.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use serde::Deserialize;
use serde_json::{json, Map, Value};

use super::questions::{Calibration, Layout, Pass, QuestionType};
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
    pub p: f64,
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
    /// Required on server responses; absent only for an unattempted pass.
    pub acceptance_floor: Option<f64>,
}

pub struct LayaClient {
    endpoint: String,
    model: String,
    agent: ureq::Agent,
    timeout: Duration,
    manual_session: Option<(String, String)>,
    experimental_session: Option<(String, String)>,
}

#[derive(Deserialize)]
struct WireResponse {
    model: String,
    #[serde(rename = "pass")]
    pass_id: String,
    acceptance_floor: f64,
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

fn probability(value: f64) -> Result<f64, VlmError> {
    if value.is_finite() && (0.0..=1.0).contains(&value) {
        Ok(value)
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
            manual_session: None,
            experimental_session: None,
        })
    }

    pub fn endpoint(&self) -> &str {
        &self.endpoint
    }
    pub fn model(&self) -> &str {
        &self.model
    }

    /// Optional manual-owner binding. Old diagnostic callers remain unbound.
    pub fn with_manual_session(mut self, session: &str, service: &str) -> Result<Self, VlmError> {
        if [session, service].iter().any(|id| {
            id.len() != 32
                || !id
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        }) {
            return Err(VlmError::Unavailable(
                "invalid-manual-session-binding".into(),
            ));
        }
        self.manual_session = Some((session.into(), service.into()));
        self.experimental_session = None;
        Ok(self)
    }

    /// Explicit opt-in belongs to this exact manual-owner binding, never an environment value.
    pub(super) fn with_experimental_bet_action(mut self, enabled: bool) -> Result<Self, VlmError> {
        self.experimental_session = if enabled {
            if self.model != VlmConfig::default().model {
                return Err(VlmError::Unavailable(
                    "experimental-model-not-installed-it1".into(),
                ));
            }
            Some(self.manual_session.clone().ok_or_else(|| {
                VlmError::Unavailable("experimental-session-binding-required".into())
            })?)
        } else {
            None
        };
        Ok(self)
    }

    pub(super) fn experimental_enabled(&self) -> bool {
        self.experimental_session.is_some() && self.experimental_session == self.manual_session
    }

    fn request(&self, endpoint: &str, timeout: Duration) -> ureq::Request {
        let mut request = self.agent.post(endpoint).timeout(timeout);
        if let Some((session, service)) = &self.manual_session {
            request = request
                .set("X-Coinpoker-Session", session)
                .set("X-Coinpoker-Service", service);
        }
        request
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
        self.predict_until(pass, images, None, None)
    }

    pub fn predict_with_deadline(
        &self,
        pass: &Pass,
        images: Vec<Vec<u8>>,
        deadline: Instant,
    ) -> Result<PassAnswers, VlmError> {
        self.predict_until(pass, images, Some(deadline), None)
    }

    pub fn predict_wager_with_deadline(
        &self,
        pass: &Pass,
        images: Vec<Vec<u8>>,
        registry: &super::wager::WagerPassRegistry,
        entry: &super::wager::WagerPassConfig,
        deadline: Instant,
    ) -> Result<PassAnswers, VlmError> {
        registry.validate_for_model(&self.model)?;
        if entry.qualification().is_err()
            || pass.id != entry.pass
            || registry.seat(entry.seat) != Some(entry)
        {
            return Err(schema());
        }
        self.predict_until(
            pass,
            images,
            Some(deadline),
            Some(("wager_capability", registry.wire_capability(entry))),
        )
    }

    pub fn predict_scene_with_deadline(
        &self,
        pass: &Pass,
        images: Vec<Vec<u8>>,
        registry: &super::scene::ScenePassRegistry,
        entry: &super::scene::ScenePassConfig,
        deadline: Instant,
    ) -> Result<PassAnswers, VlmError> {
        registry.validate_for_model(&self.model)?;
        if entry.qualification().is_err()
            || pass.id != entry.pass
            || registry.seat(entry.seat) != Some(entry)
            || images.len() != 1
        {
            return Err(schema());
        }
        let descriptor = entry.pass_descriptor().ok_or_else(schema)?;
        if pass.layout != descriptor.layout
            || pass.regions != descriptor.regions
            || pass.note != descriptor.note
            || pass.calibration != descriptor.calibration
            || pass.threshold != descriptor.threshold
            || pass.glyph_style.is_some()
            || pass.amount.is_some()
            || pass.questions.len() != descriptor.questions.len()
            || pass
                .questions
                .iter()
                .zip(&descriptor.questions)
                .any(|(a, b)| {
                    a.id != b.id
                        || a.kind != b.kind
                        || a.instructions != b.instructions
                        || a.wire_criteria() != b.wire_criteria()
                        || a.image != b.image
                })
        {
            return Err(schema());
        }
        self.predict_until(
            pass,
            images,
            Some(deadline),
            Some(("scene_capability", registry.wire_capability(entry))),
        )
    }

    pub(super) fn predict_experimental_with_deadline(
        &self,
        descriptor: &super::experimental::ExperimentalDescriptor,
        images: Vec<Vec<u8>>,
        deadline: Instant,
    ) -> Result<(PassAnswers, super::experimental::ExperimentalProvenance), VlmError> {
        if !self.experimental_enabled() {
            return Err(VlmError::Unavailable(
                "experimental-session-opt-in-required".into(),
            ));
        }
        let pass = descriptor.pass_descriptor()?;
        if images.len() != 1 {
            return Err(schema());
        }
        self.request_timeout(Some(deadline), Instant::now())?;
        let mut body = self.request_body(&pass, &images);
        let expected = serde_json::to_value(descriptor).map_err(|_| schema())?;
        body["experimental_descriptor"] = expected.clone();
        drop(images);
        let text = self.send_body(body, Some(deadline))?;
        let wire: Value = serde_json::from_str(&text).map_err(|_| schema())?;
        if wire["model"].as_str() != Some(&self.model)
            || wire["pass"].as_str() != Some(&pass.id)
            || wire.get("experimental_descriptor") != Some(&expected)
            || wire.get("acceptance_floor") != Some(&Value::Null)
            || wire.get("wager_capability").is_some()
            || wire.get("scene_capability").is_some()
        {
            return Err(schema());
        }
        let provenance_keys = [
            "diagnostic_only",
            "training",
            "geometry_status",
            "human_review",
            "donor_pass",
            "inherited_cutoff",
        ];
        let raw_provenance = wire["experimental_diagnostics"]
            .as_object()
            .ok_or_else(schema)?;
        if raw_provenance.len() != provenance_keys.len()
            || provenance_keys
                .iter()
                .any(|key| !raw_provenance.contains_key(*key))
        {
            return Err(schema());
        }
        let provenance: super::experimental::ExperimentalProvenance =
            serde_json::from_value(wire["experimental_diagnostics"].clone())
                .map_err(|_| schema())?;
        provenance.validate(descriptor)?;
        let raw = wire["answers"].as_object().ok_or_else(schema)?;
        if raw.keys().any(|id| pass.question(id).is_none()) {
            return Err(schema());
        }
        let segments = if descriptor.is_wager() {
            wire.get("segments")
                .map(|s| serde_json::from_value::<Segments>(s.clone()).map_err(|_| schema()))
                .transpose()?
        } else {
            if wire.get("segments").is_some_and(|s| !s.is_null()) {
                return Err(schema());
            }
            None
        };
        let answers = PassAnswers {
            answers: self.parse_choice_answers(&pass, raw),
            segments,
            acceptance_floor: None,
        };
        remaining_budget(deadline, Instant::now())?;
        Ok((answers, provenance))
    }

    /// Each trained stack pass retains its own prompts, images, segmentation and floor.
    /// Unsupported old helpers return 404; the caller alone may choose serial fallback.
    pub fn predict_batch_with_deadline(
        &self,
        passes: &[(&Pass, Vec<Vec<u8>>)],
        deadline: Instant,
    ) -> Result<Vec<Result<PassAnswers, VlmError>>, VlmError> {
        self.request_timeout(Some(deadline), Instant::now())?;
        if passes.is_empty() || passes.len() > 6 {
            return Err(schema());
        }
        for (i, (pass, images)) in passes.iter().enumerate() {
            if pass.layout != Layout::Glyphs
                || !matches!(
                    pass.calibration,
                    Calibration::Trained | Calibration::Calibrated
                )
                || !(1..=6).any(|seat| pass.id == format!("p5_seat_{seat}_stack"))
                || pass.glyph_style != passes[0].0.glyph_style
                || images.len() != pass.regions.len()
                || passes[..i].iter().any(|(other, _)| other.id == pass.id)
            {
                return Err(schema());
            }
        }
        self.send_batch(passes, deadline, None)
    }

    /// Mixed readouts keep their own questions, images and fitted floors in one admission.
    pub(super) fn predict_readout_batch_with_deadline(
        &self,
        passes: &[(&Pass, Vec<Vec<u8>>)],
        deadline: Instant,
    ) -> Result<Vec<Result<PassAnswers, VlmError>>, VlmError> {
        self.request_timeout(Some(deadline), Instant::now())?;
        let ids: Vec<_> = passes.iter().map(|(pass, _)| pass.id.as_str()).collect();
        if !matches!(
            ids.as_slice(),
            ["p0_full", "p2_board"]
                | ["p0_full", "p3_pot", "p5_seat_1_stack", "p5_seat_2_stack"]
                | ["p0_full", "p3_pot", "p5_seat_3_stack", "p5_seat_4_stack"]
                | ["p0_full", "p3_pot", "p5_seat_5_stack", "p5_seat_6_stack"]
        ) || passes.iter().any(|(pass, images)| {
            !matches!(
                pass.calibration,
                Calibration::Trained | Calibration::Calibrated
            ) || images.len()
                != if pass.layout == Layout::Full {
                    1
                } else {
                    pass.regions.len()
                }
        }) {
            return Err(schema());
        }
        self.send_batch(passes, deadline, Some("readout"))
    }

    fn send_batch(
        &self,
        passes: &[(&Pass, Vec<Vec<u8>>)],
        deadline: Instant,
        kind: Option<&str>,
    ) -> Result<Vec<Result<PassAnswers, VlmError>>, VlmError> {
        let endpoint = self.endpoint.strip_suffix("/predict").ok_or_else(schema)?;
        let mut requests: Vec<_> = passes
            .iter()
            .map(|(pass, images)| self.request_body(pass, images))
            .collect();
        if kind == Some("readout") {
            // Only ask the unchanged core questions required by this field group.
            // Missing role/control answers remain unknown, never inferred defaults.
            let core: &[&str] = if passes[1].0.id == "p2_board" {
                &[
                    "screen_kind",
                    "ev_table_layout",
                    "ev_readable",
                    "ev_board_area",
                    "game_phase",
                ]
            } else {
                &["screen_kind", "ev_table_layout", "ev_readable", "ev_pot"]
            };
            requests[0]["questions"]
                .as_object_mut()
                .ok_or_else(schema)?
                .retain(|id, _| core.contains(&id.as_str()));
        }
        let allowed_answers: Vec<Vec<String>> = requests
            .iter()
            .map(|request| {
                request["questions"]
                    .as_object()
                    .unwrap()
                    .keys()
                    .cloned()
                    .collect()
            })
            .collect();
        let mut body = json!({"model": self.model, "batch": requests});
        if let Some(kind) = kind {
            body["batch_kind"] = json!(kind);
        }
        let timeout = self.request_timeout(Some(deadline), Instant::now())?;
        let response = match self
            .request(&format!("{endpoint}/predict-batch"), timeout)
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
                remaining_budget(deadline, Instant::now())?;
                return Err(VlmError::Request("local Laya batch unavailable".into()));
            }
        };
        if !(200..300).contains(&response.status()) {
            return Err(VlmError::Server {
                status: response.status(),
                body: String::new(),
            });
        }
        let bytes = read_bounded(response, MAX_RESPONSE);
        remaining_budget(deadline, Instant::now())?;
        let wire: Value = serde_json::from_slice(&bytes?).map_err(|_| schema())?;
        if wire.get("model").and_then(Value::as_str) != Some(&self.model) {
            return Err(schema());
        }
        let results = wire
            .get("results")
            .and_then(Value::as_array)
            .ok_or_else(schema)?;
        if results.len() != passes.len() {
            return Err(schema());
        }
        let parsed = passes
            .iter()
            .zip(results)
            .zip(allowed_answers)
            .map(|(((pass, _), result), allowed)| {
                let answers = result
                    .get("answers")
                    .and_then(Value::as_object)
                    .ok_or_else(schema)?;
                if answers.keys().any(|id| !allowed.contains(id)) {
                    return Err(schema());
                }
                self.parse_response(pass, &result.to_string())
            })
            .collect();
        remaining_budget(deadline, Instant::now())?;
        Ok(parsed)
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
        capability: Option<(&str, Value)>,
    ) -> Result<PassAnswers, VlmError> {
        if pass.calibration == Calibration::Uncalibrated {
            return Err(VlmError::Unavailable(
                "experimental-session-opt-in-required".into(),
            ));
        }
        self.request_timeout(deadline, Instant::now())?;
        let mut body = self.request_body(pass, &images);
        if let Some((key, expected)) = &capability {
            body[*key] = expected.clone();
        }
        drop(images);
        let text = self.send_body(body, deadline)?;
        if let Some((key, expected)) = &capability {
            let wire: Value = serde_json::from_str(&text).map_err(|_| schema())?;
            let family = if *key == "scene_capability" {
                "scene"
            } else {
                "wager"
            };
            if wire.get(*key) != Some(expected) {
                return Err(VlmError::Unavailable(format!(
                    "{family}-capability-identity-mismatch"
                )));
            }
            if !wire
                .get("acceptance_floor")
                .and_then(Value::as_f64)
                .is_some_and(|f| {
                    f.is_finite() && f <= 1.0 && f >= expected["fitted_floor"].as_f64().unwrap()
                })
            {
                return Err(VlmError::Unavailable(format!(
                    "{family}-fitted-floor-mismatch"
                )));
            }
        }
        let result = if capability
            .as_ref()
            .is_some_and(|(key, _)| *key == "scene_capability")
        {
            self.parse_scene_response(pass, &text)
        } else {
            self.parse_response(pass, &text)
        };
        if let Some(deadline) = deadline {
            remaining_budget(deadline, Instant::now())?;
        }
        result
    }

    fn send_body(&self, body: Value, deadline: Option<Instant>) -> Result<String, VlmError> {
        let timeout = self.request_timeout(deadline, Instant::now())?;
        // Servers can echo requests (including screenshots) in error bodies:
        // never retain them, and never follow redirects.
        // ureq 2.12 Request::timeout overrides the agent's overall timeout,
        // including reading the response body, not just the connection phase.
        let response = match self.request(&self.endpoint, timeout).send_json(body) {
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
        String::from_utf8(bytes).map_err(|_| VlmError::Parse(VlmResponseError::Encoding))
    }

    // A malformed scene answer rejects that question only, never adjacent seat evidence.
    fn parse_scene_response(&self, pass: &Pass, text: &str) -> Result<PassAnswers, VlmError> {
        let wire: Value = serde_json::from_str(text).map_err(|_| schema())?;
        if wire["model"].as_str() != Some(&self.model) || wire["pass"].as_str() != Some(&pass.id) {
            return Err(schema());
        }
        let floor = probability(wire["acceptance_floor"].as_f64().ok_or_else(schema)?)?;
        let raw = wire["answers"].as_object().ok_or_else(schema)?;
        Ok(PassAnswers {
            answers: self.parse_choice_answers(pass, raw),
            segments: None,
            acceptance_floor: Some(floor),
        })
    }

    fn parse_choice_answers(
        &self,
        pass: &Pass,
        raw: &Map<String, Value>,
    ) -> HashMap<String, Answer> {
        let mut answers = HashMap::new();
        for question in &pass.questions {
            let Some(value) = raw.get(&question.id) else {
                continue;
            };
            let parsed = (|| {
                let answer: WireAnswer =
                    serde_json::from_value(value.clone()).map_err(|_| schema())?;
                if answer.kind != QuestionType::Choice || answer.noul.is_some() {
                    return Err(schema());
                }
                let probabilities = answer.probabilities.ok_or_else(schema)?;
                for (label, p) in &probabilities {
                    probability(*p)?;
                    if !question.has_option(label) {
                        return Err(schema());
                    }
                }
                let choice = answer.choice.ok_or_else(schema)?;
                if !question.has_option(&choice) {
                    return Err(schema());
                }
                let p = probability(*probabilities.get(&choice).ok_or_else(schema)?)?;
                Ok(Answer {
                    choice: Some(choice),
                    p,
                    truncated: answer.truncated,
                })
            })();
            answers.insert(
                question.id.clone(),
                parsed.unwrap_or(Answer {
                    choice: None,
                    p: f64::NAN,
                    truncated: value["truncated"].as_bool().unwrap_or(false),
                }),
            );
        }
        answers
    }

    fn parse_response(&self, pass: &Pass, text: &str) -> Result<PassAnswers, VlmError> {
        let wire: WireResponse = serde_json::from_str(text).map_err(|_| schema())?;
        if wire.model != self.model || wire.pass_id != pass.id {
            return Err(schema());
        }
        let acceptance_floor = probability(wire.acceptance_floor)?;
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
            acceptance_floor: Some(acceptance_floor),
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

    fn stack_batch() -> Vec<(&'static Pass, Vec<Vec<u8>>)> {
        (1..=6)
            .map(|seat| {
                (
                    pass(&format!("p5_seat_{seat}_stack")).unwrap(),
                    vec![vec![1, 2, 3]],
                )
            })
            .collect()
    }

    #[test]
    fn experimental_transport_is_explicit_session_bound_and_has_no_unbounded_shortcut() {
        let descriptor = crate::laya::experimental::ExperimentalDescriptor::wager(1).unwrap();
        let session = "a1".repeat(16);
        let service = "b2".repeat(16);
        assert!(client(0, 5).with_experimental_bet_action(true).is_err());
        let bound = client(0, 5)
            .with_manual_session(&session, &service)
            .unwrap();
        assert!(bound
            .predict_experimental_with_deadline(
                &descriptor,
                vec![png()],
                Instant::now() + Duration::from_secs(5)
            )
            .is_err());
        let disabled = client(0, 5)
            .with_manual_session(&session, &service)
            .unwrap()
            .with_experimental_bet_action(false)
            .unwrap();
        assert!(!disabled.experimental_enabled());
        let enabled = client(0, 5)
            .with_manual_session(&session, &service)
            .unwrap()
            .with_experimental_bet_action(true)
            .unwrap();
        assert!(enabled.experimental_enabled());
        let pass = descriptor.pass_descriptor().unwrap();
        assert!(enabled.predict(&pass, vec![png()]).is_err());
        assert!(enabled
            .predict_with_deadline(&pass, vec![png()], Instant::now() + Duration::from_secs(5))
            .is_err());
        assert!(matches!(
            enabled.predict_experimental_with_deadline(&descriptor, vec![png()], Instant::now()),
            Err(VlmError::Deadline)
        ));
        let rebound = enabled.with_manual_session(&session, &service).unwrap();
        assert!(
            !rebound.experimental_enabled(),
            "rebinding must require fresh explicit opt-in"
        );
        let wrong_model = VlmConfig {
            model: "other-candidate".into(),
            ..VlmConfig::default()
        };
        assert!(LayaClient::new(&wrong_model)
            .unwrap()
            .with_manual_session(&session, &service)
            .unwrap()
            .with_experimental_bet_action(true)
            .is_err());
    }

    #[test]
    fn experimental_reply_requires_exact_draft_echo_null_floor_and_honest_donor_provenance() {
        use crate::laya::experimental::{tests::provenance, ExperimentalDescriptor};
        for wager in [true, false] {
            let descriptor = if wager {
                ExperimentalDescriptor::wager(3)
            } else {
                ExperimentalDescriptor::scene(3)
            }
            .unwrap();
            let pass = descriptor.pass_descriptor().unwrap();
            for cause in [
                "valid",
                "wrong-model",
                "wrong-pass",
                "wrong-crop",
                "missing-echo",
                "floor",
                "missing-floor",
                "trained",
                "proof",
                "donor",
                "cutoff",
                "capability",
                "extra-question",
                "missing-provenance-key",
            ] {
                let mut response = json!({"model":"coinpoker-laya-vision", "pass":pass.id,
                    "experimental_descriptor":descriptor, "acceptance_floor":null,
                    "experimental_diagnostics":provenance(wager),
                    "answers":if wager { json!({"g1":{"type":"choice","choice":"7","probabilities":{"7":0.91},"truncated":false}}) }
                        else { json!({"badge":{"type":"choice","choice":"call","probabilities":{"call":0.91},"truncated":false}}) }});
                if wager {
                    response["segments"] = json!({"n":1,"overflow":false});
                }
                match cause {
                    "wrong-model" => response["model"] = json!("other-candidate"),
                    "wrong-pass" => response["pass"] = json!("p3_pot"),
                    "wrong-crop" => {
                        response["experimental_descriptor"]["region"]["bounds"][0] = json!(1)
                    }
                    "missing-echo" => {
                        response
                            .as_object_mut()
                            .unwrap()
                            .remove("experimental_descriptor");
                    }
                    "floor" => response["acceptance_floor"] = json!(0.8),
                    "missing-floor" => {
                        response.as_object_mut().unwrap().remove("acceptance_floor");
                    }
                    "trained" => {
                        response["experimental_diagnostics"]["training"] = json!("trained")
                    }
                    "proof" => {
                        response["experimental_diagnostics"]["held_out_approved"] = json!(true)
                    }
                    "donor" => response["experimental_diagnostics"]["donor_pass"] = json!("p3_pot"),
                    "cutoff" => {
                        response["experimental_diagnostics"]["inherited_cutoff"] = json!(0.79999)
                    }
                    "capability" => response["wager_capability"] = json!({}),
                    "extra-question" => response["answers"]["PRIVATE-NAME"] = json!({}),
                    "missing-provenance-key" => {
                        response["experimental_diagnostics"]
                            .as_object_mut()
                            .unwrap()
                            .remove("donor_pass");
                    }
                    _ => {}
                }
                let (port, sent) = mock_server("200 OK", response.to_string());
                let result = client(port, 5)
                    .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
                    .unwrap()
                    .with_experimental_bet_action(true)
                    .unwrap()
                    .predict_experimental_with_deadline(
                        &descriptor,
                        vec![png()],
                        Instant::now() + Duration::from_secs(5),
                    );
                assert_eq!(result.is_ok(), cause == "valid", "wager={wager}/{cause}");
                if let Ok((answers, returned)) = result {
                    assert!(answers.acceptance_floor.is_none());
                    assert_eq!(returned, provenance(wager));
                }
                let request: Value =
                    serde_json::from_slice(&sent.recv_timeout(Duration::from_secs(5)).unwrap())
                        .unwrap();
                assert_eq!(
                    request["experimental_descriptor"],
                    serde_json::to_value(&descriptor).unwrap()
                );
                assert_eq!(request["note"], pass.note);
                assert_eq!(
                    request["questions"].as_object().unwrap().len(),
                    pass.questions.len()
                );
                assert!(
                    request.get("wager_capability").is_none()
                        && request.get("scene_capability").is_none()
                );
                for question in &pass.questions {
                    assert_eq!(
                        request["questions"][&question.id]["criteria"],
                        question.wire_criteria().unwrap()
                    );
                }
            }
        }
    }

    #[test]
    fn wager_transport_requires_exact_registered_identity_and_own_response_floor() {
        let registry = crate::laya::wager::tests::registry();
        let entry = &registry.passes[0];
        let pass = entry.pass_descriptor(crate::laya::question_set()).unwrap();
        for cause in [
            "qualified",
            "missing-identity",
            "wrong-identity",
            "floor",
            "missing-floor",
        ] {
            let mut response = json!({"model":"coinpoker-laya-vision","pass":pass.id,
                "acceptance_floor":0.99,"wager_capability":registry.wire_capability(entry),
                "answers":{"g1":{"type":"choice","choice":"7","probabilities":{"7":1.0},"truncated":false}},
                "segments":{"n":1,"overflow":false}});
            match cause {
                "missing-identity" => {
                    response.as_object_mut().unwrap().remove("wager_capability");
                }
                "wrong-identity" => {
                    response["wager_capability"]["candidate_sha256"] = json!("4".repeat(64))
                }
                "floor" => response["acceptance_floor"] = json!(0.8),
                "missing-floor" => {
                    response.as_object_mut().unwrap().remove("acceptance_floor");
                }
                _ => {}
            }
            let (port, sent) = mock_server("200 OK", response.to_string());
            let result = client(port, 5).predict_wager_with_deadline(
                &pass,
                vec![vec![1, 2, 3]],
                &registry,
                entry,
                Instant::now() + Duration::from_secs(5),
            );
            assert_eq!(result.is_ok(), cause == "qualified", "{cause}");
            let request: Value =
                serde_json::from_slice(&sent.recv_timeout(Duration::from_secs(5)).unwrap())
                    .unwrap();
            assert_eq!(request["wager_capability"], registry.wire_capability(entry));
            assert_eq!(request["glyph_style"], "white");
            assert_eq!(request["questions"].as_object().unwrap().len(), 8);
        }
        let mut wrong_model = registry.clone();
        wrong_model.model_alias = "wrong-model".into();
        assert!(client(0, 5)
            .predict_wager_with_deadline(
                &pass,
                vec![vec![1]],
                &wrong_model,
                entry,
                Instant::now() + Duration::from_secs(5)
            )
            .is_err());
    }

    #[test]
    fn batch_keeps_per_pass_validation_and_independent_malformed_result_unknown() {
        let requests = stack_batch();
        let results: Vec<Value> = requests.iter().enumerate().map(|(i, (pass, _))| json!({
            "model":"coinpoker-laya-vision","pass":pass.id,"acceptance_floor":0.8,
            "answers":if i == 2 { json!({"PRIVATE-NAME":{"type":"noul","noul":1.0,"truncated":false}}) }
                else { json!({"g1":{"type":"choice","choice":"1","probabilities":{"1":0.9},"truncated":false}}) },
            "segments":{"n":1,"overflow":false}
        })).collect();
        let (port, sent) = mock_server(
            "200 OK",
            json!({"model":"coinpoker-laya-vision","results":results}).to_string(),
        );
        let result = client(port, 5)
            .predict_batch_with_deadline(&requests, Instant::now() + Duration::from_secs(5))
            .unwrap();
        assert_eq!(result.len(), 6);
        assert!(result[0].is_ok() && result[1].is_ok() && result[3].is_ok() && result[5].is_ok());
        assert_eq!(result[2].as_ref().unwrap_err().code(), "invalid-vlm-schema");
        assert!(!result[2]
            .as_ref()
            .unwrap_err()
            .to_string()
            .contains("PRIVATE-NAME"));
        let request: Value =
            serde_json::from_slice(&sent.recv_timeout(Duration::from_secs(5)).unwrap()).unwrap();
        assert_eq!(request["batch"].as_array().unwrap().len(), 6);
        assert_eq!(request["batch"][0]["pass"], "p5_seat_1_stack");
        assert_eq!(request["batch"][5]["pass"], "p5_seat_6_stack");
    }

    #[test]
    fn batch_404_and_busy_do_not_retry_or_expose_error_bodies() {
        for (status, expected) in [("404 Not Found", 404), ("409 Conflict", 409)] {
            let (port, sent) = mock_server(status, "PRIVATE raw image response".into());
            let error = client(port, 5)
                .predict_batch_with_deadline(
                    &stack_batch(),
                    Instant::now() + Duration::from_secs(5),
                )
                .unwrap_err();
            assert!(
                matches!(error, VlmError::Server { status, ref body } if status == expected && body.is_empty())
            );
            assert!(sent.recv_timeout(Duration::from_secs(5)).is_ok());
            assert!(sent.try_recv().is_err());
        }
    }

    #[test]
    fn batch_rejects_untrained_duplicate_or_expired_work_without_transport() {
        let client = client(0, 5);
        let mut requests = stack_batch();
        requests[1].0 = requests[0].0;
        assert!(client
            .predict_batch_with_deadline(&requests, Instant::now() + Duration::from_secs(5))
            .is_err());
        requests[1].0 = pass("p3_hero_chips").unwrap();
        assert!(client
            .predict_batch_with_deadline(&requests, Instant::now() + Duration::from_secs(5))
            .is_err());
        assert!(matches!(
            client.predict_batch_with_deadline(&stack_batch(), Instant::now()),
            Err(VlmError::Deadline)
        ));
    }

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

    #[test]
    fn manual_binding_reaches_every_single_and_batch_request_and_is_opt_in() {
        use std::io::{BufRead, BufReader};
        let session = "a1".repeat(16);
        let service = "b2".repeat(16);
        for bound in [false, true] {
            for batch in [0, 1, 2] {
                let listener = TcpListener::bind("127.0.0.1:0").unwrap();
                let port = listener.local_addr().unwrap().port();
                let (tx, rx) = mpsc::channel();
                thread::spawn(move || {
                    let (mut stream, _) = listener.accept().unwrap();
                    stream
                        .set_read_timeout(Some(Duration::from_secs(5)))
                        .unwrap();
                    let mut reader = BufReader::new(&mut stream);
                    let mut headers = String::new();
                    let mut length = 0;
                    loop {
                        let mut line = String::new();
                        assert!(reader.read_line(&mut line).unwrap() > 0);
                        if line == "\r\n" {
                            break;
                        }
                        if let Some(value) =
                            line.to_ascii_lowercase().strip_prefix("content-length:")
                        {
                            length = value.trim().parse::<usize>().unwrap();
                        }
                        headers.push_str(&line);
                    }
                    let mut body = vec![0; length];
                    reader.read_exact(&mut body).unwrap();
                    drop(reader);
                    tx.send(headers).unwrap();
                    stream.write_all(b"HTTP/1.1 409 Conflict\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").unwrap();
                });
                let mut client = client(port, 5);
                if bound {
                    client = client.with_manual_session(&session, &service).unwrap();
                }
                let result = if batch == 2 {
                    client
                        .predict_readout_batch_with_deadline(
                            &[
                                (pass("p0_full").unwrap(), vec![png()]),
                                (pass("p2_board").unwrap(), vec![png(); 5]),
                            ],
                            Instant::now() + Duration::from_secs(5),
                        )
                        .map(|_| ())
                } else if batch == 1 {
                    client
                        .predict_batch_with_deadline(
                            &stack_batch(),
                            Instant::now() + Duration::from_secs(5),
                        )
                        .map(|_| ())
                } else {
                    client
                        .predict(pass("p0_full").unwrap(), vec![png()])
                        .map(|_| ())
                };
                assert!(matches!(result, Err(VlmError::Server { status: 409, .. })));
                let headers = rx
                    .recv_timeout(Duration::from_secs(5))
                    .unwrap()
                    .to_ascii_lowercase();
                assert!(headers.starts_with(if batch != 0 {
                    "post /v1/laya/predict-batch "
                } else {
                    "post /v1/laya/predict "
                }));
                for (header, value) in [
                    ("x-coinpoker-session", &session),
                    ("x-coinpoker-service", &service),
                ] {
                    assert_eq!(headers.contains(&format!("{header}: {value}\r\n")), bound);
                }
            }
        }
        for invalid in [
            "".to_string(),
            "x".repeat(32),
            "A".repeat(32),
            "a".repeat(33),
            "\r\n".repeat(16),
        ] {
            assert!(client(0, 5)
                .with_manual_session(&invalid, &service)
                .is_err());
            assert!(client(0, 5)
                .with_manual_session(&session, &invalid)
                .is_err());
        }
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
        // Explicit synthetic floor for wire-format tests, not the fitted model floor.
        json!({
            "model": model, "pass": pass_id,
            "acceptance_floor": 0.8,
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
        assert_eq!(answers.acceptance_floor, Some(0.8));

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
    fn acceptance_floor_requires_a_finite_number_in_the_unit_interval() {
        let client = client(0, 1);
        let pass = pass("p0_full").unwrap();
        let valid: Value =
            serde_json::from_str(&p0_response("coinpoker-laya-vision", "p0_full")).unwrap();
        for floor in [0.0, 0.8, 0.995, 0.99999999, 1.0] {
            let mut body = valid.clone();
            body["acceptance_floor"] = json!(floor);
            let answers = client.parse_response(pass, &body.to_string()).unwrap();
            assert_eq!(answers.acceptance_floor, Some(floor));
        }
        let mut missing = valid.clone();
        missing.as_object_mut().unwrap().remove("acceptance_floor");
        let mut invalid = vec![missing.to_string()];
        for floor in [
            Value::Null,
            json!("unknown"),
            json!("0.995"),
            json!(true),
            json!([]),
            json!({}),
            json!(-0.00000001),
            json!(1.00000001),
        ] {
            let mut body = valid.clone();
            body["acceptance_floor"] = floor;
            invalid.push(body.to_string());
        }
        for floor in ["NaN", "Infinity", "-Infinity", "1e9999"] {
            invalid.push(format!(
                "{{\"model\":\"coinpoker-laya-vision\",\"pass\":\"p0_full\",\"acceptance_floor\":{floor},\"answers\":{{}}}}"
            ));
        }
        for body in invalid {
            assert!(matches!(
                client.parse_response(pass, &body),
                Err(VlmError::Parse(VlmResponseError::Schema))
            ));
        }
    }

    #[test]
    fn acceptance_floor_and_probabilities_are_retained_without_f32_rounding() {
        let client = client(0, 1);
        let body = json!({
            "model": "coinpoker-laya-vision", "pass": "p2_board", "acceptance_floor": 1.0,
            "answers": {"board_1_rank": {"type": "choice", "choice": "A",
                "probabilities": {"A": 0.99999999}, "truncated": false}}
        });
        let answers = client
            .parse_response(pass("p2_board").unwrap(), &body.to_string())
            .unwrap();
        assert_eq!(answers.acceptance_floor, Some(1.0));
        assert_eq!(answers.answers["board_1_rank"].p, 0.99999999);
        assert!(answers.answers["board_1_rank"].p < answers.acceptance_floor.unwrap());

        let body = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full", "acceptance_floor": 0.995,
            "answers": {"ev_pot": {"type": "noul", "noul": 0.99499999, "truncated": false}}
        });
        let answers = client
            .parse_response(pass("p0_full").unwrap(), &body.to_string())
            .unwrap();
        assert_eq!(answers.acceptance_floor, Some(0.995));
        assert_eq!(answers.answers["ev_pot"].p, 0.99499999);
        assert!(answers.answers["ev_pot"].p < answers.acceptance_floor.unwrap());
    }

    #[test]
    fn glyph_pass_sends_style_all_glyph_questions_and_reads_segments() {
        let body = json!({
            "model": "coinpoker-laya-vision", "pass": "p3_pot",
            "acceptance_floor": 0.8,
            "answers": {"g1": {"type": "choice", "choice": "7",
                "probabilities": {"7": 0.99}, "confidence": 0.99, "truncated": false}},
            "segments": {"n": 1, "overflow": false}, "timing_ms": {}
        });
        let (port, request_rx) = mock_server("200 OK", body.to_string());
        let answers = client(port, 5)
            .predict(pass("p3_pot").unwrap(), vec![png()])
            .expect("answers");
        assert_eq!(answers.acceptance_floor, Some(0.8));
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
            "acceptance_floor": 0.8,
            "answers": {"ev_pot": {"type": "noul", "noul": 1.5, "truncated": false}}
        });
        let unknown_label = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "acceptance_floor": 0.8,
            "answers": {"screen_kind": {"type": "choice", "choice": "casino",
                "probabilities": {"casino": 0.9}, "truncated": false}}
        });
        let wrong_type = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "acceptance_floor": 0.8,
            "answers": {"screen_kind": {"type": "noul", "noul": 0.9, "truncated": false}}
        });
        let unknown_question = json!({
            "model": "coinpoker-laya-vision", "pass": "p0_full",
            "acceptance_floor": 0.8,
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
