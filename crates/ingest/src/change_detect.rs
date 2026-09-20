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

/// A rectangular region in normalized `[0, 1]` frame coordinates.
///
/// `x`/`y` locate the top-left corner; `w`/`h` size the rect. Values may
/// fall outside `[0, 1]`; [`pixel_bounds`] clamps them to the frame.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ZoneRect {
    /// Left edge as a fraction of the frame width.
    pub x: f64,
    /// Top edge as a fraction of the frame height.
    pub y: f64,
    /// Width as a fraction of the frame width.
    pub w: f64,
    /// Height as a fraction of the frame height.
    pub h: f64,
}

/// Table regions whose changes are decision-relevant.
///
/// The order of the variants is fixed (Pot, Board, Action) and defines the
/// order of per-zone results in [`ZoneChangeResult::zones`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Zone {
    /// The pot display above the community cards.
    Pot,
    /// The community-card area in the middle of the table.
    Board,
    /// The hero's action-button strip along the bottom.
    Action,
}

/// The canonical zone order used by [`ZoneChangeDetector`].
const ZONES: [Zone; 3] = [Zone::Pot, Zone::Board, Zone::Action];

/// Per-zone detection settings.
#[derive(Debug, Clone, PartialEq)]
pub struct ZoneConfig {
    /// The region this zone occupies, in normalized frame coordinates.
    pub rect: ZoneRect,
    /// Perceptual-hash bit distance at or above which the zone counts as
    /// changed.
    pub hash_distance_threshold: u32,
}

/// Configuration for the zone-masked change detector.
///
/// The default rects target a 16:9 table layout: the pot display sits above
/// the community cards at the horizontal center, the board spans the middle,
/// and the action buttons run along the bottom strip.
#[derive(Debug, Clone, PartialEq)]
pub struct ZoneChangeDetectorConfig {
    /// Pot display region.
    pub pot: ZoneConfig,
    /// Community-card region.
    pub board: ZoneConfig,
    /// Action-button region.
    pub action: ZoneConfig,
}

impl Default for ZoneChangeDetectorConfig {
    fn default() -> Self {
        Self {
            pot: ZoneConfig {
                rect: ZoneRect {
                    x: 0.42,
                    y: 0.30,
                    w: 0.16,
                    h: 0.08,
                },
                hash_distance_threshold: 6,
            },
            board: ZoneConfig {
                rect: ZoneRect {
                    x: 0.36,
                    y: 0.42,
                    w: 0.28,
                    h: 0.12,
                },
                hash_distance_threshold: 6,
            },
            action: ZoneConfig {
                rect: ZoneRect {
                    x: 0.30,
                    y: 0.82,
                    w: 0.40,
                    h: 0.12,
                },
                hash_distance_threshold: 6,
            },
        }
    }
}

impl ZoneChangeDetectorConfig {
    /// The configured [`ZoneConfig`] for a zone.
    pub fn zone_config(&self, zone: Zone) -> &ZoneConfig {
        match zone {
            Zone::Pot => &self.pot,
            Zone::Board => &self.board,
            Zone::Action => &self.action,
        }
    }
}

/// Outcome of a zone-masked comparison against the baseline.
///
/// `zones` lists one entry per zone in the fixed order Pot, Board, Action.
#[derive(Debug, Clone, PartialEq)]
pub struct ZoneChangeResult {
    /// Whether any decision-relevant zone changed (or the frame was
    /// unusable, which fails toward "changed").
    pub changed: bool,
    /// Per-zone change flags in the order Pot, Board, Action.
    pub zones: Vec<(Zone, bool)>,
}

impl ZoneChangeResult {
    /// Whether a specific zone changed. Unknown zones report `false`.
    pub fn zone_changed(&self, zone: Zone) -> bool {
        self.zones
            .iter()
            .find(|(candidate, _)| *candidate == zone)
            .is_some_and(|(_, changed)| *changed)
    }

    /// A result reporting every zone as changed (fail-safe path).
    fn all_changed() -> Self {
        Self {
            changed: true,
            zones: ZONES.iter().map(|zone| (*zone, true)).collect(),
        }
    }
}

/// Baseline hashes captured from the last frame that reported a change.
#[derive(Debug, Clone)]
struct ZoneBaseline {
    width: u32,
    height: u32,
    /// One hash per zone in [`ZONES`] order; `None` marks a zone that could
    /// not be evaluated (out-of-frame rect).
    hashes: [Option<u64>; 3],
}

/// Region-masked change detection for the pot, board, and action zones.
///
/// Each zone is hashed with an aHash-style perceptual hash ([`perceptual_hash`])
/// and compared against the hash captured from the last frame that reported a
/// change. A zone counts as changed when its hash distance meets the zone's
/// [`ZoneConfig::hash_distance_threshold`]; the frame counts as changed when
/// any zone changed.
///
/// Fail-safe semantics mirror [`ChangeDetector`]:
/// - the first valid frame is always reported as changed and becomes the
///   baseline;
/// - malformed buffers and dimension changes are reported as changed;
/// - a malformed buffer never replaces a known-good baseline;
/// - a zone whose rect covers no pixels cannot be evaluated and reports as
///   unchanged, but a frame in which *no* zone can be evaluated is reported
///   as changed so inference is never wrongly suppressed; consecutive
///   degenerate frames compare as unchanged against an equally degenerate
///   baseline.
#[derive(Debug, Clone)]
pub struct ZoneChangeDetector {
    config: ZoneChangeDetectorConfig,
    baseline: Option<ZoneBaseline>,
}

impl ZoneChangeDetector {
    /// Construct a detector with the given zone configuration.
    pub fn new(config: ZoneChangeDetectorConfig) -> Self {
        Self {
            config,
            baseline: None,
        }
    }

    /// Compare `frame` against the last frame that reported a change.
    ///
    /// See the type documentation for baseline and fail-safe semantics.
    pub fn detect(&mut self, frame: &super::capture::Frame) -> ZoneChangeResult {
        // Malformed buffers are unsafe to hash and must never suppress
        // inference or replace a known-good baseline.
        if frame.validate().is_err() {
            return ZoneChangeResult::all_changed();
        }

        let hashes = zone_hashes(frame, &self.config);

        let baseline = match &self.baseline {
            Some(baseline) if baseline.width == frame.width && baseline.height == frame.height => {
                baseline
            }
            _ => {
                // First observation, or the window was resized: treat as
                // changed and adopt this frame as the baseline.
                self.baseline = Some(ZoneBaseline {
                    width: frame.width,
                    height: frame.height,
                    hashes,
                });
                return ZoneChangeResult::all_changed();
            }
        };

        let mut any_changed = false;
        let mut usable = 0usize;
        let zones = ZONES
            .iter()
            .zip(hashes.iter().zip(baseline.hashes.iter()))
            .map(|(zone, (current, previous))| {
                let changed = match (current, previous) {
                    (Some(current), Some(previous)) => {
                        usable += 1;
                        hamming_distance(*current, *previous)
                            >= self.config.zone_config(*zone).hash_distance_threshold
                    }
                    // An unusable zone cannot be evaluated; report it as
                    // unchanged rather than guessing.
                    _ => false,
                };
                any_changed |= changed;
                (*zone, changed)
            })
            .collect();

        // When no zone could be evaluated the comparison carries no evidence
        // of stability, so fail toward triggering inference — except when the
        // baseline was equally degenerate, in which case nothing observable
        // has changed and repeated degenerate frames stay quiet.
        let degenerate = hashes.iter().all(Option::is_none);
        let baseline_degenerate = baseline.hashes.iter().all(Option::is_none);
        let changed = any_changed || (usable == 0 && !(degenerate && baseline_degenerate));

        if changed {
            self.baseline = Some(ZoneBaseline {
                width: frame.width,
                height: frame.height,
                hashes,
            });
        }

        ZoneChangeResult { changed, zones }
    }

    /// Reset the baseline so the next valid frame is reported as changed.
    pub fn reset(&mut self) {
        self.baseline = None;
    }
}

/// Hash every configured zone of a frame, in [`ZONES`] order.
///
/// Zones whose rect covers no pixels hash to `None`.
fn zone_hashes(
    frame: &super::capture::Frame,
    config: &ZoneChangeDetectorConfig,
) -> [Option<u64>; 3] {
    ZONES.map(|zone| {
        pixel_bounds(frame, &config.zone_config(zone).rect)
            .map(|_| perceptual_hash(frame, &config.zone_config(zone).rect))
    })
}

/// Clamp a normalized rect to the frame and map it to pixel bounds.
///
/// Returns `(x, y, w, h)` with `x + w <= frame.width` and
/// `y + h <= frame.height`, or `None` when the clamped rect covers zero
/// pixels (including non-finite or non-positive rects).
pub fn pixel_bounds(
    frame: &super::capture::Frame,
    rect: &ZoneRect,
) -> Option<(u32, u32, u32, u32)> {
    if ![rect.x, rect.y, rect.w, rect.h]
        .iter()
        .all(|value| value.is_finite())
    {
        return None;
    }
    if rect.w <= 0.0 || rect.h <= 0.0 {
        return None;
    }

    let frame_w = f64::from(frame.width);
    let frame_h = f64::from(frame.height);
    let x0 = (rect.x * frame_w).floor().clamp(0.0, frame_w) as u32;
    let y0 = (rect.y * frame_h).floor().clamp(0.0, frame_h) as u32;
    let x1 = ((rect.x + rect.w) * frame_w).ceil().clamp(0.0, frame_w) as u32;
    let y1 = ((rect.y + rect.h) * frame_h).ceil().clamp(0.0, frame_h) as u32;

    let w = x1.saturating_sub(x0);
    let h = y1.saturating_sub(y0);
    if w == 0 || h == 0 {
        None
    } else {
        Some((x0, y0, w, h))
    }
}

/// aHash-style perceptual hash of a frame region.
///
/// The region is box-downsampled to an 8x8 grid of average luma values, each
/// cell is thresholded against the grid mean, and the 64 resulting bits are
/// packed into a `u64` (row-major, most significant bit first). Averaging
/// makes the hash robust to small per-pixel noise while remaining sensitive
/// to structural changes such as new cards or updated chip counts.
///
/// Returns `0` when the rect covers no pixels.
pub fn perceptual_hash(frame: &super::capture::Frame, rect: &ZoneRect) -> u64 {
    let Some((x0, y0, w, h)) = pixel_bounds(frame, rect) else {
        return 0;
    };

    let mut cells = [0f64; 64];
    for (index, cell) in cells.iter_mut().enumerate() {
        let gy = index / 8;
        let gx = index % 8;
        *cell = cell_average_luma(frame, x0, y0, w, h, gx, gy);
    }

    let mean = cells.iter().sum::<f64>() / 64.0;
    cells.iter().enumerate().fold(0u64, |hash, (index, cell)| {
        if *cell > mean {
            hash | (1u64 << (63 - index))
        } else {
            hash
        }
    })
}

/// Average luma of one 8x8 grid cell covering the given region.
///
/// Cells cover pixel ranges computed with integer box mapping. Regions
/// narrower than eight pixels leave some cells without a pixel range; those
/// cells fall back to the nearest pixel so every cell contributes.
fn cell_average_luma(
    frame: &super::capture::Frame,
    x0: u32,
    y0: u32,
    w: u32,
    h: u32,
    gx: usize,
    gy: usize,
) -> f64 {
    let (xs, xe) = cell_range(x0 as usize, w as usize, gx);
    let (ys, ye) = cell_range(y0 as usize, h as usize, gy);

    let bytes_per_row = frame.bytes_per_row();
    let mut sum = 0f64;
    let mut count = 0usize;
    for y in ys..ye {
        let row = y * bytes_per_row;
        for x in xs..xe {
            let offset = row + x * 4;
            let r = f64::from(frame.rgba[offset]);
            let g = f64::from(frame.rgba[offset + 1]);
            let b = f64::from(frame.rgba[offset + 2]);
            sum += 0.299 * r + 0.587 * g + 0.114 * b;
            count += 1;
        }
    }

    if count == 0 {
        0.0
    } else {
        sum / count as f64
    }
}

/// Pixel index range `[start, end)` covered by grid cell `g` of a
/// `length`-pixel axis starting at `origin`.
fn cell_range(origin: usize, length: usize, g: usize) -> (usize, usize) {
    let start = origin + g * length / 8;
    let end = origin + (g + 1) * length / 8;
    if end > start {
        (start, end)
    } else {
        // Narrower than the grid: sample the nearest pixel instead.
        let fallback = origin + g.min(length - 1);
        (fallback, fallback + 1)
    }
}

/// Number of differing bits between two 64-bit perceptual hashes.
pub fn hamming_distance(a: u64, b: u64) -> u32 {
    (a ^ b).count_ones()
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

#[cfg(test)]
mod zone_tests {
    use super::*;
    use crate::capture::Frame;

    /// A frame whose pot-zone cells alternate between two luma levels that
    /// sit far from the grid mean, so small noise cannot flip hash bits.
    fn structured_frame(size: u32) -> Frame {
        let mut rgba = vec![0u8; size as usize * size as usize * 4];
        for y in 0..size as usize {
            for x in 0..size as usize {
                let cell_x = x * 8 / size as usize;
                let cell_y = y * 8 / size as usize;
                let dark = (cell_x + cell_y).is_multiple_of(2);
                let value = if dark { 40u8 } else { 200u8 };
                let offset = (y * size as usize + x) * 4;
                rgba[offset] = value;
                rgba[offset + 1] = value;
                rgba[offset + 2] = value;
                rgba[offset + 3] = 255;
            }
        }
        Frame {
            width: size,
            height: size,
            rgba,
        }
    }

    fn full_frame_rect() -> ZoneRect {
        ZoneRect {
            x: 0.0,
            y: 0.0,
            w: 1.0,
            h: 1.0,
        }
    }

    #[test]
    fn hamming_distance_counts_differing_bits() {
        assert_eq!(hamming_distance(0, 0), 0);
        assert_eq!(hamming_distance(!0u64, !0u64), 0);
        assert_eq!(hamming_distance(0, !0u64), 64);
        assert_eq!(hamming_distance(0b1010, 0b0110), 2);
        assert_eq!(hamming_distance(0b1010, 0b1010), 0);
    }

    #[test]
    fn pixel_bounds_maps_and_clamps_rects() {
        let frame = Frame {
            width: 100,
            height: 50,
            rgba: vec![0; 100 * 50 * 4],
        };

        // Interior rect with binary-exact fractions maps to its pixel window.
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: 0.25,
                    y: 0.5,
                    w: 0.5,
                    h: 0.25
                }
            ),
            Some((25, 25, 50, 13))
        );

        // Full-frame rect covers everything.
        assert_eq!(
            pixel_bounds(&frame, &full_frame_rect()),
            Some((0, 0, 100, 50))
        );

        // Partially out-of-frame rects clamp to the frame.
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: -0.25,
                    y: 0.75,
                    w: 0.5,
                    h: 0.5
                }
            ),
            Some((0, 37, 25, 13))
        );

        // Fully out-of-frame, zero-size, and non-finite rects cover nothing.
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: 2.0,
                    y: 0.0,
                    w: 0.5,
                    h: 0.5
                }
            ),
            None
        );
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: 0.1,
                    y: 0.1,
                    w: 0.0,
                    h: 0.5
                }
            ),
            None
        );
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: f64::NAN,
                    y: 0.0,
                    w: 0.5,
                    h: 0.5
                }
            ),
            None
        );
        assert_eq!(
            pixel_bounds(
                &frame,
                &ZoneRect {
                    x: 0.0,
                    y: 0.0,
                    w: f64::INFINITY,
                    h: 0.5
                }
            ),
            None
        );
    }

    #[test]
    fn perceptual_hash_is_deterministic() {
        let frame = structured_frame(32);
        let rect = full_frame_rect();
        assert_eq!(
            perceptual_hash(&frame, &rect),
            perceptual_hash(&frame, &rect)
        );
    }

    #[test]
    fn perceptual_hash_ignores_tiny_noise() {
        let mut frame = structured_frame(32);
        let rect = full_frame_rect();
        let baseline = perceptual_hash(&frame, &rect);

        // Perturb two pixels by a small amount; cell averages move far less
        // than the distance between the structured luma levels and the mean.
        frame.rgba[0] = frame.rgba[0].saturating_add(10);
        frame.rgba[1] = frame.rgba[1].saturating_sub(10);
        frame.rgba[4 * 32 * 4] = frame.rgba[4 * 32 * 4].saturating_add(10);

        assert_eq!(perceptual_hash(&frame, &rect), baseline);
    }

    #[test]
    fn perceptual_hash_detects_structural_change() {
        let frame = structured_frame(32);
        let rect = full_frame_rect();
        let baseline = perceptual_hash(&frame, &rect);

        // Invert the checkerboard: every cell crosses the mean.
        let mut inverted = frame.clone();
        for byte in inverted.rgba.chunks_exact_mut(4) {
            byte[0] = 255 - byte[0];
            byte[1] = 255 - byte[1];
            byte[2] = 255 - byte[2];
        }

        assert!(hamming_distance(baseline, perceptual_hash(&inverted, &rect)) >= 32);
    }

    #[test]
    fn perceptual_hash_of_unusable_rect_is_zero() {
        let frame = structured_frame(16);
        assert_eq!(
            perceptual_hash(
                &frame,
                &ZoneRect {
                    x: 2.0,
                    y: 0.0,
                    w: 0.5,
                    h: 0.5
                }
            ),
            0
        );
    }

    fn zone_config_covering(zone_rect: ZoneRect) -> ZoneChangeDetectorConfig {
        let zone = ZoneConfig {
            rect: zone_rect,
            hash_distance_threshold: 6,
        };
        ZoneChangeDetectorConfig {
            pot: zone.clone(),
            board: zone.clone(),
            action: zone,
        }
    }

    #[test]
    fn first_frame_is_always_changed_and_becomes_baseline() {
        let mut detector = ZoneChangeDetector::new(zone_config_covering(full_frame_rect()));
        let result = detector.detect(&structured_frame(16));
        assert!(result.changed);
        assert!(result.zone_changed(Zone::Pot));
        assert!(result.zone_changed(Zone::Board));
        assert!(result.zone_changed(Zone::Action));

        // The identical frame is now unchanged against that baseline.
        let result = detector.detect(&structured_frame(16));
        assert!(!result.changed);
        assert!(!result.zone_changed(Zone::Pot));
    }

    #[test]
    fn zone_change_is_reported_per_zone() {
        let config = ZoneChangeDetectorConfig::default();
        let mut detector = ZoneChangeDetector::new(config.clone());

        // 32x32 keeps the default rects usable: the pot rect covers a small
        // window into the checkerboard.
        let baseline = structured_frame(32);
        assert!(detector.detect(&baseline).changed);

        // Change only the pot zone: paint it a flat mid-gray that differs
        // structurally from the checkerboard cells it covers.
        let bounds = pixel_bounds(&baseline, &config.pot.rect).expect("pot rect usable");
        let mut pot_changed = baseline.clone();
        fill_rect(&mut pot_changed, bounds, (255, 60, 60));

        let result = detector.detect(&pot_changed);
        assert!(result.changed, "pot-zone change must trigger");
        assert!(result.zone_changed(Zone::Pot));
        assert!(!result.zone_changed(Zone::Board), "board is untouched");
        assert!(!result.zone_changed(Zone::Action), "action is untouched");
    }

    #[test]
    fn dimension_change_is_changed_and_replaces_baseline() {
        let mut detector = ZoneChangeDetector::new(zone_config_covering(full_frame_rect()));
        assert!(detector.detect(&structured_frame(16)).changed);

        let result = detector.detect(&structured_frame(32));
        assert!(result.changed);
        assert!(result.zone_changed(Zone::Pot));

        // The new baseline is the resized frame.
        let result = detector.detect(&structured_frame(32));
        assert!(!result.changed);
    }

    #[test]
    fn malformed_frame_fails_safe_without_replacing_baseline() {
        let mut detector = ZoneChangeDetector::new(zone_config_covering(full_frame_rect()));
        let baseline = structured_frame(16);
        assert!(detector.detect(&baseline).changed);

        let malformed = Frame {
            width: 16,
            height: 16,
            rgba: vec![0; 15],
        };
        let result = detector.detect(&malformed);
        assert!(result.changed);
        assert!(result.zone_changed(Zone::Pot));

        // The known-good baseline survives: the original frame is unchanged.
        let result = detector.detect(&baseline);
        assert!(!result.changed);
    }

    #[test]
    fn all_zones_out_of_frame_still_triggers_inference() {
        let config = zone_config_covering(ZoneRect {
            x: 2.0,
            y: 2.0,
            w: 0.5,
            h: 0.5,
        });
        let mut detector = ZoneChangeDetector::new(config);
        let frame = structured_frame(16);

        // The first observation fails toward inference.
        let result = detector.detect(&frame);
        assert!(
            result.changed,
            "no evaluable zone must fail toward inference"
        );

        // Repeats against an equally degenerate baseline stay quiet, and the
        // unevaluable zones read as unchanged.
        let result = detector.detect(&frame);
        assert!(
            !result.changed,
            "identical degenerate frames do not retrigger"
        );
        assert!(!result.zone_changed(Zone::Pot));
        assert!(!result.zone_changed(Zone::Board));
        assert!(!result.zone_changed(Zone::Action));
    }

    #[test]
    fn reset_forces_next_change() {
        let mut detector = ZoneChangeDetector::new(zone_config_covering(full_frame_rect()));
        let frame = structured_frame(16);
        assert!(detector.detect(&frame).changed);
        assert!(!detector.detect(&frame).changed);

        detector.reset();
        let result = detector.detect(&frame);
        assert!(result.changed);
    }

    #[test]
    fn zone_result_reports_unknown_zones_as_unchanged() {
        let result = ZoneChangeResult {
            changed: true,
            zones: vec![(Zone::Pot, true)],
        };
        assert!(result.zone_changed(Zone::Pot));
        assert!(!result.zone_changed(Zone::Board));
        assert!(!result.zone_changed(Zone::Action));
    }

    #[test]
    fn default_config_targets_expected_table_regions() {
        let config = ZoneChangeDetectorConfig::default();
        let frame = Frame {
            width: 1920,
            height: 1080,
            rgba: vec![0; 1920 * 1080 * 4],
        };

        let (pot_x, pot_y, pot_w, pot_h) =
            pixel_bounds(&frame, &config.pot.rect).expect("pot rect usable");
        assert_eq!((pot_x, pot_y, pot_w, pot_h), (806, 324, 308, 87));

        let (board_x, board_y, board_w, board_h) =
            pixel_bounds(&frame, &config.board.rect).expect("board rect usable");
        assert_eq!((board_x, board_y, board_w, board_h), (691, 453, 538, 131));

        let (action_x, action_y, action_w, action_h) =
            pixel_bounds(&frame, &config.action.rect).expect("action rect usable");
        assert_eq!(
            (action_x, action_y, action_w, action_h),
            (576, 885, 768, 131)
        );

        for zone in [Zone::Pot, Zone::Board, Zone::Action] {
            assert_eq!(config.zone_config(zone).hash_distance_threshold, 6);
        }
    }

    fn fill_rect(frame: &mut Frame, (x0, y0, w, h): (u32, u32, u32, u32), rgb: (u8, u8, u8)) {
        for y in y0..y0 + h {
            for x in x0..x0 + w {
                let offset = ((y * frame.width + x) * 4) as usize;
                frame.rgba[offset] = rgb.0;
                frame.rgba[offset + 1] = rgb.1;
                frame.rgba[offset + 2] = rgb.2;
            }
        }
    }
}

#[cfg(test)]
mod proptests {
    use super::*;
    use crate::capture::Frame;
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn hamming_distance_is_symmetric_bounded_and_counts_xor(a in any::<u64>(), b in any::<u64>()) {
            prop_assert_eq!(hamming_distance(a, b), hamming_distance(b, a));
            prop_assert_eq!(hamming_distance(a, b), (a ^ b).count_ones());
            prop_assert!(hamming_distance(a, b) <= 64);
            prop_assert_eq!(hamming_distance(a, a), 0);
            prop_assert_eq!(hamming_distance(a, b) == 0, a == b);
        }

        #[test]
        fn pixel_bounds_stay_inside_the_frame(
            width in 1u32..64,
            height in 1u32..64,
            x in 0.0f64..2.0,
            y in 0.0f64..2.0,
            w in 0.01f64..1.5,
            h in 0.01f64..1.5,
        ) {
            let frame = Frame {
                width,
                height,
                rgba: vec![0; width as usize * height as usize * 4],
            };
            let rect = ZoneRect { x, y, w, h };
            if let Some((bx, by, bw, bh)) = pixel_bounds(&frame, &rect) {
                prop_assert!(bw > 0 && bh > 0);
                prop_assert!(bx + bw <= width);
                prop_assert!(by + bh <= height);
            }
        }

        #[test]
        fn perceptual_hash_is_deterministic_across_calls(
            width in 8u32..40,
            height in 8u32..40,
            seed in any::<u64>(),
        ) {
            let mut rgba = vec![0u8; width as usize * height as usize * 4];
            let mut state = seed;
            for byte in rgba.chunks_exact_mut(4) {
                state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                byte[0] = (state >> 33) as u8;
                byte[1] = (state >> 41) as u8;
                byte[2] = (state >> 49) as u8;
                byte[3] = 255;
            }
            let frame = Frame { width, height, rgba };
            let rect = ZoneRect { x: 0.0, y: 0.0, w: 1.0, h: 1.0 };
            prop_assert_eq!(perceptual_hash(&frame, &rect), perceptual_hash(&frame, &rect));
        }

        #[test]
        fn identical_frames_never_retrigger_after_baseline(
            width in 8u32..24,
            height in 8u32..24,
        ) {
            let mut rgba = vec![90u8; width as usize * height as usize * 4];
            for (index, byte) in rgba.iter_mut().enumerate() {
                if index % 4 != 3 {
                    *byte = (index % 251) as u8;
                }
            }
            let frame = Frame { width, height, rgba };
            let mut detector = ZoneChangeDetector::new(ZoneChangeDetectorConfig::default());
            prop_assert!(detector.detect(&frame).changed);
            let result = detector.detect(&frame);
            prop_assert!(!result.changed);
        }
    }
}
