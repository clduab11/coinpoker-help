//! `opponent-model` — adaptive opponent modeling.
//!
//! Builds dynamic opponent profiles from historical hand data and adjusts
//! recommended actions to exploit statistical inefficiencies. v1 uses a
//! deterministic threshold classifier; `linfa`-backed models are planned
//! as an optional upgrade.
//!
//! Modules (built out in subsequent steps):
//! - `features`   — VPIP, PFR, AF, WTSD feature extraction
//! - `classifier` — archetype classification (LAG/TAG/LP/TP)
//! - `exploit`    — profile-based action adjustments

pub mod classifier;
pub mod exploit;
pub mod features;
