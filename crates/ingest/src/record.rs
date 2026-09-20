//! Frame fixture recording for offline testing.
//!
//! Mirrors captured frames to disk as PNG files so the perception pipeline
//! can be replayed and tested without a live game. Recording is opt-in via
//! the `COINPOKER_RECORD_FRAMES_DIR` environment variable: when set, the
//! capture stream writes every distinct frame to `<dir>/frame_XXXXX.png`
//! until the configured limit is reached.
//!
//! Recorded fixtures are for local development only; CI uses the committed
//! synthetic fixtures in `tests/fixtures/` (see CONTRIBUTING.md for the rule
//! against committing real table data).

use std::fs;
use std::io::Cursor;
use std::path::PathBuf;

use thiserror::Error;

use crate::capture::Frame;

/// Environment variable that enables fixture recording.
pub const RECORD_FRAMES_DIR_ENV: &str = "COINPOKER_RECORD_FRAMES_DIR";

/// Default maximum number of frames a single recorder will write.
pub const DEFAULT_RECORD_LIMIT: usize = 500;

/// Errors produced while recording frames to disk.
#[derive(Debug, Error)]
pub enum RecordError {
    /// The recording directory could not be created.
    #[error("cannot create recording directory {dir}: {source}")]
    CreateDirectory { dir: String, source: std::io::Error },
    /// A frame could not be encoded as PNG.
    #[error("frame encoding failed: {0}")]
    Encoding(String),
    /// A fixture file could not be written.
    #[error("cannot write {path}: {source}")]
    Write {
        path: String,
        source: std::io::Error,
    },
}

/// Writes distinct captured frames to a directory as PNG fixtures.
///
/// Consecutive identical frames are skipped so a static table does not fill
/// the directory; the recorder also stops after `limit` files to bound disk
/// usage.
#[derive(Debug)]
pub struct FrameRecorder {
    dir: PathBuf,
    limit: usize,
    written: usize,
    last_recorded: Option<(u32, u32, Vec<u8>)>,
}

impl FrameRecorder {
    /// Create a recorder that writes fixtures into `dir`, creating the
    /// directory if needed.
    ///
    /// The limit bounds the number of files written; recording silently stops
    /// once reached.
    pub fn new(dir: impl Into<PathBuf>, limit: usize) -> Result<Self, RecordError> {
        let dir = dir.into();
        fs::create_dir_all(&dir).map_err(|source| RecordError::CreateDirectory {
            dir: dir.display().to_string(),
            source,
        })?;
        Ok(Self {
            dir,
            limit,
            written: 0,
            last_recorded: None,
        })
    }

    /// Construct a recorder from the environment when fixture recording is
    /// enabled via [`RECORD_FRAMES_DIR_ENV`].
    ///
    /// Returns `None` when the variable is unset or empty. This never fails:
    /// a broken configuration disables recording rather than aborting the
    /// capture pipeline.
    pub fn from_env() -> Option<Self> {
        let dir = std::env::var(RECORD_FRAMES_DIR_ENV).ok()?;
        let dir = dir.trim().to_string();
        if dir.is_empty() {
            return None;
        }
        match Self::new(dir, DEFAULT_RECORD_LIMIT) {
            Ok(recorder) => Some(recorder),
            Err(error) => {
                eprintln!("frame recording disabled: {error}");
                None
            }
        }
    }

    /// Record a frame if it differs from the previously recorded one.
    ///
    /// Returns `Ok(true)` when a file was written, `Ok(false)` when the frame
    /// was skipped (duplicate, malformed, or limit reached).
    pub fn record(&mut self, frame: &Frame) -> Result<bool, RecordError> {
        if self.written >= self.limit {
            return Ok(false);
        }
        if frame.validate().is_err() {
            return Ok(false);
        }

        let fingerprint = (frame.width, frame.height, frame.rgba.clone());
        if self.last_recorded.as_ref() == Some(&fingerprint) {
            return Ok(false);
        }

        let path = self.dir.join(format!("frame_{:05}.png", self.written));
        let png = encode_frame_as_png(frame)?;
        fs::write(&path, png).map_err(|source| RecordError::Write {
            path: path.display().to_string(),
            source,
        })?;

        self.last_recorded = Some(fingerprint);
        self.written += 1;
        Ok(true)
    }

    /// Number of fixture files written so far.
    pub fn written(&self) -> usize {
        self.written
    }

    /// Maximum number of files this recorder will write.
    pub fn limit(&self) -> usize {
        self.limit
    }

    /// The directory fixtures are written to.
    pub fn dir(&self) -> &std::path::Path {
        &self.dir
    }
}

/// Encode a frame as PNG bytes.
fn encode_frame_as_png(frame: &Frame) -> Result<Vec<u8>, RecordError> {
    let image = frame
        .to_rgba_image()
        .map_err(|e| RecordError::Encoding(e.to_string()))?;
    let mut png = Vec::new();
    image
        .write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
        .map_err(|e| RecordError::Encoding(e.to_string()))?;
    Ok(png)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn solid_frame(width: u32, height: u32, value: u8) -> Frame {
        Frame {
            width,
            height,
            rgba: vec![value; width as usize * height as usize * 4],
        }
    }

    fn temp_dir(tag: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("coinpoker-record-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn records_distinct_frames_as_png_files() {
        let dir = temp_dir("distinct");
        let mut recorder = FrameRecorder::new(&dir, 10).expect("create recorder in temp dir");

        assert!(recorder.record(&solid_frame(4, 4, 10)).expect("record"));
        assert!(recorder.record(&solid_frame(4, 4, 20)).expect("record"));
        assert_eq!(recorder.written(), 2);

        let first = fs::read(dir.join("frame_00000.png")).expect("first fixture");
        let decoded = image::load_from_memory(&first).expect("valid png");
        assert_eq!((decoded.width(), decoded.height()), (4, 4));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn skips_consecutive_duplicate_frames() {
        let dir = temp_dir("duplicate");
        let mut recorder = FrameRecorder::new(&dir, 10).expect("create recorder in temp dir");

        assert!(recorder.record(&solid_frame(4, 4, 10)).expect("record"));
        assert!(!recorder
            .record(&solid_frame(4, 4, 10))
            .expect("duplicate skipped"));
        assert!(!recorder
            .record(&solid_frame(4, 4, 10))
            .expect("duplicate skipped again"));
        assert!(recorder.record(&solid_frame(4, 4, 30)).expect("record"));
        assert_eq!(recorder.written(), 2);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn respects_the_file_limit() {
        let dir = temp_dir("limit");
        let mut recorder = FrameRecorder::new(&dir, 2).expect("create recorder");

        assert!(recorder.record(&solid_frame(2, 2, 1)).expect("record"));
        assert!(recorder.record(&solid_frame(2, 2, 2)).expect("record"));
        assert!(!recorder
            .record(&solid_frame(2, 2, 3))
            .expect("limit reached"));
        assert_eq!(recorder.written(), 2);
        assert_eq!(recorder.limit(), 2);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn malformed_frames_are_skipped_not_recorded() {
        let dir = temp_dir("malformed");
        let mut recorder = FrameRecorder::new(&dir, 10).expect("create recorder in temp dir");

        let malformed = Frame {
            width: 2,
            height: 2,
            rgba: vec![0; 15],
        };
        assert!(!recorder.record(&malformed).expect("malformed skipped"));
        assert_eq!(recorder.written(), 0);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn records_again_after_returning_to_an_earlier_frame() {
        // The dedup check is against the *last recorded* frame only, so
        // A, B, A must write three files.
        let dir = temp_dir("alternating");
        let mut recorder = FrameRecorder::new(&dir, 10).expect("create recorder in temp dir");

        assert!(recorder.record(&solid_frame(4, 4, 10)).expect("record"));
        assert!(recorder.record(&solid_frame(4, 4, 20)).expect("record"));
        assert!(recorder.record(&solid_frame(4, 4, 10)).expect("record"));
        assert_eq!(recorder.written(), 3);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn env_recording_follows_the_environment() {
        // Both environment interactions live in a single test so parallel
        // tests never race on the shared variable.
        let saved = std::env::var(RECORD_FRAMES_DIR_ENV).ok();

        std::env::remove_var(RECORD_FRAMES_DIR_ENV);
        assert!(FrameRecorder::from_env().is_none());

        std::env::set_var(RECORD_FRAMES_DIR_ENV, "");
        assert!(FrameRecorder::from_env().is_none());

        let dir = temp_dir("from-env");
        std::env::set_var(RECORD_FRAMES_DIR_ENV, dir.as_os_str());
        let recorder = FrameRecorder::from_env();

        if let Some(value) = saved {
            std::env::set_var(RECORD_FRAMES_DIR_ENV, value);
        } else {
            std::env::remove_var(RECORD_FRAMES_DIR_ENV);
        }

        let mut recorder = recorder.expect("recorder constructed from env");
        assert_eq!(recorder.dir(), dir);
        assert!(recorder.record(&solid_frame(2, 2, 1)).expect("record"));

        let _ = fs::remove_dir_all(&dir);
    }
}
