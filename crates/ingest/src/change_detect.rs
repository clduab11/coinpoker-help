//! Cheap change detection between consecutive frames.
//!
//! Computes a sampled pixel-diff score against the last trigger baseline and
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

/// Outcome of comparing a frame against the current baseline.
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

/// Compares frames against the last accepted trigger baseline.
#[derive(Debug, Clone)]
pub struct ChangeDetector {
    config: ChangeDetectorConfig,
    baseline: Option<super::capture::Frame>,
}

impl ChangeDetector {
    pub fn new(config: ChangeDetectorConfig) -> Self {
        Self {
            config,
            baseline: None,
        }
    }

    /// Compare `frame` against the last frame that triggered a change.
    ///
    /// The first valid frame after construction is always reported as changed
    /// and becomes the baseline. Sub-threshold frames do not replace that
    /// baseline, allowing incremental visual changes to accumulate.
    pub fn detect(&mut self, frame: &super::capture::Frame) -> ChangeResult {
        // Malformed buffers are unsafe to compare and must never suppress
        // inference or replace a known-good baseline.
        if frame.validate().is_err() {
            return ChangeResult::Changed { score: 1.0 };
        }

        let baseline = match &self.baseline {
            Some(baseline) => baseline,
            None => {
                self.baseline = Some(frame.clone());
                return ChangeResult::Changed { score: 1.0 };
            }
        };

        if baseline.validate().is_err()
            || baseline.width != frame.width
            || baseline.height != frame.height
        {
            self.baseline = Some(frame.clone());
            return ChangeResult::Changed { score: 1.0 };
        }

        let score = diff_score(baseline, frame, &self.config);

        if score >= self.config.changed_fraction {
            self.baseline = Some(frame.clone());
            ChangeResult::Changed { score }
        } else {
            ChangeResult::Unchanged { score }
        }
    }

    /// Reset the baseline so the next valid frame is reported as changed.
    pub fn reset(&mut self) {
        self.baseline = None;
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
    fn cumulative_sub_threshold_changes_trigger_against_baseline() {
        let config = ChangeDetectorConfig {
            sample_stride: 1,
            channel_delta: 24,
            changed_fraction: 0.5,
        };
        let mut detector = ChangeDetector::new(config);
        let baseline = solid_frame(4, 1, 0);
        detector.detect(&baseline);

        let mut one_pixel_changed = baseline.clone();
        one_pixel_changed.rgba[0] = 255;
        assert!(!detector.detect(&one_pixel_changed).is_changed());

        let mut two_pixels_changed = one_pixel_changed;
        two_pixels_changed.rgba[4] = 255;
        let result = detector.detect(&two_pixels_changed);
        assert!(result.is_changed());
        assert_eq!(result.score(), 0.5);
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
    fn malformed_buffer_is_fail_safe_changed_without_replacing_baseline() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig::default());
        let baseline = solid_frame(2, 2, 128);
        detector.detect(&baseline);

        let malformed = Frame {
            width: 2,
            height: 2,
            rgba: vec![128; 15],
        };
        let result = detector.detect(&malformed);
        assert!(result.is_changed());
        assert_eq!(result.score(), 1.0);

        let result = detector.detect(&baseline);
        assert!(!result.is_changed());
        assert_eq!(result.score(), 0.0);
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
