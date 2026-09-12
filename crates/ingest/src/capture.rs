//! Window capture via ScreenCaptureKit (macOS).
//!
//! Targets the CoinPoker application window by title/application-name match
//! and returns frames as raw RGBA pixel buffers. On macOS 14+ this uses the
//! single-frame screenshot API (`SCScreenshotManager`), which suits the
//! poll-based change-detection pipeline better than a continuous stream.
//!
//! On non-macOS hosts the capturer is a no-op stub so the workspace remains
//! buildable anywhere; `capture_frame` returns [`CaptureError::UnsupportedPlatform`].

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
    /// Number of bytes per row (tightly packed).
    pub fn bytes_per_row(&self) -> usize {
        self.width as usize * 4
    }

    /// Convert into an `image`-crate RGBA image for downstream consumers.
    pub fn to_rgba_image(&self) -> image::RgbaImage {
        image::RgbaImage::from_raw(self.width, self.height, self.rgba.clone())
            .expect("frame buffer size always matches width * height * 4")
    }
}

/// A shareable window descriptor, used for calibration and debugging.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowInfo {
    pub title: Option<String>,
    pub app_name: Option<String>,
    pub on_screen: bool,
}

/// Captures frames from a target application window.
///
/// The macOS backend is selected at compile time; on other platforms the
/// struct is an inert stub that always reports [`CaptureError::UnsupportedPlatform`].
pub struct WindowCapturer {
    #[cfg(target_os = "macos")]
    inner: macos::MacCapturer,
    #[cfg(not(target_os = "macos"))]
    config: CaptureConfig,
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
            Ok(Self { config })
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
            let _ = &self.config;
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
            macos::list_windows(&self.inner.config)
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = &self.config;
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

            Ok(Frame {
                width,
                height,
                rgba,
            })
        }
    }

    /// Find the first on-screen window whose title or owning application
    /// matches the configured substrings.
    fn find_window(
        content: &SCShareableContent,
        config: &CaptureConfig,
    ) -> Option<screencapturekit::shareable_content::window::SCWindow> {
        content
            .windows()
            .into_iter()
            .filter(|w| w.is_on_screen())
            .find(|w| {
                let title_match = w
                    .title()
                    .map(|t| t.contains(&config.window_title))
                    .unwrap_or(false);
                let app_match = w
                    .owning_application()
                    .map(|a| a.application_name().contains(&config.app_name))
                    .unwrap_or(false);
                title_match || app_match
            })
    }

    pub(super) fn list_windows(config: &CaptureConfig) -> Result<Vec<WindowInfo>, CaptureError> {
        let content =
            SCShareableContent::get().map_err(|e| CaptureError::Backend(e.to_string()))?;

        let windows = content
            .windows()
            .into_iter()
            .filter(|w| {
                let title_match = w
                    .title()
                    .map(|t| t.contains(&config.window_title))
                    .unwrap_or(false);
                let app_match = w
                    .owning_application()
                    .map(|a| a.application_name().contains(&config.app_name))
                    .unwrap_or(false);
                title_match || app_match
            })
            .map(|w| WindowInfo {
                title: w.title(),
                app_name: w.owning_application().map(|a| a.application_name()),
                on_screen: w.is_on_screen(),
            })
            .collect();

        Ok(windows)
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
    fn frame_bytes_per_row_is_tightly_packed() {
        let frame = Frame {
            width: 3,
            height: 2,
            rgba: vec![0u8; 3 * 2 * 4],
        };
        assert_eq!(frame.bytes_per_row(), 12);
        let img = frame.to_rgba_image();
        assert_eq!(img.width(), 3);
        assert_eq!(img.height(), 2);
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn non_macos_capture_is_unsupported() {
        let capturer = WindowCapturer::new(CaptureConfig::default()).expect("stub constructs");
        let err = capturer.capture_frame().expect_err("capture must fail");
        assert_eq!(err, CaptureError::UnsupportedPlatform);
        assert!(capturer.list_candidate_windows().is_err());
    }
}
