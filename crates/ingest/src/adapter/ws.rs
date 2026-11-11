//! Minimal RFC 6455 WebSocket client + HTTP GET for loopback CDP.
//!
//! Phase 0 proved a stdlib-class client is viable on loopback (no TLS, no
//! external crates): the Chrome DevTools endpoint speaks plain WS/1.1 on
//! `127.0.0.1:9222`. This module is deliberately small: text frames, ping
//! handling, and 16/64-bit lengths are all that CDP requires from us.

use std::io::{ErrorKind, Read, Write};
use std::net::TcpStream;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Debug)]
pub enum WsError {
    Io(std::io::Error),
    Protocol(String),
    Closed,
}

impl std::fmt::Display for WsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(f, "ws io: {error}"),
            Self::Protocol(message) => write!(f, "ws protocol: {message}"),
            Self::Closed => write!(f, "ws closed"),
        }
    }
}

impl From<std::io::Error> for WsError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}

/// One websocket client connection to a CDP target.
pub struct WsClient {
    stream: TcpStream,
    buf: Vec<u8>,
}

impl WsClient {
    /// Connect and perform the RFC 6455 handshake. `addr` is `host:port`,
    /// `path` starts with `/` (e.g. `/devtools/page/<id>`).
    pub fn connect(addr: &str, path: &str, timeout: Duration) -> Result<Self, WsError> {
        let mut stream = TcpStream::connect(addr)?;
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))?;
        let key = handshake_key();
        let request = format!(
            "GET {path} HTTP/1.1\r\nHost: {addr}\r\nUpgrade: websocket\r\n\
             Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\
             Sec-WebSocket-Version: 13\r\n\r\n"
        );
        stream.write_all(request.as_bytes())?;
        let mut response = Vec::with_capacity(512);
        let mut byte = [0u8; 1];
        while !response.ends_with(b"\r\n\r\n") {
            let read = stream.read(&mut byte)?;
            if read == 0 {
                return Err(WsError::Protocol("eof during handshake".into()));
            }
            response.push(byte[0]);
            if response.len() > 8192 {
                return Err(WsError::Protocol("handshake too large".into()));
            }
        }
        let head = String::from_utf8_lossy(&response);
        if !head.starts_with("HTTP/1.1 101") {
            return Err(WsError::Protocol(head.lines().next().unwrap_or("").into()));
        }
        Ok(Self {
            stream,
            buf: Vec::new(),
        })
    }

    /// Send one masked text frame.
    pub fn send_text(&mut self, payload: &str) -> Result<(), WsError> {
        self.send_frame(0x1, payload.as_bytes())
    }

    fn send_frame(&mut self, opcode: u8, data: &[u8]) -> Result<(), WsError> {
        let mut frame = Vec::with_capacity(data.len() + 14);
        frame.push(0x80 | opcode);
        let mask = mask_key();
        let length = data.len();
        if length < 126 {
            frame.push(0x80 | length as u8);
        } else if length <= u16::MAX as usize {
            frame.push(0x80 | 126);
            frame.extend_from_slice(&(length as u16).to_be_bytes());
        } else {
            frame.push(0x80 | 127);
            frame.extend_from_slice(&(length as u64).to_be_bytes());
        }
        frame.extend_from_slice(&mask);
        frame.extend(data.iter().enumerate().map(|(i, b)| b ^ mask[i % 4]));
        self.stream.write_all(&frame)?;
        Ok(())
    }

    /// Receive the next complete text message before `deadline`.
    /// Returns `Ok(None)` when the deadline passes with no message, and an
    /// error when the connection closes or times out mid-message.
    pub fn recv_text_until(&mut self, deadline: Instant) -> Result<Option<String>, WsError> {
        loop {
            if let Some((opcode, payload, consumed)) = parse_frame(&self.buf)? {
                self.buf.drain(..consumed);
                match opcode {
                    0x1 => {
                        let text = String::from_utf8(payload)
                            .map_err(|error| WsError::Protocol(error.to_string()))?;
                        return Ok(Some(text));
                    }
                    0x2 => {} // binary: CDP uses text
                    0x8 => return Err(WsError::Closed),
                    0x9 => self.send_frame(0xA, &payload)?,
                    0xA => {}
                    other => {
                        return Err(WsError::Protocol(format!("opcode {other}")));
                    }
                }
                continue;
            }
            // Need more bytes; honor the deadline only between messages.
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() && self.buf.is_empty() {
                return Ok(None);
            }
            self.stream
                .set_read_timeout(Some(remaining.max(Duration::from_millis(1))))?;
            let mut chunk = [0u8; 8192];
            match self.stream.read(&mut chunk) {
                Ok(0) => return Err(WsError::Closed),
                Ok(read) => self.buf.extend_from_slice(&chunk[..read]),
                Err(error)
                    if matches!(error.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) =>
                {
                    if self.buf.is_empty() && !remaining.is_zero() {
                        continue;
                    }
                    if self.buf.is_empty() {
                        return Ok(None);
                    }
                }
                Err(error) => return Err(WsError::Io(error)),
            }
        }
    }
}

/// Parse one frame from the head of `buf`. Returns `(opcode, payload, consumed)`.
fn parse_frame(buf: &[u8]) -> Result<Option<(u8, Vec<u8>, usize)>, WsError> {
    if buf.len() < 2 {
        return Ok(None);
    }
    let opcode = buf[0] & 0x0F;
    let masked = buf[1] & 0x80 != 0;
    let length = (buf[1] & 0x7F) as usize;
    let mut offset = 2;
    let length = match length {
        126 => {
            if buf.len() < offset + 2 {
                return Ok(None);
            }
            let value = u16::from_be_bytes([buf[offset], buf[offset + 1]]) as usize;
            offset += 2;
            value
        }
        127 => {
            if buf.len() < offset + 8 {
                return Ok(None);
            }
            let mut bytes = [0u8; 8];
            bytes.copy_from_slice(&buf[offset..offset + 8]);
            offset += 8;
            u64::from_be_bytes(bytes) as usize
        }
        other => other,
    };
    let mask = if masked {
        if buf.len() < offset + 4 {
            return Ok(None);
        }
        let mask = [
            buf[offset],
            buf[offset + 1],
            buf[offset + 2],
            buf[offset + 3],
        ];
        offset += 4;
        Some(mask)
    } else {
        None
    };
    if buf.len() < offset + length {
        return Ok(None);
    }
    let mut payload = buf[offset..offset + length].to_vec();
    if let Some(mask) = mask {
        for (i, byte) in payload.iter_mut().enumerate() {
            *byte ^= mask[i % 4];
        }
    }
    Ok(Some((opcode, payload, offset + length)))
}

/// Plain HTTP GET for `/json/list` and `/json/version`. Returns the body.
pub fn http_get(addr: &str, path: &str, timeout: Duration) -> Result<String, WsError> {
    let mut stream = TcpStream::connect(addr)?;
    stream.set_read_timeout(Some(timeout))?;
    // HTTP/1.1: Chromium's devtools server rejects 1.0. It also does NOT close
    // the socket even with `Connection: close`, so read to Content-Length (with
    // the read timeout treated as end-of-read) instead of `read_to_end`.
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {addr}\r\nAccept: application/json\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes())?;
    let mut response = Vec::with_capacity(8 * 1024);
    loop {
        let split = find_header_end(&response);
        if let Some(head_end) = split {
            if let Some(length) = content_length(&response[..head_end]) {
                if response.len() >= head_end + 4 + length {
                    break;
                }
            }
        }
        let mut chunk = [0u8; 8192];
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(read) => response.extend_from_slice(&chunk[..read]),
            Err(error) if matches!(error.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                break;
            }
            Err(error) => return Err(WsError::Io(error)),
        }
    }
    let split = find_header_end(&response).ok_or_else(|| {
        WsError::Protocol(format!("no header terminator ({} bytes)", response.len()))
    })?;
    let head = String::from_utf8_lossy(&response[..split]);
    if !head.lines().next().unwrap_or("").contains(" 200 ") {
        return Err(WsError::Protocol(head.lines().next().unwrap_or("").into()));
    }
    String::from_utf8(response[split + 4..].to_vec())
        .map_err(|error| WsError::Protocol(error.to_string()))
}

fn find_header_end(buffer: &[u8]) -> Option<usize> {
    buffer.windows(4).position(|window| window == b"\r\n\r\n")
}

fn content_length(head: &[u8]) -> Option<usize> {
    let head = String::from_utf8_lossy(head);
    for line in head.lines() {
        let lower = line.to_ascii_lowercase();
        if let Some(value) = lower.strip_prefix("content-length:") {
            return value.trim().parse().ok();
        }
    }
    None
}

fn handshake_key() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mut bytes = [0u8; 16];
    bytes[..8].copy_from_slice(&nanos.to_le_bytes()[..8]);
    bytes[8..].copy_from_slice(&(nanos.rotate_left(17) ^ 0x9E37_79B9_7F4A_7C15).to_le_bytes()[..8]);
    base64(&bytes)
}

fn mask_key() -> [u8; 4] {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.subsec_nanos())
        .unwrap_or(0);
    nanos.to_le_bytes()
}

fn base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = chunk.get(1).copied().unwrap_or(0) as u32;
        let b2 = chunk.get(2).copied().unwrap_or(0) as u32;
        let triple = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[(triple >> 18) as usize & 63] as char);
        out.push(TABLE[(triple >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            TABLE[(triple >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TABLE[triple as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

/// Split a `ws://host:port/path` URL into `(host:port, /path)`.
pub fn split_ws_url(url: &str) -> Result<(String, String), WsError> {
    let rest = url
        .strip_prefix("ws://")
        .ok_or_else(|| WsError::Protocol(format!("not ws url: {url}")))?;
    let (addr, path) = rest
        .split_once('/')
        .ok_or_else(|| WsError::Protocol(format!("no path in url: {url}")))?;
    Ok((addr.to_string(), format!("/{path}")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    fn read_client_frame(stream: &mut TcpStream) -> Vec<u8> {
        let mut header = [0u8; 2];
        stream.read_exact(&mut header).unwrap();
        let mut length = (header[1] & 0x7F) as usize;
        if length == 126 {
            let mut ext = [0u8; 2];
            stream.read_exact(&mut ext).unwrap();
            length = u16::from_be_bytes(ext) as usize;
        } else if length == 127 {
            let mut ext = [0u8; 8];
            stream.read_exact(&mut ext).unwrap();
            length = u64::from_be_bytes(ext) as usize;
        }
        let mut mask = [0u8; 4];
        stream.read_exact(&mut mask).unwrap();
        let mut payload = vec![0u8; length];
        stream.read_exact(&mut payload).unwrap();
        for (i, byte) in payload.iter_mut().enumerate() {
            *byte ^= mask[i % 4];
        }
        payload
    }

    fn write_server_text(stream: &mut TcpStream, payload: &[u8]) {
        let mut frame = vec![0x81];
        if payload.len() < 126 {
            frame.push(payload.len() as u8);
        } else {
            frame.push(126);
            frame.extend_from_slice(&(payload.len() as u16).to_be_bytes());
        }
        frame.extend_from_slice(payload);
        stream.write_all(&frame).unwrap();
    }

    #[test]
    fn websocket_round_trip_with_masking_and_lengths() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap().to_string();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut byte = [0u8; 1];
            while !request.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
            }
            let head = String::from_utf8_lossy(&request);
            assert!(head.contains("Sec-WebSocket-Key:"));
            stream
                .write_all(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                .unwrap();
            write_server_text(&mut stream, b"hello-from-server");
            assert_eq!(read_client_frame(&mut stream), b"client->server-01");
            let long = vec![b'x'; 300];
            write_server_text(&mut stream, &long);
            assert_eq!(read_client_frame(&mut stream), b"bye");
        });
        let mut client = WsClient::connect(&addr, "/devtools/page/TEST", Duration::from_secs(5))
            .expect("handshake");
        client.send_text("client->server-01").unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        assert_eq!(
            client.recv_text_until(deadline).unwrap().as_deref(),
            Some("hello-from-server")
        );
        let long = client.recv_text_until(deadline).unwrap().unwrap();
        assert_eq!(long.len(), 300);
        client.send_text("bye").unwrap();
        server.join().unwrap();
    }

    #[test]
    fn http_get_returns_body() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap().to_string();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut byte = [0u8; 1];
            while !request.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                request.push(byte[0]);
            }
            let body = "[{\"id\":\"A\"}]";
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(response.as_bytes()).unwrap();
        });
        let body = http_get(&addr, "/json/list", Duration::from_secs(5)).unwrap();
        assert_eq!(body, "[{\"id\":\"A\"}]");
        server.join().unwrap();
    }
    #[test]
    fn split_ws_url_parses_loopback() {
        let (addr, path) = split_ws_url("ws://127.0.0.1:9222/devtools/page/ABC").unwrap();
        assert_eq!(addr, "127.0.0.1:9222");
        assert_eq!(path, "/devtools/page/ABC");
    }

    #[test]
    #[ignore]
    fn raw_http_probe() {
        let mut stream = TcpStream::connect("127.0.0.1:9222").unwrap();
        stream
            .set_read_timeout(Some(Duration::from_millis(1500)))
            .unwrap();
        stream
            .write_all(
                b"GET /json/version HTTP/1.1\r\nHost: 127.0.0.1:9222\r\nAccept: application/json\r\nConnection: close\r\n\r\n",
            )
            .unwrap();
        let mut buf = Vec::new();
        match stream.read_to_end(&mut buf) {
            Ok(read) => println!("read_to_end ok: {read} bytes"),
            Err(error) => println!("read_to_end err: {error} after {} bytes", buf.len()),
        }
        let head = String::from_utf8_lossy(&buf[..buf.len().min(260)]).replace('\r', "<CR>");
        println!("head: {head}");
    }
}
