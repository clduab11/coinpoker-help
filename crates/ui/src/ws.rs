//! Feature-gated loopback WebSocket mirror for [`OverlayEvent`]s.
//!
//! This deliberately implements only the server-to-client RFC 6455 text-frame
//! subset required by local consumers. It binds to `127.0.0.1` only, accepts a
//! standard opening handshake, and drops slow or disconnected clients without
//! interrupting the study overlay.

use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use crate::overlay::OverlayEvent;

const HANDSHAKE_LIMIT: usize = 16 * 1024;
const WEBSOCKET_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

/// Publishes overlay events to a local [`EventMirrorServer`].
#[derive(Debug, Clone)]
pub struct EventPublisher {
    events: mpsc::Sender<String>,
}

impl EventPublisher {
    /// Queue an event for every connected client.
    ///
    /// Serialization and receiver failures are intentionally ignored: the
    /// overlay must continue working even when an external consumer exits.
    pub fn publish(&self, event: &OverlayEvent) {
        if let Ok(payload) = serde_json::to_string(event) {
            let _ = self.events.send(payload);
        }
    }
}

/// A loopback-only server that mirrors serialized [`OverlayEvent`] values.
#[derive(Debug)]
pub struct EventMirrorServer {
    address: SocketAddr,
    publisher: EventPublisher,
    shutdown: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl EventMirrorServer {
    /// Bind an ephemeral loopback port and start accepting WebSocket clients.
    pub fn bind() -> io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        let address = listener.local_addr()?;
        listener.set_nonblocking(true)?;

        let (events, receiver) = mpsc::channel();
        let shutdown = Arc::new(AtomicBool::new(false));
        let worker_shutdown = Arc::clone(&shutdown);
        let worker = thread::Builder::new()
            .name("overlay-ws-mirror".to_string())
            .spawn(move || run_server(listener, receiver, worker_shutdown))?;

        Ok(Self {
            address,
            publisher: EventPublisher { events },
            shutdown,
            worker: Some(worker),
        })
    }

    /// The local address external consumers should connect to.
    pub const fn local_addr(&self) -> SocketAddr {
        self.address
    }

    /// Obtain a cloneable publisher for a capture/background thread.
    pub fn publisher(&self) -> EventPublisher {
        self.publisher.clone()
    }

    /// Queue an event for every connected client.
    pub fn publish(&self, event: &OverlayEvent) {
        self.publisher.publish(event);
    }

    /// Stop the listener and join its worker thread.
    pub fn shutdown(mut self) {
        self.stop();
    }

    fn stop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

impl Drop for EventMirrorServer {
    fn drop(&mut self) {
        self.stop();
    }
}

fn run_server(listener: TcpListener, events: mpsc::Receiver<String>, shutdown: Arc<AtomicBool>) {
    let mut clients = Vec::new();
    while !shutdown.load(Ordering::Acquire) {
        accept_clients(&listener, &mut clients);
        while let Ok(payload) = events.try_recv() {
            broadcast(&mut clients, &payload);
        }
        thread::sleep(Duration::from_millis(5));
    }
}

fn accept_clients(listener: &TcpListener, clients: &mut Vec<TcpStream>) {
    loop {
        match listener.accept() {
            Ok((mut stream, _)) => {
                let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
                let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
                if complete_handshake(&mut stream).is_ok() {
                    let _ = stream.set_read_timeout(None);
                    clients.push(stream);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
            Err(_) => break,
        }
    }
}

fn complete_handshake(stream: &mut TcpStream) -> io::Result<()> {
    let request = read_http_request(stream)?;
    let request = std::str::from_utf8(&request)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "handshake is not UTF-8"))?;
    let key = request
        .split("\r\n")
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("Sec-WebSocket-Key")
                .then(|| value.trim())
        })
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing WebSocket key"))?;
    let accept = websocket_accept(key);
    stream.write_all(
        format!(
            "HTTP/1.1 101 Switching Protocols\r\n\
             Upgrade: websocket\r\n\
             Connection: Upgrade\r\n\
             Sec-WebSocket-Accept: {accept}\r\n\
             \r\n"
        )
        .as_bytes(),
    )?;
    stream.flush()
}

/// Read the full HTTP headers before responding to an opening handshake.
fn read_http_request(stream: &mut TcpStream) -> io::Result<Vec<u8>> {
    let mut request = Vec::with_capacity(1024);
    let mut bytes = [0_u8; 1024];
    while request.len() < HANDSHAKE_LIMIT {
        let read = stream.read(&mut bytes)?;
        if read == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "connection closed during handshake",
            ));
        }
        request.extend_from_slice(&bytes[..read]);
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            return Ok(request);
        }
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "WebSocket handshake is too large",
    ))
}

fn broadcast(clients: &mut Vec<TcpStream>, payload: &str) {
    let frame = text_frame(payload.as_bytes());
    let mut active = Vec::with_capacity(clients.len());
    for mut client in clients.drain(..) {
        if client.write_all(&frame).is_ok() {
            active.push(client);
        }
    }
    *clients = active;
}

fn text_frame(payload: &[u8]) -> Vec<u8> {
    let mut frame = Vec::with_capacity(payload.len() + 10);
    frame.push(0x81); // FIN + text opcode
    match payload.len() {
        length @ 0..=125 => frame.push(length as u8),
        length @ 126..=65_535 => {
            frame.push(126);
            frame.extend_from_slice(&(length as u16).to_be_bytes());
        }
        length => {
            frame.push(127);
            frame.extend_from_slice(&(length as u64).to_be_bytes());
        }
    }
    frame.extend_from_slice(payload);
    frame
}

fn websocket_accept(key: &str) -> String {
    let mut source = String::with_capacity(key.len() + WEBSOCKET_GUID.len());
    source.push_str(key);
    source.push_str(WEBSOCKET_GUID);
    base64_encode(&sha1(source.as_bytes()))
}

fn base64_encode(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut encoded = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let first = chunk[0];
        let second = *chunk.get(1).unwrap_or(&0);
        let third = *chunk.get(2).unwrap_or(&0);
        encoded.push(ALPHABET[(first >> 2) as usize] as char);
        encoded.push(ALPHABET[(((first & 0b11) << 4) | (second >> 4)) as usize] as char);
        encoded.push(if chunk.len() > 1 {
            ALPHABET[(((second & 0b1111) << 2) | (third >> 6)) as usize] as char
        } else {
            '='
        });
        encoded.push(if chunk.len() > 2 {
            ALPHABET[(third & 0b11_1111) as usize] as char
        } else {
            '='
        });
    }
    encoded
}

fn sha1(input: &[u8]) -> [u8; 20] {
    let mut message = input.to_vec();
    let bit_length = (message.len() as u64).wrapping_mul(8);
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_length.to_be_bytes());

    let mut h0 = 0x6745_2301_u32;
    let mut h1 = 0xEFCD_AB89_u32;
    let mut h2 = 0x98BA_DCFE_u32;
    let mut h3 = 0x1032_5476_u32;
    let mut h4 = 0xC3D2_E1F0_u32;

    for chunk in message.chunks_exact(64) {
        let mut words = [0_u32; 80];
        for (index, word) in words.iter_mut().take(16).enumerate() {
            let offset = index * 4;
            *word = u32::from_be_bytes(chunk[offset..offset + 4].try_into().expect("chunk size"));
        }
        for index in 16..80 {
            words[index] =
                (words[index - 3] ^ words[index - 8] ^ words[index - 14] ^ words[index - 16])
                    .rotate_left(1);
        }

        let (mut a, mut b, mut c, mut d, mut e) = (h0, h1, h2, h3, h4);
        for (index, word) in words.iter().enumerate() {
            let (function, constant) = match index {
                0..=19 => ((b & c) | ((!b) & d), 0x5A82_7999),
                20..=39 => (b ^ c ^ d, 0x6ED9_EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1B_BCDC),
                _ => (b ^ c ^ d, 0xCA62_C1D6),
            };
            let next = a
                .rotate_left(5)
                .wrapping_add(function)
                .wrapping_add(e)
                .wrapping_add(constant)
                .wrapping_add(*word);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = next;
        }
        h0 = h0.wrapping_add(a);
        h1 = h1.wrapping_add(b);
        h2 = h2.wrapping_add(c);
        h3 = h3.wrapping_add(d);
        h4 = h4.wrapping_add(e);
    }

    let mut digest = [0_u8; 20];
    for (index, word) in [h0, h1, h2, h3, h4].into_iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    digest
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rfc_handshake_example_produces_the_expected_accept_value() {
        assert_eq!(
            websocket_accept("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        );
    }

    #[test]
    fn text_frames_support_short_and_extended_payloads() {
        assert_eq!(text_frame(b"ok"), vec![0x81, 2, b'o', b'k']);
        let frame = text_frame(&[0; 126]);
        assert_eq!(&frame[..4], &[0x81, 126, 0, 126]);
    }
}
