//! Multimodal inference contract for structured game-state extraction.
//!
//! [`VlmBackend`] is the only seam the pipeline depends on. Laya Vision
//! ([`crate::laya::LayaBackend`]) is the sole live backend: it asks a loopback
//! `scripts/laya-server.py` closed-vocabulary questions about region crops and
//! assembles the screen envelope deterministically. The `prompt` argument is
//! part of the contract (scripted test backends assert it) but Laya ignores it.
//! API compatibility alone does not establish extraction accuracy; see the
//! visual evaluation.

use std::io::{Cursor, Read};
use std::time::{Duration, Instant};

use base64::Engine;
use thiserror::Error;
use url::{Host, Url};

use crate::capture::Frame;

/// Errors produced by the VLM layer.
#[derive(Debug, Error)]
pub enum VlmError {
    /// The source-bound total decision deadline expired, not a per-request timeout.
    #[error("decision-deadline-exceeded")]
    Deadline,
    /// The endpoint failed the screenshot transport policy.
    #[error("invalid VLM endpoint: {0}")]
    InvalidEndpoint(&'static str),
    /// No backend is configured or the configured backend is unavailable.
    #[error("VLM backend unavailable: {0}")]
    Unavailable(String),
    /// The HTTP request to the local VLM server failed.
    #[error("VLM server request failed: {0}")]
    Request(String),
    /// The VLM server responded with a non-success status.
    #[error("VLM server error (status {status}); response body omitted for screenshot privacy")]
    Server { status: u16, body: String },
    /// The response body could not be parsed.
    #[error("{0}")]
    Parse(VlmResponseError),
    /// The frame could not be encoded for submission.
    #[error("image encoding failed: {0}")]
    ImageEncoding(String),
}

/// Closed response failures with no backend-authored diagnostic payloads.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum VlmResponseError {
    #[error("invalid-vlm-schema")]
    Schema,
    #[error("invalid-vlm-encoding")]
    Encoding,
    #[error("invalid-vlm-size")]
    Size,
}

impl VlmResponseError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Schema => "invalid-vlm-schema",
            Self::Encoding => "invalid-vlm-encoding",
            Self::Size => "invalid-vlm-size",
        }
    }
}

impl VlmError {
    /// Safe classification for output boundaries, independent of error formatting.
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Deadline => "decision-deadline-exceeded",
            Self::Server {
                status: 400 | 404 | 422,
                ..
            } => "unsupported-model-api",
            Self::Parse(error) => error.code(),
            Self::InvalidEndpoint(_)
            | Self::Unavailable(_)
            | Self::Request(_)
            | Self::Server { .. }
            | Self::ImageEncoding(_) => "vlm-unavailable",
        }
    }
}

/// Configuration for the Laya Vision backend.
#[derive(Debug, Clone, PartialEq)]
pub struct VlmConfig {
    /// Predict URL of the loopback Laya server (`/v1/laya/predict`).
    pub endpoint: String,
    /// Model alias as registered on the server.
    pub model: String,
    /// Per-request timeout in seconds.
    pub timeout_secs: u64,
    /// Optional global confidence threshold; it can only raise per-pass thresholds.
    pub threshold: Option<f32>,
}

impl Default for VlmConfig {
    fn default() -> Self {
        Self {
            endpoint: "http://127.0.0.1:18090/v1/laya/predict".to_string(),
            model: "coinpoker-laya-vision".to_string(),
            timeout_secs: 5,
            threshold: None,
        }
    }
}

/// Raw analysis result from the vision backend.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VlmOutput {
    /// Envelope text (expected to be JSON describing the screen).
    pub text: String,
}

/// Abstraction over VLM runtimes; the pipeline depends only on this contract.
pub trait VlmBackend {
    /// Analyze a captured frame with the given prompt and return raw text.
    /// Backends may ignore the prompt (Laya asks its own closed questions).
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError>;

    /// Live work receives one source-bound deadline, never a new budget per pass.
    fn analyze_with_deadline(
        &self,
        frame: &Frame,
        prompt: &str,
        deadline: Instant,
    ) -> Result<VlmOutput, VlmError> {
        remaining_budget(deadline, Instant::now())?;
        let result = self.analyze(frame, prompt);
        remaining_budget(deadline, Instant::now())?;
        result
    }
}

pub(crate) fn remaining_budget(deadline: Instant, now: Instant) -> Result<Duration, VlmError> {
    deadline
        .checked_duration_since(now)
        .filter(|remaining| !remaining.is_zero())
        .ok_or(VlmError::Deadline)
}

/// Screenshot transport policy: HTTP(S) to a loopback host only, with no
/// credentials, query string, or fragment. Remote endpoints are always refused.
pub fn validate_endpoint(endpoint: &str) -> Result<Url, VlmError> {
    let parsed = Url::parse(endpoint).map_err(|_| VlmError::InvalidEndpoint("invalid URL"))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err(VlmError::InvalidEndpoint("HTTP or HTTPS required"));
    }
    if !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err(VlmError::InvalidEndpoint(
            "credentials, query strings, and fragments are forbidden",
        ));
    }
    let loopback = match parsed.host() {
        Some(Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        None => return Err(VlmError::InvalidEndpoint("host required")),
    };
    if !loopback {
        return Err(VlmError::InvalidEndpoint(
            "loopback host required; screenshots never leave this machine",
        ));
    }
    Ok(parsed)
}

/// Blocking agent that ignores proxy environment variables, never follows
/// redirects (one could escape the approved endpoint), and bounds each request.
pub(crate) fn http_agent(timeout_secs: u64) -> ureq::Agent {
    ureq::AgentBuilder::new()
        .try_proxy_from_env(false)
        .timeout(Duration::from_secs(timeout_secs))
        .redirects(0)
        .build()
}

/// Read at most `max` bytes of a response body; larger bodies are rejected.
pub(crate) fn read_bounded(response: ureq::Response, max: u64) -> Result<Vec<u8>, VlmError> {
    let mut bytes = Vec::new();
    response
        .into_reader()
        .take(max + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| VlmError::Request("response read failed or timed out".into()))?;
    if bytes.len() as u64 > max {
        return Err(VlmError::Parse(VlmResponseError::Size));
    }
    Ok(bytes)
}

/// Encode an RGBA image as PNG bytes.
pub(crate) fn encode_png(image: &image::RgbaImage) -> Result<Vec<u8>, VlmError> {
    let mut png = Vec::new();
    image
        .write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
        .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
    Ok(png)
}

/// Standard base64 of PNG bytes, as carried in `images_png_b64`.
pub(crate) fn base64_png(png: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(png)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn png_encoding_round_trips() {
        let image = image::RgbaImage::from_raw(
            2,
            2,
            vec![
                255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255,
            ],
        )
        .unwrap();
        let png = encode_png(&image).expect("encode");
        let b64 = base64_png(&png);
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .expect("valid base64");
        let decoded = image::load_from_memory(&bytes).expect("valid png");
        assert_eq!((decoded.width(), decoded.height()), (2, 2));
    }

    #[test]
    fn defaults_target_the_loopback_laya_server() {
        let config = VlmConfig::default();
        assert_eq!(config.endpoint, "http://127.0.0.1:18090/v1/laya/predict");
        assert_eq!(config.model, "coinpoker-laya-vision");
        assert_eq!(config.timeout_secs, 5);
        assert_eq!(config.threshold, None);
        validate_endpoint(&config.endpoint).expect("default is loopback");
    }

    #[test]
    fn loopback_endpoints_are_allowed() {
        for endpoint in [
            "http://localhost:18090/v1/laya/predict",
            "http://LOCALHOST:18090/v1/laya/predict",
            "http://127.0.0.2:18090/v1/laya/predict",
            "https://[::1]:18090/v1/laya/predict",
            // Transport injection is not the product CLI port policy.
            "http://127.0.0.1:0/v1/laya/predict",
        ] {
            assert!(validate_endpoint(endpoint).is_ok(), "{endpoint}");
        }
    }

    #[test]
    fn remote_and_ambiguous_endpoints_are_always_rejected() {
        for endpoint in [
            "https://example.com/v1/laya/predict",
            "http://192.168.1.2/v1/laya/predict",
            "http://localhost.evil.com/",
            "http://localhost:8080@evil.example/v1",
            "http://user:password@127.0.0.1:8080/v1/laya/predict",
            "http://127.0.0.1:8080/v1/laya/predict?token=x",
            "http://127.0.0.1:8080/v1/laya/predict#fragment",
            "file:///tmp/screenshot",
            "not a URL",
        ] {
            assert!(
                matches!(
                    validate_endpoint(endpoint),
                    Err(VlmError::InvalidEndpoint(_))
                ),
                "{endpoint}"
            );
        }
    }

    #[test]
    fn error_codes_are_closed_categories() {
        for (error, code) in [
            (VlmError::Deadline, "decision-deadline-exceeded"),
            (
                VlmError::Parse(VlmResponseError::Schema),
                "invalid-vlm-schema",
            ),
            (
                VlmError::Parse(VlmResponseError::Encoding),
                "invalid-vlm-encoding",
            ),
            (VlmError::Parse(VlmResponseError::Size), "invalid-vlm-size"),
            (
                VlmError::Server {
                    status: 404,
                    body: String::new(),
                },
                "unsupported-model-api",
            ),
            (
                VlmError::Server {
                    status: 302,
                    body: String::new(),
                },
                "vlm-unavailable",
            ),
            (VlmError::Request("x".into()), "vlm-unavailable"),
        ] {
            assert_eq!(error.code(), code);
        }
    }

    #[test]
    fn total_budget_is_strict_and_decreases_without_clock_sleeps() {
        let start = Instant::now();
        let deadline = start + Duration::from_millis(5_000);
        assert_eq!(
            remaining_budget(deadline, start).unwrap(),
            Duration::from_millis(5_000)
        );
        assert_eq!(
            remaining_budget(deadline, start + Duration::from_millis(4_999)).unwrap(),
            Duration::from_millis(1)
        );
        for now in [deadline, deadline + Duration::from_millis(1)] {
            assert!(matches!(
                remaining_budget(deadline, now),
                Err(VlmError::Deadline)
            ));
        }
    }

    #[test]
    fn exhausted_total_budget_skips_the_backend_entirely() {
        struct Never;
        impl VlmBackend for Never {
            fn analyze(&self, _: &Frame, _: &str) -> Result<VlmOutput, VlmError> {
                panic!("expired source must not start inference")
            }
        }
        let frame = Frame::new(1, 1, vec![0; 4]).unwrap();
        assert!(matches!(
            Never.analyze_with_deadline(&frame, "", Instant::now()),
            Err(VlmError::Deadline)
        ));
    }
}
