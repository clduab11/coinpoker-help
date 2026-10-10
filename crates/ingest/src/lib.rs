//! `ingest` — VLM-based game state ingestion.
//!
//! This crate owns the perception pipeline: it captures the target
//! application window, detects when the visible table state changes, and
//! extracts a structured [`GameState`] via a local visual language model.
//!
//! Modules:
//! - `capture`       — Windows window capture via Windows Graphics Capture
//! - `change_detect` — baseline pixel-diff trigger to avoid needless inference
//! - `vlm`           — backend contract, error codes, and loopback transport policy
//! - `laya`          — Laya Vision backend (the sole live perception backend)
//! - `parser`        — VLM JSON output → validated [`GameState`]
//! - `prompt`        — strict system and analysis prompts
//! - `state_machine` — decision-relevant state tracking and event emission

pub mod capture;
pub mod change_detect;
pub mod discovery;
pub mod laya;
pub mod parser;
pub mod partial;
pub mod prompt;
pub mod recorder;
pub mod runtime;
pub mod screen;
pub mod state_machine;
pub mod vlm;
#[cfg(target_os = "windows")]
mod windows;
