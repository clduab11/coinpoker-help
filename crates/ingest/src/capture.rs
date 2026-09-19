//! Window capture via ScreenCaptureKit (macOS).
//!
//! Targets the CoinPoker application window by title/application-name match
//! and returns frames as raw RGBA pixel buffers. On macOS 14+ this uses the
//! single-frame screenshot API (`SCScreenshotManager`), which suits the
//! poll-based change-detection pipeline better than a continuous stream.
//!
//! On non-macOS hosts the crate remains buildable, but capturer construction
//! fails immediately with [`CaptureError::UnsupportedPlatform`].

use thiserror::Error;

/// Errors produced by the capture layer.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum CaptureError {
    /// Screen capture is only implemented for macOS 14+.
    #[error("screen capture is only supported on macOS 14+")]
    UnsupportedPlatform,
    /// The capture backend returned an error.
    #[error("capture backend error: {0}")]
    Backend(String),
    /// No window matching the configured title/application name was found.
    #[error("target window not found (title/app: {0})")]
    WindowNotFound(String),
    /// Screen Recording permission has not been granted.
    #[error(
        "permission denied: grant Screen Recording access in System Settings > Privacy & Security"
    )]
    PermissionDenied,
}

/// Errors produced when constructing or converting a [`Frame`].
#[derive(Debug, Error, PartialEq, Eq)]
pub enum FrameError {
    /// The declared dimensions cannot be represented as a packed RGBA buffer.
    #[error("frame dimensions {width}x{height} overflow the RGBA buffer size")]
    DimensionsOverflow { width: u32, height: u32 },
    /// The pixel buffer length does not match the declared dimensions.
    #[error("invalid RGBA buffer length: expected {expected} bytes, got {actual}")]
    InvalidBufferLength { expected: usize, actual: usize },
}

/// Configuration for the window capturer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CaptureConfig {
    /// Substring matched against window titles to find the target window.
    pub window_title: String,
    /// Fallback substring matched against the owning application name.
    pub app_name: String,
    /// Target capture width in pixels.
    pub width: u32,
    /// Target capture height in pixels.
    pub height: u32,
}

impl Default for CaptureConfig {
    fn default() -> Self {
        Self {
            window_title: "CoinPoker".to_string(),
            app_name: "CoinPoker".to_string(),
            width: 1920,
            height: 1080,
        }
    }
}

/// A single captured frame as tightly-packed RGBA8 pixels.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    /// Frame width in pixels.
    pub width: u32,
    /// Frame height in pixels.
    pub height: u32,
    /// `width * height * 4` bytes, row-major, RGBA order.
    pub rgba: Vec<u8>,
}

impl Frame {
    /// Construct a frame after checking that the buffer matches its dimensions.
    pub fn new(width: u32, height: u32, rgba: Vec<u8>) -> Result<Self, FrameError> {
        let frame = Self {
            width,
            height,
            rgba,
        };
        frame.validate()?;
        Ok(frame)
    }

    /// Number of bytes per row (tightly packed).
    pub fn bytes_per_row(&self) -> usize {
        self.width as usize * 4
    }

    /// Check that the pixel buffer exactly matches the declared dimensions.
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

    /// Convert into an `image`-crate RGBA image for downstream consumers.
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

/// A shareable window descriptor, used for calibration and debugging.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowInfo {
    pub title: Option<String>,
    pub app_name: Option<String>,
    pub on_screen: bool,
}

#[cfg(any(target_os = "macos", test))]
fn match_priority(
    title: Option<&str>,
    app_name: Option<&str>,
    config: &CaptureConfig,
) -> Option<u8> {
    if !config.window_title.is_empty()
        && title.is_some_and(|title| title.contains(&config.window_title))
    {
        Some(0)
    } else if !config.app_name.is_empty()
        && app_name.is_some_and(|app| app.contains(&config.app_name))
    {
        Some(1)
    } else {
        None
    }
}

/// Captures frames from a target application window.
///
/// The macOS backend is selected at compile time; construction fails with
/// [`CaptureError::UnsupportedPlatform`] on other platforms.
pub struct WindowCapturer {
    #[cfg(target_os = "macos")]
    inner: macos::MacCapturer,
}

impl WindowCapturer {
    /// Locate the target window and prepare the capture backend.
    pub fn new(config: CaptureConfig) -> Result<Self, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            Ok(Self {
                inner: macos::MacCapturer::new(&config)?,
            })
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = config;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// List all windows currently exposed by the platform's shareable-content API.
    ///
    /// This is an associated function so calibration does not require locating a
    /// configured target window first.
    pub fn list_windows() -> Result<Vec<WindowInfo>, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            macos::list_windows()
        }
        #[cfg(not(target_os = "macos"))]
        {
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// Capture a single frame of the target window.
    pub fn capture_frame(&self) -> Result<Frame, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            self.inner.capture()
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// List candidate windows matching the configured title/application name.
    ///
    /// Useful for calibration: run once to confirm the target window is
    /// discoverable and to inspect the exact title used by the client.
    pub fn list_candidate_windows(&self) -> Result<Vec<WindowInfo>, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            macos::list_candidate_windows(&self.inner.config)
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }
}

#[cfg(target_os = "macos")]
mod macos {
    use super::*;
    use screencapturekit::prelude::*;
    use screencapturekit::screenshot_manager::{CGImageExt, SCScreenshotManager};
    use screencapturekit::shareable_content::SCShareableContent;
    use screencapturekit::stream::configuration::SCStreamConfiguration;
    use screencapturekit::stream::content_filter::SCContentFilter;

    /// macOS backend: a window content filter plus a screenshot configuration.
    pub(super) struct MacCapturer {
        pub(super) config: CaptureConfig,
        filter: SCContentFilter,
        stream_config: SCStreamConfiguration,
    }

    impl MacCapturer {
        pub(super) fn new(config: &CaptureConfig) -> Result<Self, CaptureError> {
            let content =
                SCShareableContent::get().map_err(|e| CaptureError::Backend(e.to_string()))?;

            let window = find_window(&content, config)
                .ok_or_else(|| CaptureError::WindowNotFound(config.window_title.clone()))?;

            let filter = SCContentFilter::create().with_window(&window).build();
            let stream_config = SCStreamConfiguration::new()
                .with_width(config.width)
                .with_height(config.height)
                .with_pixel_format(PixelFormat::BGRA);

            Ok(Self {
                config: config.clone(),
                filter,
                stream_config,
            })
        }

        pub(super) fn capture(&self) -> Result<Frame, CaptureError> {
            let image = SCScreenshotManager::capture_image(&self.filter, &self.stream_config)
                .map_err(|e| CaptureError::Backend(e.to_string()))?;

            let width = image.width() as u32;
            let height = image.height() as u32;
            let rgba = image
                .rgba_data()
                .map_err(|e| CaptureError::Backend(e.to_string()))?;

            Frame::new(width, height, rgba).map_err(|e| CaptureError::Backend(e.to_string()))
        }
    }

    /// Find the first on-screen title match, falling back to the first owning
    /// application match only when no title matches.
    fn find_window(
        content: &SCShareableContent,
        config: &CaptureConfig,
    ) -> Option<screencapturekit::shareable_content::window::SCWindow> {
        content
            .windows()
            .into_iter()
            .filter(|window| window.is_on_screen())
            .filter_map(|window| {
                let title = window.title();
                let app_name = window
                    .owning_application()
                    .map(|application| application.application_name());
                match_priority(title.as_deref(), app_name.as_deref(), config)
                    .map(|priority| (priority, window))
            })
            .min_by_key(|(priority, _)| *priority)
            .map(|(_, window)| window)
    }

    pub(super) fn list_windows() -> Result<Vec<WindowInfo>, CaptureError> {
        let content =
            SCShareableContent::get().map_err(|e| CaptureError::Backend(e.to_string()))?;

        Ok(content
            .windows()
            .into_iter()
            .map(|w| WindowInfo {
                title: w.title(),
                app_name: w.owning_application().map(|a| a.application_name()),
                on_screen: w.is_on_screen(),
            })
            .collect())
    }

    pub(super) fn list_candidate_windows(
        config: &CaptureConfig,
    ) -> Result<Vec<WindowInfo>, CaptureError> {
        Ok(list_windows()?
            .into_iter()
            .filter(|window| {
                window.on_screen
                    && match_priority(window.title.as_deref(), window.app_name.as_deref(), config)
                        .is_some()
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_targets_coinpoker() {
        let cfg = CaptureConfig::default();
        assert_eq!(cfg.window_title, "CoinPoker");
        assert_eq!(cfg.app_name, "CoinPoker");
        assert_eq!(cfg.width, 1920);
        assert_eq!(cfg.height, 1080);
    }

    #[test]
    fn title_matches_take_priority_over_application_fallbacks() {
        let config = CaptureConfig {
            window_title: "Table 42".to_string(),
            app_name: "CoinPoker".to_string(),
            ..CaptureConfig::default()
        };

        assert_eq!(
            match_priority(Some("Table 42 - NLH"), Some("CoinPoker"), &config),
            Some(0)
        );
        assert_eq!(
            match_priority(Some("Lobby"), Some("CoinPoker"), &config),
            Some(1)
        );
        assert_eq!(
            match_priority(Some("Other"), Some("Browser"), &config),
            None
        );
    }

    #[test]
    fn empty_selectors_do_not_match_every_window() {
        let config = CaptureConfig {
            window_title: String::new(),
            app_name: String::new(),
            ..CaptureConfig::default()
        };
        assert_eq!(
            match_priority(Some("Any window"), Some("Any app"), &config),
            None
        );
    }

    #[test]
    fn frame_bytes_per_row_is_tightly_packed() {
        let frame = Frame {
            width: 3,
            height: 2,
            rgba: vec![0u8; 3 * 2 * 4],
        };
        assert_eq!(frame.bytes_per_row(), 12);
        let img = frame.to_rgba_image().expect("valid frame");
        assert_eq!(img.width(), 3);
        assert_eq!(img.height(), 2);
    }

    #[test]
    fn malformed_frame_conversion_returns_error() {
        let frame = Frame {
            width: 2,
            height: 2,
            rgba: vec![0u8; 15],
        };

        assert_eq!(
            frame.to_rgba_image(),
            Err(FrameError::InvalidBufferLength {
                expected: 16,
                actual: 15,
            })
        );
        assert!(matches!(
            Frame::new(2, 2, vec![0u8; 15]),
            Err(FrameError::InvalidBufferLength { .. })
        ));
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn non_macos_capture_fails_fast() {
        assert!(matches!(
            WindowCapturer::new(CaptureConfig::default()),
            Err(CaptureError::UnsupportedPlatform)
        ));
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn non_macos_window_listing_fails_without_construction() {
        assert_eq!(
            WindowCapturer::list_windows(),
            Err(CaptureError::UnsupportedPlatform)
        );
    }
}
