//! `ui` — minimalist output interface.
//!
//! Presents the primary decision (Fold/Call/Raise) and the underlying
//! probability metrics with a high signal-to-noise ratio. JSON-lines output is
//! always available; the egui overlay is compiled only with the `desktop`
//! feature.
//!
//! Modules:
//! - `app`      — optional egui overlay application (`desktop` feature)
//! - `widgets`  — decision view, geometry helpers, and overlay rendering
//! - `overlay`  — overlay event model and headless state transitions
//! - `headless` — JSON-lines stdout output
//! - `ws`       — optional localhost WebSocket event mirror (`ws` feature)

#[cfg(feature = "desktop")]
pub mod app;
pub mod headless;
pub mod overlay;
pub mod widgets;
#[cfg(feature = "ws")]
pub mod ws;
