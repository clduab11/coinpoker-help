//! Headless JSON output.
//!
//! Emits decision recommendations as JSON lines to stdout for programmatic
//! consumers. A WebSocket transport is a planned follow-up; the emitter
//! interface keeps the transport swappable.

use crate::widgets::DecisionView;

/// A transport for headless output.
pub trait Emit {
    fn emit(&self, line: &str);
}

/// Emits JSON lines to stdout.
#[derive(Debug, Clone, Copy, Default)]
pub struct StdoutEmitter;

impl Emit for StdoutEmitter {
    fn emit(&self, line: &str) {
        println!("{line}");
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
    pub fn emit_decision(&self, view: &DecisionView) -> Result<(), serde_json::Error> {
        let line = serde_json::to_string(view)?;
        self.transport.emit(&line);
        Ok(())
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
        fn emit(&self, line: &str) {
            self.0.lock().expect("lock").push(line.to_string());
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
    fn stdout_emitter_constructs() {
        let _ = stdout();
    }
}
