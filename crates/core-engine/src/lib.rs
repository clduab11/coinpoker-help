//! `core-engine` — mathematical decision kernel.
//!
//! Pure, deterministic computation of the quantities a decision-support
//! system needs: pot odds, implied odds, hand equity, and expected value
//! for multi-way pots.
//!
//! Modules (built out in subsequent steps):
//! - `pot_odds` — pot odds, implied odds, multi-way EV
//! - `equity`   — Monte Carlo equity estimation via `rs-poker`
//! - `decision` — Fold/Call/Raise recommendation with confidence bounds

pub mod decision;
pub mod equity;
pub mod pot_odds;
