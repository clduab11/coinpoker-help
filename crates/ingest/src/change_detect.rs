//! Cheap change detection between consecutive frames.
//!
//! Computes a sampled pixel-diff score against the previous frame and
//! reports whether the visible table state changed enough to justify a VLM
//! inference pass. This avoids the prefill cost of needless inference on a
//! static table: capture runs at ~10fps, but the VLM fires only when the
//! score exceeds the configured threshold.
//!
//! The detector is intentionally pure (no clocks, no I/O); debouncing and
//! minimum fire intervals are the caller's concern.

/// Configuration for the change detector.
#[derive(Debug, Clone, PartialEq)]
pub struct ChangeDetectorConfig {
    /// Sample every Nth pixel (1 = compare every pixel).
    pub sample_stride: u32,
    /// Per-channel absolute difference that counts a sampled pixel as changed.
    pub channel_delta: u8,
    /// Fraction of sampled pixels that must differ to report a change.
    pub changed_fraction: f64,
}

impl Default for ChangeDetectorConfig {
    fn default() -> Self {
        Self {
            sample_stride: 4,
            channel_delta: 24,
            changed_fraction: 0.005,
        }
    }
}

/// Outcome of comparing a frame against the previous one.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ChangeResult {
    /// The table state changed enough to trigger inference.
    Changed { score: f64 },
    /// No meaningful change; the previous state remains valid.
    Unchanged { score: f64 },
}

impl ChangeResult {
    /// The raw change score (fraction of sampled pixels that differed).
    pub fn score(&self) -> f64 {
        match self {
            ChangeResult::Changed { score } | ChangeResult::Unchanged { score } => *score,
        }
    }

    pub fn is_changed(&self) -> bool {
        matches!(self, ChangeResult::Changed { .. })
    }
}

/// Compares consecutive frames and reports whether the table changed.
#[derive(Debug, Clone)]
pub struct ChangeDetector {
    config: ChangeDetectorConfig,
    previous: Option<super::capture::Frame>,
}

impl ChangeDetector {
    pub fn new(config: ChangeDetectorConfig) -> Self {
        Self {
            config,
            previous: None,
        }
    }

    /// Compare `frame` against the previously seen frame.
    ///
    /// The first frame after construction is always reported as changed
    /// (there is no baseline to compare against), and becomes the baseline.
    pub fn detect(&mut self, frame: &super::capture::Frame) -> ChangeResult {
        let previous = match &self.previous {
            Some(prev) => prev,
            None => {
                self.previous = Some(frame.clone());
                return ChangeResult::Changed { score: 1.0 };
            }
        };

        // Dimension mismatch is an unambiguous change.
        if previous.width != frame.width || previous.height != frame.height {
            self.previous = Some(frame.clone());
            return ChangeResult::Changed { score: 1.0 };
        }

        let score = diff_score(previous, frame, &self.config);
        self.previous = Some(frame.clone());

        if score >= self.config.changed_fraction {
            ChangeResult::Changed { score }
        } else {
            ChangeResult::Unchanged { score }
        }
    }

    /// Reset the baseline so the next frame is reported as changed.
    pub fn reset(&mut self) {
        self.previous = None;
    }
}

/// Fraction of sampled pixels whose per-channel difference exceeds
/// `config.channel_delta`.
fn diff_score(
    a: &super::capture::Frame,
    b: &super::capture::Frame,
    config: &ChangeDetectorConfig,
) -> f64 {
    let stride = config.sample_stride.max(1) as usize;
    let delta = config.channel_delta;

    let mut sampled = 0usize;
    let mut changed = 0usize;

    for (pa, pb) in a
        .rgba
        .chunks_exact(4)
        .zip(b.rgba.chunks_exact(4))
        .step_by(stride)
    {
        sampled += 1;
        let differs = pa
            .iter()
            .zip(pb.iter())
            .any(|(x, y)| x.abs_diff(*y) > delta);
        if differs {
            changed += 1;
        }
    }

    if sampled == 0 {
        0.0
    } else {
        changed as f64 / sampled as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::capture::Frame;

    fn solid_frame(width: u32, height: u32, value: u8) -> Frame {
        Frame {
            width,
            height,
            rgba: vec![value; width as usize * height as usize * 4],
        }
    }

    #[test]
    fn first_frame_is_always_changed() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
        let frame = solid_frame(16, 16, 128);
        let result = detector.detect(&frame);
        assert!(result.is_changed());
        assert_eq!(result.score(), 1.0);
    }

    #[test]
    fn identical_frames_are_unchanged() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
        let frame = solid_frame(16, 16, 128);
        detector.detect(&frame); // baseline
        let result = detector.detect(&frame);
        assert!(!result.is_changed());
        assert_eq!(result.score(), 0.0);
    }

    #[test]
    fn dimension_change_is_detected() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
        detector.detect(&solid_frame(16, 16, 128));
        let result = detector.detect(&solid_frame(32, 16, 128));
        assert!(result.is_changed());
        assert_eq!(result.score(), 1.0);
    }

    #[test]
    fn small_fraction_of_pixels_does_not_trigger() {
        let config = ChangeDetectorConfig {
            sample_stride: 1,
            channel_delta: 24,
            changed_fraction: 0.5,
        };
        let mut detector = ChangeDetector::new(config);
        let mut frame = solid_frame(16, 16, 128);
        detector.detect(&frame.clone());

        // Change a single pixel far beyond the channel delta.
        frame.rgba[0] = 255;
        let result = detector.detect(&frame);
        assert!(!result.is_changed());
        assert!(result.score() > 0.0 && result.score() < 0.5);
    }

    #[test]
    fn large_fraction_of_pixels_triggers() {
        let config = ChangeDetectorConfig {
            sample_stride: 1,
            channel_delta: 24,
            changed_fraction: 0.5,
        };
        let mut detector = ChangeDetector::new(config);
        let mut frame = solid_frame(16, 16, 128);
        detector.detect(&frame.clone());

        // Change the entire first half of the frame.
        let half = frame.rgba.len() / 2;
        for byte in frame.rgba.iter_mut().take(half) {
            *byte = 255;
        }
        let result = detector.detect(&frame);
        assert!(result.is_changed());
        assert!(result.score() >= 0.5);
    }

    #[test]
    fn reset_forces_next_change() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
        let frame = solid_frame(16, 16, 128);
        detector.detect(&frame);
        detector.reset();
        assert!(detector.detect(&frame).is_changed());
    }
}
