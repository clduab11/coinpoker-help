//! Selected-window capture on Windows 10 version 1903 and later.
//!
//! Discovery reads Win32 window metadata without pixels. Selection rechecks the
//! executable, PID, HWND, title, visibility, and bounds before creating a
//! `Windows.Graphics.Capture` item with `CreateForWindow`. The explicit visible
//! desktop adapter copies displayed pixels with regional owned-popup masks;
//! neither adapter focuses windows or supplies input. Other platforms retain stdin.

use serde::{Deserialize, Serialize};
use std::time::Instant;
use thiserror::Error;

use crate::discovery::TableIdentity;
pub use crate::discovery::{ApplicationInfo, DiscoverySnapshot};

/// Errors produced by the capture layer.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum CaptureError {
    #[error("live window capture is supported only on Windows 10 version 1903 or later")]
    UnsupportedPlatform,
    #[error("Windows Graphics Capture requires Windows 10 version 1903 (build 18362) or later")]
    UnsupportedWindowsVersion,
    #[error("capture backend error: {0}")]
    Backend(String),
    #[error("target window not found: {0}")]
    WindowNotFound(String),
    #[error("configure an exact executable name before capture")]
    ConfigurationRequired,
    #[error("multiple matching windows; configure an HWND or a narrower table title")]
    AmbiguousWindows,
    #[error("window 0x{hwnd:x} is stale or unavailable; rediscover before capture")]
    StaleWindow { hwnd: usize },
    #[error("no window selected; discover and select a window before capture")]
    NoWindowSelected,
    #[error("Windows denied access to this window's capture content")]
    PermissionDenied,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum FrameError {
    #[error("frame dimensions {width}x{height} overflow the RGBA buffer size")]
    DimensionsOverflow { width: u32, height: u32 },
    #[error("invalid RGBA buffer length: expected {expected} bytes, got {actual}")]
    InvalidBufferLength { expected: usize, actual: usize },
    #[error("invalid frame visibility or popup capture metadata")]
    InvalidVisibility,
}

pub const MAX_OWNED_POPUPS: usize = 4;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PixelSource {
    /// Caller-supplied/offline pixels, not a verified desktop-source assertion.
    #[default]
    Unspecified,
    SelectedWindowSurface,
    VisibleDesktopPixels,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FrameReadability {
    #[default]
    Full,
    Regional,
    Unknown,
}

/// OS ownership is not profile/seat/player qualification. Bounds are original
/// table-relative edges, intentionally signed and NOT clipped to the table PNG.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OwnedPopup {
    #[serde(with = "crate::discovery::hwnd_serde")]
    pub hwnd: usize,
    #[serde(with = "crate::discovery::hwnd_serde")]
    pub owner_hwnd: usize,
    #[serde(with = "crate::discovery::hwnd_serde")]
    pub root_owner_hwnd: usize,
    pub process_id: u32,
    pub process_created_at_100ns: u64,
    pub window_class: String,
    pub relative_bounds: [i64; 4],
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrameVisibility {
    pub pixel_source: PixelSource,
    pub source_process_created_at_100ns: Option<u64>,
    pub readability: FrameReadability,
    /// Clipped table-relative half-open rectangles. Any overlap is unreadable.
    pub occluded_regions: Vec<[u32; 4]>,
    pub owned_popups: Vec<OwnedPopup>,
}

impl FrameVisibility {
    fn valid_for(&self, width: u32, height: u32) -> bool {
        self.occluded_regions.len() <= MAX_OWNED_POPUPS
            && self.owned_popups.len() <= MAX_OWNED_POPUPS
            && (self.pixel_source != PixelSource::VisibleDesktopPixels
                || self.source_process_created_at_100ns.is_some_and(|n| n > 0))
            && (self.readability != FrameReadability::Full || self.occluded_regions.is_empty())
            && self
                .occluded_regions
                .iter()
                .all(|[l, t, r, b]| l < r && t < b && *r <= width && *b <= height)
            && self.owned_popups.iter().all(|popup| {
                let [l, t, r, b] = popup.relative_bounds;
                let clipped = [
                    l.max(0),
                    t.max(0),
                    r.min(i64::from(width)),
                    b.min(i64::from(height)),
                ];
                popup.hwnd != 0
                    && popup.owner_hwnd != 0
                    && popup.root_owner_hwnd != 0
                    && popup.process_id != 0
                    && popup.process_created_at_100ns != 0
                    && !popup.window_class.is_empty()
                    && l < r
                    && t < b
                    && r.checked_sub(l).is_some_and(|n| n <= i64::from(i32::MAX))
                    && b.checked_sub(t).is_some_and(|n| n <= i64::from(i32::MAX))
                    && (clipped[0] >= clipped[2]
                        || clipped[1] >= clipped[3]
                        || self.occluded_regions.contains(&clipped.map(|n| n as u32)))
            })
    }

    pub fn region_readable(&self, width: u32, height: u32, bounds: [u32; 4]) -> bool {
        let [l, t, r, b] = bounds;
        self.valid_for(width, height)
            && self.readability != FrameReadability::Unknown
            && l < r
            && t < b
            && r <= width
            && b <= height
            && !self
                .occluded_regions
                .iter()
                .any(|[a, c, d, e]| l < *d && r > *a && t < *e && b > *c)
    }
}

/// A distinct synchronous desktop copy, never composited into the table frame.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapturedPopup {
    pub window: OwnedPopup,
    pub frame: Box<Frame>,
    pub source_utc_unix_ms: u64,
    pub started: Instant,
}

/// Original capture-call receipt carried WITH the queued pixels, not looked up
/// by nearby timestamps. Paths, window titles and popup ownership stay private.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OriginalCapture {
    pub schema_version: u8,
    pub timestamp_basis: &'static str,
    pub frame_index: u64,
    pub recording_session_id: String,
    pub capture_session_id: Option<String>,
    /// Decimal text preserves the complete u64 namespace in browser JSON.
    pub native_source_id: Option<String>,
    pub source_utc_unix_ms: u64,
    pub captured_at_monotonic_ms: u64,
    pub width: u32,
    pub height: u32,
    pub sha256: String,
    pub pixel_source: PixelSource,
    pub readability: FrameReadability,
    pub occluded_regions: Vec<[u32; 4]>,
}

/// A single captured frame as tightly packed RGBA8 pixels.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Frame {
    pub width: u32,
    pub height: u32,
    /// `width * height * 4` bytes, row-major, RGBA order.
    pub rgba: Vec<u8>,
    pub visibility: FrameVisibility,
    pub popup_frames: Vec<CapturedPopup>,
    pub original_capture: Option<OriginalCapture>,
}

impl Frame {
    pub fn new(width: u32, height: u32, rgba: Vec<u8>) -> Result<Self, FrameError> {
        let frame = Self {
            width,
            height,
            rgba,
            ..Self::default()
        };
        frame.validate()?;
        Ok(frame)
    }

    pub fn bytes_per_row(&self) -> usize {
        self.width as usize * 4
    }

    pub fn validate(&self) -> Result<(), FrameError> {
        let expected = self.expected_rgba_len()?;
        if self.rgba.len() != expected {
            return Err(FrameError::InvalidBufferLength {
                expected,
                actual: self.rgba.len(),
            });
        }
        if !self.visibility.valid_for(self.width, self.height)
            || self.popup_frames.len() > MAX_OWNED_POPUPS
            || self.popup_frames.iter().any(|popup| {
                let [l, t, r, b] = popup.window.relative_bounds;
                !self.visibility.owned_popups.contains(&popup.window)
                    || popup.source_utc_unix_ms == 0
                    || !popup.frame.popup_frames.is_empty()
                    || popup.frame.visibility.pixel_source != PixelSource::VisibleDesktopPixels
                    || popup.frame.visibility.readability != FrameReadability::Full
                    || !popup.frame.visibility.owned_popups.is_empty()
                    || r.checked_sub(l) != Some(i64::from(popup.frame.width))
                    || b.checked_sub(t) != Some(i64::from(popup.frame.height))
                    || popup.frame.validate().is_err()
            })
        {
            return Err(FrameError::InvalidVisibility);
        }
        if self.original_capture.as_ref().is_some_and(|original| {
            original.width != self.width
                || original.height != self.height
                || original.schema_version != 1
                || original.timestamp_basis != "capture_call_start"
                || original.frame_index == 0
                || original.sha256.len() != 64
                || !original
                    .sha256
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        }) {
            return Err(FrameError::InvalidVisibility);
        }
        Ok(())
    }

    pub fn region_readable(&self, bounds: [u32; 4]) -> bool {
        self.visibility
            .region_readable(self.width, self.height, bounds)
    }

    pub fn to_rgba_image(&self) -> Result<image::RgbaImage, FrameError> {
        self.validate()?;
        image::RgbaImage::from_raw(self.width, self.height, self.rgba.clone()).ok_or(
            FrameError::InvalidBufferLength {
                expected: self.expected_rgba_len()?,
                actual: self.rgba.len(),
            },
        )
    }

    fn expected_rgba_len(&self) -> Result<usize, FrameError> {
        (self.width as usize)
            .checked_mul(self.height as usize)
            .and_then(|pixels| pixels.checked_mul(4))
            .ok_or(FrameError::DimensionsOverflow {
                width: self.width,
                height: self.height,
            })
    }
}

/// Shareable metadata only; constructing this descriptor captures no pixels.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WindowInfo {
    #[serde(with = "crate::discovery::hwnd_serde")]
    pub hwnd: usize,
    pub process_id: u32,
    pub exe_name: String,
    pub title: Option<String>,
    pub on_screen: bool,
    /// Window bounds from Win32; frame dimensions come from the WGC item.
    pub width: u32,
    pub height: u32,
}

impl WindowInfo {
    pub fn identity(&self) -> TableIdentity {
        TableIdentity {
            exe_name: self.exe_name.clone(),
            process_id: self.process_id,
            hwnd: self.hwnd,
        }
    }
}

/// Mockable discovery, selection, and capture boundary.
#[derive(Debug, Clone, Copy)]
pub struct CaptureTiming {
    pub monotonic_ms: u64,
    pub utc_unix_ms: u64,
    pub started: Instant,
}

/// A source may provide the exact call-start clock shared with the runtime.
pub trait CaptureSource {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError>;
    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError>;
    fn capture(&mut self) -> Result<Frame, CaptureError>;
    fn reset(&mut self);
    fn last_capture_timing(&self) -> Option<CaptureTiming> {
        None
    }
}

/// Default platform adapter. Construction performs no discovery or capture.
#[derive(Default)]
pub struct PlatformCapture {
    capturer: Option<WindowCapturer>,
    visible_window: Option<WindowInfo>,
    visible_process_created_at_100ns: Option<u64>,
    visible_desktop_pixels: bool,
}

impl PlatformCapture {
    /// Explicit screen pixels; only selected-owned transients get regional masks.
    pub fn visible_desktop_pixels() -> Self {
        Self {
            visible_desktop_pixels: true,
            ..Self::default()
        }
    }
}

impl CaptureSource for PlatformCapture {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
        let result = WindowCapturer::discover();
        if result.is_err() {
            self.reset();
        }
        result
    }

    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError> {
        self.reset();
        if self.visible_desktop_pixels {
            self.visible_process_created_at_100ns =
                Some(WindowCapturer::verify_visible_window(window)?);
            self.visible_window = Some(window.clone());
            return Ok(());
        }
        self.capturer = Some(WindowCapturer::for_window(window)?);
        Ok(())
    }

    fn capture(&mut self) -> Result<Frame, CaptureError> {
        let result = if self.visible_desktop_pixels {
            WindowCapturer::capture_visible_frame(
                self.visible_window
                    .as_ref()
                    .ok_or(CaptureError::NoWindowSelected)?,
                self.visible_process_created_at_100ns
                    .ok_or(CaptureError::NoWindowSelected)?,
            )
        } else {
            self.capturer
                .as_mut()
                .ok_or(CaptureError::NoWindowSelected)?
                .capture_frame()
        };
        if result.is_err() {
            self.reset();
        }
        result
    }

    fn reset(&mut self) {
        self.capturer = None;
        self.visible_window = None;
        self.visible_process_created_at_100ns = None;
    }
}

/// Captures a selected Windows application window.
pub struct WindowCapturer {
    #[cfg(target_os = "windows")]
    inner: crate::windows::WindowsCapturer,
}

impl WindowCapturer {
    fn verify_visible_window(window: &WindowInfo) -> Result<u64, CaptureError> {
        #[cfg(target_os = "windows")]
        {
            crate::windows::verify_visible_window(window)
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = window;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    fn capture_visible_frame(
        window: &WindowInfo,
        process_created_at_100ns: u64,
    ) -> Result<Frame, CaptureError> {
        #[cfg(target_os = "windows")]
        {
            crate::windows::capture_visible_frame(window, process_created_at_100ns)
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = (window, process_created_at_100ns);
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    pub fn discover() -> Result<DiscoverySnapshot, CaptureError> {
        #[cfg(target_os = "windows")]
        {
            crate::windows::discover()
        }
        #[cfg(not(target_os = "windows"))]
        {
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// Select a window after revalidating its identity and current metadata.
    pub fn for_window(window: &WindowInfo) -> Result<Self, CaptureError> {
        #[cfg(target_os = "windows")]
        {
            Ok(Self {
                inner: crate::windows::WindowsCapturer::for_window(window)?,
            })
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = window;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    pub fn list_windows() -> Result<Vec<WindowInfo>, CaptureError> {
        Self::discover().map(|snapshot| snapshot.windows)
    }

    pub fn capture_frame(&mut self) -> Result<Frame, CaptureError> {
        #[cfg(target_os = "windows")]
        {
            self.inner.capture()
        }
        #[cfg(not(target_os = "windows"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn visible_desktop_capture_requires_explicit_selection_and_reset_keeps_policy() {
        let mut default = PlatformCapture::default();
        assert!(!default.visible_desktop_pixels);
        assert_eq!(default.capture(), Err(CaptureError::NoWindowSelected));
        let mut visible = PlatformCapture::visible_desktop_pixels();
        assert!(visible.visible_desktop_pixels);
        assert_eq!(visible.capture(), Err(CaptureError::NoWindowSelected));
        visible.reset();
        assert!(visible.visible_desktop_pixels);
        assert!(visible.visible_window.is_none());
        assert!(visible.capturer.is_none());
    }

    #[test]
    fn frame_requires_exact_packed_rgba_length() {
        assert!(matches!(
            Frame::new(2, 2, vec![0; 15]),
            Err(FrameError::InvalidBufferLength { .. })
        ));
        let frame = Frame::new(2, 2, vec![7; 16]).unwrap();
        assert_eq!(frame.bytes_per_row(), 8);
        assert_eq!(frame.to_rgba_image().unwrap().as_raw(), &vec![7; 16]);
    }

    #[test]
    fn regional_readability_rejects_stationary_covered_pixels_and_keeps_adjacent_crops() {
        let mut frame = Frame::new(8, 6, vec![7; 8 * 6 * 4]).unwrap();
        frame.visibility = FrameVisibility {
            pixel_source: PixelSource::VisibleDesktopPixels,
            source_process_created_at_100ns: Some(100),
            readability: FrameReadability::Regional,
            occluded_regions: vec![[2, 2, 4, 4]],
            ..FrameVisibility::default()
        };
        let stationary = frame.clone();
        assert_eq!(stationary.rgba, frame.rgba);
        assert!(!stationary.region_readable([0, 0, 8, 6]));
        assert!(!stationary.region_readable([3, 3, 5, 5]));
        assert!(stationary.region_readable([4, 2, 8, 4]));
        assert!(stationary.region_readable([0, 0, 2, 2]));
        frame.visibility.readability = FrameReadability::Unknown;
        assert!(!frame.region_readable([0, 0, 2, 2]));
        frame.visibility.readability = FrameReadability::Full;
        assert_eq!(frame.validate(), Err(FrameError::InvalidVisibility));
        assert!(!frame.region_readable([0, 0, 2, 2]));
    }

    #[test]
    fn invalid_masks_and_unverified_desktop_source_are_never_readable() {
        let mut frame = Frame::new(8, 6, vec![7; 8 * 6 * 4]).unwrap();
        frame.visibility.readability = FrameReadability::Regional;
        for bounds in [[2, 2, 2, 4], [4, 2, 2, 4], [2, 2, 9, 4], [2, 2, 4, 7]] {
            frame.visibility.occluded_regions = vec![bounds];
            assert_eq!(frame.validate(), Err(FrameError::InvalidVisibility));
            assert!(!frame.region_readable([0, 0, 1, 1]));
        }
        frame.visibility.occluded_regions.clear();
        frame.visibility.pixel_source = PixelSource::VisibleDesktopPixels;
        assert_eq!(frame.validate(), Err(FrameError::InvalidVisibility));
        frame.visibility.source_process_created_at_100ns = Some(100);
        assert!(frame.validate().is_ok());
        for bounds in [[0, 0, 0, 1], [2, 0, 1, 1], [0, 0, 9, 1], [0, 0, 1, 7]] {
            assert!(!frame.region_readable(bounds));
        }
    }

    #[cfg(not(target_os = "windows"))]
    #[test]
    fn live_capture_is_unsupported_off_windows() {
        assert_eq!(
            WindowCapturer::discover(),
            Err(CaptureError::UnsupportedPlatform)
        );
    }
}
