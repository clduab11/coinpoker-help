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
//! - `outs`     — rule of two and four, exact draw equity, memorized draws
//! - `ranges`   — six-handed preflop opening ranges and hand-notation parsing
//! - `table_rules` — seat positions and betting rounds from
//!   `poker-info-sheet.pdf`, used by the Laya perception assembly

pub mod decision;
pub mod equity;
pub mod outs;
pub mod pot_odds;
pub mod ranges;
pub mod table_rules;
