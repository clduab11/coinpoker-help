//! Explicit offline-only replay of a private, already-stopped capture receipt.
//! No capture backend, service connection, or model is constructed.

use std::cell::{Cell, RefCell};
use std::collections::VecDeque;
use std::fs;
use std::path::Path;
use std::rc::Rc;
use std::time::{Duration, Instant};

use ingest::capture::Frame;
use ingest::change_detect::{ChangeDetector, ChangeDetectorConfig, FrameTracker, StabilityConfig};
use ingest::laya::geometry;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Clone)]
struct SavedFrame {
    frame: Frame,
    captured: u64,
    utc: u64,
    done: u64,
}

fn runtime_submissions(
    samples: &[SavedFrame],
    stable_captures: u32,
    scoped: bool,
) -> Vec<ingest::runtime::Ticket> {
    use ingest::capture::{
        CaptureError, CaptureSource, CaptureTiming, DiscoverySnapshot, WindowInfo,
    };
    use ingest::discovery::DiscoveryConfig;
    use ingest::runtime::{
        Clock, Completion, InferenceFailure, InferenceJob, InferencePort, LiveRuntime,
        RuntimeConfig, Ticket,
    };
    struct Time(Cell<u64>);
    impl Clock for Time {
        fn now_ms(&self) -> u64 {
            self.0.get()
        }
    }
    struct SavedSource {
        frames: VecDeque<SavedFrame>,
        window: WindowInfo,
        time: Rc<Time>,
        timing: Option<CaptureTiming>,
    }
    fn window() -> WindowInfo {
        WindowInfo {
            hwnd: 1,
            process_id: 1,
            exe_name: "CoinPoker.exe".into(),
            title: Some("CoinPoker".into()),
            on_screen: true,
            width: 892,
            height: 680,
        }
    }
    impl CaptureSource for SavedSource {
        fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
            Ok(DiscoverySnapshot {
                windows: vec![self.window.clone()],
                ..Default::default()
            })
        }
        fn select(&mut self, selected: &WindowInfo) -> Result<(), CaptureError> {
            assert_eq!(selected, &self.window);
            Ok(())
        }
        fn capture(&mut self) -> Result<Frame, CaptureError> {
            let saved = self
                .frames
                .pop_front()
                .expect("only the supplied saved frames may be replayed");
            self.time.0.set(saved.done);
            self.timing = Some(CaptureTiming {
                monotonic_ms: saved.captured,
                utc_unix_ms: saved.utc,
                started: Instant::now() - Duration::from_millis(saved.done - saved.captured),
            });
            Ok(saved.frame)
        }
        fn reset(&mut self) {
            self.timing = None;
        }
        fn last_capture_timing(&self) -> Option<CaptureTiming> {
            self.timing
        }
    }
    struct SpyWorker {
        starts: Rc<RefCell<Vec<Ticket>>>,
        saved: Vec<SavedFrame>,
    }
    impl InferencePort<()> for SpyWorker {
        fn start(&mut self, job: InferenceJob) -> Result<(), InferenceFailure> {
            let source = self
                .saved
                .iter()
                .find(|saved| saved.captured == job.ticket.captured_at_ms)
                .unwrap();
            assert_eq!(
                job.frame.rgba, source.frame.rgba,
                "same already-recorded pixels"
            );
            assert_eq!(job.ticket.captured_at_unix_ms, Some(source.utc));
            self.starts.borrow_mut().push(job.ticket);
            Ok(())
        }
        fn try_complete(&mut self) -> Result<Option<Completion<()>>, InferenceFailure> {
            // Deliberately produce no predictions, synthetic or otherwise.
            Ok(None)
        }
    }
    let time = Rc::new(Time(Cell::new(0)));
    let starts = Rc::new(RefCell::new(Vec::new()));
    let mut runtime = LiveRuntime::new(
        SavedSource {
            frames: samples.to_vec().into(),
            window: WindowInfo {
                width: samples[0].frame.width,
                height: samples[0].frame.height,
                ..window()
            },
            time: time.clone(),
            timing: None,
        },
        SpyWorker {
            starts: starts.clone(),
            saved: samples.to_vec(),
        },
        DiscoveryConfig {
            exe_name: Some("CoinPoker.exe".into()),
            table_title: Some("CoinPoker".into()),
            ..Default::default()
        },
        RuntimeConfig {
            poll_ms: 500,
            stability: StabilityConfig {
                stable_captures,
                ..Default::default()
            },
            ..Default::default()
        },
    )
    .unwrap();
    if scoped {
        runtime.enable_activity_probe();
    }
    for sample in samples {
        time.0.set(sample.captured);
        runtime.tick(time.as_ref());
        assert!(runtime.active_count() <= 1 && runtime.queued_count() <= 1);
        assert!(runtime.take_activity_sample().is_none());
    }
    runtime.stop("offline-replay-complete");
    let result = starts.borrow().clone();
    result
}

#[test]
#[ignore = "requires the private stopped nine-frame capture; offline pixels only"]
fn stopped_saved_capture_stability_replay() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let source = root.join(".local/captures/utc-1791783199-453121700-practice");
    let stdout =
        root.join(".local/laya/manual-capture/640472df41444a20bf317bd63d4e3637/stdout.jsonl");
    let output =
        root.join(".local/laya/train/automatic-inference-20261012/native-runtime-diagnosis");
    fs::create_dir_all(&output).unwrap();
    let records: Vec<Value> = fs::read_to_string(source.join("manifest.jsonl"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let events: Vec<Value> = fs::read_to_string(stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(records.len(), 9);
    assert!(!events
        .iter()
        .any(|event| event["event"] == "perception_diagnostics" || event["state"] == "analyzing"));

    let mut tracker_three =
        FrameTracker::new(ChangeDetectorConfig::default(), StabilityConfig::default());
    let mut tracker_two = FrameTracker::new(
        ChangeDetectorConfig::default(),
        StabilityConfig {
            stable_captures: 2,
            ..Default::default()
        },
    );
    let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
    let names: Vec<_> = (1..=5)
        .map(|n| format!("board_slot_{n}"))
        .chain(std::iter::once("pot".into()))
        .chain((1..=6).map(|n| format!("seat_{n}_stack")))
        .collect();
    let mut previous: Option<Frame> = None;
    let mut rows = Vec::new();
    let mut samples = Vec::new();
    for record in &records {
        let index = record["frame_index"].as_u64().unwrap();
        let bytes = fs::read(source.join(format!("frame-{index:010}.png"))).unwrap();
        assert_eq!(
            format!("{:x}", Sha256::digest(&bytes)),
            record["sha256"].as_str().unwrap()
        );
        let image = image::load_from_memory(&bytes).unwrap().to_rgba8();
        let frame = Frame {
            width: image.width(),
            height: image.height(),
            rgba: image.into_raw(),
            ..Frame::default()
        };
        assert_eq!((frame.width, frame.height), (892, 680));
        let receipt = events
            .iter()
            .find(|event| {
                event["event"] == "manual_capture" && event["latest_frame"]["frame_index"] == index
            })
            .unwrap();
        let now = receipt["elapsed_ms"].as_u64().unwrap();
        let captured = record["captured_at_monotonic_ms"].as_u64().unwrap();
        samples.push(SavedFrame {
            frame: frame.clone(),
            captured,
            utc: record["source_utc_unix_ms"].as_u64().unwrap(),
            done: now,
        });
        let changed = detector.detect(&frame);
        let three = tracker_three.observe(&frame, now);
        let two = tracker_two.observe(&frame, now);
        let mut regions = serde_json::Map::new();
        let mut inside = vec![false; (frame.width * frame.height) as usize];
        for name in &names {
            let (a, b, c, d) = geometry::region_px(name, frame.width, frame.height).unwrap();
            let mut exact_changed = 0;
            let mut above_delta = 0;
            for y in b..d {
                for x in a..c {
                    let pixel = (y * frame.width + x) as usize;
                    inside[pixel] = true;
                    if let Some(previous) = &previous {
                        let start = pixel * 4;
                        let differences = previous.rgba[start..start + 4]
                            .iter()
                            .zip(&frame.rgba[start..start + 4]);
                        exact_changed += usize::from(differences.clone().any(|(a, b)| a != b));
                        above_delta +=
                            usize::from(differences.clone().any(|(a, b)| a.abs_diff(*b) > 8));
                    }
                }
            }
            regions.insert(name.clone(), json!({"bounds":[a,b,c,d],"exact_changed_pixels":exact_changed,"delta_over_8_pixels":above_delta}));
        }
        let mut total_exact = 0;
        let mut outside_exact = 0;
        if let Some(previous) = &previous {
            for (pixel, (a, b)) in previous
                .rgba
                .chunks_exact(4)
                .zip(frame.rgba.chunks_exact(4))
                .enumerate()
            {
                if a != b {
                    total_exact += 1;
                    outside_exact += usize::from(!inside[pixel]);
                }
            }
        }
        rows.push(json!({"frame":index,"captured_at_ms":captured,"progress_elapsed_ms":now,
            "capture_to_progress_ms":now - captured,"saved_gap_ms":record["previous_saved_gap_ms"],
            "changed":three.changed,"global_score":changed.score(),"suppressed_tiles":detector.suppressed_tiles(),
            "trigger_tiles":detector.trigger_tiles(),"stable_three":three.stable,"stable_two":two.stable,
            "exact_changed_pixels":total_exact,"outside_activity_regions_exact_changed_pixels":outside_exact,"regions":regions}));
        previous = Some(frame);
    }
    let stable_three: Vec<_> = rows
        .iter()
        .filter(|row| row["stable_three"] == true)
        .map(|row| row["frame"].clone())
        .collect();
    let stable_two: Vec<_> = rows
        .iter()
        .filter(|row| row["stable_two"] == true)
        .map(|row| row["frame"].clone())
        .collect();
    let submissions_three = runtime_submissions(&samples, 3, false);
    let submissions_two = runtime_submissions(&samples, 2, false);
    assert!(submissions_three.is_empty());
    assert_eq!(
        submissions_two.len(),
        1,
        "spy worker holds its one slot; it never returns predictions"
    );
    assert_eq!(submissions_two[0].captured_at_ms, 2_163);
    let report = json!({"kind":"offline-saved-real-pixel-replay","predictions":"none","source":source,
        "frames":9,"all_original_png_hashes_verified":true,"model_or_capture_backend_constructed":false,
        "original_change_config":ChangeDetectorConfig::default(),"original_stability":StabilityConfig::default(),
        "stable_three_frames":stable_three,"stable_two_frames":stable_two,
        "runtime_spy_submissions_three":submissions_three,"runtime_spy_submissions_two":submissions_two,
        "spy_worker":"holds one slot, returns no predictions; same-source timestamps and pixels asserted", "rows":rows});
    fs::write(
        output.join("saved-frame-stability.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
    assert!(
        stable_three.is_empty(),
        "reproduces actual zero-submission stability gate"
    );
    assert_eq!(stable_two, vec![json!(2), json!(6)]);
    println!(
        "SAVED_CAPTURE_REPLAY={} stable_three={stable_three:?} stable_two={stable_two:?}",
        output.join("saved-frame-stability.json").display()
    );
}

#[test]
#[ignore = "requires an explicitly supplied private stopped session; pixels/spy only, no predictions"]
fn stopped_saved_readout_scope_replay() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let session = root
        .join(std::env::var("COINPOKER_REPLAY_SESSION").unwrap())
        .canonicalize()
        .unwrap();
    assert!(session.starts_with(
        root.join(".local/laya/manual-capture")
            .canonicalize()
            .unwrap()
    ));
    let status: Value =
        serde_json::from_str(&fs::read_to_string(session.join("status.json")).unwrap()).unwrap();
    assert!(matches!(
        status["status"].as_str(),
        Some("failed" | "stopped" | "interrupted")
    ));
    let source = Path::new(status["capture_directory"].as_str().unwrap())
        .canonicalize()
        .unwrap();
    assert!(source.starts_with(root.join(".local/captures").canonicalize().unwrap()));
    let events: Vec<Value> = fs::read_to_string(session.join("stdout.jsonl"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let manifest: Vec<Value> = fs::read_to_string(source.join("manifest.jsonl"))
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .filter(|row| row["event"] == "frame")
        .collect();
    let stability = StabilityConfig {
        stable_captures: 2,
        ..Default::default()
    };
    let mut legacy = FrameTracker::new(ChangeDetectorConfig::default(), stability.clone());
    let mut per_region: Vec<_> = geometry::TABLE_READOUT_REGIONS
        .iter()
        .map(|_| FrameTracker::new(ChangeDetectorConfig::default(), stability.clone()))
        .collect();
    let mut rows = Vec::new();
    let mut samples = Vec::new();
    for row in &manifest {
        let index = row["frame_index"].as_u64().unwrap();
        let bytes = fs::read(source.join(format!("frame-{index:010}.png"))).unwrap();
        assert_eq!(
            format!("{:x}", Sha256::digest(&bytes)),
            row["sha256"].as_str().unwrap()
        );
        let image = image::load_from_memory(&bytes).unwrap().to_rgba8();
        let frame = Frame::new(image.width(), image.height(), image.into_raw()).unwrap();
        let captured = row["captured_at_monotonic_ms"].as_u64().unwrap();
        let done = events
            .iter()
            .find(|event| {
                event["event"] == "manual_capture" && event["latest_frame"]["frame_index"] == index
            })
            .unwrap()["elapsed_ms"]
            .as_u64()
            .unwrap();
        assert!(done >= captured);
        let legacy_eligible = legacy.observe(&frame, done).stable;
        let regions = geometry::readout_tracking_frames(&frame).unwrap();
        let stable_regions: Vec<_> = per_region
            .iter_mut()
            .zip(&regions)
            .zip(geometry::TABLE_READOUT_REGIONS)
            .filter_map(|((tracker, region), name)| {
                tracker.observe(region, done).stable.then_some(name)
            })
            .collect();
        rows.push(
            json!({"frame":index,"captured_at_ms":captured,"done_ms":done,
            "source_utc_unix_ms":row["source_utc_unix_ms"],"sha256":row["sha256"],
            "legacy_eligible":legacy_eligible,"stable_regions":stable_regions}),
        );
        samples.push(SavedFrame {
            frame,
            captured,
            utc: row["source_utc_unix_ms"].as_u64().unwrap(),
            done,
        });
    }
    assert!(samples
        .windows(2)
        .all(|pair| pair[1].captured > pair[0].captured && pair[1].utc > pair[0].utc));
    let legacy_eligible: Vec<_> = rows
        .iter()
        .filter(|row| row["legacy_eligible"] == true)
        .map(|row| row["frame"].clone())
        .collect();
    let scoped_eligible: Vec<_> = rows
        .iter()
        .filter(|row| !row["stable_regions"].as_array().unwrap().is_empty())
        .map(|row| row["frame"].clone())
        .collect();
    let legacy_starts = runtime_submissions(&samples, 2, false);
    let scoped_starts = runtime_submissions(&samples, 2, true);
    assert!(scoped_eligible.len() > legacy_eligible.len());
    assert_eq!(
        scoped_starts.len(),
        1,
        "busy spy cannot be preempted or duplicated"
    );
    assert!(scoped_starts[0].captured_at_ms < legacy_starts[0].captured_at_ms);
    let output = root.join(std::env::var("COINPOKER_REPLAY_OUTPUT").unwrap());
    assert!(output
        .parent()
        .unwrap()
        .canonicalize()
        .unwrap()
        .starts_with(root.join(".local").canonicalize().unwrap()));
    let result = json!({"classification":"saved-source-pixels-and-clock-spy-only",
        "frames_verified":samples.len(),"legacy_eligible":legacy_eligible,"scoped_eligible":scoped_eligible,
        "legacy_spy_starts":legacy_starts,"scoped_spy_starts":scoped_starts,
        "model_predictions":0,"gate_activation_claimed":false,"readings_published":0,"rows":rows});
    serde_json::to_writer_pretty(
        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output)
            .unwrap(),
        &result,
    )
    .unwrap();
    println!("Verified {} original PNG hashes and source clocks; eligibility {} -> {}; no model predictions or gate activation claimed",
        samples.len(), legacy_eligible.len(), scoped_eligible.len());
}
