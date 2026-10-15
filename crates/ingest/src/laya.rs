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
pub mod experimental;
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

/// Automatic readouts are source-bound field batches; diagnostics remain separate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ObservationPass {
    Table,
    Pot,
    Board,
    Stack(u8),
    Numbers(u8),
    ReadoutPair(u8),
    BoardReadout,
    Wager(u8),
    Scene(u8),
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

    /// Bind every manual pass/batch to the separately approved service and session.
    pub fn with_manual_session(mut self, session: &str, service: &str) -> Result<Self, VlmError> {
        self.client = self.client.with_manual_session(session, service)?;
        Ok(self)
    }

    /// Bounded diagnostics only. Enabling requires a separately approved session/service binding.
    pub fn with_experimental_bet_action(mut self, enabled: bool) -> Result<Self, VlmError> {
        self.client = self.client.with_experimental_bet_action(enabled)?;
        Ok(self)
    }

    /// Separate observing path. Strict assembly runs against the exact same answers,
    /// without a second model request or a relaxed GameState/action gate.
    pub fn analyze_observation_with_deadline(
        &self,
        frame: &Frame,
        deadline: Instant,
    ) -> Result<LayaAnalysis, VlmError> {
        self.analyze_observation_passes(frame, deadline, None)
    }

    /// Skipped fields remain unknown; no answer is reused from another source frame.
    pub fn analyze_partial_with_deadline(
        &self,
        frame: &Frame,
        deadline: Instant,
        pass: ObservationPass,
    ) -> Result<LayaAnalysis, VlmError> {
        self.analyze_observation_passes(frame, deadline, Some(pass))
    }

    fn analyze_observation_passes(
        &self,
        frame: &Frame,
        deadline: Instant,
        subset: Option<ObservationPass>,
    ) -> Result<LayaAnalysis, VlmError> {
        let experimental = match subset {
            Some(ObservationPass::Wager(seat)) => {
                Some(experimental::ExperimentalDescriptor::wager(seat)?)
            }
            Some(ObservationPass::Scene(seat)) => {
                Some(experimental::ExperimentalDescriptor::scene(seat)?)
            }
            _ => None,
        };
        if let Some(descriptor) = experimental {
            // Separate diagnostic descriptors never consult or weaken approved registries.
            return self.analyze_experimental(frame, deadline, descriptor);
        }
        let readout_ids = match subset {
            Some(ObservationPass::ReadoutPair(seat @ (1 | 3 | 5))) => Some(vec![
                "p0_full".to_string(),
                "p3_pot".to_string(),
                format!("p5_seat_{seat}_stack"),
                format!("p5_seat_{}_stack", seat + 1),
            ]),
            Some(ObservationPass::ReadoutPair(_)) => {
                return Err(VlmError::Unavailable(
                    "invalid-observation-seat-pair".into(),
                ));
            }
            Some(ObservationPass::BoardReadout) => {
                Some(vec!["p0_full".to_string(), "p2_board".to_string()])
            }
            _ => None,
        };
        let selected = match subset {
            None => None,
            Some(ObservationPass::Table) => Some(String::new()),
            Some(ObservationPass::Pot) => Some("p3_pot".into()),
            Some(ObservationPass::Board) => Some("p2_board".into()),
            Some(ObservationPass::ReadoutPair(_) | ObservationPass::BoardReadout) => {
                Some(String::new())
            }
            Some(ObservationPass::Stack(seat @ 1..=6) | ObservationPass::Numbers(seat @ 1..=6)) => {
                Some(format!("p5_seat_{seat}_stack"))
            }
            Some(ObservationPass::Stack(_) | ObservationPass::Numbers(_)) => {
                return Err(VlmError::Unavailable("invalid-observation-seat".into()));
            }
            Some(ObservationPass::Wager(_) | ObservationPass::Scene(_)) => unreachable!(),
        };
        if subset.is_some() && (self.wager_registry.is_some() || self.scene_registry.is_some()) {
            return Err(VlmError::Unavailable(
                "partial-pass-extension-unsupported".into(),
            ));
        }
        remaining_budget(deadline, Instant::now())?;
        let image = frame
            .to_rgba_image()
            .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
        let size = (image.width(), image.height());
        let mut batch_answers = std::collections::HashMap::new();
        let mut batch_attempted = false;
        let numbers = matches!(subset, Some(ObservationPass::Numbers(_)));
        let mut serial_stacks = subset.is_some();
        let mut pass_times = std::collections::HashMap::new();
        let mut readout_answers = std::collections::HashMap::new();
        let mut readout_ms = None;
        if let Some(ids) = &readout_ids {
            let started = Instant::now();
            let mut passes = Vec::new();
            for id in ids {
                let pass = question_set().pass(id).unwrap();
                let images = pass_images(&image, pass)?
                    .ok_or_else(|| VlmError::Unavailable("readout-crop-unavailable".into()))?;
                passes.push((pass, images));
            }
            let answers = self
                .client
                .predict_readout_batch_with_deadline(&passes, deadline)?;
            readout_ms = Some(started.elapsed().as_secs_f64() * 1000.0);
            for ((pass, _), answers) in passes.into_iter().zip(answers) {
                readout_answers.insert(pass.id.clone(), answers);
            }
        }
        let mut run = |pass: &Pass| -> Result<PassAnswers, VlmError> {
            remaining_budget(deadline, Instant::now())?;
            if readout_ids.is_some() {
                return readout_answers
                    .remove(&pass.id)
                    .unwrap_or_else(|| Err(VlmError::Unavailable("pass-not-scheduled".into())));
            }
            if selected.as_ref().is_some_and(|id| {
                pass.id != "p0_full" && pass.id != *id && !(numbers && pass.id == "p3_pot")
            }) {
                return Err(VlmError::Unavailable("pass-not-scheduled".into()));
            }
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
            if selected.is_none() && pass.id.starts_with("p5_seat_") && !batch_attempted {
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
            // A malformed individual pass does not erase independent amounts.
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
        // Shared batches have one measured duration, never an invented per-pass split.
        diagnostics.timing.inference_ms = readout_ms;
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

    fn analyze_experimental(
        &self,
        frame: &Frame,
        deadline: Instant,
        descriptor: experimental::ExperimentalDescriptor,
    ) -> Result<LayaAnalysis, VlmError> {
        use crate::partial::{
            DiagnosticAdmission, DiagnosticReason as Reason, EvidenceStatus as Status, FieldName,
        };
        if !self.client.experimental_enabled() {
            return Err(VlmError::Unavailable(
                "experimental-session-opt-in-required".into(),
            ));
        }
        let deadline = deadline.min(Instant::now() + std::time::Duration::from_secs(5));
        remaining_budget(deadline, Instant::now())?;
        let image = frame
            .to_rgba_image()
            .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
        let size = (image.width(), image.height());
        let p0 = question_set().pass("p0_full").expect("vendored table core");
        let mut diagnostics = crate::partial::PerceptionDiagnostics {
            frame_width: size.0,
            frame_height: size.1,
            ..Default::default()
        };
        let started = Instant::now();
        let (answers, failure) =
            match self
                .client
                .predict_with_deadline(p0, vec![encode_png(&image)?], deadline)
            {
                Ok(answers) => (answers, None),
                Err(VlmError::Deadline) => {
                    diagnostics.set_admission(DiagnosticAdmission::DecisionBudgetExpired, None);
                    (PassAnswers::default(), Some(Reason::DecisionDeadline))
                }
                Err(_) => (PassAnswers::default(), Some(Reason::PassUnavailable)),
            };
        let p0_floor = answers.acceptance_floor.map(|floor| {
            floor
                .max(0.995)
                .max(p0.threshold)
                .max(self.threshold.map_or(0.0, f64::from))
        });
        let core_reading = partial::Reading {
            pass: p0,
            answers,
            floor: p0_floor,
            failure,
        };
        diagnostics.passes.push(crate::partial::PassDiagnostic {
            pass: p0.id.clone(),
            crop_bounds: vec![[0, 0, size.0, size.1]],
            crop_dimensions: vec![[size.0, size.1]],
            questions: p0
                .questions
                .iter()
                .map(|q| core_reading.diagnostic(&q.id))
                .collect(),
            segments: None,
            total_ms: Some(started.elapsed().as_secs_f64() * 1000.0),
        });
        let mut core_accepted = self.lobby != Some(size);
        for (field, id) in [
            (FieldName::ScreenKind, "screen_kind"),
            (FieldName::TableLayout, "ev_table_layout"),
            (FieldName::Readable, "ev_readable"),
        ] {
            let q = core_reading.diagnostic(id);
            let matches = q.status == Status::Accepted
                && match q.answer.as_ref() {
                    Some(crate::partial::SafeAnswer::Choice(label)) => label == "poker_table",
                    Some(crate::partial::SafeAnswer::Noul(value)) => *value,
                    _ => false,
                };
            partial::record(
                &mut diagnostics.fields,
                field,
                None,
                None,
                if matches {
                    Status::Accepted
                } else if q.status == Status::Accepted {
                    Status::Rejected
                } else {
                    q.status
                },
                if matches {
                    Reason::Accepted
                } else if q.status == Status::Accepted {
                    Reason::DependencyRejected
                } else {
                    q.reason
                },
            );
            core_accepted &= matches;
        }
        if core_accepted {
            if let Some(bounds @ [a, b, c, d]) = descriptor.crop_bounds(size.0, size.1) {
                let started = Instant::now();
                let crop = image::imageops::crop_imm(&image, a, b, c - a, d - b).to_image();
                let (answers, provenance, failure) = match self
                    .client
                    .predict_experimental_with_deadline(
                        &descriptor,
                        vec![encode_png(&crop)?],
                        deadline,
                    ) {
                    Ok((answers, provenance)) => (answers, Some(provenance), None),
                    Err(VlmError::Deadline) => {
                        diagnostics.set_admission(DiagnosticAdmission::DecisionBudgetExpired, None);
                        (PassAnswers::default(), None, Some(Reason::DecisionDeadline))
                    }
                    Err(_) => (PassAnswers::default(), None, Some(Reason::PassUnavailable)),
                };
                let inherited_cutoff = provenance
                    .as_ref()
                    .and_then(|p| p.inherited_cutoff)
                    .map(|floor| floor.max(self.threshold.map_or(0.0, f64::from)));
                experimental::append_diagnostics(
                    &mut diagnostics,
                    &descriptor,
                    &answers,
                    bounds,
                    failure,
                    inherited_cutoff,
                    started.elapsed().as_secs_f64() * 1000.0,
                );
                if let Some(provenance) = provenance {
                    diagnostics.experimental = Some(experimental::ExperimentalDiagnostics::bind(
                        descriptor,
                        provenance,
                        frame,
                        core_accepted,
                    )?);
                }
            }
        }
        if remaining_budget(deadline, Instant::now()).is_err() {
            diagnostics.set_admission(DiagnosticAdmission::DecisionBudgetExpired, None);
        }
        let kind = core_reading
            .answers
            .answers
            .get("screen_kind")
            .and_then(|a| a.choice.as_deref())
            .filter(|kind| {
                ["poker_table", "lobby", "other_coin_poker_window", "unknown"].contains(kind)
            })
            .unwrap_or("unknown");
        Ok(LayaAnalysis {
            output: VlmOutput {
                text: serde_json::json!({"screen_kind":kind,
                "evidence":{"table_layout":false,"hero_cards":false,"board_area":false,
                    "pot":false,"action_controls":false,"readable":false},"state":null})
                .to_string(),
            },
            partial: None,
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
                    ..Frame::default()
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
            ..Frame::default()
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

    fn partial_reply(request: &Value) -> Value {
        if request["pass"].as_str().unwrap().starts_with("p5_seat_") {
            return json!({"model":"coinpoker-laya-vision", "pass":request["pass"],
                "acceptance_floor":0.8, "answers":{"g1":choice("1")},
                "segments":{"n":1,"overflow":false}});
        }
        let mut reply = unseated_flop(request);
        if request["pass"] == "p0_full" {
            reply["acceptance_floor"] = json!(0.995);
            for answer in reply["answers"].as_object_mut().unwrap().values_mut() {
                if let Some(p) = answer.get_mut("noul") {
                    *p = json!(if p.as_f64().unwrap() > 0.5 { 1.0 } else { 0.0 });
                } else {
                    let label = answer["choice"].as_str().unwrap().to_string();
                    answer["probabilities"][label] = json!(1.0);
                }
            }
            reply["answers"]["hero_seat_index"]["probabilities"]["not_seated"] = json!(0.9925);
        }
        reply["answers"]
            .as_object_mut()
            .unwrap()
            .retain(|id, _| request["questions"].get(id).is_some());
        reply
    }

    fn experimental_reply(request: &Value) -> Value {
        let Some(descriptor) = request.get("experimental_descriptor") else {
            return partial_reply(request);
        };
        let descriptor: experimental::ExperimentalDescriptor =
            serde_json::from_value(descriptor.clone()).unwrap();
        let answers = if descriptor.is_wager() {
            json!({"g1":choice("1"), "g2":choice("."), "g3":choice("5")})
        } else {
            Value::Object(
                scene::SCENE_QUESTIONS
                    .iter()
                    .map(|(_, id, _, labels)| ((*id).into(), choice(labels[0])))
                    .collect(),
            )
        };
        let mut result = json!({"model":"coinpoker-laya-vision", "pass":descriptor.pass,
            "experimental_descriptor":descriptor, "acceptance_floor":null,
            "experimental_diagnostics":experimental::tests::provenance(descriptor.is_wager()), "answers":answers});
        if descriptor.is_wager() {
            result["segments"] = json!({"n":3,"overflow":false});
        }
        result
    }

    #[test]
    fn explicit_experimental_jobs_run_only_core_and_one_diagnostic_crop_without_any_admission() {
        use crate::partial::{DiagnosticReason, EvidenceStatus};
        for seat in 1..=6 {
            for selected in [ObservationPass::Wager(seat), ObservationPass::Scene(seat)] {
                let (port, requests) = scripted_server(experimental_reply);
                let source = frame(900, 686);
                let backend = backend(port, None)
                    .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
                    .unwrap()
                    .with_experimental_bet_action(true)
                    .unwrap()
                    .with_wager_registry(wager::tests::registry())
                    .unwrap()
                    .with_scene_registry(scene::ScenePassRegistry {
                        version: 1,
                        model_alias: "coinpoker-laya-vision".into(),
                        passes: Vec::new(),
                    })
                    .unwrap();
                let result = backend
                    .analyze_partial_with_deadline(
                        &source,
                        Instant::now() + std::time::Duration::from_secs(5),
                        selected,
                    )
                    .unwrap();
                assert!(result.partial.is_none());
                let observation = parse_screen_output(&result.output).unwrap();
                assert!(observation.state.is_none());
                assert!(!observation.evidence.readable && !observation.evidence.action_controls);
                assert!(
                    !result.diagnostics.source_current,
                    "runtime must independently validate the original source ticket/crop"
                );
                assert_eq!(result.diagnostics.passes.len(), 2);
                let proof = result.diagnostics.experimental.as_ref().unwrap();
                assert!(proof.core_accepted && proof.source_matches(&source));
                assert_eq!(
                    proof.provenance.inherited_cutoff,
                    if proof.descriptor.is_wager() {
                        Some(0.8)
                    } else {
                        None
                    }
                );
                let pass = &result.diagnostics.passes[1];
                assert_eq!(pass.pass, proof.descriptor.pass);
                assert_eq!(pass.crop_bounds, [proof.crop_bounds]);
                assert_eq!(pass.crop_dimensions, [proof.crop_dimensions]);
                for (index, question) in pass.questions.iter().enumerate() {
                    assert!(question.effective_floor.is_none());
                    assert_eq!(question.status, EvidenceStatus::Unknown);
                    if proof.descriptor.is_wager() && index >= 3 {
                        assert_eq!(question.reason, DiagnosticReason::MissingAnswer);
                        assert!(question.answer.is_none() && question.score.is_none());
                    } else {
                        assert_eq!(question.reason, DiagnosticReason::UnapprovedCapability);
                        assert!(question.answer.is_some() && question.score.is_some());
                    }
                }
                if proof.descriptor.is_wager() {
                    assert_eq!(pass.segments.as_ref().unwrap().n, 3);
                    assert_eq!(pass.questions.len(), question_set().max_glyphs as usize);
                }
                assert!(result
                    .diagnostics
                    .fields
                    .iter()
                    .filter(|f| f.seat.is_some())
                    .all(|f| f.status == EvidenceStatus::Unknown
                        && f.admission_status != EvidenceStatus::Accepted));
                let sent: Vec<_> = requests.try_iter().collect();
                assert_eq!(sent.len(), 2);
                assert_eq!(sent[0]["pass"], "p0_full");
                assert_eq!(sent[1]["pass"], proof.descriptor.pass);
                assert!(sent.iter().all(|r| r.get("batch").is_none()));
                assert!(
                    sent[1].get("wager_capability").is_none()
                        && sent[1].get("scene_capability").is_none()
                );
                let png = base64::engine::general_purpose::STANDARD
                    .decode(sent[1]["images_png_b64"][0].as_str().unwrap())
                    .unwrap();
                let crop = image::load_from_memory(&png).unwrap().to_rgba8();
                let [a, b, c, d] = proof.crop_bounds;
                let original = source.to_rgba_image().unwrap();
                assert_eq!(
                    crop,
                    image::imageops::crop_imm(&original, a, b, c - a, d - b).to_image()
                );
            }
        }
    }

    #[test]
    fn experimental_jobs_fail_closed_without_session_opt_in_or_current_qualified_core() {
        for pass in [ObservationPass::Wager(1), ObservationPass::Scene(1)] {
            for configured in [false, true] {
                let mut backend = backend(0, None);
                if configured {
                    backend = backend
                        .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
                        .unwrap();
                }
                assert!(backend
                    .analyze_partial_with_deadline(
                        &frame(900, 686),
                        Instant::now() + std::time::Duration::from_secs(5),
                        pass
                    )
                    .is_err());
            }
            let (port, requests) = scripted_server(|request| {
                let mut response = partial_reply(request);
                response["answers"]["ev_readable"]["noul"] = json!(0.98);
                response
            });
            let result = backend(port, None)
                .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
                .unwrap()
                .with_experimental_bet_action(true)
                .unwrap()
                .analyze_partial_with_deadline(
                    &frame(900, 686),
                    Instant::now() + std::time::Duration::from_secs(5),
                    pass,
                )
                .unwrap();
            assert!(result.partial.is_none() && result.diagnostics.experimental.is_none());
            assert_eq!(requests.try_iter().count(), 1);
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
        }
        assert!(backend(0, None).with_experimental_bet_action(true).is_err());
        let bound = backend(0, None)
            .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
            .unwrap()
            .with_experimental_bet_action(true)
            .unwrap();
        let error = bound
            .analyze_partial_with_deadline(
                &frame(900, 686),
                Instant::now(),
                ObservationPass::Wager(1),
            )
            .err()
            .unwrap();
        assert!(matches!(error, VlmError::Deadline));
    }

    #[test]
    fn automatic_partial_passes_keep_core_witness_floors_and_independent_unknowns() {
        use crate::partial::{DiagnosticReason, FieldName};
        for selected in [
            ObservationPass::Table,
            ObservationPass::Pot,
            ObservationPass::Board,
        ]
        .into_iter()
        .chain((1..=6).map(ObservationPass::Stack))
        {
            let (port, requests) = scripted_server(partial_reply);
            let source = frame(800, 613);
            let result = backend(port, None)
                .analyze_partial_with_deadline(
                    &source,
                    Instant::now() + std::time::Duration::from_secs(5),
                    selected,
                )
                .unwrap();
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
            let candidate = result.partial.unwrap();
            assert!(candidate.core_accepted());
            assert!(candidate.table_content_witness(&source).is_some());
            assert_eq!(
                candidate.view.role, None,
                "hero identity is still unconfirmed"
            );
            assert_eq!(candidate.view.game_phase, None);
            assert!(candidate.view.board_slots.iter().all(Option::is_none));
            assert_eq!(
                candidate.view.pot_size,
                (selected == ObservationPass::Pot).then_some(250)
            );
            for (index, seat) in candidate.view.seats.iter().enumerate() {
                assert_eq!(
                    seat.displayed_stack,
                    (selected == ObservationPass::Stack(index as u8 + 1)).then_some(100)
                );
                assert!(seat.visible_wager.is_none() && seat.street_contribution.is_none());
            }
            let sent: Vec<_> = requests.try_iter().collect();
            assert_eq!(
                sent.len(),
                if selected == ObservationPass::Table {
                    1
                } else {
                    2
                }
            );
            assert_eq!(sent[0]["pass"], "p0_full");
            assert!(sent.iter().all(|request| request.get("batch").is_none()));
            let expected = match selected {
                ObservationPass::Table => "p0_full".to_string(),
                ObservationPass::Pot => "p3_pot".to_string(),
                ObservationPass::Board => "p2_board".to_string(),
                ObservationPass::Stack(seat) => format!("p5_seat_{seat}_stack"),
                ObservationPass::Numbers(_) => unreachable!("numeric pair has separate coverage"),
                ObservationPass::ReadoutPair(_) | ObservationPass::BoardReadout => {
                    unreachable!("mixed batches have separate coverage")
                }
                ObservationPass::Wager(_) | ObservationPass::Scene(_) => {
                    unreachable!("diagnostics have separate coverage")
                }
            };
            assert_eq!(sent.last().unwrap()["pass"], expected);
            for pass in &result.diagnostics.passes {
                assert_eq!(
                    pass.total_ms.is_some(),
                    pass.pass == "p0_full" || pass.pass == expected
                );
                if selected == ObservationPass::Board && pass.pass == "p2_board" {
                    assert!(pass
                        .questions
                        .iter()
                        .all(|question| question.effective_floor == Some(1.0)
                            && question.reason == DiagnosticReason::BelowFloor));
                }
            }
            if selected != ObservationPass::Pot {
                assert!(result
                    .diagnostics
                    .fields
                    .iter()
                    .any(|field| field.field == FieldName::PotSize
                        && field.reason == DiagnosticReason::PassUnavailable));
            }
            assert!(!candidate.view.quality_approved);
        }
    }

    #[test]
    fn automatic_partial_passes_never_reuse_answers_from_previous_source_jobs() {
        let (port, requests) = scripted_server(partial_reply);
        let backend = backend(port, None);
        for selected in [
            ObservationPass::Pot,
            ObservationPass::Stack(3),
            ObservationPass::Table,
        ] {
            let result = backend
                .analyze_partial_with_deadline(
                    &frame(800, 613),
                    Instant::now() + std::time::Duration::from_secs(5),
                    selected,
                )
                .unwrap();
            let candidate = result.partial.unwrap();
            assert_eq!(
                candidate.view.pot_size.is_some(),
                selected == ObservationPass::Pot
            );
            assert_eq!(
                candidate.view.seats[2].displayed_stack.is_some(),
                selected == ObservationPass::Stack(3)
            );
        }
        assert_eq!(requests.try_iter().count(), 5);
    }

    #[test]
    fn mixed_readouts_use_one_request_without_merging_sources_or_weakening_floors() {
        for (selected, first_seat) in [
            (ObservationPass::ReadoutPair(1), Some(1)),
            (ObservationPass::ReadoutPair(3), Some(3)),
            (ObservationPass::ReadoutPair(5), Some(5)),
            (ObservationPass::BoardReadout, None),
        ] {
            let (port, requests) = scripted_server(|request| {
                json!({"model":"coinpoker-laya-vision", "results":request["batch"]
                    .as_array().unwrap().iter().map(|request| {
                        let mut result = partial_reply(request);
                        result["answers"].as_object_mut().unwrap().retain(|id, _| request["questions"].get(id).is_some());
                        result
                    }).collect::<Vec<_>>()})
            });
            let source = frame(800, 613);
            let result = backend(port, None)
                .with_manual_session(&"a1".repeat(16), &"b2".repeat(16))
                .unwrap()
                .analyze_partial_with_deadline(
                    &source,
                    Instant::now() + std::time::Duration::from_secs(5),
                    selected,
                )
                .unwrap();
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
            let mut candidate = result.partial.unwrap();
            assert!(candidate.core_accepted() && candidate.retain_source_current_fields(&source));
            assert!(!candidate.view.quality_approved && candidate.view.hero_seated.is_none());
            assert_eq!(candidate.view.pot_size, first_seat.map(|_| 250));
            for (i, seat) in candidate.view.seats.iter().enumerate() {
                let included = first_seat.is_some_and(|first| i + 1 == first || i == first);
                assert_eq!(seat.displayed_stack, included.then_some(100));
                assert!(seat.visible_wager.is_none() && seat.street_contribution.is_none());
            }
            assert!(candidate.view.board_slots.iter().all(Option::is_none));
            assert!(result.diagnostics.timing.inference_ms.is_some());
            assert!(result
                .diagnostics
                .passes
                .iter()
                .all(|pass| pass.total_ms.is_none()));
            let sent: Vec<_> = requests.try_iter().collect();
            assert_eq!(sent.len(), 1);
            assert_eq!(sent[0]["batch_kind"], "readout");
            let batch = sent[0]["batch"].as_array().unwrap();
            assert_eq!(batch.len(), if first_seat.is_some() { 4 } else { 2 });
            assert_eq!(batch[0]["pass"], "p0_full");
            let core: Vec<_> = batch[0]["questions"]
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect();
            assert_eq!(
                core,
                if first_seat.is_some() {
                    vec!["ev_pot", "ev_readable", "ev_table_layout", "screen_kind"]
                } else {
                    vec![
                        "ev_board_area",
                        "ev_readable",
                        "ev_table_layout",
                        "game_phase",
                        "screen_kind",
                    ]
                }
            );
            for request in batch {
                let pass = question_set()
                    .pass(request["pass"].as_str().unwrap())
                    .unwrap();
                let expected = pass_images(&source.to_rgba_image().unwrap(), pass)
                    .unwrap()
                    .unwrap();
                for (wire, original) in request["images_png_b64"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .zip(expected)
                {
                    assert_eq!(
                        base64::engine::general_purpose::STANDARD
                            .decode(wire.as_str().unwrap())
                            .unwrap(),
                        original
                    );
                }
            }
            if first_seat.is_none() {
                let board = result
                    .diagnostics
                    .passes
                    .iter()
                    .find(|p| p.pass == "p2_board")
                    .unwrap();
                assert!(board
                    .questions
                    .iter()
                    .all(|q| q.effective_floor == Some(1.0)));
            }
        }
    }

    #[test]
    fn mixed_readouts_reject_unrequested_role_answers() {
        for selected in [
            ObservationPass::ReadoutPair(1),
            ObservationPass::BoardReadout,
        ] {
            let (port, _) = scripted_server(|request| {
                let results: Vec<_> = request["batch"].as_array().unwrap().iter().map(|request| {
                    let mut response = partial_reply(request);
                    if request["pass"] == "p0_full" {
                        response["answers"]["hero_seat_index"] = json!({"type":"choice", "choice":"not_seated", "probabilities":{"not_seated":1.0}});
                        for (id, p) in [("action_on_hero", 0.0), ("ev_seat_controls", 1.0), ("ev_hero_cards", 0.0), ("ev_action_controls", 0.0)] {
                            response["answers"][id] = json!({"type":"noul", "noul":p});
                        }
                    }
                    response
                }).collect();
                json!({"model":"coinpoker-laya-vision", "results":results})
            });
            let result = backend(port, None)
                .analyze_partial_with_deadline(
                    &frame(800, 613),
                    Instant::now() + std::time::Duration::from_secs(5),
                    selected,
                )
                .unwrap();
            assert!(result.partial.is_none());
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
        }
    }

    #[test]
    fn mixed_readouts_isolate_malformed_fields_and_reject_failed_core() {
        for bad_pass in ["p0_full", "p5_seat_1_stack"] {
            let (port, _) = scripted_server(move |request| {
                let results: Vec<_> = request["batch"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|request| {
                        if request["pass"] == bad_pass {
                            json!({"model":"wrong-model"})
                        } else {
                            partial_reply(request)
                        }
                    })
                    .collect();
                json!({"model":"coinpoker-laya-vision", "results":results})
            });
            let result = backend(port, None)
                .analyze_partial_with_deadline(
                    &frame(800, 613),
                    Instant::now() + std::time::Duration::from_secs(5),
                    ObservationPass::ReadoutPair(1),
                )
                .unwrap();
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
            if bad_pass == "p0_full" {
                assert!(result.partial.is_none());
            } else {
                let candidate = result.partial.unwrap();
                assert_eq!(candidate.view.pot_size, Some(250));
                assert!(candidate.view.seats[0].displayed_stack.is_none());
                assert_eq!(candidate.view.seats[1].displayed_stack, Some(100));
            }
        }
        for seat in [0, 2, 4, 6, 7, u8::MAX] {
            assert!(backend(0, None)
                .analyze_partial_with_deadline(
                    &frame(800, 613),
                    Instant::now() + std::time::Duration::from_secs(5),
                    ObservationPass::ReadoutPair(seat)
                )
                .is_err());
        }
        assert!(matches!(
            backend(0, None)
                .analyze_partial_with_deadline(
                    &frame(800, 613),
                    Instant::now(),
                    ObservationPass::ReadoutPair(1)
                )
                .err(),
            Some(VlmError::Deadline)
        ));
    }

    #[test]
    fn automatic_numeric_pair_refreshes_pot_and_selected_stack_without_a_slow_large_batch() {
        let (port, requests) = scripted_server(partial_reply);
        let source = frame(800, 613);
        let backend = backend(port, None);
        for selected in 1..=6 {
            let result = backend
                .analyze_partial_with_deadline(
                    &source,
                    Instant::now() + std::time::Duration::from_secs(5),
                    ObservationPass::Numbers(selected),
                )
                .unwrap();
            let candidate = result.partial.unwrap();
            assert!(candidate.core_accepted());
            assert!(candidate.table_content_witness(&source).is_some());
            assert_eq!(candidate.view.pot_size, Some(250));
            for (index, seat) in candidate.view.seats.iter().enumerate() {
                assert_eq!(
                    seat.displayed_stack,
                    (index + 1 == selected as usize).then_some(100)
                );
                assert!(seat.visible_wager.is_none() && seat.street_contribution.is_none());
            }
            assert!(candidate.view.board_slots.iter().all(Option::is_none));
            assert!(candidate.view.hero_seated.is_none() && !candidate.view.quality_approved);
            assert!(parse_screen_output(&result.output).unwrap().state.is_none());
            let sent: Vec<_> = requests.try_iter().collect();
            assert_eq!(sent.len(), 3);
            assert_eq!(sent[0]["pass"], "p0_full");
            assert_eq!(sent[1]["pass"], "p3_pot");
            assert_eq!(sent[2]["pass"], format!("p5_seat_{selected}_stack"));
            assert!(sent.iter().all(|request| request.get("batch").is_none()));
            assert!(!sent
                .iter()
                .any(|request| request["pass"].as_str().is_some_and(|pass| pass
                    .starts_with("p1_")
                    || pass.starts_with("p2_")
                    || pass.starts_with("p6_")
                    || pass.starts_with("p7_"))));
        }
    }

    #[test]
    fn sustained_numbers_synthetic_request_cost_preserves_serial_requests_and_original_source() {
        let (port, requests) = scripted_server(partial_reply);
        let backend = backend(port, None);
        let source = frame(800, 613);
        for (label, lanes, expected_requests) in [
            (
                "separate",
                vec![ObservationPass::Pot, ObservationPass::Stack(1)],
                4,
            ),
            ("numbers", vec![ObservationPass::Numbers(1)], 3),
        ] {
            let started = Instant::now();
            let mut transport_ms = 0.0;
            for lane in lanes {
                let result = backend
                    .analyze_partial_with_deadline(
                        &source,
                        Instant::now() + std::time::Duration::from_millis(4_700),
                        lane,
                    )
                    .unwrap();
                let mut candidate = result.partial.unwrap();
                assert!(candidate.retain_source_current_fields(&source));
                assert!(!candidate.view.quality_approved);
                assert_eq!(
                    candidate.view.pot_size,
                    (lane != ObservationPass::Stack(1)).then_some(250)
                );
                assert_eq!(
                    candidate.view.seats[0].displayed_stack,
                    (lane != ObservationPass::Pot).then_some(100)
                );
                assert!(candidate.view.seats[1..]
                    .iter()
                    .all(|seat| seat.displayed_stack.is_none()));
                transport_ms += result
                    .diagnostics
                    .passes
                    .iter()
                    .filter_map(|pass| pass.total_ms)
                    .sum::<f64>();
            }
            let sent: Vec<_> = requests.try_iter().collect();
            assert_eq!(sent.len(), expected_requests);
            assert!(sent.iter().all(|request| request.get("batch").is_none()));
            assert_eq!(
                sent.iter()
                    .filter(|request| request["pass"] == "p0_full")
                    .count(),
                if label == "separate" { 2 } else { 1 }
            );
            println!("SYNTHETIC_NUMERIC_COST lane={label} requests={} wall_ms={:.3} transport_ms={transport_ms:.3}; mock HTTP only, not model latency",
                sent.len(), started.elapsed().as_secs_f64() * 1_000.0);
        }
    }

    #[test]
    fn automatic_partial_passes_reject_invalid_seats_and_elapsed_leases_without_io() {
        let malformed = Frame {
            width: 2,
            height: 2,
            rgba: vec![0; 15],
            ..Frame::default()
        };
        for seat in [0, 7, u8::MAX] {
            for selected in [
                ObservationPass::Stack(seat),
                ObservationPass::Numbers(seat),
                ObservationPass::Wager(seat),
                ObservationPass::Scene(seat),
            ] {
                let error = backend(0, None)
                    .analyze_partial_with_deadline(
                        &malformed,
                        Instant::now() + std::time::Duration::from_secs(5),
                        selected,
                    )
                    .err()
                    .unwrap();
                assert!(matches!(error, VlmError::Unavailable(_)));
            }
        }
        let error = backend(0, None)
            .analyze_partial_with_deadline(&malformed, Instant::now(), ObservationPass::Table)
            .err()
            .unwrap();
        assert!(matches!(error, VlmError::Deadline));
    }

    #[test]
    fn automatic_partial_passes_reject_extensions_before_encoding_or_io() {
        let with_wagers = backend(0, None)
            .with_wager_registry(wager::tests::registry())
            .unwrap();
        let mut with_scene = backend(0, None);
        with_scene.scene_registry = Some(scene::ScenePassRegistry {
            version: scene::SCENE_REGISTRY_VERSION,
            model_alias: "coinpoker-laya-vision".into(),
            passes: Vec::new(),
        });
        let malformed = Frame {
            width: 2,
            height: 2,
            rgba: vec![0; 15],
            ..Frame::default()
        };
        for backend in [with_wagers, with_scene] {
            let error = backend
                .analyze_partial_with_deadline(
                    &malformed,
                    Instant::now() + std::time::Duration::from_secs(5),
                    ObservationPass::Pot,
                )
                .err()
                .unwrap();
            assert!(
                matches!(error, VlmError::Unavailable(message) if message == "partial-pass-extension-unsupported")
            );
        }
    }

    #[test]
    fn automatic_partial_passes_do_not_run_fields_after_unqualified_core() {
        let (port, requests) = scripted_server(|request| {
            let mut reply = partial_reply(request);
            reply["answers"]["ev_readable"]["noul"] = json!(0.98);
            reply
        });
        let result = backend(port, None)
            .analyze_partial_with_deadline(
                &frame(800, 613),
                Instant::now() + std::time::Duration::from_secs(5),
                ObservationPass::Pot,
            )
            .unwrap();
        assert!(result.partial.is_none());
        assert_eq!(requests.try_iter().count(), 1);
    }
}
