//! `ui` — minimalist output interface (merged from the `ui` crate).
//!
//! JSON-lines output is always available; the unwired egui panel is compiled
//! only with the `desktop` feature.
//!
//! Modules:
//! - `app`      — optional egui application state (`desktop` feature)
//! - `widgets`  — decision view and optional panel rendering
//! - `headless` — JSON-lines stdout output

#[cfg(feature = "desktop")]
pub mod app;
pub mod headless;
pub mod widgets;
