//! Region geometry shared with `scripts/laya_prep.py` (`content_rect`, `box_px`).
//!
//! The integer results MUST equal the Python functions. Python's `round` rounds
//! half to even, so this module uses [`f64::round_ties_even`]; for every size
//! that is not an exact `.5` tie the result also equals `f64::round`.

use std::collections::HashMap;
use std::sync::OnceLock;

use image::RgbaImage;
use serde::Deserialize;

const REGIONS_JSON: &str = include_str!("../../assets/laya/regions.json");

/// `coinpoker-laya-regions/1`.
#[derive(Debug, Clone, Deserialize)]
pub struct Regions {
    pub schema: String,
    pub version: String,
    pub layout: String,
    pub geometry: Geometry,
    /// Normalized content boxes `[u0, v0, u1, v1]`.
    pub regions: HashMap<String, [f64; 4]>,
    #[serde(default)]
    pub provisional: Vec<String>,
}

#[derive(Debug, Clone, Copy, Deserialize)]
pub struct Geometry {
    pub title_bar_px: i64,
    pub title_bar_range_px: [i64; 2],
    pub content_aspect: f64,
    pub min_crop_px: u32,
}

/// The vendored region set (parsed once).
pub fn regions() -> &'static Regions {
    static REGIONS: OnceLock<Regions> = OnceLock::new();
    REGIONS
        .get_or_init(|| serde_json::from_str(REGIONS_JSON).expect("vendored regions.json is valid"))
}

/// `(x0, y0, cw, ch)` of the content area below CoinPoker's unscaled title bar.
pub fn content_rect(w: u32, h: u32) -> (u32, u32, u32, u32) {
    let g = regions().geometry;
    let (w, h) = (i64::from(w), i64::from(h));
    let aspect = g.content_aspect;
    let round = |value: f64| value.round_ties_even() as i64;
    let t = h - round(w as f64 / aspect);
    let rect = if (g.title_bar_range_px[0]..=g.title_bar_range_px[1]).contains(&t) {
        (0, t, w, h - t)
    } else {
        let avail_h = h - g.title_bar_px;
        if avail_h <= 0 {
            (0, g.title_bar_px, w, 0)
        } else if w as f64 / avail_h as f64 > aspect {
            // pillarbox
            let cw = round(avail_h as f64 * aspect);
            ((w - cw).div_euclid(2), g.title_bar_px, cw, avail_h)
        } else {
            // letterbox
            let ch = round(w as f64 / aspect);
            (0, g.title_bar_px + (avail_h - ch).div_euclid(2), w, ch)
        }
    };
    let clamp = |v: i64| v.clamp(0, i64::from(u32::MAX)) as u32;
    (clamp(rect.0), clamp(rect.1), clamp(rect.2), clamp(rect.3))
}

/// Normalized content box -> integer px `(a, b, c, d)` (floor start, ceil end, clamped).
pub fn box_px(region: [f64; 4], w: u32, h: u32) -> (u32, u32, u32, u32) {
    let (x0, y0, cw, ch) = content_rect(w, h);
    let [u0, v0, u1, v1] = region;
    let (x0, y0, cw, ch) = (f64::from(x0), f64::from(y0), f64::from(cw), f64::from(ch));
    let clamp = |v: f64, max: u32| (v as i64).clamp(0, i64::from(max)) as u32;
    (
        clamp((x0 + u0 * cw).floor(), w),
        clamp((y0 + v0 * ch).floor(), h),
        clamp((x0 + u1 * cw).ceil(), w),
        clamp((y0 + v1 * ch).ceil(), h),
    )
}

/// Pixel box of a named region, or `None` for an unknown name.
pub fn region_px(name: &str, w: u32, h: u32) -> Option<(u32, u32, u32, u32)> {
    regions()
        .regions
        .get(name)
        .map(|region| box_px(*region, w, h))
}

/// Crop a named region; `None` for unknown regions or crops under `min_crop_px`.
pub fn crop(frame: &RgbaImage, region: &str) -> Option<RgbaImage> {
    let (a, b, c, d) = region_px(region, frame.width(), frame.height())?;
    let min = regions().geometry.min_crop_px;
    let (width, height) = (c.saturating_sub(a), d.saturating_sub(b));
    if width < min || height < min {
        return None;
    }
    Some(image::imageops::crop_imm(frame, a, b, width, height).to_image())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regions_asset_parses() {
        let r = regions();
        assert_eq!(r.schema, "coinpoker-laya-regions/1");
        assert_eq!(r.version, "0.4.0");
        assert_eq!(r.geometry.min_crop_px, 8);
        assert_eq!(r.regions.len(), 20);
    }

    /// Expected values computed with `scripts/laya_prep.content_rect`; none of
    /// these sizes hits an exact `.5` rounding tie.
    #[test]
    fn content_rect_matches_python() {
        for (size, expected) in [
            ((800, 613), (0, 28, 800, 585)),
            ((1015, 770), (0, 28, 1015, 742)),
            ((1280, 963), (0, 27, 1280, 936)),
            ((1280, 720), (167, 28, 946, 692)),
            ((800, 700), (0, 71, 800, 585)),
            ((1280, 778), (127, 28, 1026, 750)),
            ((100, 20), (0, 28, 100, 0)),
        ] {
            assert_eq!(content_rect(size.0, size.1), expected, "{size:?}");
        }
    }

    #[test]
    fn box_px_matches_python() {
        for (size, region, expected) in [
            ((800, 613), "board_slot_1", (248, 247, 309, 332)),
            ((800, 613), "pot", (320, 222, 512, 247)),
            ((1015, 770), "board_slot_1", (315, 306, 391, 413)),
            ((1015, 770), "pot", (406, 275, 650, 305)),
            ((1015, 770), "board_slot_5", (624, 306, 700, 413)),
            ((1280, 720), "board_slot_1", (461, 287, 532, 387)),
            ((1280, 720), "pot", (545, 258, 773, 287)),
            ((800, 700), "board_slot_1", (248, 290, 309, 375)),
            ((800, 700), "pot", (320, 265, 512, 290)),
            ((1280, 963), "board_slot_1", (398, 378, 494, 512)),
            ((1280, 963), "pot", (512, 338, 820, 377)),
            ((1280, 778), "seat_controls", (783, 706, 1153, 771)),
            ((100, 20), "pot", (40, 20, 64, 20)),
        ] {
            assert_eq!(
                region_px(region, size.0, size.1),
                Some(expected),
                "{size:?} {region}"
            );
        }
    }

    #[test]
    fn crops_have_the_box_size_and_tiny_crops_are_refused() {
        let frame = RgbaImage::from_pixel(800, 613, image::Rgba([1, 2, 3, 255]));
        let slot = crop(&frame, "board_slot_1").expect("slot crop");
        assert_eq!((slot.width(), slot.height()), (309 - 248, 332 - 247));
        assert!(crop(&frame, "no_such_region").is_none());
        let tiny = RgbaImage::from_pixel(100, 20, image::Rgba([1, 2, 3, 255]));
        assert!(crop(&tiny, "pot").is_none());
        let small = RgbaImage::from_pixel(60, 60, image::Rgba([1, 2, 3, 255]));
        assert!(crop(&small, "pot").is_none(), "pot is only ~2 px tall here");
    }
}
