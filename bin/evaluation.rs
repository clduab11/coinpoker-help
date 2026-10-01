//! Local-only visual evaluation. Synthetic responses test contracts, NOT vision accuracy.
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::time::Instant;

use crate::{live, Pipeline, RunError};
use ingest::capture::Frame;
use ingest::discovery::TableIdentity;
use ingest::parser::GameState;
use ingest::runtime::{observation_is_current, Freshness, Ticket};
use ingest::screen::{inspect_frame, parse_screen_output, MetadataEvidence, ScreenKind, TableGate};
use ingest::vlm::{OpenAiServerBackend, VlmBackend, VlmConfig, VlmOutput};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    format: u32,
    source: String,
    cases: Vec<Case>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    sequence: String,
    identity: TableIdentity,
    metadata: String,
    expected_kind: ScreenKind,
    expected_state: Option<GameState>,
    recommendation_allowed: bool,
    tags: Vec<String>,
    image: Option<String>,
    synthetic_image: Option<SyntheticImage>,
    response: Option<Value>,
    freshness: Option<SequenceFreshness>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SyntheticImage {
    width: u32,
    height: u32,
    seed: u8,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SequenceFreshness {
    generation: u64,
    current_generation: u64,
    epoch: u64,
    current_epoch: u64,
    age_ms: u64,
    current_identity: Option<TableIdentity>,
    fresh_capture: bool,
    expected_fresh: bool,
}
#[derive(Default)]
struct Ratio {
    correct: usize,
    total: usize,
}
impl Ratio {
    fn record(&mut self, correct: bool) {
        self.total += 1;
        self.correct += usize::from(correct);
    }
    fn value(&self) -> Value {
        if self.total == 0 {
            Value::Null
        } else {
            json!(self.correct as f64 / self.total as f64)
        }
    }
}

fn kind(kind: ScreenKind) -> &'static str {
    match kind {
        ScreenKind::Lobby => "lobby",
        ScreenKind::PokerTable => "poker_table",
        ScreenKind::OtherCoinPokerWindow => "other_coin_poker_window",
        ScreenKind::Unknown => "unknown",
    }
}
fn fail(message: &str) -> RunError {
    RunError::Message(message.into())
}
fn metadata(value: &str) -> Result<MetadataEvidence, RunError> {
    match value {
        "candidate" => Ok(MetadataEvidence::Candidate),
        "table_title" => Ok(MetadataEvidence::TableTitle),
        "lobby_title" => Ok(MetadataEvidence::LobbyTitle),
        "other" => Ok(MetadataEvidence::Other),
        _ => Err(fail("unknown fixture metadata evidence")),
    }
}
fn within(root: &Path, relative: &str) -> Result<PathBuf, RunError> {
    let path = root.join(relative).canonicalize()?;
    if !path.starts_with(root) {
        return Err(fail("fixture image path escapes its manifest directory"));
    }
    Ok(path)
}
fn frame(case: &Case, root: &Path, synthetic: bool) -> Result<Frame, RunError> {
    if synthetic {
        if case.image.is_some() {
            return Err(fail(
                "synthetic cases must use generated pixels, not screenshots",
            ));
        }
        let spec = case
            .synthetic_image
            .as_ref()
            .ok_or_else(|| fail("synthetic image specification required"))?;
        if spec.width == 0
            || spec.height == 0
            || u64::from(spec.width) * u64::from(spec.height) > 16_777_216
        {
            return Err(fail("invalid or oversized synthetic image"));
        }
        let mut rgba = Vec::with_capacity(spec.width as usize * spec.height as usize * 4);
        for y in 0..spec.height {
            for x in 0..spec.width {
                let v = (x.wrapping_add(y) as u8).wrapping_add(spec.seed);
                rgba.extend_from_slice(&[v, spec.seed, 255 - v, 255]);
            }
        }
        Frame::new(spec.width, spec.height, rgba).map_err(|_| fail("invalid synthetic frame"))
    } else {
        if case.synthetic_image.is_some() || case.response.is_some() {
            return Err(fail(
                "local-image cases cannot substitute synthetic pixels or recorded VLM responses",
            ));
        }
        let path = within(
            root,
            case.image
                .as_deref()
                .ok_or_else(|| fail("local image path required"))?,
        )?;
        let reader = image::ImageReader::open(path)?.with_guessed_format()?;
        let image = reader
            .decode()
            .map_err(|_| fail("cannot decode local fixture image"))?
            .to_rgba8();
        Frame::new(image.width(), image.height(), image.into_raw())
            .map_err(|_| fail("invalid fixture frame"))
    }
}
fn percentile(samples: &mut [u64], percentile: usize) -> Value {
    if samples.is_empty() {
        return Value::Null;
    }
    samples.sort_unstable();
    json!(samples[(samples.len() * percentile).div_ceil(100).saturating_sub(1)])
}

pub fn run(path: &str, config: VlmConfig) -> Result<(), RunError> {
    crate::config::validate_vlm_endpoint(&config.endpoint, false).map_err(RunError::Message)?;
    let path = Path::new(path).canonicalize()?;
    let root = path
        .parent()
        .ok_or_else(|| fail("manifest needs a parent directory"))?;
    let manifest: Manifest = serde_json::from_slice(&std::fs::read(&path)?)
        .map_err(|_| fail("invalid version-2 fixture manifest"))?;
    if manifest.format != 2
        || !matches!(manifest.source.as_str(), "synthetic" | "local_images")
        || manifest.cases.is_empty()
    {
        return Err(fail(
            "expected format 2, source synthetic/local_images, and nonempty cases",
        ));
    }
    let synthetic = manifest.source == "synthetic";
    let backend =
        OpenAiServerBackend::new(config).map_err(|error| RunError::Message(error.to_string()))?;
    let pipeline = Pipeline::new();
    let mut gates: HashMap<&str, TableGate> = HashMap::new();
    let mut ids = BTreeSet::new();
    let mut confusion: BTreeMap<&str, BTreeMap<&str, usize>> = BTreeMap::new();
    let mut tags: BTreeMap<&str, usize> = BTreeMap::new();
    let mut cards = Ratio::default();
    let mut pot = Ratio::default();
    let mut stack = Ratio::default();
    let mut to_call = Ratio::default();
    let mut actions = Ratio::default();
    let mut raises = Ratio::default();
    let mut lobby_fp = Ratio::default();
    let mut nontable_fp = Ratio::default();
    let (mut true_positive, mut false_positive, mut false_negative) = (0, 0, 0);
    let (mut critical, mut errors, mut stale_failures, mut stale_cases) = (0, 0, 0, 0);
    let mut latencies = Vec::new();
    let mut decision_recall = Ratio::default();
    let mut emitted_decisions = 0usize;
    for case in &manifest.cases {
        let metadata = metadata(&case.metadata)?;
        if !ids.insert(&case.id) {
            return Err(fail("fixture IDs must be unique"));
        }
        for tag in &case.tags {
            *tags.entry(tag).or_default() += 1;
        }
        let image = frame(case, root, synthetic)?;
        let start = Instant::now();
        let response = if synthetic {
            VlmOutput {
                text: serde_json::to_string(
                    case.response
                        .as_ref()
                        .ok_or_else(|| fail("synthetic response required"))?,
                )
                .map_err(|_| fail("invalid synthetic response"))?,
            }
        } else {
            match backend.analyze(&image, &ingest::prompt::build_analysis_prompt()) {
                Ok(output) => output,
                Err(_) => {
                    errors += 1;
                    VlmOutput {
                        text: String::new(),
                    }
                }
            }
        };
        let observation = parse_screen_output(&response).ok();
        let actual_kind = observation
            .as_ref()
            .map_or(ScreenKind::Unknown, |o| o.screen_kind);
        *confusion
            .entry(kind(case.expected_kind))
            .or_default()
            .entry(kind(actual_kind))
            .or_default() += 1;
        if case.expected_kind == ScreenKind::Lobby {
            lobby_fp.record(actual_kind == ScreenKind::PokerTable);
        }
        if case.expected_kind != ScreenKind::PokerTable {
            nontable_fp.record(actual_kind == ScreenKind::PokerTable);
        }
        let actual = observation.as_ref().and_then(|o| o.state.as_ref());
        if let Some(expected) = case.expected_state.as_ref() {
            cards.record(
                actual.is_some_and(|s| {
                    s.hero_cards == expected.hero_cards && s.board == expected.board
                }),
            );
            pot.record(actual.is_some_and(|s| s.pot_size == expected.pot_size));
            stack.record(actual.is_some_and(|s| {
                s.hero_chips == expected.hero_chips
                    && s.players
                        .iter()
                        .map(|p| (&p.name, p.chips))
                        .eq(expected.players.iter().map(|p| (&p.name, p.chips)))
            }));
            to_call.record(actual.is_some_and(|s| s.to_call == expected.to_call));
            let mut expected_actions = expected.available_actions.clone();
            expected_actions.sort();
            actions.record(actual.is_some_and(|s| {
                let mut a = s.available_actions.clone();
                a.sort();
                a == expected_actions
            }));
            raises.record(actual.is_some_and(|s| {
                s.min_raise_to == expected.min_raise_to && s.max_raise_to == expected.max_raise_to
            }));
        }
        let wanted_action = case
            .expected_state
            .as_ref()
            .is_some_and(|s| s.action_required);
        let got_action = actual.is_some_and(|s| s.action_required);
        true_positive += usize::from(wanted_action && got_action);
        false_positive += usize::from(!wanted_action && got_action);
        false_negative += usize::from(wanted_action && !got_action);
        let mut fresh = true;
        if let Some(f) = &case.freshness {
            stale_cases += 1;
            fresh = observation_is_current(
                &Ticket {
                    identity: case.identity.clone(),
                    generation: f.generation,
                    epoch: f.epoch,
                    captured_at_ms: 0,
                },
                Freshness {
                    identity: f.current_identity.as_ref(),
                    generation: f.current_generation,
                    epoch: f.current_epoch,
                    now_ms: f.age_ms,
                    fresh_capture: f.fresh_capture,
                    max_frame_age_ms: 5_000,
                },
            );
            stale_failures += usize::from(!f.expected_fresh && fresh);
        }
        let gate = gates.entry(&case.sequence).or_default();
        let permitted = if fresh {
            observation
                .as_ref()
                .and_then(|o| {
                    gate.observe(&case.identity, o, metadata, inspect_frame(&image))
                        .accepted_state
                })
                .filter(|s| s.action_required)
                .is_some_and(|s| pipeline.decide(&s).is_ok())
        } else {
            gate.break_consensus();
            false
        };
        emitted_decisions += usize::from(permitted);
        if case.recommendation_allowed {
            decision_recall.record(permitted);
        }
        if permitted
            && (!case.recommendation_allowed || case.expected_kind != ScreenKind::PokerTable)
        {
            critical += 1;
        }
        stale_failures += usize::from(!fresh && permitted);
        if observation.is_none() {
            gate.break_consensus();
        }

        latencies.push(start.elapsed().as_millis() as u64);
    }
    let rate = |num: usize, den: usize| {
        if den == 0 {
            Value::Null
        } else {
            json!(num as f64 / den as f64)
        }
    };
    let report = json!({
        "format":2,"event":"evaluation","source":manifest.source,"cases":manifest.cases.len(),
        "beta_acceptance":false,"evidence": if synthetic { "synthetic contract tests; NOT vision accuracy" } else { "local image inference; Windows lifecycle acceptance still separate" },
        "screen_kind_confusion_matrix":confusion,"lobby_to_table_false_positive_rate":lobby_fp.value(),
        "non_table_to_table_false_positive_rate":nontable_fp.value(),"card_extraction_exact_accuracy":cards.value(),
        "pot_exact_accuracy":pot.value(),"stack_exact_accuracy":stack.value(),"to_call_exact_accuracy":to_call.value(),
        "action_required_precision":rate(true_positive,true_positive+false_positive),
        "action_required_recall":rate(true_positive,true_positive+false_negative),
        "available_action_exact_accuracy":actions.value(),"raise_bound_exact_accuracy":raises.value(),
        "critical_actionable_false_positives":critical,"request_errors":errors,
        "recommendations_emitted":emitted_decisions,"eligible_decision_recall":decision_recall.value(),
        "stale_result_suppression_failures":if stale_cases == 0 { Value::Null } else { json!(stale_failures) },
        "stale_cases":stale_cases,"stale_evidence":"shared freshness predicate; concurrent runtime separately unit-tested",
        "latency_ms":{"p50":percentile(&mut latencies,50),"p95":percentile(&mut latencies,95),"p99":percentile(&mut latencies,99)},
        "coverage_tags":tags,"raw_images_saved":false,"raw_responses_saved":false,
    });
    live::emit(&report)?;
    if critical > 0 || stale_failures > 0 || errors > 0 {
        Err(fail(
            "visual evaluation has critical failures or server errors",
        ))
    } else {
        Ok(())
    }
}
