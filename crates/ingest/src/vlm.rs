//! Client for the local vision language model.
//!
//! Talks to an OpenAI-compatible chat-completions endpoint (the MLX VLM
//! server) and returns raw model text for downstream parsing.
//!
//! Latency-critical choices, in the order they apply:
//! - frames are cropped to the table ROI and downscaled before submission
//!   ([`RoiConfig`], see [`crate::roi`]);
//! - images are JPEG-encoded at a configurable quality (default q80) —
//!   base64 JPEG is several times smaller than the equivalent PNG, which
//!   cuts prefill tokens and wire time;
//! - HTTP connections are kept alive: a single shared [`ureq::Agent`]
//!   pools connections per host, so repeated calls reuse the same TCP
//!   stream instead of paying a fresh TLS/TCP handshake each time;
//! - requests carry a `response_format` JSON Schema so servers with guided
//!   decoding constrain the model to the state contract up front
//!   ([`crate::schema`]). Servers without schema support ignore it.
//!
//! Model output remains untrusted regardless: [`crate::parser`] validates
//! every field before a state is usable.

use std::io::Cursor;
use std::time::Duration;

use base64::Engine as _;
use thiserror::Error;
use ureq::Agent;

use crate::capture::Frame;
use crate::roi::{apply_roi, RoiConfig, RoiError};

/// Default JPEG quality for submitted frames.
pub const DEFAULT_JPEG_QUALITY: u8 = 80;

/// Errors produced while talking to the VLM server.
#[derive(Debug, Error)]
pub enum VlmError {
    /// The request could not be delivered to the server.
    #[error("request failed: {0}")]
    Transport(String),
    /// The frame could not be prepared for submission.
    #[error("frame preparation failed: {0}")]
    FramePreparation(#[from] RoiError),
    /// The frame could not be encoded as JPEG.
    #[error("frame encoding failed: {0}")]
    Encoding(String),
    /// The server rejected the request.
    #[error("server error ({code}): {message}")]
    Server { code: u16, message: String },
    /// The response body could not be read or parsed.
    #[error("response body could not be read: {0}")]
    ResponseBody(#[from] std::io::Error),
    /// The response could not be parsed as a chat completion.
    #[error("unexpected response format: {0}")]
    UnexpectedResponse(String),
    /// The model stopped because the generation budget was exhausted.
    #[error("VLM response was truncated (finish_reason: {0})")]
    Truncated(String),
}

/// Errors surfaced by [`VlmConfig::validate`].
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum VlmConfigError {
    /// The JPEG quality must be in 1..=100.
    #[error("jpeg quality must be between 1 and 100, got {0}")]
    InvalidJpegQuality(u8),
}

/// Configuration for the VLM client.
#[derive(Debug, Clone, PartialEq)]
pub struct VlmConfig {
    /// Base URL of the OpenAI-compatible server.
    pub base_url: String,
    /// Model identifier.
    pub model: String,
    /// Sampling temperature; low values keep output parseable.
    pub temperature: f64,
    /// Maximum tokens the model may generate.
    pub max_tokens: u32,
    /// Request timeout for a single analysis call.
    pub timeout: Duration,
    /// Region-of-interest cropping and downscaling applied before encoding.
    pub roi: RoiConfig,
    /// JPEG quality (1..=100) for the submitted image.
    pub jpeg_quality: u8,
    /// Whether to attach the `response_format` JSON Schema to requests.
    pub schema_constrained: bool,
}

impl Default for VlmConfig {
    fn default() -> Self {
        Self {
            base_url: "http://127.0.0.1:8080".to_string(),
            model: "qwen2-vl-7b".to_string(),
            temperature: 0.1,
            max_tokens: 512,
            timeout: Duration::from_secs(30),
            roi: RoiConfig::default(),
            jpeg_quality: DEFAULT_JPEG_QUALITY,
            schema_constrained: true,
        }
    }
}

impl VlmConfig {
    /// Validate the configuration values that carry semantic constraints.
    pub fn validate(&self) -> Result<(), VlmConfigError> {
        if self.jpeg_quality == 0 || self.jpeg_quality > 100 {
            return Err(VlmConfigError::InvalidJpegQuality(self.jpeg_quality));
        }
        Ok(())
    }
}

/// Raw text output from the VLM.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VlmOutput {
    /// The assistant message content.
    pub text: String,
}

/// A backend that can analyze a frame into raw model text.
pub trait VlmBackend {
    /// Analyze a frame, returning the model's raw text output.
    ///
    /// # Errors
    ///
    /// Returns the backend's error type on transport, encoding, or server
    /// failures.
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError>;
}

/// OpenAI-compatible chat-completions backend for a local MLX VLM server.
///
/// The backend holds one [`ureq::Agent`] for its lifetime. The agent pools
/// keep-alive connections per host, so consecutive calls to
/// [`Self::analyze`] reuse an established connection instead of
/// re-handshaking.
#[derive(Debug, Clone)]
pub struct MlxServerBackend {
    config: VlmConfig,
    agent: Agent,
}

impl MlxServerBackend {
    /// Construct a backend with a keep-alive connection pool.
    pub fn new(config: VlmConfig) -> Self {
        let agent = agent_for(&config);
        Self { config, agent }
    }

    /// The configuration in use.
    pub fn config(&self) -> &VlmConfig {
        &self.config
    }

    /// Build the chat-completions request body for a frame and prompt.
    ///
    /// Exposed for tests: the body carries the system prompt, the
    /// image data URL, and — when enabled — the schema-constrained
    /// `response_format`.
    pub fn build_request_body(
        &self,
        frame: &Frame,
        prompt: &str,
    ) -> Result<serde_json::Value, VlmError> {
        let image_data_url = encode_frame_as_jpeg_data_url(frame, &self.config)?;

        let mut body = serde_json::json!({
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": crate::prompt::SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": { "url": image_data_url },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                },
            ],
        });

        if self.config.schema_constrained {
            body["response_format"] = crate::schema::response_format();
        }

        Ok(body)
    }

    /// The chat-completions endpoint URL.
    fn completions_url(&self) -> String {
        format!(
            "{}/v1/chat/completions",
            self.config.base_url.trim_end_matches('/')
        )
    }
}

impl VlmBackend for MlxServerBackend {
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError> {
        let body = self.build_request_body(frame, prompt)?;
        let response = match self
            .agent
            .post(&self.completions_url())
            .timeout(self.config.timeout)
            .send_json(body)
        {
            Ok(response) => response,
            // ureq surfaces HTTP error statuses as typed errors carrying
            // the response; convert them so callers see the server body.
            Err(ureq::Error::Status(code, response)) => {
                let message = response
                    .into_string()
                    .unwrap_or_else(|_| "no response body".to_string());
                return Err(VlmError::Server { code, message });
            }
            Err(error) => return Err(VlmError::Transport(error.to_string())),
        };

        if response.status() != 200 {
            let code = response.status();
            let message = response
                .into_string()
                .unwrap_or_else(|_| "no response body".to_string());
            return Err(VlmError::Server { code, message });
        }

        let response: serde_json::Value = response.into_json()?;
        parse_completion(&response)
    }
}

/// Build a keep-alive HTTP agent for the given configuration.
///
/// `ureq` agents pool connections per host and keep them alive between
/// calls; the configured analysis timeout applies to each request.
fn agent_for(config: &VlmConfig) -> Agent {
    ureq::AgentBuilder::new().timeout(config.timeout).build()
}

/// Parse an OpenAI-style chat completion into its message text.
fn parse_completion(response: &serde_json::Value) -> Result<VlmOutput, VlmError> {
    let first_choice = response
        .get("choices")
        .and_then(|choices| choices.get(0))
        .ok_or_else(|| VlmError::UnexpectedResponse("missing choices array".to_string()))?;

    // A length-capped generation means the state JSON is incomplete; treat
    // it as a hard error rather than letting the parser reject a mangled
    // object downstream.
    if let Some(finish_reason) = first_choice
        .get("finish_reason")
        .and_then(|reason| reason.as_str())
    {
        if finish_reason == "length" {
            return Err(VlmError::Truncated(finish_reason.to_string()));
        }
    }

    let text = first_choice
        .get("message")
        .and_then(|message| message.get("content"))
        .and_then(|content| content.as_str())
        .ok_or_else(|| VlmError::UnexpectedResponse("missing message content".to_string()))?;
    Ok(VlmOutput {
        text: text.to_string(),
    })
}

/// Crop, downscale, and JPEG-encode a frame as a base64 data URL.
///
/// The ROI and quality come from the backend configuration; the result is
/// the `data:image/jpeg;base64,...` URL embedded in the request body.
fn encode_frame_as_jpeg_data_url(frame: &Frame, config: &VlmConfig) -> Result<String, VlmError> {
    let prepared = apply_roi(frame, &config.roi)?;
    let jpeg = encode_jpeg(&prepared, config.jpeg_quality)?;
    Ok(format!(
        "data:image/jpeg;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(jpeg)
    ))
}

/// Encode a frame as JPEG bytes at the given quality.
fn encode_jpeg(frame: &Frame, quality: u8) -> Result<Vec<u8>, VlmError> {
    let image = frame
        .to_rgba_image()
        .map_err(|e| VlmError::Encoding(e.to_string()))?;
    // JPEG has no alpha channel; drop it explicitly rather than relying on
    // encoder-specific conversion.
    let rgb = image::DynamicImage::ImageRgba8(image).to_rgb8();
    let mut jpeg = Vec::new();
    let mut cursor = Cursor::new(&mut jpeg);
    let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut cursor, quality);
    encoder
        .encode_image(&image::DynamicImage::ImageRgb8(rgb))
        .map_err(|e| VlmError::Encoding(e.to_string()))?;
    Ok(jpeg)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;

    fn tiny_frame() -> Frame {
        Frame {
            width: 2,
            height: 2,
            rgba: vec![255; 2 * 2 * 4],
        }
    }

    fn test_config() -> VlmConfig {
        VlmConfig::default()
    }

    #[test]
    fn default_config_uses_jpeg_80_and_schema_constraint() {
        let config = VlmConfig::default();
        assert_eq!(config.jpeg_quality, 80);
        assert!(config.schema_constrained);
        assert_eq!(config.roi.max_width, 1280);
        assert!(config.validate().is_ok());
    }

    #[test]
    fn invalid_jpeg_quality_is_rejected() {
        let mut config = test_config();
        config.jpeg_quality = 0;
        assert_eq!(
            config.validate(),
            Err(VlmConfigError::InvalidJpegQuality(0))
        );
        config.jpeg_quality = 101;
        assert_eq!(
            config.validate(),
            Err(VlmConfigError::InvalidJpegQuality(101))
        );
    }

    #[test]
    fn request_body_carries_jpeg_image_and_response_format() {
        let backend = MlxServerBackend::new(test_config());
        let body = backend
            .build_request_body(&tiny_frame(), "analyze this")
            .expect("build body");

        let content = &body["messages"][1]["content"];
        assert_eq!(content[0]["type"], "image_url");
        let url = content[0]["image_url"]["url"].as_str().expect("data url");
        assert!(url.starts_with("data:image/jpeg;base64,"));
        assert_eq!(content[1]["text"], "analyze this");
        assert_eq!(body["model"], "qwen2-vl-7b");
        assert_eq!(
            body["response_format"]["json_schema"]["name"],
            crate::schema::SCHEMA_NAME
        );
    }

    #[test]
    fn schema_constraint_can_be_disabled() {
        let mut config = test_config();
        config.schema_constrained = false;
        let backend = MlxServerBackend::new(config);
        let body = backend
            .build_request_body(&tiny_frame(), "analyze this")
            .expect("build body");
        assert!(body.get("response_format").is_none());
    }

    #[test]
    fn roi_crop_applies_before_encoding() {
        let mut config = test_config();
        config.roi.rect = crate::change_detect::ZoneRect {
            x: 0.0,
            y: 0.0,
            w: 0.5,
            h: 1.0,
        };
        config.roi.max_width = 0;
        let backend = MlxServerBackend::new(config);

        let frame = Frame {
            width: 4,
            height: 2,
            rgba: vec![255; 4 * 2 * 4],
        };
        let body = backend
            .build_request_body(&frame, "analyze this")
            .expect("build body");

        let url = body["messages"][1]["content"][0]["image_url"]["url"]
            .as_str()
            .expect("data url");
        let encoded = url.strip_prefix("data:image/jpeg;base64,").expect("prefix");
        let jpeg = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .expect("base64");
        // A 2x2 crop of a 4x2 frame: JPEG dimensions are read from SOF0.
        let (width, height) = jpeg_dimensions(&jpeg).expect("parseable jpeg");
        assert_eq!((width, height), (2, 2));
    }

    #[test]
    fn empty_roi_fails_frame_preparation() {
        let mut config = test_config();
        config.roi.rect = crate::change_detect::ZoneRect {
            x: 2.0,
            y: 0.0,
            w: 0.5,
            h: 0.5,
        };
        let backend = MlxServerBackend::new(config);
        let err = backend
            .build_request_body(&tiny_frame(), "analyze this")
            .expect_err("empty ROI");
        assert!(matches!(err, VlmError::FramePreparation(_)));
    }

    /// Extract the JPEG SOF0 dimensions without an image crate dependency.
    fn jpeg_dimensions(jpeg: &[u8]) -> Option<(u16, u16)> {
        let mut index = 2;
        while index + 9 < jpeg.len() {
            if jpeg[index] != 0xFF {
                return None;
            }
            let marker = jpeg[index + 1];
            let length = u16::from_be_bytes([jpeg[index + 2], jpeg[index + 3]]) as usize;
            if marker == 0xC0 || marker == 0xC2 {
                let height = u16::from_be_bytes([jpeg[index + 5], jpeg[index + 6]]);
                let width = u16::from_be_bytes([jpeg[index + 7], jpeg[index + 8]]);
                return Some((width, height));
            }
            index += 2 + length;
        }
        None
    }

    #[test]
    fn jpeg_encoding_is_smaller_than_png_at_q80() {
        // A photographic-ish gradient compresses far better as JPEG q80
        // than as lossless PNG.
        let width = 64;
        let height = 64;
        let mut rgba = vec![0u8; width * height * 4];
        for (index, pixel) in rgba.chunks_exact_mut(4).enumerate() {
            let x = index % width;
            let y = index / width;
            pixel[0] = (x * 4) as u8;
            pixel[1] = (y * 4) as u8;
            pixel[2] = ((x + y) % 256) as u8;
            pixel[3] = 255;
        }
        let frame = Frame {
            width: width as u32,
            height: height as u32,
            rgba,
        };

        let jpeg = encode_jpeg(&frame, 80).expect("jpeg");
        let mut png = Vec::new();
        frame
            .to_rgba_image()
            .expect("valid frame")
            .write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
            .expect("png");
        assert!(
            jpeg.len() < png.len(),
            "jpeg {} vs png {}",
            jpeg.len(),
            png.len()
        );
    }

    #[test]
    fn parse_error_on_empty_choices() {
        let response = serde_json::json!({ "choices": [] });
        assert!(matches!(
            parse_completion(&response),
            Err(VlmError::UnexpectedResponse(_))
        ));
    }

    #[test]
    fn parse_error_on_missing_content() {
        let response = serde_json::json!({ "choices": [{ "message": {} }] });
        assert!(matches!(
            parse_completion(&response),
            Err(VlmError::UnexpectedResponse(_))
        ));
    }

    #[test]
    fn truncated_completions_are_rejected() {
        let response = serde_json::json!({
            "choices": [{ "finish_reason": "length", "message": { "content": "{\"game" } }]
        });
        assert!(matches!(
            parse_completion(&response),
            Err(VlmError::Truncated(reason)) if reason == "length"
        ));
    }

    #[test]
    fn stop_finish_reason_parses_normally() {
        let response = serde_json::json!({
            "choices": [{ "finish_reason": "stop", "message": { "content": "ok" } }]
        });
        assert_eq!(parse_completion(&response).expect("parse").text, "ok");
    }

    #[test]
    fn parses_first_choice_content() {
        let response = serde_json::json!({
            "choices": [
                { "message": { "content": "first" } },
                { "message": { "content": "second" } },
            ]
        });
        assert_eq!(parse_completion(&response).expect("parse").text, "first");
    }

    /// Read one full HTTP request (headers plus Content-Length body).
    ///
    /// A single `read()` can return a partial request; responding before the
    /// client finished sending would reset the connection.
    fn read_request(stream: &mut std::net::TcpStream) -> String {
        let mut buffer = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            let read = stream.read(&mut chunk).expect("read request");
            if read == 0 {
                break;
            }
            buffer.extend_from_slice(&chunk[..read]);
            let text = String::from_utf8_lossy(&buffer);
            let Some(header_end) = text.find("\r\n\r\n") else {
                continue;
            };
            let Some(length) = text.lines().find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())?
            }) else {
                continue;
            };
            if buffer.len() >= header_end + 4 + length {
                break;
            }
        }
        String::from_utf8_lossy(&buffer).to_string()
    }

    #[test]
    fn server_error_status_is_surfaced() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = read_request(&mut stream);
            let _ = stream.write_all(
                b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 5\r\nConnection: close\r\n\r\nboom!",
            );
        });

        let mut config = test_config();
        config.base_url = format!("http://127.0.0.1:{port}");
        let backend = MlxServerBackend::new(config);
        let err = backend
            .analyze(&tiny_frame(), "analyze this")
            .expect_err("server error");
        eprintln!("PROBE: {err:?}");
        assert!(matches!(err, VlmError::Server { code: 500, .. }));
    }

    #[test]
    fn analyze_returns_first_choice_content() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let request = read_request(&mut stream);
            assert!(
                request.contains("POST /v1/chat/completions"),
                "path: {request}"
            );
            assert!(request.contains("data:image/jpeg;base64,"), "jpeg data url");
            assert!(request.contains("response_format"), "schema constraint");
            let body = concat!(
                "HTTP/1.1 200 OK\r\n",
                "Content-Type: application/json\r\n",
                "Content-Length: 42\r\n",
                "Connection: close\r\n\r\n",
                "{\"choices\":[{\"message\":{\"content\":\"ok\"}}]}"
            );
            let _ = stream.write_all(body.as_bytes());
        });

        let mut config = test_config();
        config.base_url = format!("http://127.0.0.1:{port}");
        let backend = MlxServerBackend::new(config);
        let output = backend
            .analyze(&tiny_frame(), "analyze this")
            .expect("analyze");
        assert_eq!(output.text, "ok");
    }

    #[test]
    fn keep_alive_reuses_one_connection_across_calls() {
        // The server accepts exactly one TCP connection and serves two
        // responses on it. Two analyze() calls succeeding proves the agent
        // reused the keep-alive connection instead of opening a second.
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let body = concat!(
                "HTTP/1.1 200 OK\r\n",
                "Content-Type: application/json\r\n",
                "Content-Length: 42\r\n",
                "Connection: keep-alive\r\n\r\n",
                "{\"choices\":[{\"message\":{\"content\":\"ok\"}}]}"
            );
            for _ in 0..2 {
                let request = read_request(&mut stream);
                assert!(request.contains("POST /v1/chat/completions"));
                let _ = stream.write_all(body.as_bytes());
            }
            // A third connection attempt would fail the test: the listener
            // never accepts again.
        });

        let mut config = test_config();
        config.base_url = format!("http://127.0.0.1:{port}");
        let backend = MlxServerBackend::new(config);
        for _ in 0..2 {
            let output = backend
                .analyze(&tiny_frame(), "analyze this")
                .expect("keep-alive call");
            assert_eq!(output.text, "ok");
        }
    }
}
