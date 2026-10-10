//! Opt-in private PNG evidence, independent of inference and publication leases.
//!
//! Only new `ROOT/.local/captures/utc-SECONDS-NANOSECONDS-practice` sessions are
//! writable. UTC names use the Unix epoch, not local time. No cleanup, overwrite,
//! resume, arbitrary destination, title, executable name, or player field exists.

use std::collections::hash_map::RandomState;
use std::fs::{self, File, Metadata, OpenOptions};
use std::hash::BuildHasher;
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use image::{codecs::png::PngEncoder, ExtendedColorType, ImageEncoder};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::capture::{CaptureError, CaptureSource, DiscoverySnapshot, Frame, WindowInfo};

pub const PRIVATE_CAPTURE_DIR: &str = ".local/captures";
pub const MAX_RECORD_FRAMES: u64 = 20_000;
pub const MAX_RECORD_BYTES: u64 = 2_147_483_648;
pub const MIN_RECORD_INTERVAL_MS: u64 = 250;
pub const MAX_RECORD_INTERVAL_MS: u64 = 60_000;
// Bounds encoder work and scratch memory even if a caller supplies a huge frame.
const MAX_RGBA_BYTES: usize = 64 * 1024 * 1024;
const MAX_PNG_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RecorderConfig {
    pub max_frames: u64,
    /// PNG plus manifest bytes, including unacknowledged bytes on a terminal error.
    pub max_bytes: u64,
    pub interval_ms: u64,
}

impl Default for RecorderConfig {
    fn default() -> Self {
        Self {
            max_frames: 7_200,
            max_bytes: 1_073_741_824,
            interval_ms: 500,
        }
    }
}

impl RecorderConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1..=MAX_RECORD_FRAMES).contains(&self.max_frames) {
            return Err("--record-max-frames must be 1..20000");
        }
        if !(1..=MAX_RECORD_BYTES).contains(&self.max_bytes) {
            return Err("--record-max-bytes must be 1..2147483648");
        }
        if !(MIN_RECORD_INTERVAL_MS..=MAX_RECORD_INTERVAL_MS).contains(&self.interval_ms) {
            return Err("--record-interval-ms must be 250..60000");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecorderStatus {
    Disabled,
    Active,
    CountLimit,
    DiskLimit,
    IoFailure,
}

/// Metadata only. Completeness means the eligible sampled prefix, not a final
/// session, every captured frame, validated game history, or a current reading.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct RecorderSnapshot {
    pub recording_enabled: bool,
    pub recorded_frames: u64,
    /// Bytes of durably acknowledged PNGs and their manifest rows only.
    pub recorded_bytes: u64,
    pub recording_status: RecorderStatus,
    pub recording_complete: bool,
}

impl Default for RecorderSnapshot {
    fn default() -> Self {
        Self {
            recording_enabled: false,
            recorded_frames: 0,
            recorded_bytes: 0,
            recording_status: RecorderStatus::Disabled,
            recording_complete: false,
        }
    }
}

#[derive(Clone, Default)]
pub struct RecorderHandle(Arc<Mutex<RecorderSnapshot>>);

impl RecorderHandle {
    pub fn snapshot(&self) -> RecorderSnapshot {
        match self.0.lock() {
            Ok(snapshot) => *snapshot,
            Err(poisoned) => RecorderSnapshot {
                recording_status: RecorderStatus::IoFailure,
                recording_complete: false,
                ..*poisoned.into_inner()
            },
        }
    }

    fn publish(&self, snapshot: RecorderSnapshot) {
        *self.0.lock().unwrap_or_else(|e| e.into_inner()) = snapshot;
    }
}

/// Supplied by the capture caller, before acquisition. `Frame` does not expose
/// the WGC driver's original timestamp. Never substitute encode/publication time.
#[derive(Debug, Clone, Copy)]
pub struct CaptureStamp {
    pub source_utc: SystemTime,
    pub captured_at_monotonic_ms: u64,
    /// Only set when actually known by the caller. The platform wrapper uses None.
    pub generation: Option<u64>,
    pub source_id: Option<u64>,
}

#[derive(Serialize)]
struct ManifestFrame {
    schema_version: u8,
    event: &'static str,
    timestamp_basis: &'static str,
    frame_index: u64,
    source_utc_unix_ms: u64,
    captured_at_monotonic_ms: u64,
    width: u32,
    height: u32,
    png_bytes: u64,
    sha256: String,
    generation: Option<u64>,
    source_id: Option<u64>,
}

pub struct PrivateRecorder {
    config: RecorderConfig,
    session: PathBuf,
    manifest: File,
    // Windows handles deny write/delete sharing on every directory component,
    // so a junction or renamed parent cannot redirect a later write.
    directories: Vec<File>,
    handle: RecorderHandle,
    frame_index: u64,
    last_seen_ms: Option<u64>,
    last_recorded_ms: Option<u64>,
}

fn unavailable() -> io::Error {
    io::Error::other("private recorder unavailable")
}

fn io_failure<T>(_: T) -> RecorderStatus {
    RecorderStatus::IoFailure
}

fn is_link(metadata: &Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        // Includes junctions and every other Windows reparse point.
        metadata.file_attributes() & 0x400 != 0 || metadata.file_type().is_symlink()
    }
    #[cfg(not(windows))]
    {
        metadata.file_type().is_symlink()
    }
}

fn directory_guard(path: &Path) -> io::Result<File> {
    let metadata = fs::symlink_metadata(path)?;
    if is_link(&metadata) || !metadata.is_dir() {
        return Err(unavailable());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // BACKUP_SEMANTICS | OPEN_REPARSE_POINT; FILE_SHARE_READ only.
        options
            .custom_flags(0x0200_0000 | 0x0020_0000)
            .share_mode(1);
    }
    let directory = options.open(path)?;
    let metadata = directory.metadata()?;
    if is_link(&metadata) || !metadata.is_dir() {
        return Err(unavailable());
    }
    Ok(directory)
}

fn create_file(path: &Path, append: bool) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.create_new(true);
    if append {
        options.append(true);
    } else {
        options.write(true);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // WRITE_THROUGH | OPEN_REPARSE_POINT; no write/delete sharing.
        options
            .custom_flags(0x8000_0000 | 0x0020_0000)
            .share_mode(1);
    }
    options.open(path)
}

impl PrivateRecorder {
    /// `root` must be an existing absolute plain-directory chain. Session UTC is
    /// a SystemTime, not a user-controlled path; a duplicate session is refused.
    /// Failure never removes directories, partial files, or previous evidence.
    pub fn new(root: &Path, config: RecorderConfig, session_utc: SystemTime) -> io::Result<Self> {
        config.validate().map_err(|_| unavailable())?;
        if !root.is_absolute()
            || root
                .components()
                .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
        {
            return Err(unavailable());
        }
        #[cfg(windows)]
        if root.components().any(|component| {
            matches!(component, Component::Prefix(prefix)
                if !matches!(prefix.kind(), std::path::Prefix::Disk(_) | std::path::Prefix::VerbatimDisk(_)))
        }) {
            return Err(unavailable());
        }
        let utc = session_utc
            .duration_since(UNIX_EPOCH)
            .map_err(|_| unavailable())?;
        let mut directories = Vec::new();
        let mut path = PathBuf::new();
        for component in root.components() {
            path.push(component.as_os_str());
            if matches!(component, Component::Normal(_) | Component::RootDir) {
                directories.push(directory_guard(&path)?);
            }
        }
        for component in [".local", "captures"] {
            path.push(component);
            match fs::create_dir(&path) {
                Ok(()) => {}
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(error),
            }
            directories.push(directory_guard(&path)?);
        }
        path.push(format!(
            "utc-{}-{:09}-practice",
            utc.as_secs(),
            utc.subsec_nanos()
        ));
        fs::create_dir(&path)?;
        directories.push(directory_guard(&path)?);
        let manifest = create_file(&path.join("manifest.jsonl"), true)?;
        manifest.sync_all()?;
        let handle = RecorderHandle::default();
        handle.publish(RecorderSnapshot {
            recording_enabled: true,
            recording_status: RecorderStatus::Active,
            recording_complete: true,
            ..RecorderSnapshot::default()
        });
        Ok(Self {
            config,
            session: path,
            manifest,
            directories,
            handle,
            frame_index: 0,
            last_seen_ms: None,
            last_recorded_ms: None,
        })
    }

    pub fn handle(&self) -> RecorderHandle {
        self.handle.clone()
    }

    fn stop(&self, status: RecorderStatus) {
        self.handle.publish(RecorderSnapshot {
            recording_status: status,
            recording_complete: false,
            ..self.handle.snapshot()
        });
    }

    /// Borrow one frame; keep neither pixels nor encoded PNGs after this call.
    /// Counters advance only after frame flush/sync AND append-only manifest sync.
    pub fn record(&mut self, frame: &Frame, stamp: CaptureStamp) {
        if self.handle.snapshot().recording_status != RecorderStatus::Active {
            return;
        }
        let Some(index) = self.frame_index.checked_add(1) else {
            self.stop(RecorderStatus::IoFailure);
            return;
        };
        self.frame_index = index;
        if self
            .last_seen_ms
            .is_some_and(|last| stamp.captured_at_monotonic_ms < last)
        {
            self.stop(RecorderStatus::IoFailure);
            return;
        }
        self.last_seen_ms = Some(stamp.captured_at_monotonic_ms);
        if self
            .last_recorded_ms
            .is_some_and(|last| stamp.captured_at_monotonic_ms - last < self.config.interval_ms)
        {
            return;
        }
        match self.commit_frame(frame, stamp) {
            Ok(bytes) => {
                self.last_recorded_ms = Some(stamp.captured_at_monotonic_ms);
                let previous = self.handle.snapshot();
                let count_limit = previous.recorded_frames + 1 == self.config.max_frames;
                let disk_limit = previous.recorded_bytes + bytes == self.config.max_bytes;
                self.handle.publish(RecorderSnapshot {
                    recorded_frames: previous.recorded_frames + 1,
                    recorded_bytes: previous.recorded_bytes + bytes,
                    recording_status: if count_limit {
                        RecorderStatus::CountLimit
                    } else if disk_limit {
                        RecorderStatus::DiskLimit
                    } else {
                        RecorderStatus::Active
                    },
                    recording_complete: !count_limit && !disk_limit,
                    ..previous
                });
            }
            Err(status) => self.stop(status),
        }
    }

    fn commit_frame(&mut self, frame: &Frame, stamp: CaptureStamp) -> Result<u64, RecorderStatus> {
        frame.validate().map_err(io_failure)?;
        if frame.width == 0 || frame.height == 0 || frame.rgba.len() > MAX_RGBA_BYTES {
            return Err(RecorderStatus::IoFailure);
        }
        let source_utc_unix_ms = stamp
            .source_utc
            .duration_since(UNIX_EPOCH)
            .ok()
            .and_then(|time| u64::try_from(time.as_millis()).ok())
            .ok_or(RecorderStatus::IoFailure)?;
        let remaining = self.config.max_bytes - self.handle.snapshot().recorded_bytes;
        // Measure/hash into a sink first. A disk cap never creates an oversized
        // orphan, and streaming avoids an extra full PNG/RGBA buffer or queue.
        let mut probe = BoundedHashWriter::new(io::sink(), remaining.min(MAX_PNG_BYTES));
        if encode(frame, &mut probe).is_err() {
            return Err(if probe.limit_hit {
                RecorderStatus::DiskLimit
            } else {
                RecorderStatus::IoFailure
            });
        }
        let hash = format!("{:x}", probe.hasher.clone().finalize());
        let row = ManifestFrame {
            schema_version: 1,
            event: "frame",
            timestamp_basis: "capture_call_start",
            frame_index: self.frame_index,
            source_utc_unix_ms,
            captured_at_monotonic_ms: stamp.captured_at_monotonic_ms,
            width: frame.width,
            height: frame.height,
            png_bytes: probe.bytes,
            sha256: hash.clone(),
            generation: stamp.generation,
            source_id: stamp.source_id,
        };
        let mut line = serde_json::to_vec(&row).map_err(io_failure)?;
        line.push(b'\n');
        let bytes = probe.bytes + line.len() as u64;
        if bytes > remaining {
            return Err(RecorderStatus::DiskLimit);
        }
        for directory in &self.directories {
            let metadata = directory.metadata().map_err(io_failure)?;
            if is_link(&metadata) || !metadata.is_dir() {
                return Err(RecorderStatus::IoFailure);
            }
        }
        // Recheck all ancestors before each write, including on non-Windows.
        for ancestor in self.session.ancestors() {
            let metadata = fs::symlink_metadata(ancestor).map_err(io_failure)?;
            if is_link(&metadata) || !metadata.is_dir() {
                return Err(RecorderStatus::IoFailure);
            }
        }
        let file = create_file(
            &self
                .session
                .join(format!("frame-{:010}.png", self.frame_index)),
            false,
        )
        .map_err(io_failure)?;
        let mut writer = BoundedHashWriter::new(file, probe.bytes);
        encode(frame, &mut writer).map_err(io_failure)?;
        writer.flush().map_err(io_failure)?;
        writer.inner.sync_all().map_err(io_failure)?;
        if writer.bytes != probe.bytes || format!("{:x}", writer.hasher.finalize()) != hash {
            return Err(RecorderStatus::IoFailure);
        }
        #[cfg(not(windows))]
        self.directories
            .last()
            .ok_or(RecorderStatus::IoFailure)?
            .sync_all()
            .map_err(io_failure)?;
        // A partial trailing row on failure stays in place; prior durable rows
        // and images are never truncated, deleted, reused, or falsely counted.
        self.manifest.write_all(&line).map_err(io_failure)?;
        self.manifest.flush().map_err(io_failure)?;
        self.manifest.sync_all().map_err(io_failure)?;
        Ok(bytes)
    }
}

fn encode(frame: &Frame, writer: &mut impl Write) -> image::ImageResult<()> {
    PngEncoder::new(writer).write_image(
        &frame.rgba,
        frame.width,
        frame.height,
        ExtendedColorType::Rgba8,
    )
}

struct BoundedHashWriter<W> {
    inner: W,
    hasher: Sha256,
    bytes: u64,
    limit: u64,
    limit_hit: bool,
}

impl<W> BoundedHashWriter<W> {
    fn new(inner: W, limit: u64) -> Self {
        Self {
            inner,
            hasher: Sha256::new(),
            bytes: 0,
            limit,
            limit_hit: false,
        }
    }
}

impl<W: Write> Write for BoundedHashWriter<W> {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        if buffer.len() as u64 > self.limit - self.bytes {
            self.limit_hit = true;
            return Err(unavailable());
        }
        let written = self.inner.write(buffer)?;
        self.hasher.update(&buffer[..written]);
        self.bytes += written as u64;
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

/// Decorator only: recording failure is metadata, never a replacement capture
/// result. No inference/validation/lease behavior is changed or bypassed.
pub struct RecordingCapturer<S> {
    inner: S,
    recorder: Option<PrivateRecorder>,
    handle: RecorderHandle,
    started: Instant,
    source_ids: RandomState,
    selected_source: Option<u64>,
}

impl<S> RecordingCapturer<S> {
    pub fn new(
        inner: S,
        root: &Path,
        config: Option<RecorderConfig>,
        session_utc: SystemTime,
    ) -> Self {
        let recorder = config.map(|config| PrivateRecorder::new(root, config, session_utc));
        let (recorder, handle) = match recorder {
            None => (None, RecorderHandle::default()),
            Some(Ok(recorder)) => {
                let handle = recorder.handle();
                (Some(recorder), handle)
            }
            Some(Err(_)) => {
                let handle = RecorderHandle::default();
                handle.publish(RecorderSnapshot {
                    recording_enabled: true,
                    recording_status: RecorderStatus::IoFailure,
                    ..RecorderSnapshot::default()
                });
                (None, handle)
            }
        };
        Self {
            inner,
            recorder,
            handle,
            started: Instant::now(),
            source_ids: RandomState::new(),
            selected_source: None,
        }
    }

    pub fn recording(&self) -> RecorderHandle {
        self.handle.clone()
    }
}

impl<S: CaptureSource> CaptureSource for RecordingCapturer<S> {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        self.inner.discover()
    }

    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError> {
        self.selected_source = None;
        self.inner.select(window)?;
        self.selected_source = Some(self.source_ids.hash_one((window.process_id, window.hwnd)));
        Ok(())
    }

    fn capture(&mut self) -> Result<Frame, CaptureError> {
        let stamp = CaptureStamp {
            source_utc: SystemTime::now(),
            captured_at_monotonic_ms: self.started.elapsed().as_millis().min(u64::MAX as u128)
                as u64,
            generation: None,
            source_id: self.selected_source,
        };
        let frame = self.inner.capture()?;
        if let Some(recorder) = &mut self.recorder {
            recorder.record(&frame, stamp);
        }
        Ok(frame)
    }

    fn reset(&mut self) {
        self.selected_source = None;
        self.inner.reset();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    fn temp_root() -> tempfile::TempDir {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        tempfile::Builder::new()
            .prefix("recorder-b-synthetic-")
            .tempdir_in(root.join(".local/laya/train/checkpoint-b-20261010"))
            .unwrap()
    }

    fn utc() -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(1_791_642_000) + Duration::from_nanos(123)
    }

    fn stamp(ms: u64) -> CaptureStamp {
        CaptureStamp {
            source_utc: utc(),
            captured_at_monotonic_ms: ms,
            generation: None,
            source_id: Some(42),
        }
    }

    fn frame() -> Frame {
        Frame::new(2, 2, [19, 31, 73, 255].repeat(4)).unwrap()
    }

    fn recorder(root: &tempfile::TempDir, config: RecorderConfig) -> PrivateRecorder {
        PrivateRecorder::new(root.path(), config, utc()).unwrap()
    }

    fn rows(recorder: &PrivateRecorder) -> Vec<serde_json::Value> {
        fs::read_to_string(recorder.session.join("manifest.jsonl"))
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }

    #[test]
    fn recorder_png_hash_manifest_and_durable_counters_are_exact() {
        let root = temp_root();
        let mut recorder = recorder(&root, RecorderConfig::default());
        let pixels = frame();
        recorder.record(
            &pixels,
            CaptureStamp {
                generation: Some(9),
                ..stamp(100)
            },
        );
        let row = &rows(&recorder)[0];
        let png = fs::read(recorder.session.join("frame-0000000001.png")).unwrap();
        assert_eq!(&png[..8], b"\x89PNG\r\n\x1a\n");
        assert_eq!(
            image::load_from_memory(&png).unwrap().to_rgba8().as_raw(),
            &pixels.rgba
        );
        assert_eq!(row["sha256"], format!("{:x}", Sha256::digest(&png)));
        assert_eq!(row["png_bytes"], png.len() as u64);
        assert_eq!(row["width"], 2);
        assert_eq!(row["height"], 2);
        assert_eq!(row["frame_index"], 1);
        assert_eq!(row["source_utc_unix_ms"], 1_791_642_000_000u64);
        assert_eq!(row["captured_at_monotonic_ms"], 100);
        assert_eq!(row["timestamp_basis"], "capture_call_start");
        assert_eq!(row["generation"], 9);
        assert_eq!(row["source_id"], 42);
        let snapshot = recorder.handle().snapshot();
        assert_eq!(snapshot.recorded_frames, 1);
        assert_eq!(
            snapshot.recorded_bytes,
            png.len() as u64 + recorder.manifest.metadata().unwrap().len()
        );
        assert!(snapshot.recording_complete && snapshot.recording_enabled);
        assert_eq!(snapshot.recording_status, RecorderStatus::Active);
    }

    #[test]
    fn recorder_sampling_preserves_source_indices_and_timestamps() {
        let root = temp_root();
        let mut recorder = recorder(
            &root,
            RecorderConfig {
                interval_ms: 1_000,
                ..RecorderConfig::default()
            },
        );
        for ms in [100, 140, 999, 1_099, 1_100] {
            recorder.record(&frame(), stamp(ms));
        }
        let rows = rows(&recorder);
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0]["frame_index"], 1);
        assert_eq!(rows[1]["frame_index"], 5);
        assert_eq!(rows[1]["captured_at_monotonic_ms"], 1_100);
        assert!(rows[1]["generation"].is_null());
        assert!(!recorder.session.join("frame-0000000002.png").exists());
        assert_eq!(recorder.handle().snapshot().recorded_frames, 2);
    }

    #[test]
    fn recorder_count_cap_is_terminal_and_preserves_evidence() {
        let root = temp_root();
        let mut recorder = recorder(
            &root,
            RecorderConfig {
                max_frames: 1,
                ..RecorderConfig::default()
            },
        );
        recorder.record(&frame(), stamp(0));
        let prefix = fs::read(recorder.session.join("manifest.jsonl")).unwrap();
        let image = fs::read(recorder.session.join("frame-0000000001.png")).unwrap();
        for ms in [500, 1_000, 20_000] {
            recorder.record(&frame(), stamp(ms));
        }
        let snapshot = recorder.handle().snapshot();
        assert_eq!(snapshot.recording_status, RecorderStatus::CountLimit);
        assert_eq!(snapshot.recorded_frames, 1);
        assert!(!snapshot.recording_complete);
        assert_eq!(
            fs::read(recorder.session.join("manifest.jsonl")).unwrap(),
            prefix
        );
        assert_eq!(
            fs::read(recorder.session.join("frame-0000000001.png")).unwrap(),
            image
        );
        assert!(!recorder.session.join("frame-0000000002.png").exists());
    }

    #[test]
    fn recorder_disk_cap_includes_manifest_and_never_writes_an_oversized_frame() {
        let template_root = temp_root();
        let mut template = recorder(&template_root, RecorderConfig::default());
        template.record(&frame(), stamp(0));
        let bytes = template.handle().snapshot().recorded_bytes;
        let root = temp_root();
        let mut recorder = recorder(
            &root,
            RecorderConfig {
                max_bytes: bytes + 1,
                ..RecorderConfig::default()
            },
        );
        recorder.record(&frame(), stamp(0));
        let prefix = fs::read(recorder.session.join("manifest.jsonl")).unwrap();
        recorder.record(&frame(), stamp(500));
        recorder.record(&frame(), stamp(1_000));
        let snapshot = recorder.handle().snapshot();
        assert_eq!(snapshot.recording_status, RecorderStatus::DiskLimit);
        assert_eq!(snapshot.recorded_frames, 1);
        assert_eq!(snapshot.recorded_bytes, bytes);
        assert!(!snapshot.recording_complete);
        assert_eq!(
            fs::read(recorder.session.join("manifest.jsonl")).unwrap(),
            prefix
        );
        assert!(!recorder.session.join("frame-0000000002.png").exists());
        assert!(
            fs::read_dir(&recorder.session)
                .unwrap()
                .map(|entry| entry.unwrap().metadata().unwrap().len())
                .sum::<u64>()
                <= bytes + 1
        );
    }

    #[test]
    fn recorder_never_reuses_a_session_or_overwrites_a_frame() {
        let root = temp_root();
        let mut first = recorder(&root, RecorderConfig::default());
        first.record(&frame(), stamp(0));
        let prefix = fs::read(first.session.join("manifest.jsonl")).unwrap();
        assert!(PrivateRecorder::new(root.path(), RecorderConfig::default(), utc()).is_err());
        let second = PrivateRecorder::new(
            root.path(),
            RecorderConfig::default(),
            utc() + Duration::from_nanos(100),
        )
        .unwrap();
        assert_ne!(first.session, second.session);
        assert!(second
            .session
            .starts_with(root.path().join(PRIVATE_CAPTURE_DIR)));
        let collision = first.session.join("frame-0000000002.png");
        let mut existing = create_file(&collision, false).unwrap();
        existing.write_all(b"SYNTHETIC_EXISTING_EVIDENCE").unwrap();
        existing.sync_all().unwrap();
        first.record(&frame(), stamp(500));
        assert_eq!(
            first.handle().snapshot().recording_status,
            RecorderStatus::IoFailure
        );
        assert_eq!(fs::read(collision).unwrap(), b"SYNTHETIC_EXISTING_EVIDENCE");
        assert_eq!(
            fs::read(first.session.join("manifest.jsonl")).unwrap(),
            prefix
        );
        assert_eq!(first.handle().snapshot().recorded_frames, 1);
    }

    #[test]
    fn recorder_manifest_failure_keeps_the_acknowledged_prefix_and_orphan() {
        let root = temp_root();
        let mut recorder = recorder(&root, RecorderConfig::default());
        recorder.record(&frame(), stamp(0));
        let acknowledged = recorder.handle().snapshot();
        let prefix = fs::read(recorder.session.join("manifest.jsonl")).unwrap();
        // Replace only this synthetic test handle with a read-only handle.
        recorder.manifest = File::open(recorder.session.join("manifest.jsonl")).unwrap();
        recorder.record(&frame(), stamp(500));
        let snapshot = recorder.handle().snapshot();
        assert_eq!(snapshot.recording_status, RecorderStatus::IoFailure);
        assert!(!snapshot.recording_complete);
        assert_eq!(snapshot.recorded_frames, acknowledged.recorded_frames);
        assert_eq!(snapshot.recorded_bytes, acknowledged.recorded_bytes);
        assert_eq!(
            fs::read(recorder.session.join("manifest.jsonl")).unwrap(),
            prefix
        );
        assert!(recorder.session.join("frame-0000000002.png").exists());
        recorder.record(&frame(), stamp(1_000));
        assert!(!recorder.session.join("frame-0000000003.png").exists());
    }

    #[test]
    fn recorder_bad_bounds_roots_and_frames_fail_closed_without_reset() {
        let root = temp_root();
        for config in [
            RecorderConfig {
                max_frames: 0,
                ..RecorderConfig::default()
            },
            RecorderConfig {
                max_frames: MAX_RECORD_FRAMES + 1,
                ..RecorderConfig::default()
            },
            RecorderConfig {
                max_bytes: 0,
                ..RecorderConfig::default()
            },
            RecorderConfig {
                max_bytes: MAX_RECORD_BYTES + 1,
                ..RecorderConfig::default()
            },
            RecorderConfig {
                interval_ms: 249,
                ..RecorderConfig::default()
            },
            RecorderConfig {
                interval_ms: 60_001,
                ..RecorderConfig::default()
            },
        ] {
            assert!(PrivateRecorder::new(root.path(), config, utc()).is_err());
        }
        for path in [
            PathBuf::from("."),
            root.path().join("../escape"),
            root.path().join("missing"),
        ] {
            assert!(PrivateRecorder::new(&path, RecorderConfig::default(), utc()).is_err());
        }
        assert!(PrivateRecorder::new(
            root.path(),
            RecorderConfig::default(),
            UNIX_EPOCH - Duration::from_secs(1)
        )
        .is_err());
        assert!(!root.path().join(".local").exists());
        let mut recorder = recorder(&root, RecorderConfig::default());
        recorder.record(&frame(), stamp(500));
        recorder.record(&frame(), stamp(499));
        assert_eq!(
            recorder.handle().snapshot().recording_status,
            RecorderStatus::IoFailure
        );
        assert_eq!(recorder.handle().snapshot().recorded_frames, 1);
        let zero_root = temp_root();
        let mut zero =
            PrivateRecorder::new(zero_root.path(), RecorderConfig::default(), utc()).unwrap();
        zero.record(
            &Frame {
                width: 0,
                height: 0,
                rgba: vec![],
            },
            stamp(0),
        );
        assert_eq!(zero.handle().snapshot().recorded_frames, 0);
        assert_eq!(
            zero.handle().snapshot().recording_status,
            RecorderStatus::IoFailure
        );
    }

    #[test]
    fn recorder_streaming_scratch_is_bounded_and_frames_are_not_retained() {
        let root = temp_root();
        let mut recorder = recorder(&root, RecorderConfig::default());
        let pixels = frame();
        let pointer = pixels.rgba.as_ptr();
        let size = std::mem::size_of_val(&recorder);
        let capacity = recorder.directories.capacity();
        for index in 0..200 {
            recorder.record(&pixels, stamp(index * 500));
        }
        assert_eq!(pixels.rgba.as_ptr(), pointer);
        assert_eq!(recorder.directories.capacity(), capacity);
        assert_eq!(std::mem::size_of_val(&recorder), size);
        assert!(size < 1_024);
        assert_eq!(recorder.handle().snapshot().recorded_frames, 200);
        let mut writer = BoundedHashWriter::new(io::sink(), 4);
        writer.write_all(b"RGBA").unwrap();
        assert!(writer.write_all(b"TOO_MANY").is_err());
        assert_eq!(writer.bytes, 4);
        assert!(writer.limit_hit);
    }

    struct SyntheticSource(Option<Frame>);
    impl CaptureSource for SyntheticSource {
        fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
            Ok(DiscoverySnapshot::default())
        }
        fn select(&mut self, _: &WindowInfo) -> Result<(), CaptureError> {
            Ok(())
        }
        fn capture(&mut self) -> Result<Frame, CaptureError> {
            self.0.take().ok_or(CaptureError::NoWindowSelected)
        }
        fn reset(&mut self) {}
    }

    #[test]
    fn recorder_wrapper_privacy_failure_continuation_and_disabled_no_io() {
        let root = temp_root();
        let pixels = frame();
        let pointer = pixels.rgba.as_ptr();
        let mut source = RecordingCapturer::new(
            SyntheticSource(Some(pixels)),
            root.path(),
            Some(RecorderConfig::default()),
            utc(),
        );
        let selected = WindowInfo {
            hwnd: 1234,
            process_id: 5678,
            exe_name: "PRIVATE_EXECUTABLE_SENTINEL.exe".into(),
            title: Some("PRIVATE_TITLE_PLAYER_SENTINEL".into()),
            on_screen: true,
            width: 2,
            height: 2,
        };
        source.select(&selected).unwrap();
        assert_eq!(source.capture().unwrap().rgba.as_ptr(), pointer);
        let recorder = source.recorder.as_ref().unwrap();
        let text = fs::read_to_string(recorder.session.join("manifest.jsonl")).unwrap();
        assert!(
            !text.contains("PRIVATE_") && !text.contains("exe_name") && !text.contains("title")
        );
        assert!(!text.contains(&root.path().to_string_lossy().to_string()));
        let row = &rows(recorder)[0];
        assert!(row["generation"].is_null());
        assert!(row["source_id"].as_u64().is_some());
        assert_ne!(row["source_id"].as_u64(), Some(1234));
        let bad_root = root.path().join("missing");
        let mut failed = RecordingCapturer::new(
            SyntheticSource(Some(frame())),
            &bad_root,
            Some(RecorderConfig::default()),
            utc(),
        );
        assert!(failed.capture().is_ok());
        assert_eq!(
            failed.recording().snapshot().recording_status,
            RecorderStatus::IoFailure
        );
        assert!(failed.recording().snapshot().recording_enabled);
        assert!(!failed.recording().snapshot().recording_complete);
        let disabled_root = temp_root();
        let mut disabled = RecordingCapturer::new(
            SyntheticSource(Some(frame())),
            disabled_root.path(),
            None,
            utc(),
        );
        assert!(disabled.capture().is_ok());
        assert_eq!(disabled.recording().snapshot(), RecorderSnapshot::default());
        assert!(!disabled_root.path().join(".local").exists());
    }

    #[test]
    fn recorder_wrapper_returns_original_frames_after_count_or_write_failure() {
        let capped_root = temp_root();
        let mut capped = RecordingCapturer::new(
            SyntheticSource(Some(frame())),
            capped_root.path(),
            Some(RecorderConfig {
                max_frames: 1,
                ..RecorderConfig::default()
            }),
            utc(),
        );
        assert!(capped.capture().is_ok());
        let capped_snapshot = capped.recording().snapshot();
        assert_eq!(capped_snapshot.recording_status, RecorderStatus::CountLimit);
        capped.inner.0 = Some(frame());
        assert!(capped.capture().is_ok());
        assert_eq!(capped.recording().snapshot(), capped_snapshot);

        let failed_root = temp_root();
        let mut failed = RecordingCapturer::new(
            SyntheticSource(Some(frame())),
            failed_root.path(),
            Some(RecorderConfig::default()),
            utc(),
        );
        assert!(failed.capture().is_ok());
        let recorder = failed.recorder.as_mut().unwrap();
        let prefix = fs::read(recorder.session.join("manifest.jsonl")).unwrap();
        recorder.manifest = File::open(recorder.session.join("manifest.jsonl")).unwrap();
        failed.started = Instant::now() - Duration::from_secs(1);
        let pixels = frame();
        let pointer = pixels.rgba.as_ptr();
        failed.inner.0 = Some(pixels);
        assert_eq!(failed.capture().unwrap().rgba.as_ptr(), pointer);
        let snapshot = failed.recording().snapshot();
        assert_eq!(snapshot.recording_status, RecorderStatus::IoFailure);
        assert_eq!(snapshot.recorded_frames, 1);
        assert!(!snapshot.recording_complete);
        assert_eq!(
            fs::read(
                failed
                    .recorder
                    .as_ref()
                    .unwrap()
                    .session
                    .join("manifest.jsonl")
            )
            .unwrap(),
            prefix
        );
    }

    #[test]
    fn recorder_rejects_symlinks_and_windows_junctions_when_supported() {
        let root = temp_root();
        let target = root.path().join("synthetic-target");
        fs::create_dir(&target).unwrap();
        let link = root.path().join(".local");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&target, &link).unwrap();
        #[cfg(windows)]
        if let Err(error) = std::os::windows::fs::symlink_dir(&target, &link) {
            assert!(matches!(
                error.kind(),
                io::ErrorKind::PermissionDenied | io::ErrorKind::Unsupported
            ));
            eprintln!("synthetic symlink test skipped: Windows symlink privilege unavailable");
            return;
        }
        assert!(PrivateRecorder::new(root.path(), RecorderConfig::default(), utc()).is_err());
        assert!(!target.join("captures").exists());
    }
}
