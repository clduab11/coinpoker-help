//! One-shot manually approved capture. No model, worker, parser, or decision path.

use std::collections::hash_map::RandomState;
use std::fs::{self, OpenOptions};
use std::hash::BuildHasher;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use ingest::capture::{CaptureSource, PlatformCapture, WindowInfo};
use ingest::recorder::{CaptureStamp, PrivateRecorder, RecorderConfig, RecorderStatus};
use serde::Deserialize;
use serde_json::json;

use crate::RunError;

const MAX_SECONDS: u64 = 600;
const MAX_FRAMES: u64 = 1_200;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Approval {
    version: u8,
    mode: String,
    operator_assertion: String,
    confirmed_at_unix_ms: u64,
    max_seconds: u64,
    max_frames: u64,
    source: WindowInfo,
}

fn fail(code: &str) -> RunError {
    RunError::Message(code.into())
}

fn unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |time| time.as_millis().min(u128::from(u64::MAX)) as u64)
}

fn valid_approval(approval: &Approval, now: u64) -> bool {
    approval.version == 1
        && approval.mode == "capture-only"
        && approval.operator_assertion == "I am seated and ready"
        && now
            .checked_sub(approval.confirmed_at_unix_ms)
            .is_some_and(|age| age <= 30_000)
        && (1..=MAX_SECONDS).contains(&approval.max_seconds)
        && (1..=MAX_FRAMES).contains(&approval.max_frames)
        && approval.source.process_id != 0
        && approval.source.hwnd != 0
        && approval
            .source
            .exe_name
            .eq_ignore_ascii_case("CoinPoker.exe")
        && approval
            .source
            .title
            .as_ref()
            .is_some_and(|title| !title.is_empty())
        && approval.source.on_screen
        && approval.source.width > 0
        && approval.source.height > 0
}

fn same_source(approved: &WindowInfo, current: &WindowInfo) -> bool {
    approved.hwnd == current.hwnd
        && approved.process_id == current.process_id
        && approved.exe_name.eq_ignore_ascii_case(&current.exe_name)
        && approved.title == current.title
        && current.on_screen
        && current.width > 0
        && current.height > 0
}

fn budget_reason(elapsed: u64, limit_ms: u64, status: RecorderStatus) -> Option<&'static str> {
    if elapsed >= limit_ms {
        return Some("duration-limit");
    }
    match status {
        RecorderStatus::Active => None,
        RecorderStatus::CountLimit => Some("frame-limit"),
        RecorderStatus::DiskLimit => Some("disk-limit"),
        _ => Some("recorder-failure"),
    }
}

fn emit_status(
    recorder: &PrivateRecorder,
    elapsed_ms: u64,
    reason: Option<&str>,
    capture_failures: u64,
) -> Result<(), RunError> {
    crate::live::emit(&json!({
        "event": "manual_capture", "version": 1, "mode": "capture-only",
        "elapsed_ms": elapsed_ms, "stop_reason": reason,
        "recording": recorder.handle().snapshot(),
        "capture_failures": capture_failures,
        "capture_directory": recorder.session_path(),
        "latest_frame": recorder.last_receipt(),
        "updated_at_unix_ms": unix_ms()
    }))
}

fn capture_loop(
    source: &mut impl CaptureSource,
    approval: &Approval,
    root: &Path,
    stop: &Path,
    elapsed: impl Fn() -> u64,
    mut wait: impl FnMut(),
) -> Result<(), RunError> {
    let mut recorder = PrivateRecorder::new(
        root,
        RecorderConfig {
            max_frames: approval.max_frames,
            ..RecorderConfig::default()
        },
        SystemTime::now(),
    )?;
    let mut selected: Option<WindowInfo> = None;
    let mut capture_failures = 0;
    let source_id = RandomState::new().hash_one((approval.source.process_id, approval.source.hwnd));
    let mut next_frame_ms = 0;
    let reason = loop {
        if stop.exists() {
            break "operator-stop";
        }
        if let Some(reason) = budget_reason(
            elapsed(),
            approval.max_seconds * 1_000,
            recorder.handle().snapshot().recording_status,
        ) {
            break reason;
        }
        let listing = match source.discover() {
            Ok(listing) => listing,
            Err(_) => break "source-unavailable",
        };
        let matches: Vec<_> = listing
            .windows
            .iter()
            .filter(|window| same_source(&approval.source, window))
            .collect();
        if matches.len() != 1 {
            break "source-changed";
        }
        let current = matches[0];
        if stop.exists() {
            break "operator-stop";
        }
        if elapsed() >= approval.max_seconds * 1_000 {
            break "duration-limit";
        }
        // A resize retains the approved identity and recorder, not a new budget.
        if selected.as_ref() != Some(current) {
            if source.select(current).is_err() {
                break "source-unavailable";
            }
            selected = Some(current.clone());
        }
        let capture_ms = elapsed();
        if stop.exists() {
            break "operator-stop";
        }
        if capture_ms >= approval.max_seconds * 1_000 {
            break "duration-limit";
        }
        if capture_ms >= next_frame_ms {
            let stamp = CaptureStamp {
                source_utc: SystemTime::now(),
                captured_at_monotonic_ms: capture_ms,
                generation: None,
                source_id: Some(source_id),
            };
            match source.capture() {
                Ok(frame) => {
                    let current = match source.discover() {
                        Ok(listing) => listing.windows,
                        Err(_) => break "source-unavailable",
                    };
                    if current
                        .iter()
                        .filter(|window| same_source(&approval.source, window))
                        .count()
                        != 1
                    {
                        break "source-changed";
                    }
                    // A slow acquisition must not become an after-budget saved frame.
                    if elapsed() >= approval.max_seconds * 1_000 || stop.exists() {
                        break if stop.exists() {
                            "operator-stop"
                        } else {
                            "duration-limit"
                        };
                    }
                    recorder.record(&frame, stamp);
                    next_frame_ms = capture_ms + 500;
                }
                Err(ingest::capture::CaptureError::StaleWindow { .. }) => {
                    capture_failures += 1;
                    let resized = match source.discover() {
                        Ok(listing) => listing.windows,
                        Err(_) => break "source-unavailable",
                    };
                    let matches: Vec<_> = resized
                        .iter()
                        .filter(|window| {
                            same_source(&approval.source, window)
                                && (window.width != current.width
                                    || window.height != current.height)
                        })
                        .collect();
                    if matches.len() != 1 {
                        break "source-changed";
                    }
                    if stop.exists() || elapsed() >= approval.max_seconds * 1_000 {
                        break if stop.exists() {
                            "operator-stop"
                        } else {
                            "duration-limit"
                        };
                    }
                    // Only a proven resize can rebuild WGC under this approval.
                    if source.select(matches[0]).is_err() {
                        break "source-unavailable";
                    }
                    selected = Some(matches[0].clone());
                }
                Err(_) => {
                    capture_failures += 1;
                    break "capture-failed";
                }
            }
        }
        if let Some(reason) = budget_reason(
            elapsed(),
            approval.max_seconds * 1_000,
            recorder.handle().snapshot().recording_status,
        ) {
            break reason;
        }
        emit_status(&recorder, elapsed(), None, capture_failures)?;
        wait();
    };
    source.reset();
    emit_status(&recorder, elapsed(), Some(reason), capture_failures)?;
    Ok(())
}

pub fn run(args: &[String]) -> Result<(), RunError> {
    if args.len() != 3 || args[1] != "--approval-file" {
        return Err(fail(
            "capture-only requires a fresh manual CLI approval file",
        ));
    }
    let root = std::env::current_dir()?;
    let path = PathBuf::from(&args[2]);
    let base = root.join(".local/laya/manual-capture");
    let parent = path
        .parent()
        .ok_or_else(|| fail("invalid-capture-approval"))?;
    if !path.is_absolute()
        || path.file_name().is_none_or(|name| name != "approval.json")
        || parent.parent() != Some(base.as_path())
    {
        return Err(fail("invalid-capture-approval"));
    }
    for ancestor in path.ancestors() {
        let metadata = fs::symlink_metadata(ancestor)?;
        if metadata.file_type().is_symlink() {
            return Err(fail("invalid-capture-approval"));
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return Err(fail("invalid-capture-approval"));
            }
        }
    }
    let mut bytes = Vec::new();
    fs::File::open(&path)?
        .take(16_385)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 16_384 {
        return Err(fail("invalid-capture-approval"));
    }
    let approval: Approval =
        serde_json::from_slice(&bytes).map_err(|_| fail("invalid-capture-approval"))?;
    if !valid_approval(&approval, unix_ms()) {
        return Err(fail("invalid-or-expired-capture-approval"));
    }
    let mut claimed = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(parent.join("claimed"))?;
    writeln!(claimed, "{}", unix_ms())?;
    claimed.sync_all()?;
    let started = Instant::now();
    capture_loop(
        &mut PlatformCapture::default(),
        &approval,
        &root,
        &parent.join("STOP"),
        || started.elapsed().as_millis().min(u128::from(u64::MAX)) as u64,
        || std::thread::sleep(Duration::from_millis(100)),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approval() -> Approval {
        Approval {
            version: 1,
            mode: "capture-only".into(),
            operator_assertion: "I am seated and ready".into(),
            confirmed_at_unix_ms: 1_000,
            max_seconds: 600,
            max_frames: 1_200,
            source: WindowInfo {
                hwnd: 11,
                process_id: 22,
                exe_name: "CoinPoker.exe".into(),
                title: Some("SYNTHETIC PRIVATE TITLE".into()),
                on_screen: true,
                width: 800,
                height: 600,
            },
        }
    }

    #[test]
    fn manual_capture_approval_is_fresh_strict_and_bounded() {
        let mut value = approval();
        assert!(valid_approval(&value, 31_000));
        assert!(!valid_approval(&value, 31_001));
        assert!(!valid_approval(&value, 999));
        value.max_frames = 1_201;
        assert!(!valid_approval(&value, 1_000));
        value.max_frames = 1_200;
        value.max_seconds = 601;
        assert!(!valid_approval(&value, 1_000));
        value.max_seconds = 600;
        value.operator_assertion = "ready".into();
        assert!(!valid_approval(&value, 1_000));
    }

    #[test]
    fn manual_capture_identity_allows_only_resize_not_replacement() {
        let expected = approval().source;
        let mut current = expected.clone();
        current.width = 900;
        assert!(same_source(&expected, &current));
        current.hwnd += 1;
        assert!(!same_source(&expected, &current));
        current = expected.clone();
        current.process_id += 1;
        assert!(!same_source(&expected, &current));
        current = expected.clone();
        current.title = Some("REPLACEMENT".into());
        assert!(!same_source(&expected, &current));
    }

    #[test]
    fn manual_capture_budget_expiry_is_terminal_without_capture() {
        assert_eq!(
            budget_reason(600_000, 600_000, RecorderStatus::Active),
            Some("duration-limit")
        );
        assert_eq!(
            budget_reason(0, 600_000, RecorderStatus::CountLimit),
            Some("frame-limit")
        );
        assert_eq!(
            budget_reason(0, 600_000, RecorderStatus::IoFailure),
            Some("recorder-failure")
        );
        assert_eq!(budget_reason(0, 600_000, RecorderStatus::Active), None);
        assert!(run(&["--capture-only".into(), "--enable-inference".into()]).is_err());
    }

    struct FakeSource {
        windows: Vec<WindowInfo>,
        captures: usize,
        selected: Vec<WindowInfo>,
        resize: bool,
        replace_after_capture: bool,
        stale_first: bool,
    }

    impl CaptureSource for FakeSource {
        fn discover(
            &mut self,
        ) -> Result<ingest::capture::DiscoverySnapshot, ingest::capture::CaptureError> {
            if self.resize && self.captures == 1 {
                self.windows[0].width = 900;
            }
            if self.replace_after_capture && self.captures > 0 {
                self.windows[0].hwnd += 1;
            }
            Ok(ingest::capture::DiscoverySnapshot {
                windows: self.windows.clone(),
                ..Default::default()
            })
        }
        fn select(&mut self, window: &WindowInfo) -> Result<(), ingest::capture::CaptureError> {
            self.selected.push(window.clone());
            Ok(())
        }
        fn capture(&mut self) -> Result<ingest::capture::Frame, ingest::capture::CaptureError> {
            self.captures += 1;
            if self.stale_first && self.captures == 1 {
                return Err(ingest::capture::CaptureError::StaleWindow {
                    hwnd: self.windows[0].hwnd,
                });
            }
            Ok(ingest::capture::Frame::new(2, 2, [1, 2, 3, 255].repeat(4)).unwrap())
        }
        fn reset(&mut self) {}
    }

    #[test]
    fn manual_capture_fake_source_count_resize_and_stop_are_one_shot() {
        let base = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .join(".local/laya/train/companion-20261011/capture/native-fixtures");
        for case in [
            "count",
            "resize",
            "replacement",
            "replacement_after",
            "stop",
            "time",
            "stale_unchanged",
            "stale_resize",
        ] {
            let root = base.join(format!(
                "{case}-{}",
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            fs::create_dir_all(&root).unwrap();
            let mut approval = approval();
            approval.max_frames = if case == "resize" { 2 } else { 1 };
            let mut source = FakeSource {
                windows: vec![approval.source.clone()],
                captures: 0,
                selected: vec![],
                resize: matches!(case, "resize" | "stale_resize"),
                replace_after_capture: case == "replacement_after",
                stale_first: case.starts_with("stale_"),
            };
            let clock = std::cell::Cell::new(if case == "time" { 600_000 } else { 0 });
            if case == "stop" {
                fs::write(root.join("STOP"), b"stop").unwrap();
            }
            if case == "replacement" {
                source.windows[0].hwnd += 1;
            }
            capture_loop(
                &mut source,
                &approval,
                &root,
                &root.join("STOP"),
                || clock.get(),
                || clock.set(clock.get() + 500),
            )
            .unwrap();
            assert_eq!(
                source.captures,
                match case {
                    "count" | "replacement_after" | "stale_unchanged" => 1,
                    "resize" | "stale_resize" => 2,
                    _ => 0,
                }
            );
            if matches!(case, "resize" | "stale_resize") {
                assert_eq!(
                    source
                        .selected
                        .iter()
                        .map(|window| window.width)
                        .collect::<Vec<_>>(),
                    [800, 900]
                );
            }
            assert_eq!(
                fs::read_dir(root.join(".local/captures")).unwrap().count(),
                1
            );
            if matches!(case, "replacement_after" | "stale_unchanged") {
                let session = fs::read_dir(root.join(".local/captures"))
                    .unwrap()
                    .next()
                    .unwrap()
                    .unwrap()
                    .path();
                assert_eq!(
                    fs::metadata(session.join("manifest.jsonl")).unwrap().len(),
                    0
                );
            }
        }
    }
}
