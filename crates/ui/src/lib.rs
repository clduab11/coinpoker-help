//! `ui` — minimalist output interface.
//!
//! Presents the primary decision (Fold/Call/Raise) and the underlying
//! probability metrics with a high signal-to-noise ratio, in two modes:
//! an egui desktop panel and a headless JSON/WebSocket stream.
//!
//! Modules (built out in subsequent steps):
//! - `app`      — egui application state
//! - `widgets`  — decision panel and probability metric widgets
//! - `headless` — JSON stdout / WebSocket output

pub mod app;
pub mod headless;
pub mod widgets;
