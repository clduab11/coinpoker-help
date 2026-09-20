//! `coinpoker` — shared library for the decision-support binary.
//!
//! Holds the pieces that tests and the overlay UI need to drive directly:
//! the decision [`pipeline`], the [`cli`] argument parser, and the
//! environment-driven [`config`] loaders. The thin `main.rs` binary keeps
//! only the IO loops.

pub mod cli;
pub mod config;
pub mod pipeline;
