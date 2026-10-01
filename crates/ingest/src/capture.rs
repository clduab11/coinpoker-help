//! Window-only capture on Windows 10 version 1903 and later.
//!
//! Discovery reads Win32 window metadata without pixels. Selection rechecks the
//! executable, PID, HWND, title, visibility, and bounds before creating a
//! `Windows.Graphics.Capture` item with `CreateForWindow`. No desktop capture or
//! input APIs are used. Other platforms retain the library's stdin path.

use serde::{Deserialize, Serialize};
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
}

/// A single captured frame as tightly packed RGBA8 pixels.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    pub width: u32,
    pub height: u32,
    /// `width * height * 4` bytes, row-major, RGBA order.
    pub rgba: Vec<u8>,
}

impl Frame {
    pub fn new(width: u32, height: u32, rgba: Vec<u8>) -> Result<Self, FrameError> {
        let frame = Self {
            width,
            height,
            rgba,
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
        Ok(())
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
pub trait CaptureSource {
    fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError>;
    fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError>;
    fn capture(&mut self) -> Result<Frame, CaptureError>;
    fn reset(&mut self);
}

/// Default platform adapter. Construction performs no discovery or capture.
#[derive(Default)]
pub struct PlatformCapture {
    capturer: Option<WindowCapturer>,
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
        self.capturer = Some(WindowCapturer::for_window(window)?);
        Ok(())
    }

    fn capture(&mut self) -> Result<Frame, CaptureError> {
        let result = self
            .capturer
            .as_mut()
            .ok_or(CaptureError::NoWindowSelected)?
            .capture_frame();
        if result.is_err() {
            self.reset();
        }
        result
    }

    fn reset(&mut self) {
        self.capturer = None;
    }
}

/// Captures a selected Windows application window.
pub struct WindowCapturer {
    #[cfg(target_os = "windows")]
    inner: crate::windows::WindowsCapturer,
}

impl WindowCapturer {
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
    fn frame_requires_exact_packed_rgba_length() {
        assert!(matches!(
            Frame::new(2, 2, vec![0; 15]),
            Err(FrameError::InvalidBufferLength { .. })
        ));
        let frame = Frame::new(2, 2, vec![7; 16]).unwrap();
        assert_eq!(frame.bytes_per_row(), 8);
        assert_eq!(frame.to_rgba_image().unwrap().as_raw(), &vec![7; 16]);
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
