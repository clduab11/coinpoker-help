//! `core-engine` — mathematical decision kernel.
//!
//! Pure, deterministic computation of the quantities a decision-support
//! system needs: pot odds, implied odds, hand equity, and expected value
//! for multi-way pots.
//!
//! Modules:
//! - `pot_odds` — pot odds, implied odds, and expected value
//! - `equity`   — Monte Carlo equity estimation via `rs-poker`
//! - `decision` — legal-action-aware Fold/Check/Call/Raise recommendations

pub mod decision;
pub mod equity;
pub mod pot_odds;
