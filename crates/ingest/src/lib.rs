//! `ingest` — VLM-based game state ingestion.
//!
//! This crate owns the perception pipeline: it captures the target
//! application window, detects when the visible table state changes, and
//! extracts a structured [`GameState`] via a local visual language model.
//!
//! Modules:
//! - `adapter`       — per-surface table adapters (CDP lobby; CV felt)
//! - `capture`       — platform window capture (Windows GDI/WGC; macOS SCK)
//! - `change_detect` — baseline pixel-diff, stability, and zone-masked triggers
//! - `consensus`     — 2-of-N observation agreement before state changes
//! - `discovery`     — window/application identity and calibrated selection
//! - `laya`          — Laya Vision backend (the sole live perception backend)
//! - `parser`        — VLM JSON output → validated [`GameState`]
//! - `partial`       — source-leased partial observations and diagnostics
//! - `prompt`        — strict system and analysis prompts
//! - `record`        — optional frame fixture recording for offline testing
//! - `recorder`      — private PNG capture sessions with a manifest
//! - `roi`           — crop and downscale frames before VLM submission
//! - `runtime`       — live scheduling, admission gates, and event emission
//! - `schema`        — JSON Schema for constrained VLM output
//! - `screen`        — screen classification and strict state validation
//! - `state_machine` — decision-relevant state tracking and event emission
//! - `vlm`           — backend contract, error codes, and loopback transport policy
//!
//! [`GameState`]: crate::parser::GameState

pub mod adapter;
pub mod capture;
pub mod change_detect;
pub mod consensus;
pub mod discovery;
pub mod laya;
pub mod parser;
pub mod partial;
pub mod prompt;
pub mod record;
pub mod recorder;
pub mod roi;
pub mod runtime;
pub mod schema;
pub mod screen;
pub mod state_machine;
pub mod vlm;
#[cfg(target_os = "windows")]
pub mod windows;
