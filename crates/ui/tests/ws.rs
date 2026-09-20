use std::io::{self, Read, Write};
use std::net::TcpStream;
use std::time::Duration;

use ui::overlay::{OverlayEvent, TableBounds};
use ui::ws::EventMirrorServer;

#[test]
fn server_broadcasts_valid_overlay_event_json_to_a_websocket_client() {
    let server = EventMirrorServer::bind().expect("bind loopback mirror");
    let mut first = connect_mock_client(&server);
    let mut second = connect_mock_client(&server);

    server.publish(&OverlayEvent::Position(TableBounds {
        x: 12.5,
        y: 34.5,
        width: 800.0,
        height: 600.0,
    }));
    for client in [&mut first, &mut second] {
        let payload = read_text_frame(client).expect("read broadcast text frame");
        let event: serde_json::Value = serde_json::from_slice(&payload).expect("valid event JSON");
        assert_eq!(event["event"], "position");
        assert_eq!(event["payload"]["width"], 800.0);
    }

    server.publish(&OverlayEvent::Clear("action-not-required".to_string()));
    let payload = read_text_frame(&mut first).expect("read second event");
    let event: serde_json::Value = serde_json::from_slice(&payload).expect("valid event JSON");
    assert_eq!(event["event"], "clear");
    assert_eq!(event["payload"], "action-not-required");

    server.shutdown();
}

fn connect_mock_client(server: &EventMirrorServer) -> TcpStream {
    let mut client = TcpStream::connect(server.local_addr()).expect("connect client");
    client
        .set_read_timeout(Some(Duration::from_secs(1)))
        .expect("set read timeout");
    client
        .write_all(
            b"GET / HTTP/1.1\r\n\
              Host: localhost\r\n\
              Upgrade: websocket\r\n\
              Connection: Upgrade\r\n\
              Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\
              Sec-WebSocket-Version: 13\r\n\
              \r\n",
        )
        .expect("write complete handshake");
    client.flush().expect("flush handshake");
    let response = read_until(&mut client, b"\r\n\r\n").expect("read handshake response");
    assert!(response.starts_with(b"HTTP/1.1 101 Switching Protocols"));
    client
}

fn read_until(stream: &mut TcpStream, marker: &[u8]) -> io::Result<Vec<u8>> {
    let mut received = Vec::new();
    let mut buffer = [0_u8; 256];
    loop {
        let read = stream.read(&mut buffer)?;
        if read == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "connection closed before marker",
            ));
        }
        received.extend_from_slice(&buffer[..read]);
        if received
            .windows(marker.len())
            .any(|window| window == marker)
        {
            return Ok(received);
        }
    }
}

fn read_text_frame(stream: &mut TcpStream) -> io::Result<Vec<u8>> {
    let mut header = [0_u8; 2];
    stream.read_exact(&mut header)?;
    if header[0] != 0x81 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "expected final text frame",
        ));
    }
    let length = match header[1] {
        length @ 0..=125 => usize::from(length),
        126 => {
            let mut bytes = [0_u8; 2];
            stream.read_exact(&mut bytes)?;
            usize::from(u16::from_be_bytes(bytes))
        }
        127 => {
            let mut bytes = [0_u8; 8];
            stream.read_exact(&mut bytes)?;
            usize::try_from(u64::from_be_bytes(bytes)).map_err(|_| {
                io::Error::new(io::ErrorKind::InvalidData, "frame exceeds address space")
            })?
        }
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "masked server frame",
            ))
        }
    };
    let mut payload = vec![0_u8; length];
    stream.read_exact(&mut payload)?;
    Ok(payload)
}
