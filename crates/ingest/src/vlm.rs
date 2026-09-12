//! Multimodal inference for structured game-state extraction.
//!
//! # Deployment constraint: MLX format
//!
//! The Gemma 4 E2B model is obtained in **MLX format** (Apple's framework
//! layout), not GGUF. llama.cpp does not load MLX-format weights, so this
//! module does not use llama.cpp.
//!
//! # Runtime strategy (verified against the current ecosystem)
//!
//! - [`mlxrs`] (safe Rust bindings to MLX via the `mlx-c` FFI) ships a `vlm`
//!   feature, but per-model architectures are opt-in and Gemma 4 is not yet
//!   among them (qwen3 and lfm2-vl only). In-process Gemma 4 E2B inference
//!   from Rust is therefore not available today.
//! - Rust-native MLX servers that run MLX-format weights directly on Metal
//!   (e.g. `rMLX`, `mlxcel`) expose an OpenAI-compatible HTTP API with image
//!   input, and the Python reference `mlx-vlm` server does the same.
//!
//! Consequently this module defines a backend-agnostic [`VlmBackend`] trait
//! and ships [`MlxServerBackend`], an OpenAI-compatible HTTP client that
//! targets a local MLX VLM server. The pipeline is unchanged if an
//! in-process `mlxrs` backend is added later.
//!
//! # Model note
//!
//! Early MLX quantizations of Gemma 4 produced garbage output because PLE
//! (per-layer embedding) layers were quantized incorrectly. Use the
//! PLE-safe `OptiQ` variants, e.g. `mlx-community/gemma-4-e2b-it-OptiQ-4bit`.

use std::io::Cursor;
use std::time::Duration;

use base64::Engine;
use serde::Deserialize;
use thiserror::Error;

use crate::capture::Frame;

/// Errors produced by the VLM layer.
#[derive(Debug, Error)]
pub enum VlmError {
    /// No backend is configured or the configured backend is unavailable.
    #[error("VLM backend unavailable: {0}")]
    Unavailable(String),
    /// The HTTP request to the local VLM server failed.
    #[error("VLM server request failed: {0}")]
    Request(String),
    /// The VLM server responded with a non-success status.
    #[error("VLM server error (status {status}): {body}")]
    Server { status: u16, body: String },
    /// The response body could not be parsed.
    #[error("VLM response parse error: {0}")]
    Parse(String),
    /// The frame could not be encoded for submission.
    #[error("image encoding failed: {0}")]
    ImageEncoding(String),
}

/// Configuration for the VLM backend.
#[derive(Debug, Clone, PartialEq)]
pub struct VlmConfig {
    /// Base URL of the local MLX VLM server (OpenAI-compatible).
    pub endpoint: String,
    /// Model name as registered on the server.
    pub model: String,
    /// Sampling temperature; kept low for deterministic structured output.
    pub temperature: f32,
    /// Maximum tokens to generate.
    pub max_tokens: u32,
    /// Per-request timeout in seconds.
    pub timeout_secs: u64,
}

impl Default for VlmConfig {
    fn default() -> Self {
        Self {
            endpoint: "http://127.0.0.1:8080/v1/chat/completions".to_string(),
            model: "gemma-4-e2b-it".to_string(),
            temperature: 0.1,
            max_tokens: 256,
            timeout_secs: 30,
        }
    }
}

/// Raw analysis result from the vision model.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VlmOutput {
    /// Model-generated text (expected to be JSON describing the table).
    pub text: String,
}

/// Abstraction over VLM runtimes so the pipeline can switch between an
/// in-process MLX engine and a local MLX server without changes.
pub trait VlmBackend {
    /// Analyze a captured frame with the given prompt and return raw text.
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError>;
}

/// OpenAI-compatible HTTP client for a local MLX VLM server.
///
/// Works with any server that accepts the multimodal chat-completions
/// format (data-URL images), including Rust-native MLX servers (`rMLX`,
/// `mlxcel`) and the `mlx-vlm` reference server.
pub struct MlxServerBackend {
    config: VlmConfig,
    agent: ureq::Agent,
}

impl MlxServerBackend {
    pub fn new(config: VlmConfig) -> Self {
        let agent = ureq::AgentBuilder::new()
            .timeout(Duration::from_secs(config.timeout_secs))
            .build();
        Self { config, agent }
    }

    /// The endpoint this backend targets.
    pub fn endpoint(&self) -> &str {
        &self.config.endpoint
    }
}

impl VlmBackend for MlxServerBackend {
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError> {
        let data_url = encode_frame_as_png_data_url(frame)?;

        let body = serde_json::json!({
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    { "type": "text", "text": prompt },
                    { "type": "image_url", "image_url": { "url": data_url } }
                ]
            }]
        });

        // ureq 2.x surfaces non-2xx statuses as `Error::Status`, so handle
        // that variant explicitly to preserve the server's error body.
        let response = match self.agent.post(&self.config.endpoint).send_json(body) {
            Ok(response) => response,
            Err(ureq::Error::Status(status, response)) => {
                let body = response
                    .into_string()
                    .map_err(|e| VlmError::Request(e.to_string()))?;
                return Err(VlmError::Server { status, body });
            }
            Err(e) => return Err(VlmError::Request(e.to_string())),
        };

        let text = response
            .into_string()
            .map_err(|e| VlmError::Request(e.to_string()))?;

        parse_chat_response(&text)
    }
}

/// Encode a frame as a PNG and wrap it in a `data:` URL for submission.
fn encode_frame_as_png_data_url(frame: &Frame) -> Result<String, VlmError> {
    let img = frame.to_rgba_image();
    let mut png = Vec::new();
    img.write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
        .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;

    let encoded = base64::engine::general_purpose::STANDARD.encode(&png);
    Ok(format!("data:image/png;base64,{encoded}"))
}

/// OpenAI chat-completions response subset.
#[derive(Debug, Deserialize)]
struct ChatResponse {
    choices: Vec<ChatChoice>,
}

#[derive(Debug, Deserialize)]
struct ChatChoice {
    message: ChatMessage,
}

#[derive(Debug, Deserialize)]
struct ChatMessage {
    content: String,
}

fn parse_chat_response(body: &str) -> Result<VlmOutput, VlmError> {
    let parsed: ChatResponse =
        serde_json::from_str(body).map_err(|e| VlmError::Parse(e.to_string()))?;
    let content = parsed
        .choices
        .into_iter()
        .next()
        .map(|c| c.message.content)
        .ok_or_else(|| VlmError::Parse("response contained no choices".to_string()))?;
    Ok(VlmOutput { text: content })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;

    fn tiny_frame() -> Frame {
        Frame {
            width: 2,
            height: 2,
            rgba: vec![
                255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255,
            ],
        }
    }

    /// Read a full HTTP request (headers + Content-Length body) so the mock
    /// server can respond without triggering a connection reset.
    fn read_http_request(stream: &mut TcpStream) {
        let mut buf = [0u8; 4096];
        let mut data: Vec<u8> = Vec::new();

        let header_end = loop {
            let n = stream.read(&mut buf).expect("read request");
            if n == 0 {
                return;
            }
            data.extend_from_slice(&buf[..n]);
            if let Some(pos) = data.windows(4).position(|w| w == b"\r\n\r\n") {
                break pos + 4;
            }
        };

        let headers = String::from_utf8_lossy(&data[..header_end]);
        let content_length = headers
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(|v| v.trim().parse::<usize>().unwrap_or(0))
            })
            .unwrap_or(0);

        while data.len() < header_end + content_length {
            let n = stream.read(&mut buf).expect("read body");
            if n == 0 {
                break;
            }
            data.extend_from_slice(&buf[..n]);
        }
    }

    /// Spawn a one-shot mock server that reads the request and replies with
    /// the given status line and JSON body. Returns the bound port.
    fn mock_server(status_line: &'static str, body: &'static str) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();

        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            read_http_request(&mut stream);
            let response = format!(
                "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).expect("write");
        });

        port
    }

    #[test]
    fn png_data_url_round_trips() {
        let url = encode_frame_as_png_data_url(&tiny_frame()).expect("encode");
        let b64 = url.strip_prefix("data:image/png;base64,").expect("prefix");
        let png = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .expect("valid base64");
        let decoded = image::load_from_memory(&png).expect("valid png");
        assert_eq!(decoded.width(), 2);
        assert_eq!(decoded.height(), 2);
    }

    #[test]
    fn parses_standard_chat_completion() {
        let body = r#"{
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": { "role": "assistant", "content": "{\"game_phase\":\"preflop\"}" },
                    "finish_reason": "stop"
                }
            ]
        }"#;
        let out = parse_chat_response(body).expect("parse");
        assert_eq!(out.text, "{\"game_phase\":\"preflop\"}");
    }

    #[test]
    fn parse_error_on_empty_choices() {
        let body = r#"{"choices": []}"#;
        assert!(matches!(parse_chat_response(body), Err(VlmError::Parse(_))));
    }

    #[test]
    fn request_to_closed_port_fails_cleanly() {
        // Bind a port and drop the listener so nothing is listening.
        let port = {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
            listener.local_addr().expect("addr").port()
        };
        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 2,
            ..VlmConfig::default()
        };
        let backend = MlxServerBackend::new(config);
        let err = backend
            .analyze(&tiny_frame(), "test")
            .expect_err("must fail");
        assert!(matches!(err, VlmError::Request(_)));
    }

    #[test]
    fn happy_path_against_mock_server() {
        let port = mock_server(
            "200 OK",
            r#"{"choices":[{"message":{"role":"assistant","content":"{\"action_required\":true}"}}]}"#,
        );

        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 5,
            ..VlmConfig::default()
        };
        let backend = MlxServerBackend::new(config);
        let out = backend
            .analyze(&tiny_frame(), "describe the table")
            .expect("mock server responds");
        assert_eq!(out.text, "{\"action_required\":true}");
    }

    #[test]
    fn server_error_status_is_surfaced() {
        let port = mock_server("404 Not Found", "model not found");

        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 5,
            ..VlmConfig::default()
        };
        let backend = MlxServerBackend::new(config);
        let err = backend
            .analyze(&tiny_frame(), "describe the table")
            .expect_err("404 must error");
        assert!(matches!(err, VlmError::Server { status: 404, .. }));
    }
}
