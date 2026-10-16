//! One-shot approval shared by capture-only and separately approved inference.

use std::collections::hash_map::RandomState;
use std::fs::{self, OpenOptions};
use std::hash::BuildHasher;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use ingest::capture::{CaptureError, CaptureSource, PlatformCapture, WindowInfo};
use ingest::recorder::{CaptureStamp, PrivateRecorder, RecorderConfig, RecorderStatus};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::RunError;

const MAX_SECONDS: u64 = 600;
const MAX_FRAMES: u64 = 1_200;

#[derive(Debug, Serialize)]
pub(crate) struct CaptureFailure {
    pub(crate) code: &'static str,
    pub(crate) detail: String,
}

// Explanatory only: these codes never decide source eligibility or recovery.
pub(crate) fn capture_failure(error: &CaptureError) -> CaptureFailure {
    let code = match error {
        CaptureError::Backend(message) => message
            .strip_prefix("selected window surface is obscured or ambiguous: cause=")
            .and_then(|cause| cause.split_once(" offender=("))
            .map_or("backend", |(cause, _)| match cause {
                "foreign-overlap" => "foreign-overlap",
                "popup-overlap" => "popup-overlap",
                "nonpositive-geometry" => "nonpositive-geometry",
                "popup-geometry" => "popup-geometry",
                "popup-limit" => "popup-limit",
                "center-mismatch" => "center-mismatch",
                "window-geometry-query-failed" => "window-geometry-query-failed",
                "cloak-query-failed" => "cloak-query-failed",
                "selected-not-enumerated" => "selected-not-enumerated",
                _ => "backend",
            }),
        CaptureError::UnsupportedPlatform => "unsupported-platform",
        CaptureError::UnsupportedWindowsVersion => "unsupported-windows-version",
        CaptureError::WindowNotFound(_) => "window-not-found",
        CaptureError::ConfigurationRequired => "configuration-required",
        CaptureError::AmbiguousWindows => "ambiguous-windows",
        CaptureError::StaleWindow { .. } => "stale-window",
        CaptureError::NoWindowSelected => "no-window-selected",
        CaptureError::PermissionDenied => "permission-denied",
    };
    let message = match error {
        CaptureError::Backend(message) => std::borrow::Cow::Borrowed(message.as_str()),
        _ => std::borrow::Cow::Owned(error.to_string()),
    };
    CaptureFailure {
        code,
        detail: message
            .chars()
            .take(1024)
            .map(|character| {
                if character.is_ascii_graphic() || character == ' ' {
                    character
                } else {
                    '?'
                }
            })
            .collect(),
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum SourcePolicy {
    #[default]
    Manual,
    AutomaticBounded,
    AutomaticSustained,
}

impl SourcePolicy {
    pub(crate) fn is_automatic(self) -> bool {
        matches!(self, Self::AutomaticBounded | Self::AutomaticSustained)
    }

    pub(crate) fn is_sustained(self) -> bool {
        self == Self::AutomaticSustained
    }

    pub(crate) fn approval_version(self) -> u8 {
        if self.is_sustained() {
            2
        } else {
            1
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Approval {
    version: u8,
    pub(crate) mode: String,
    operator_assertion: Option<String>,
    #[serde(default)]
    pub(crate) source_policy: SourcePolicy,
    automatic_assertion: Option<String>,
    confirmed_at_unix_ms: u64,
    pub(crate) max_seconds: u64,
    pub(crate) max_frames: u64,
    pub(crate) source: WindowInfo,
    inference_assertion: Option<String>,
    pub(crate) service_instance_id: Option<String>,
    #[serde(default)]
    pub(crate) experimental_bet_action: bool,
    #[serde(default)]
    pub(crate) cpu_visual_board: bool,
}

fn fail(code: &str) -> RunError {
    RunError::Message(code.into())
}

pub(crate) fn unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |time| time.as_millis().min(u128::from(u64::MAX)) as u64)
}

fn valid_approval(approval: &Approval, now: u64) -> bool {
    approval.version == approval.source_policy.approval_version()
        && (!approval.cpu_visual_board
            || approval.mode == "inference-enabled" && approval.source_policy.is_sustained())
        && (!approval.experimental_bet_action
            || approval.mode == "inference-enabled"
                && approval.source_policy.is_automatic()
                && !approval.source_policy.is_sustained())
        && match approval.mode.as_str() {
            "capture-only" => {
                approval.inference_assertion.is_none() && approval.service_instance_id.is_none()
            }
            "inference-enabled" => {
                approval.inference_assertion.as_deref()
                    == Some("USE INSTALLED IT1 FOR THIS SESSION")
                    && approval.service_instance_id.as_deref().is_some_and(|id| {
                        id.len() == 32
                            && id
                                .bytes()
                                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                    })
            }
            _ => false,
        }
        && match approval.source_policy {
            SourcePolicy::Manual => {
                // Older receipts may contain the seating assertion; new ones need none.
                matches!(
                    approval.operator_assertion.as_deref(),
                    None | Some("I am seated and ready")
                ) && approval.automatic_assertion.is_none()
            }
            SourcePolicy::AutomaticBounded => {
                approval.mode == "inference-enabled"
                    && approval.operator_assertion.is_none()
                    && approval.automatic_assertion.as_deref()
                        == Some("AUTHORIZE BOUNDED AUTOMATIC OBSERVATION")
            }
            SourcePolicy::AutomaticSustained => {
                approval.mode == "inference-enabled"
                    && !approval.experimental_bet_action
                    && approval.operator_assertion.is_none()
                    && approval.automatic_assertion.as_deref()
                        == Some("AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION")
            }
        }
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

pub(crate) fn same_source(approved: &WindowInfo, current: &WindowInfo) -> bool {
    approved.hwnd == current.hwnd
        && approved.process_id == current.process_id
        && approved.exe_name.eq_ignore_ascii_case(&current.exe_name)
        && approved.title == current.title
        && current.on_screen
        && current.width > 0
        && current.height > 0
}

pub(crate) fn find_approved_window<'a>(
    windows: &'a [WindowInfo],
    approved: &WindowInfo,
) -> Option<&'a WindowInfo> {
    let mut matches = windows
        .iter()
        .filter(|window| same_source(approved, window));
    let current = matches.next()?;
    matches.next().is_none().then_some(current)
}

pub(crate) fn budget_reason(
    elapsed: u64,
    limit_ms: u64,
    status: RecorderStatus,
) -> Option<&'static str> {
    if elapsed >= limit_ms {
        return Some("duration-limit");
    }
    match status {
        RecorderStatus::Active => None,
        RecorderStatus::DurationLimit => Some("duration-limit"),
        RecorderStatus::CountLimit => Some("frame-limit"),
        RecorderStatus::DiskLimit => Some("disk-limit"),
        _ => Some("recorder-failure"),
    }
}

pub(crate) fn recording_end_reason(status: RecorderStatus) -> Option<&'static str> {
    match status {
        RecorderStatus::DurationLimit => Some("duration-limit"),
        RecorderStatus::CountLimit => Some("frame-limit"),
        RecorderStatus::DiskLimit => Some("disk-limit"),
        _ => None,
    }
}

pub(crate) fn effective_recording_end_reason(
    reason: Option<&str>,
    status: RecorderStatus,
) -> Option<&str> {
    reason
        .filter(|reason| matches!(*reason, "duration-limit" | "frame-limit" | "disk-limit"))
        .or_else(|| recording_end_reason(status))
}

fn emit_status(
    recorder: &PrivateRecorder,
    elapsed_ms: u64,
    reason: Option<&str>,
    capture_failures: u64,
    capture_failure: Option<&CaptureFailure>,
    emit: &mut impl FnMut(&serde_json::Value) -> Result<(), RunError>,
) -> Result<(), RunError> {
    let snapshot = recorder.handle().snapshot();
    emit(&json!({
        "event": "manual_capture", "version": 1, "mode": "capture-only",
        "elapsed_ms": elapsed_ms, "stop_reason": reason,
        "recording_end_reason": effective_recording_end_reason(reason, snapshot.recording_status),
        "recording": snapshot,
        "capture_failures": capture_failures,
        "capture_failure": capture_failure,
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
    mut emit: impl FnMut(&serde_json::Value) -> Result<(), RunError>,
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
    let mut failure = None;
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
        let Some(current) = find_approved_window(&listing.windows, &approval.source) else {
            break "source-changed";
        };
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
                    if find_approved_window(&current, &approval.source).is_none() {
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
                Err(error @ CaptureError::StaleWindow { .. }) => {
                    capture_failures += 1;
                    failure = Some(capture_failure(&error));
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
                Err(error) => {
                    capture_failures += 1;
                    failure = Some(capture_failure(&error));
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
        emit_status(
            &recorder,
            elapsed(),
            None,
            capture_failures,
            failure.as_ref(),
            &mut emit,
        )?;
        wait();
    };
    source.reset();
    emit_status(
        &recorder,
        elapsed(),
        Some(reason),
        capture_failures,
        failure.as_ref(),
        &mut emit,
    )?;
    Ok(())
}

pub fn run(args: &[String]) -> Result<(), RunError> {
    let experimental = args.len() == 4 && args[1] == "--experimental-bet-action";
    let approval_index = if experimental { 2 } else { 1 };
    if !matches!(args.len(), 3 | 4)
        || args.len() == 4 && !experimental
        || args[approval_index] != "--approval-file"
        || !matches!(args[0].as_str(), "--capture-only" | "--manual-inference")
        || experimental && args[0] != "--manual-inference"
    {
        return Err(fail(
            "capture-only requires a fresh manual CLI approval file",
        ));
    }
    let root = std::env::current_dir()?;
    let path = PathBuf::from(&args[approval_index + 1]);
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
    let expected_mode = if args[0] == "--manual-inference" {
        "inference-enabled"
    } else {
        "capture-only"
    };
    if approval.mode != expected_mode
        || !valid_approval(&approval, unix_ms())
        || approval.experimental_bet_action != experimental
    {
        return Err(fail("invalid-or-expired-capture-approval"));
    }
    let mut claimed = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(parent.join("claimed"))?;
    writeln!(claimed, "{}", unix_ms())?;
    claimed.sync_all()?;
    if approval.mode == "inference-enabled" {
        return crate::manual_inference::run(approval, &root, &parent.join("STOP"), experimental);
    }
    let started = Instant::now();
    capture_loop(
        &mut PlatformCapture::default(),
        &approval,
        &root,
        &parent.join("STOP"),
        || started.elapsed().as_millis().min(u128::from(u64::MAX)) as u64,
        || std::thread::sleep(Duration::from_millis(100)),
        crate::live::emit,
    )
}

#[cfg(test)]
#[path = "manual_capture_tests.rs"]
mod tests;
