//! `ghost-layer` — bet-sizing and latency utilities.
//!
//! Provides quantized pot-fraction bet sizing with bounded off-grid variation
//! and log-normal reaction-time sampling for decision-support experiments.
//!
//! Modules:
//! - `temporal`        — log-normal reaction-time sampling
//! - `betting_entropy` — weighted sizing menu with off-grid jitter
//! - `profile`         — serializable sizing and latency parameter store

pub mod betting_entropy;
pub mod profile;
pub mod temporal;
