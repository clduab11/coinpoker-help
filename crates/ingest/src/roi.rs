//! Region-of-interest cropping and downscaling for VLM submissions.
//!
//! Shrinks frames before they reach the vision model: cropping removes
//! non-table window chrome (title bars, sidebars, chat) and downscaling
//! bounds the encoded image size. Fewer pixels means faster prefill and
//! lower latency, with no loss of decision-relevant detail when the ROI
//! covers the table.

use thiserror::Error;

use crate::capture::{Frame, FrameError};
use crate::change_detect::{pixel_bounds, ZoneRect};

/// Errors produced while preparing a frame ROI.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum RoiError {
    /// The frame buffer does not match its declared dimensions.
    #[error("invalid frame: {0}")]
    InvalidFrame(#[from] FrameError),
    /// The ROI covers no pixels.
    #[error("ROI covers no pixels: {0}")]
    EmptyRegion(String),
}

/// Configuration for frame preprocessing before a VLM call.
#[derive(Debug, Clone, PartialEq)]
pub struct RoiConfig {
    /// The region of the captured window that contains the table, in
    /// normalized frame coordinates.
    pub rect: ZoneRect,
    /// Downscale so the submitted image is at most this many pixels wide.
    /// `0` disables downscaling.
    pub max_width: u32,
}

impl Default for RoiConfig {
    fn default() -> Self {
        Self {
            // The full window by default: the table layout is not known
            // ahead of calibration, so nothing is cropped without explicit
            // configuration.
            rect: ZoneRect {
                x: 0.0,
                y: 0.0,
                w: 1.0,
                h: 1.0,
            },
            max_width: 1280,
        }
    }
}

/// Crop `frame` to the configured ROI and downscale to the configured width.
///
/// Downscaling uses a triangle filter: it is fast and, at the resolutions
/// involved, preserves card and chip legibility. Frames already within the
/// size bound are returned cropped but unscaled.
pub fn apply_roi(frame: &Frame, config: &RoiConfig) -> Result<Frame, RoiError> {
    frame.validate()?;

    let (x0, y0, w, h) = pixel_bounds(frame, &config.rect).ok_or_else(|| {
        RoiError::EmptyRegion(format!(
            "rect x={} y={} w={} h={} on {}x{}",
            config.rect.x, config.rect.y, config.rect.w, config.rect.h, frame.width, frame.height
        ))
    })?;

    let cropped = crop(frame, x0, y0, w, h)?;

    if config.max_width > 0 && cropped.width > config.max_width {
        downscale(&cropped, config.max_width)
    } else {
        Ok(cropped)
    }
}

/// Copy a rectangular region of a frame into a new frame.
fn crop(frame: &Frame, x0: u32, y0: u32, w: u32, h: u32) -> Result<Frame, RoiError> {
    let src_row = frame.bytes_per_row();
    let dst_row = w as usize * 4;
    let mut rgba = Vec::with_capacity(dst_row * h as usize);
    for y in y0..y0 + h {
        let start = y as usize * src_row + x0 as usize * 4;
        rgba.extend_from_slice(&frame.rgba[start..start + dst_row]);
    }
    Ok(Frame::new(w, h, rgba)?)
}

/// Downscale a frame to `max_width` pixels, preserving aspect ratio.
fn downscale(frame: &Frame, max_width: u32) -> Result<Frame, RoiError> {
    let source = frame.to_rgba_image()?;
    let scale = f64::from(max_width) / f64::from(frame.width);
    let target_w = max_width;
    let target_h = ((f64::from(frame.height) * scale).round() as u32).max(1);
    let resized = image::imageops::resize(
        &source,
        target_w,
        target_h,
        image::imageops::FilterType::Triangle,
    );

    let (width, height) = resized.dimensions();
    Ok(Frame::new(width, height, resized.into_raw())?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gradient_frame(width: u32, height: u32) -> Frame {
        let mut rgba = vec![0u8; width as usize * height as usize * 4];
        for (index, pixel) in rgba.chunks_exact_mut(4).enumerate() {
            let value = (index % 256) as u8;
            pixel[0] = value;
            pixel[1] = value;
            pixel[2] = value;
            pixel[3] = 255;
        }
        Frame {
            width,
            height,
            rgba,
        }
    }

    fn config(rect: ZoneRect, max_width: u32) -> RoiConfig {
        RoiConfig { rect, max_width }
    }

    fn full_rect() -> ZoneRect {
        ZoneRect {
            x: 0.0,
            y: 0.0,
            w: 1.0,
            h: 1.0,
        }
    }

    #[test]
    fn default_config_covers_the_full_frame() {
        let frame = gradient_frame(64, 32);
        let result = apply_roi(&frame, &RoiConfig::default()).expect("full-frame ROI");
        assert_eq!((result.width, result.height), (64, 32));
        assert_eq!(result.rgba, frame.rgba);
    }

    #[test]
    fn crop_removes_surrounding_chrome() {
        let frame = gradient_frame(100, 50);
        let rect = ZoneRect {
            x: 0.25,
            y: 0.5,
            w: 0.5,
            h: 0.25,
        };
        let result = apply_roi(&frame, &config(rect, 0)).expect("crop");
        assert_eq!((result.width, result.height), (50, 13));

        // The cropped pixels are the source region, not a rescale.
        assert_eq!(result.rgba.len(), 50 * 13 * 4);
        let src_row = frame.bytes_per_row();
        let dst_row = result.bytes_per_row();
        assert_eq!(
            &result.rgba[..dst_row],
            &frame.rgba[25 * src_row + 100..25 * src_row + 100 + dst_row]
        );
    }

    #[test]
    fn downscale_bounds_width_and_preserves_aspect() {
        let frame = gradient_frame(1920, 1080);
        let result = apply_roi(&frame, &config(full_rect(), 1280)).expect("downscale");
        assert_eq!(result.width, 1280);
        assert_eq!(result.height, 720);
    }

    #[test]
    fn small_frames_are_not_upscaled() {
        let frame = gradient_frame(64, 32);
        let result = apply_roi(&frame, &config(full_rect(), 1280)).expect("no rescale");
        assert_eq!((result.width, result.height), (64, 32));
    }

    #[test]
    fn zero_max_width_disables_downscaling() {
        let frame = gradient_frame(1920, 1080);
        let result = apply_roi(&frame, &config(full_rect(), 0)).expect("no rescale");
        assert_eq!(result.width, 1920);
    }

    #[test]
    fn empty_roi_is_rejected() {
        let frame = gradient_frame(64, 32);
        let rect = ZoneRect {
            x: 2.0,
            y: 0.0,
            w: 0.5,
            h: 0.5,
        };
        let err = apply_roi(&frame, &config(rect, 1280)).expect_err("out-of-frame rect");
        assert!(matches!(err, RoiError::EmptyRegion(_)));
    }

    #[test]
    fn malformed_frame_is_rejected() {
        let frame = Frame {
            width: 4,
            height: 4,
            rgba: vec![0; 15],
        };
        let err = apply_roi(&frame, &RoiConfig::default()).expect_err("malformed");
        assert!(matches!(err, RoiError::InvalidFrame(_)));
    }

    #[test]
    fn extreme_downscale_keeps_at_least_one_row() {
        let frame = gradient_frame(1920, 2);
        let result = apply_roi(&frame, &config(full_rect(), 64)).expect("downscale");
        assert_eq!(result.width, 64);
        assert!(result.height >= 1);
        assert!(result.validate().is_ok());
    }
}
