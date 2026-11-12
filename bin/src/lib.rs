//! `coinpoker` — shared library for the decision-support binary.
//!
//! Holds the pieces that tests and the overlay UI need to drive directly:
//! the decision [`pipeline`] and every user-facing [`ui`] surface (overlay
//! event model, widgets, headless emitter, optional WebSocket mirror).
//! The thin `main.rs` binary keeps only the IO loops.

pub mod pipeline;
pub mod ui;
