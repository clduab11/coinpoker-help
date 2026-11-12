//! `ui` — decision presentation.
//!
//! JSON-lines output is always available; the egui overlay compiles only with
//! the `desktop` feature and the loopback WebSocket mirror only with `ws`.
//!
//! Modules:
//! - `app`      — optional egui overlay application (`desktop` feature)
//! - `overlay`  — overlay event model and headless state transitions
//! - `widgets`  — decision view, geometry helpers, and overlay rendering
//! - `headless` — JSON-lines stdout output
//! - `ws`       — optional localhost WebSocket event mirror (`ws` feature)

#[cfg(feature = "desktop")]
pub mod app;
pub mod headless;
pub mod overlay;
pub mod widgets;
#[cfg(feature = "ws")]
pub mod ws;
