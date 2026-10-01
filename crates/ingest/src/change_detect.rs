//! Cheap change detection between consecutive frames.
//!
//! Computes a sampled pixel-diff score against the last trigger baseline and
//! reports whether the visible table state changed enough to justify a VLM
//! inference pass. This avoids the prefill cost of needless inference on a
//! static table: capture runs at ~10fps, but the VLM fires only when the
//! score exceeds the configured threshold.
//!
//! All pixels also participate in a local tile check, so a small card digit or
//! action control is not averaged away by the whole window. Thresholds are
//! conservative engineering defaults, not visually calibrated accuracy claims.

use serde::Serialize;

/// Configuration for the change detector.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ChangeDetectorConfig {
    /// Sample every Nth pixel (1 = compare every pixel).
    pub sample_stride: u32,
    /// Per-channel absolute difference that counts a sampled pixel as changed.
    pub channel_delta: u8,
    /// Fraction of sampled pixels that must differ to report a change.
    pub changed_fraction: f64,
    /// Local tiles compare every pixel, independently of the global sample stride.
    pub tile_size: u32,
    /// Fraction within any tile that invalidates the frame.
    pub local_changed_fraction: f64,
}

impl Default for ChangeDetectorConfig {
    fn default() -> Self {
        Self {
            sample_stride: 1,
            channel_delta: 8,
            changed_fraction: 0.001,
            tile_size: 16,
            local_changed_fraction: 0.003,
        }
    }
}

impl ChangeDetectorConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1..=64).contains(&self.sample_stride)
            || !(1..=128).contains(&self.channel_delta)
            || !(8..=128).contains(&self.tile_size)
            || !self.changed_fraction.is_finite()
            || !self.local_changed_fraction.is_finite()
            || !(0.000001..=1.0).contains(&self.changed_fraction)
            || !(0.000001..=1.0).contains(&self.local_changed_fraction)
        {
            return Err("invalid change thresholds: stride 1..64, delta 1..128, tile 8..128, fractions 0.000001..1");
        }
        Ok(())
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
        if frame.validate().is_err() || frame.width == 0 || frame.height == 0 {
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

        let (score, local_change) = diff_score(baseline, frame, &self.config);

        if score >= self.config.changed_fraction || local_change {
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
) -> (f64, bool) {
    let stride = config.sample_stride.max(1) as usize;
    let delta = config.channel_delta;

    let mut sampled = 0usize;
    let mut changed = 0usize;
    let tile = config.tile_size.max(1) as usize;
    let columns = (a.width as usize).div_ceil(tile);
    let rows = (a.height as usize).div_ceil(tile);
    let mut tiles = vec![(0usize, 0usize); columns * rows];

    for (index, (pa, pb)) in a
        .rgba
        .chunks_exact(4)
        .zip(b.rgba.chunks_exact(4))
        .enumerate()
    {
        let differs = pa
            .iter()
            .zip(pb.iter())
            .any(|(x, y)| x.abs_diff(*y) > delta);
        if index % stride == 0 {
            sampled += 1;
            changed += usize::from(differs);
        }
        let x = index % a.width as usize;
        let y = index / a.width as usize;
        let entry = &mut tiles[(y / tile) * columns + x / tile];
        entry.0 += usize::from(differs);
        entry.1 += 1;
    }

    let score = if sampled == 0 {
        0.0
    } else {
        changed as f64 / sampled as f64
    };
    let local = tiles.iter().any(|(changed, total)| {
        *total > 0 && *changed as f64 / *total as f64 >= config.local_changed_fraction
    });
    (score, local)
}

/// Caller-supplied monotonic time makes stabilization deterministic in tests.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct StabilityConfig {
    pub stable_ms: u64,
    pub stable_captures: u32,
}

impl Default for StabilityConfig {
    fn default() -> Self {
        Self {
            stable_ms: 300,
            stable_captures: 3,
        }
    }
}

impl StabilityConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(100..=5_000).contains(&self.stable_ms) || !(2..=50).contains(&self.stable_captures) {
            return Err("stability requires 100..5000 ms and 2..50 captures");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FrameProgress {
    pub changed: bool,
    pub stable: bool,
}

pub struct FrameTracker {
    detector: ChangeDetector,
    config: StabilityConfig,
    since: Option<u64>,
    count: u32,
}

impl FrameTracker {
    pub fn new(change: ChangeDetectorConfig, stability: StabilityConfig) -> Self {
        Self {
            detector: ChangeDetector::new(change),
            config: stability,
            since: None,
            count: 0,
        }
    }

    pub fn observe(&mut self, frame: &super::capture::Frame, now_ms: u64) -> FrameProgress {
        if frame.validate().is_err() || frame.width == 0 || frame.height == 0 {
            self.reset();
            return FrameProgress {
                changed: true,
                stable: false,
            };
        }
        let changed = self.detector.detect(frame).is_changed();
        if changed || self.since.is_none_or(|since| now_ms < since) {
            self.since = Some(now_ms);
            self.count = 1;
        } else {
            self.count = self.count.saturating_add(1);
        }
        FrameProgress {
            changed,
            stable: self.count >= self.config.stable_captures
                && self
                    .since
                    .is_some_and(|since| now_ms.saturating_sub(since) >= self.config.stable_ms),
        }
    }

    pub fn reset(&mut self) {
        self.detector.reset();
        self.since = None;
        self.count = 0;
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
            local_changed_fraction: 1.0,
            ..ChangeDetectorConfig::default()
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
            local_changed_fraction: 1.0,
            ..ChangeDetectorConfig::default()
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
            local_changed_fraction: 1.0,
            ..ChangeDetectorConfig::default()
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
    fn local_pixel_outside_global_sample_grid_triggers() {
        let mut detector = ChangeDetector::new(ChangeDetectorConfig {
            sample_stride: 64,
            ..ChangeDetectorConfig::default()
        });
        let mut frame = solid_frame(320, 240, 64);
        detector.detect(&frame);
        frame.rgba[4 * 37] = 255;
        assert!(detector.detect(&frame).is_changed());
    }

    #[test]
    fn animation_cannot_become_stable_until_it_stops() {
        let mut tracker =
            FrameTracker::new(ChangeDetectorConfig::default(), StabilityConfig::default());
        for step in 0..10 {
            let result = tracker.observe(&solid_frame(160, 120, (step * 30) as u8), step * 100);
            assert!(!result.stable);
        }
        let frame = solid_frame(160, 120, 50);
        assert!(!tracker.observe(&frame, 1_000).stable);
        assert!(!tracker.observe(&frame, 1_100).stable);
        assert!(!tracker.observe(&frame, 1_200).stable);
        assert!(tracker.observe(&frame, 1_300).stable);
        tracker.reset();
        assert!(!tracker.observe(&frame, 1_400).stable);
    }

    #[test]
    fn malformed_and_size_changes_break_stability() {
        let mut tracker =
            FrameTracker::new(ChangeDetectorConfig::default(), StabilityConfig::default());
        let frame = solid_frame(160, 120, 50);
        tracker.observe(&frame, 0);
        tracker.observe(&frame, 100);
        assert!(tracker.observe(&frame, 300).stable);
        let mut malformed = frame.clone();
        malformed.rgba.pop();
        assert!(!tracker.observe(&malformed, 400).stable);
        assert!(!tracker.observe(&frame, 500).stable);
        assert!(!tracker.observe(&solid_frame(320, 240, 50), 800).stable);
    }

    #[test]
    fn validated_bounds_reject_nonfinite_and_unsafe_thresholds() {
        for fraction in [f64::NAN, f64::INFINITY, 0.0, -1.0, 1.1] {
            assert!(ChangeDetectorConfig {
                changed_fraction: fraction,
                ..ChangeDetectorConfig::default()
            }
            .validate()
            .is_err());
        }
        assert!(StabilityConfig {
            stable_ms: 0,
            stable_captures: 1
        }
        .validate()
        .is_err());
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
