//! Headless JSON output.
//!
//! Emits decision recommendations as JSON lines to stdout for programmatic
//! consumers. A WebSocket transport is a planned follow-up; the emitter
//! interface keeps the transport swappable.

use std::io::{self, Write};

use crate::widgets::DecisionView;

/// A transport for headless output.
pub trait Emit {
    fn emit(&self, line: &str) -> io::Result<()>;
}

/// Emits JSON lines to stdout.
#[derive(Debug, Clone, Copy, Default)]
pub struct StdoutEmitter;

impl Emit for StdoutEmitter {
    fn emit(&self, line: &str) -> io::Result<()> {
        writeln!(io::stdout().lock(), "{line}")
    }
}

/// Serializes decision views and pushes them to a transport.
#[derive(Debug, Clone)]
pub struct HeadlessEmitter<E: Emit> {
    transport: E,
}

impl<E: Emit> HeadlessEmitter<E> {
    pub fn new(transport: E) -> Self {
        Self { transport }
    }

    /// Emit one decision as a JSON line.
    pub fn emit_decision(&self, view: &DecisionView) -> io::Result<()> {
        let line = serde_json::to_string(view)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        self.transport.emit(&line)
    }

    /// Tell stream consumers that any previously emitted recommendation is no
    /// longer actionable.
    pub fn emit_clear(&self, reason: &str) -> io::Result<()> {
        let line = serde_json::to_string(&serde_json::json!({
            "event": "clear",
            "reason": reason,
        }))
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        self.transport.emit(&line)
    }
}

/// Convenience constructor for the stdout emitter.
pub fn stdout() -> HeadlessEmitter<StdoutEmitter> {
    HeadlessEmitter::new(StdoutEmitter)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// Test transport that captures emitted lines.
    #[derive(Debug, Default)]
    struct Capture(Mutex<Vec<String>>);

    impl Emit for std::sync::Arc<Capture> {
        fn emit(&self, line: &str) -> io::Result<()> {
            self.0.lock().expect("lock").push(line.to_string());
            Ok(())
        }
    }

    fn view() -> DecisionView {
        DecisionView {
            action: "raise".to_string(),
            amount: 750,
            ev: 0.67,
            pot_odds: Some(0.238),
            equity: 0.412,
            break_even: Some(0.238),
            opponent: Some("tag".to_string()),
            confidence: Some(0.9),
        }
    }

    #[test]
    fn emits_one_json_line_per_decision() {
        let capture = std::sync::Arc::new(Capture::default());
        let emitter = HeadlessEmitter::new(capture.clone());
        emitter.emit_decision(&view()).expect("serialize");

        let lines = capture.0.lock().expect("lock");
        assert_eq!(lines.len(), 1);
        let parsed: serde_json::Value = serde_json::from_str(&lines[0]).expect("valid json");
        assert_eq!(parsed["action"], "raise");
        assert_eq!(parsed["amount"], 750);
        assert_eq!(parsed["ev"], 0.67);
    }

    #[test]
    fn emits_clear_event() {
        let capture = std::sync::Arc::new(Capture::default());
        let emitter = HeadlessEmitter::new(capture.clone());
        emitter
            .emit_clear("action-not-required")
            .expect("serialize");

        let lines = capture.0.lock().expect("lock");
        let parsed: serde_json::Value = serde_json::from_str(&lines[0]).expect("valid json");
        assert_eq!(parsed["event"], "clear");
        assert_eq!(parsed["reason"], "action-not-required");
    }

    #[test]
    fn stdout_emitter_constructs() {
        let _ = stdout();
    }
}
