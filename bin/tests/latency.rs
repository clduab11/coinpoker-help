//! Latency benchmark harness for the change-to-decision path.
//!
//! Measures the full pipeline from change detection to an emitted decision
//! view — VLM inference (mocked with a representative delay), parsing,
//! validation, 2-of-3 frame consensus, state-machine transition, equity
//! estimation, and decision — and asserts the p50 stays under one second.
//!
//! The mock VLM delay models a fast local MLX server; the harness exists to
//! catch pipeline regressions (consensus window growth, equity blowups,
//! encoding overhead), not to measure the model itself.

use std::time::{Duration, Instant};

use coinpoker::pipeline::Pipeline;
use ingest::capture::Frame;
use ingest::consensus::{ConsensusConfig, ConsensusOutcome, ConsensusTracker};
use ingest::parser::{parse_vlm_output, validate_game_state};
use ingest::state_machine::{StateMachine, TableEvent};
use ingest::vlm::{VlmBackend, VlmError, VlmOutput};
use ui::widgets::DecisionView;

const FLOP_STATE: &str = include_str!("fixtures/flop_state.json");

/// Latency a fast local VLM server adds per inference call.
const MOCK_VLM_DELAY: Duration = Duration::from_millis(200);

/// Samples for the percentile estimate.
const SAMPLES: usize = 20;

/// The p50 budget for change-to-decision.
const P50_BUDGET: Duration = Duration::from_secs(1);

/// A VLM backend that simulates a local server's response time.
struct MockVlm {
    delay: Duration,
}

impl VlmBackend for MockVlm {
    fn analyze(&self, _frame: &Frame, _prompt: &str) -> Result<VlmOutput, VlmError> {
        std::thread::sleep(self.delay);
        Ok(VlmOutput {
            text: FLOP_STATE.to_string(),
        })
    }
}

fn tiny_frame() -> Frame {
    Frame {
        width: 2,
        height: 2,
        rgba: vec![255; 2 * 2 * 4],
    }
}

/// The p`p`-th percentile of a sorted, non-empty sample set.
fn percentile(sorted: &[Duration], p: f64) -> Duration {
    assert!(!sorted.is_empty());
    let index = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[index.min(sorted.len() - 1)]
}

/// Run one change-to-decision cycle and return the elapsed latency.
fn cycle(backend: &MockVlm) -> Duration {
    let frame = tiny_frame();
    let prompt = ingest::prompt::build_analysis_prompt();
    let mut consensus =
        ConsensusTracker::try_new(ConsensusConfig::default()).expect("valid consensus config");
    let mut state_machine = StateMachine::new();
    let mut pipeline = Pipeline::new();

    let start = Instant::now();
    let mut decision: Option<DecisionView> = None;

    // A change was detected; the pipeline observes frames until 2-of-3
    // consensus confirms a state and a decision is produced.
    for _ in 0..3 {
        let output = backend.analyze(&frame, &prompt).expect("mock vlm succeeds");
        let state = parse_vlm_output(&output).expect("fixture parses");
        validate_game_state(&state).expect("fixture validates");
        if let ConsensusOutcome::Accepted(state) = consensus.observe(state) {
            if let TableEvent::ActionRequired(state) | TableEvent::StateChanged(state) =
                state_machine.update(state)
            {
                if state.action_required {
                    decision = Some(pipeline.decide(&state).expect("decision"));
                }
            }
        }
    }

    let latency = start.elapsed();
    let decision = decision.expect("a decision within the observation window");
    assert!(
        matches!(
            decision.action.as_str(),
            "check" | "raise" | "call" | "fold" | "allin"
        ),
        "unexpected action {:?}",
        decision.action
    );
    latency
}

#[test]
fn change_to_decision_p50_stays_under_one_second() {
    let backend = MockVlm {
        delay: MOCK_VLM_DELAY,
    };

    let mut latencies = Vec::with_capacity(SAMPLES);
    for _ in 0..SAMPLES {
        latencies.push(cycle(&backend));
    }
    latencies.sort();

    let p50 = percentile(&latencies, 0.5);
    let p99 = percentile(&latencies, 0.99);
    println!(
        "change-to-decision over {SAMPLES} samples: p50={p50:?} p99={p99:?} min={:?} max={:?}",
        latencies[0],
        latencies[SAMPLES - 1]
    );

    assert!(
        p50 < P50_BUDGET,
        "p50 change-to-decision latency {p50:?} exceeds the {P50_BUDGET:?} budget"
    );
}

#[test]
fn percentile_helper_is_exact_on_known_inputs() {
    let samples = [Duration::from_millis(1); 4];
    assert_eq!(percentile(&samples, 0.5), Duration::from_millis(1));

    let samples = [
        Duration::from_millis(1),
        Duration::from_millis(2),
        Duration::from_millis(3),
    ];
    assert_eq!(percentile(&samples, 0.0), Duration::from_millis(1));
    assert_eq!(percentile(&samples, 0.5), Duration::from_millis(2));
    assert_eq!(percentile(&samples, 1.0), Duration::from_millis(3));
}
