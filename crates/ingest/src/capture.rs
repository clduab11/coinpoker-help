//! Window capture via ScreenCaptureKit (macOS).
//!
//! Targets the CoinPoker application window by title/application-name match
//! and delivers frames through a continuous [`SCStream`] that uses a
//! window-scoped [`SCContentFilter`]. Frames arrive on a ScreenCaptureKit
//! dispatch queue via an output-handler callback (an SCStream delegate
//! pattern); the capturer exposes the most recent complete frame to callers
//! without blocking.
//!
//! The delegate records unexpected stream stops (window closed, permission
//! revoked) so the pipeline can distinguish "no new frame yet" from "the
//! stream is gone". Set `COINPOKER_RECORD_FRAMES_DIR` to mirror captured
//! frames to disk as PNG fixtures for offline testing (see [`crate::record`]).
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
    /// The capture stream was stopped unexpectedly and must be restarted.
    #[error("capture stream stopped: {0}")]
    StreamStopped(String),
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

/// On-screen bounds of the captured window in global display coordinates
/// (top-left origin, points).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WindowBounds {
    /// Left edge of the window.
    pub x: f64,
    /// Top edge of the window.
    pub y: f64,
    /// Window width.
    pub width: f64,
    /// Window height.
    pub height: f64,
}

impl WindowBounds {
    /// Build bounds from a CoreGraphics-style rect, rejecting non-finite or
    /// non-positive extents.
    pub fn from_cg_rect(x: f64, y: f64, width: f64, height: f64) -> Option<Self> {
        if ![x, y, width, height].iter().all(|value| value.is_finite()) {
            return None;
        }
        if width <= 0.0 || height <= 0.0 {
            return None;
        }
        Some(Self {
            x,
            y,
            width,
            height,
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

/// Captures frames from a target application window via a continuous
/// ScreenCaptureKit stream.
///
/// Construction locates the window and prepares the stream; [`Self::start`]
/// begins frame delivery, [`Self::latest_frame`] returns each new frame
/// exactly once, and the SCStream delegate records unexpected stops for
/// [`Self::take_stop_error`].
///
/// The macOS backend is selected at compile time; construction fails with
/// [`CaptureError::UnsupportedPlatform`] on other platforms.
pub struct WindowCapturer {
    #[cfg(target_os = "macos")]
    inner: macos::StreamCapturer,
}

impl WindowCapturer {
    /// Locate the target window and prepare the capture stream.
    ///
    /// The stream is not running until [`Self::start`] is called.
    pub fn new(config: CaptureConfig) -> Result<Self, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            Ok(Self {
                inner: macos::StreamCapturer::new(&config)?,
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

    /// Start the capture stream. Idempotent: starting twice is a no-op.
    pub fn start(&mut self) -> Result<(), CaptureError> {
        #[cfg(target_os = "macos")]
        {
            self.inner.start()
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// Stop the capture stream. Idempotent.
    pub fn stop(&mut self) -> Result<(), CaptureError> {
        #[cfg(target_os = "macos")]
        {
            self.inner.stop()
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// Return the newest frame if one arrived since the last call.
    ///
    /// This never blocks: `Ok(None)` means no new complete frame has been
    /// delivered by the stream yet.
    pub fn latest_frame(&mut self) -> Result<Option<Frame>, CaptureError> {
        #[cfg(target_os = "macos")]
        {
            self.inner.latest_frame()
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            Err(CaptureError::UnsupportedPlatform)
        }
    }

    /// On-screen bounds of the captured window in global display coordinates.
    ///
    /// Consumers use this to position overlays relative to the table window.
    pub fn window_bounds(&self) -> Option<WindowBounds> {
        #[cfg(target_os = "macos")]
        {
            Some(self.inner.bounds())
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            None
        }
    }

    /// Take the error recorded when the stream stopped unexpectedly, if any.
    ///
    /// Reading clears the recorded error; a subsequent unexpected stop records
    /// a new one. A stopped stream needs [`Self::start`] to resume delivery.
    pub fn take_stop_error(&self) -> Option<String> {
        #[cfg(target_os = "macos")]
        {
            self.inner.take_stop_error()
        }
        #[cfg(not(target_os = "macos"))]
        {
            let _ = self;
            None
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
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::{Arc, Mutex};

    use screencapturekit::cm::{
        CMSampleBuffer, CMSampleBufferExt, CMSampleBufferSCExt, SCFrameStatus,
    };
    use screencapturekit::error::SCError;
    use screencapturekit::prelude::*;
    use screencapturekit::screenshot_manager::CGImageExt;
    use screencapturekit::shareable_content::SCShareableContent;
    use screencapturekit::stream::output_type::SCStreamOutputType;
    use screencapturekit::stream::sc_stream::SCStream;

    use super::{match_priority, CaptureConfig, CaptureError, Frame, WindowBounds, WindowInfo};

    /// State shared between the capturer owner and the stream callbacks.
    #[derive(Default)]
    struct StreamShared {
        latest: Mutex<Option<Frame>>,
        sequence: AtomicU64,
        stop_error: Mutex<Option<String>>,
    }

    impl StreamShared {
        /// Publish a frame and bump the sequence so consumers see it as new.
        fn publish(&self, frame: Frame) {
            *self.latest.lock().expect("frame lock") = Some(frame);
            self.sequence.fetch_add(1, Ordering::AcqRel);
        }
    }

    /// SCStream delegate capturing unexpected stream stops.
    struct StreamDelegate {
        shared: Arc<StreamShared>,
    }

    impl screencapturekit::stream::delegate_trait::SCStreamDelegateTrait for StreamDelegate {
        fn did_stop_with_error(&self, error: SCError) {
            *self.shared.stop_error.lock().expect("stop-error lock") = Some(error.to_string());
        }
    }

    /// macOS backend: a window-scoped SCStream with delegate-driven delivery.
    pub(super) struct StreamCapturer {
        pub(super) config: CaptureConfig,
        stream: SCStream,
        shared: Arc<StreamShared>,
        bounds: WindowBounds,
        seen_sequence: u64,
        started: bool,
    }

    impl StreamCapturer {
        pub(super) fn new(config: &CaptureConfig) -> Result<Self, CaptureError> {
            let content =
                SCShareableContent::get().map_err(|e| CaptureError::Backend(e.to_string()))?;

            let window = find_window(&content, config)
                .ok_or_else(|| CaptureError::WindowNotFound(config.window_title.clone()))?;

            let frame_rect = window.frame();
            let bounds = WindowBounds::from_cg_rect(
                frame_rect.origin.x,
                frame_rect.origin.y,
                frame_rect.size.width,
                frame_rect.size.height,
            )
            .ok_or_else(|| {
                CaptureError::Backend(format!(
                    "window {:?} reported unusable bounds {:?}",
                    window.title(),
                    frame_rect
                ))
            })?;

            // Window-scoped filter: only the target window's content is
            // captured, excluding the rest of the display.
            let filter = SCContentFilter::create().with_window(&window).build();
            let stream_config = SCStreamConfiguration::new()
                .with_width(config.width)
                .with_height(config.height)
                .with_pixel_format(PixelFormat::BGRA)
                .with_shows_cursor(false)
                .with_queue_depth(3);

            let shared = Arc::new(StreamShared::default());

            let delegate = StreamDelegate {
                shared: Arc::clone(&shared),
            };
            let mut stream = SCStream::new_with_delegate(&filter, &stream_config, delegate);

            let handler_shared = Arc::clone(&shared);
            let handler_recorder = Arc::new(Mutex::new(crate::record::FrameRecorder::from_env()));
            stream.add_output_handler(
                move |sample: CMSampleBuffer, output_type| {
                    if output_type != SCStreamOutputType::Screen {
                        return;
                    }
                    if sample.frame_status() != Some(SCFrameStatus::Complete) {
                        return;
                    }
                    let frame = match sample_buffer_to_frame(&sample) {
                        Some(frame) => frame,
                        None => return,
                    };
                    if let Ok(mut guard) = handler_recorder.lock() {
                        if let Some(recorder) = guard.as_mut() {
                            if let Err(error) = recorder.record(&frame) {
                                eprintln!("frame recording failed: {error}");
                            }
                        }
                    }
                    handler_shared.publish(frame);
                },
                SCStreamOutputType::Screen,
            );

            Ok(Self {
                config: config.clone(),
                stream,
                shared,
                bounds,
                seen_sequence: 0,
                started: false,
            })
        }

        pub(super) fn start(&mut self) -> Result<(), CaptureError> {
            if self.started {
                return Ok(());
            }
            self.stream
                .start_capture()
                .map_err(|e| CaptureError::Backend(e.to_string()))?;
            self.started = true;
            Ok(())
        }

        pub(super) fn stop(&mut self) -> Result<(), CaptureError> {
            if !self.started {
                return Ok(());
            }
            self.stream
                .stop_capture()
                .map_err(|e| CaptureError::Backend(e.to_string()))?;
            self.started = false;
            Ok(())
        }

        pub(super) fn latest_frame(&mut self) -> Result<Option<Frame>, CaptureError> {
            if let Some(error) = self.take_stop_error() {
                return Err(CaptureError::StreamStopped(error));
            }
            let sequence = self.shared.sequence.load(Ordering::Acquire);
            if sequence <= self.seen_sequence {
                return Ok(None);
            }
            let frame = self.shared.latest.lock().expect("frame lock").clone();
            self.seen_sequence = sequence;
            Ok(frame)
        }

        pub(super) fn bounds(&self) -> WindowBounds {
            self.bounds
        }

        pub(super) fn take_stop_error(&self) -> Option<String> {
            self.shared
                .stop_error
                .lock()
                .expect("stop-error lock")
                .take()
        }
    }

    /// Convert a complete screen sample buffer into a validated [`Frame`].
    ///
    /// Returns `None` for samples that cannot be decoded or that fail
    /// validation; the caller skips them rather than interrupting the stream.
    fn sample_buffer_to_frame(sample: &CMSampleBuffer) -> Option<Frame> {
        let image = sample.cg_image().ok()?;
        let width = image.width() as u32;
        let height = image.height() as u32;
        let rgba = image.rgba_data().ok()?;
        Frame::new(width, height, rgba).ok()
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

    #[test]
    fn window_bounds_rejects_unusable_rects() {
        assert_eq!(
            WindowBounds::from_cg_rect(10.0, 20.0, 800.0, 600.0),
            Some(WindowBounds {
                x: 10.0,
                y: 20.0,
                width: 800.0,
                height: 600.0
            })
        );
        assert_eq!(WindowBounds::from_cg_rect(0.0, 0.0, 0.0, 100.0), None);
        assert_eq!(WindowBounds::from_cg_rect(0.0, 0.0, 100.0, -1.0), None);
        assert_eq!(
            WindowBounds::from_cg_rect(f64::NAN, 0.0, 100.0, 100.0),
            None
        );
        assert_eq!(
            WindowBounds::from_cg_rect(0.0, f64::INFINITY, 100.0, 100.0),
            None
        );
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
