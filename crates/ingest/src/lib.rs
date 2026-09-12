//! `ingest` — VLM-based game state ingestion.
//!
//! This crate owns the perception pipeline: it captures the target
//! application window, detects when the visible table state changes, and
//! extracts a structured [`GameState`] via a local visual language model.
//!
//! Modules (built out in subsequent steps):
//! - `capture`       — window capture via ScreenCaptureKit (macOS)
//! - `change_detect` — cheap pixel-diff trigger to avoid needless inference
//! - `vlm`           — multimodal inference via llama.cpp
//! - `parser`        — VLM JSON output → validated [`GameState`]
//! - `prompt`        — system prompt and few-shot templates
//! - `state_machine` — game-phase tracking and event emission

pub mod capture;
pub mod change_detect;
pub mod parser;
pub mod prompt;
pub mod state_machine;
pub mod vlm;
