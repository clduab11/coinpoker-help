//! `ghost-layer` — behavioral mimicry.
//!
//! Injects human-like variance into the system's output so that decisions
//! retain behavioral parity with a human operator: log-normal reaction-time
//! distributions and discretized bet sizing with rare off-grid events.
//!
//! Modules (built out in subsequent steps):
//! - `temporal`        — log-normal reaction-time sampling
//! - `betting_entropy` — weighted sizing menu with off-grid jitter
//! - `profile`         — serializable human-parity parameter store

pub mod betting_entropy;
pub mod profile;
pub mod temporal;
