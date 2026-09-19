//! `ui` — minimalist output interface.
//!
//! Presents the primary decision (Fold/Call/Raise) and the underlying
//! probability metrics with a high signal-to-noise ratio. JSON-lines output is
//! always available; the unwired egui panel is compiled only with the
//! `desktop` feature.
//!
//! Modules:
//! - `app`      — optional egui application state (`desktop` feature)
//! - `widgets`  — decision view and optional panel rendering
//! - `headless` — JSON-lines stdout output

#[cfg(feature = "desktop")]
pub mod app;
pub mod headless;
pub mod widgets;
