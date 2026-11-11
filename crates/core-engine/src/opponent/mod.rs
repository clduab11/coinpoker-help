//! Opponent modeling: observation ledger, feature stats, archetype
//! classification, and exploit deltas.
//!
//! Merged from the former `opponent-model` crate (module paths are unchanged
//! below the crate root: `core_engine::opponent::*`).

pub mod betting;
pub mod classifier;
pub mod exploit;
pub mod features;
pub mod observer;
pub mod observing;
pub mod position;
