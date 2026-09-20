//! `ingest` — VLM-based game state ingestion.
//!
//! This crate owns the perception pipeline: it captures the target
//! application window, detects when the visible table state changes, and
//! extracts a structured [`GameState`] via a local visual language model.
//!
//! Modules:
//! - `capture`       — SCStream delegate window capture (macOS)
//! - `change_detect` — baseline pixel-diff and zone-masked perceptual-hash triggers
//! - `record`        — optional frame fixture recording for offline testing
//! - `roi`           — crop and downscale frames before VLM submission
//! - `vlm`           — OpenAI-compatible client for a local MLX VLM server
//! - `schema`        — JSON Schema for constrained VLM output
//! - `consensus`     — 2-of-N observation agreement before state changes
//! - `parser`        — VLM JSON output → validated [`GameState`]
//! - `prompt`        — strict system and analysis prompts
//! - `state_machine` — decision-relevant state tracking and event emission
//!
//! [`GameState`]: crate::parser::GameState

pub mod capture;
pub mod change_detect;
pub mod consensus;
pub mod parser;
pub mod prompt;
pub mod record;
pub mod roi;
pub mod schema;
pub mod state_machine;
pub mod vlm;
