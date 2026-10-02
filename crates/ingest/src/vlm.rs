//! Multimodal inference for structured game-state extraction.
//!
//! The local llama.cpp server loads a revision-pinned Gemma 4 E2B GGUF and its
//! separate vision projector. [`OpenAiServerBackend`] sends a non-streaming
//! OpenAI-compatible request with one PNG data URL. Model, projector, and server
//! provenance are checked by the Windows setup scripts. API compatibility alone
//! does not establish poker-table extraction accuracy; see the visual evaluation.

use std::io::{Cursor, Read};
use std::time::Duration;

use base64::Engine;
use serde::Deserialize;
use thiserror::Error;
use url::{Host, Url};

use crate::capture::Frame;
use crate::prompt::SYSTEM_PROMPT;

/// Errors produced by the VLM layer.
#[derive(Debug, Error)]
pub enum VlmError {
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
    /// The model stopped because the generation budget was exhausted.
    #[error("truncated")]
    Truncated,
}

/// Closed response failures with no backend-authored diagnostic payloads.
#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum VlmResponseError {
    #[error("invalid-vlm-schema")]
    Schema,
    #[error("invalid-vlm-choices")]
    Choices,
    #[error("finish-reason")]
    FinishReason,
    #[error("invalid-vlm-empty")]
    EmptyContent,
    #[error("invalid-vlm-encoding")]
    Encoding,
    #[error("invalid-vlm-size")]
    Size,
}

impl VlmResponseError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Schema => "invalid-vlm-schema",
            Self::Choices => "invalid-vlm-choices",
            Self::FinishReason => "finish-reason",
            Self::EmptyContent => "invalid-vlm-empty",
            Self::Encoding => "invalid-vlm-encoding",
            Self::Size => "invalid-vlm-size",
        }
    }
}

impl VlmError {
    /// Safe classification for output boundaries, independent of error formatting.
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Server {
                status: 400 | 404 | 422,
                ..
            } => "unsupported-model-api",
            Self::Truncated => "truncated",
            Self::Parse(error) => error.code(),
            Self::InvalidEndpoint(_)
            | Self::Unavailable(_)
            | Self::Request(_)
            | Self::Server { .. }
            | Self::ImageEncoding(_) => "vlm-unavailable",
        }
    }
}

/// Configuration for the VLM backend.
#[derive(Debug, Clone, PartialEq)]
pub struct VlmConfig {
    /// Chat completions URL of the OpenAI-compatible VLM server.
    pub endpoint: String,
    /// Explicitly permit a non-loopback HTTPS endpoint to receive screenshots.
    pub allow_remote: bool,
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
            allow_remote: false,
            model: "coinpoker-gemma-4-e2b".to_string(),
            temperature: 0.1,
            max_tokens: 2048,
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

/// Abstraction over VLM runtimes; the pipeline depends only on this contract.
pub trait VlmBackend {
    /// Analyze a captured frame with the given prompt and return raw text.
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError>;
}

/// OpenAI-compatible HTTP client for a multimodal VLM server.
///
/// Requires the exact tested message/response contract, including PNG data URLs
/// and non-streaming text with a `stop` finish reason. Model/runtime compatibility
/// must be validated independently against the pinned GGUF and projector.
pub struct OpenAiServerBackend {
    config: VlmConfig,
    agent: ureq::Agent,
}

impl OpenAiServerBackend {
    pub fn new(mut config: VlmConfig) -> Result<Self, VlmError> {
        // Validate at the library boundary, including callers that bypass the CLI.
        // Send the parsed URL so validation and transport use one interpretation.
        config.endpoint = validate_endpoint(&config.endpoint, config.allow_remote)?.into();
        let agent = ureq::AgentBuilder::new()
            // Even feature unification must not route local screenshots through
            // an HTTP_PROXY/HTTPS_PROXY configured elsewhere in the process.
            .try_proxy_from_env(false)
            .timeout(Duration::from_secs(config.timeout_secs))
            // A redirect could escape the approved endpoint.
            .redirects(0)
            .build();
        Ok(Self { config, agent })
    }

    /// The endpoint this backend targets.
    pub fn endpoint(&self) -> &str {
        &self.config.endpoint
    }
}

fn validate_endpoint(endpoint: &str, allow_remote: bool) -> Result<Url, VlmError> {
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
    if !loopback && !allow_remote {
        return Err(VlmError::InvalidEndpoint(
            "remote screenshots require explicit opt-in",
        ));
    }
    if !loopback && parsed.scheme() != "https" {
        return Err(VlmError::InvalidEndpoint("remote HTTPS required"));
    }
    Ok(parsed)
}

impl VlmBackend for OpenAiServerBackend {
    fn analyze(&self, frame: &Frame, prompt: &str) -> Result<VlmOutput, VlmError> {
        let data_url = encode_frame_as_png_data_url(frame)?;

        let body = serde_json::json!({
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": false,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        { "type": "text", "text": prompt },
                        { "type": "image_url", "image_url": { "url": data_url } }
                    ]
                }
            ]
        });

        // Servers can echo entire requests (including screenshots) in error bodies.
        // Never retain or log them, and never follow redirects to another host.
        let response = match self.agent.post(&self.config.endpoint).send_json(body) {
            Ok(response) => response,
            Err(ureq::Error::Status(status, _)) => {
                return Err(VlmError::Server {
                    status,
                    body: String::new(),
                });
            }
            Err(_) => {
                return Err(VlmError::Request(
                    "connection or request timeout; check the local server".into(),
                ))
            }
        };

        // With redirects disabled, ureq returns 3xx responses directly rather
        // than as `Error::Status`; surface them before parsing the body.
        let status = response.status();
        if !(200..300).contains(&status) {
            return Err(VlmError::Server {
                status,
                body: String::new(),
            });
        }

        const MAX_RESPONSE: u64 = 1_048_576;
        let mut bytes = Vec::new();
        response
            .into_reader()
            .take(MAX_RESPONSE + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| VlmError::Request("response read failed or timed out".into()))?;
        if bytes.len() as u64 > MAX_RESPONSE {
            return Err(VlmError::Parse(VlmResponseError::Size));
        }
        let text =
            std::str::from_utf8(&bytes).map_err(|_| VlmError::Parse(VlmResponseError::Encoding))?;
        parse_chat_response(text)
    }
}

/// Encode a frame as a PNG and wrap it in a `data:` URL for submission.
fn encode_frame_as_png_data_url(frame: &Frame) -> Result<String, VlmError> {
    let img = frame
        .to_rgba_image()
        .map_err(|e| VlmError::ImageEncoding(e.to_string()))?;
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
    #[serde(default)]
    finish_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ChatMessage {
    content: String,
}

fn parse_chat_response(body: &str) -> Result<VlmOutput, VlmError> {
    let parsed: ChatResponse =
        serde_json::from_str(body).map_err(|_| VlmError::Parse(VlmResponseError::Schema))?;
    let choice = parsed
        .choices
        .into_iter()
        .next()
        .ok_or(VlmError::Parse(VlmResponseError::Choices))?;

    if matches!(
        choice.finish_reason.as_deref(),
        Some("length" | "max_tokens")
    ) {
        return Err(VlmError::Truncated);
    }

    if choice.finish_reason.as_deref() != Some("stop") {
        return Err(VlmError::Parse(VlmResponseError::FinishReason));
    }

    if choice.message.content.trim().is_empty() {
        return Err(VlmError::Parse(VlmResponseError::EmptyContent));
    }

    Ok(VlmOutput {
        text: choice.message.content,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::sync::mpsc::{self, Receiver};
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
    fn read_http_request(stream: &mut TcpStream) -> Vec<u8> {
        let mut buf = [0u8; 4096];
        let mut data: Vec<u8> = Vec::new();

        let header_end = loop {
            let n = stream.read(&mut buf).expect("read request");
            if n == 0 {
                return Vec::new();
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

        data[header_end..data.len().min(header_end + content_length)].to_vec()
    }

    /// Spawn a one-shot mock server that captures the request body and replies
    /// with the given status line and body.
    fn mock_server(status_line: &'static str, body: &'static str) -> (u16, Receiver<Vec<u8>>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        let (request_tx, request_rx) = mpsc::channel();

        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let request_body = read_http_request(&mut stream);
            request_tx.send(request_body).expect("send request body");
            let response = format!(
                "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).expect("write");
        });

        (port, request_rx)
    }

    fn mock_redirect_server(location: String) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();

        thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let _ = read_http_request(&mut stream);
            let response = format!(
                "HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
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
    fn safe_category_finish_reason() {
        let body = serde_json::json!({"choices": [{
            "message": {"content": "SYNTHETIC_RESPONSE_SENTINEL"},
            "finish_reason": "SYNTHETIC_FINISH_SENTINEL"
        }]});
        let diagnostic = parse_chat_response(&body.to_string())
            .unwrap_err()
            .to_string();
        assert_eq!(diagnostic, "finish-reason");
        let record = serde_json::json!({"reason": diagnostic}).to_string();
        assert!(!record.contains("SYNTHETIC_RESPONSE_SENTINEL"));
        assert!(!record.contains("SYNTHETIC_FINISH_SENTINEL"));
        assert!(!record.contains("completion finish reason"));
    }

    #[test]
    fn safe_category_truncated() {
        for reason in ["length", "max_tokens"] {
            let body = serde_json::json!({"choices": [{
                "message": {"content": "SYNTHETIC_RESPONSE_SENTINEL"},
                "finish_reason": reason
            }]});
            let diagnostic = parse_chat_response(&body.to_string())
                .unwrap_err()
                .to_string();
            assert_eq!(diagnostic, "truncated");
            let record = serde_json::json!({"reason": diagnostic}).to_string();
            assert!(!record.contains("SYNTHETIC_RESPONSE_SENTINEL"));
            assert!(!record.contains("finish_reason"));
            assert!(!record.contains(reason));
        }
    }

    #[test]
    fn parse_error_on_empty_choices() {
        let body = r#"{"choices": []}"#;
        assert!(matches!(parse_chat_response(body), Err(VlmError::Parse(_))));
    }

    #[test]
    fn rejects_truncated_chat_completion() {
        let body = r#"{
            "choices": [{
                "message": {"role": "assistant", "content": "{\"game_phase\":"},
                "finish_reason": "length"
            }]
        }"#;
        assert!(matches!(
            parse_chat_response(body),
            Err(VlmError::Truncated)
        ));
    }

    #[test]
    fn rejects_empty_chat_completion_content() {
        let body = r#"{
            "choices": [{
                "message": {"role": "assistant", "content": "  \n "},
                "finish_reason": "stop"
            }]
        }"#;
        assert!(matches!(parse_chat_response(body), Err(VlmError::Parse(_))));
    }

    #[test]
    fn malformed_frame_encoding_returns_error() {
        let frame = Frame {
            width: 2,
            height: 2,
            rgba: vec![0; 15],
        };
        assert!(matches!(
            encode_frame_as_png_data_url(&frame),
            Err(VlmError::ImageEncoding(_))
        ));
    }

    #[test]
    fn backend_rejects_remote_without_opt_in_or_https() {
        let remote_https = VlmConfig {
            endpoint: "https://example.com/v1/chat/completions".into(),
            ..VlmConfig::default()
        };
        assert!(matches!(
            OpenAiServerBackend::new(remote_https.clone()),
            Err(VlmError::InvalidEndpoint(_))
        ));
        let remote_http = VlmConfig {
            endpoint: "http://example.com/v1/chat/completions".into(),
            allow_remote: true,
            ..VlmConfig::default()
        };
        assert!(matches!(
            OpenAiServerBackend::new(remote_http),
            Err(VlmError::InvalidEndpoint(_))
        ));
        assert!(OpenAiServerBackend::new(VlmConfig {
            allow_remote: true,
            ..remote_https
        })
        .is_ok());
    }

    #[test]
    fn backend_allows_local_http_and_rejects_ambiguous_urls() {
        for endpoint in [
            "http://localhost:8080/v1/chat/completions",
            "http://127.0.0.2:8080/v1/chat/completions",
            "http://[::1]:8080/v1/chat/completions",
        ] {
            assert!(OpenAiServerBackend::new(VlmConfig {
                endpoint: endpoint.into(),
                ..VlmConfig::default()
            })
            .is_ok());
        }
        for endpoint in [
            "http://user:password@127.0.0.1:8080/v1/chat/completions",
            "http://127.0.0.1:8080/v1/chat/completions?token=x",
            "http://127.0.0.1:8080/v1/chat/completions#fragment",
            "file:///tmp/screenshot",
        ] {
            assert!(matches!(
                OpenAiServerBackend::new(VlmConfig {
                    endpoint: endpoint.into(),
                    ..VlmConfig::default()
                }),
                Err(VlmError::InvalidEndpoint(_))
            ));
        }
    }

    #[test]
    fn request_to_closed_port_fails_cleanly() {
        // Port zero cannot be a listening TCP endpoint. Releasing a random
        // bound port here is racy: another parallel test can claim it before
        // this request, changing the error into a server response.
        let config = VlmConfig {
            endpoint: "http://127.0.0.1:0/v1/chat/completions".to_string(),
            timeout_secs: 2,
            ..VlmConfig::default()
        };
        let backend = OpenAiServerBackend::new(config).expect("valid loopback endpoint");
        let err = backend
            .analyze(&tiny_frame(), "test")
            .expect_err("must fail");
        assert!(matches!(err, VlmError::Request(_)), "got {err:?}");
    }

    #[test]
    fn happy_path_against_mock_server() {
        let (port, request_rx) = mock_server(
            "200 OK",
            r#"{"choices":[{"message":{"role":"assistant","content":"{\"action_required\":true}"},"finish_reason":"stop"}]}"#,
        );

        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 5,
            ..VlmConfig::default()
        };
        let backend = OpenAiServerBackend::new(config).expect("valid loopback endpoint");
        let out = backend
            .analyze(&tiny_frame(), "describe the table")
            .expect("mock server responds");
        assert_eq!(out.text, "{\"action_required\":true}");

        let request_body = request_rx.recv().expect("captured request body");
        let request: serde_json::Value =
            serde_json::from_slice(&request_body).expect("request is JSON");
        let messages = request["messages"].as_array().expect("messages array");
        assert_eq!(messages.len(), 2);
        assert_eq!(messages[0]["role"], "system");
        assert_eq!(messages[0]["content"], SYSTEM_PROMPT);
        assert_eq!(messages[1]["role"], "user");
        assert_eq!(messages[1]["content"][0]["type"], "text");
        assert_eq!(messages[1]["content"][0]["text"], "describe the table");
        assert_eq!(messages[1]["content"][1]["type"], "image_url");
        assert!(messages[1]["content"][1]["image_url"]["url"]
            .as_str()
            .expect("image data URL")
            .starts_with("data:image/png;base64,"));
    }

    #[test]
    fn redirects_are_surfaced_instead_of_followed() {
        // Keep the redirect target reserved until after the assertion so a
        // parallel mock cannot reuse the endpoint.
        let target_listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let target_port = target_listener.local_addr().expect("addr").port();
        let port =
            mock_redirect_server(format!("http://127.0.0.1:{target_port}/unapproved-target"));
        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 2,
            ..VlmConfig::default()
        };
        let backend = OpenAiServerBackend::new(config).expect("valid loopback endpoint");
        let err = backend
            .analyze(&tiny_frame(), "describe the table")
            .expect_err("redirect must not be followed");
        assert!(
            matches!(err, VlmError::Server { status: 302, .. }),
            "got {err:?}"
        );
        drop(target_listener);
    }

    #[test]
    fn timeout_is_bounded_without_a_sleeping_mock() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().unwrap().port();
        let (release, blocked) = mpsc::sync_channel::<()>(1);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            read_http_request(&mut stream);
            let _ = blocked.recv_timeout(Duration::from_secs(5));
        });
        let backend = OpenAiServerBackend::new(VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 1,
            ..VlmConfig::default()
        })
        .expect("valid loopback endpoint");
        assert!(matches!(
            backend.analyze(&tiny_frame(), "test"),
            Err(VlmError::Request(_))
        ));
        let _ = release.send(());
        server.join().unwrap();
    }

    #[test]
    fn errors_never_echo_screenshot_payloads() {
        let (port, _request) = mock_server(
            "500 Internal Server Error",
            "data:image/png;base64,PRIVATE_SCREENSHOT",
        );
        let backend = OpenAiServerBackend::new(VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            ..VlmConfig::default()
        })
        .expect("valid loopback endpoint");
        let error = backend.analyze(&tiny_frame(), "test").unwrap_err();
        assert!(!format!("{error:?} {error}").contains("PRIVATE_SCREENSHOT"));
        assert!(!format!("{error:?} {error}").contains("data:image"));
    }

    #[test]
    fn server_error_status_is_surfaced() {
        let (port, _request_rx) = mock_server("404 Not Found", "model not found");

        let config = VlmConfig {
            endpoint: format!("http://127.0.0.1:{port}/v1/chat/completions"),
            timeout_secs: 5,
            ..VlmConfig::default()
        };
        let backend = OpenAiServerBackend::new(config).expect("valid loopback endpoint");
        let err = backend
            .analyze(&tiny_frame(), "describe the table")
            .expect_err("404 must error");
        assert!(matches!(err, VlmError::Server { status: 404, .. }));
    }
}
