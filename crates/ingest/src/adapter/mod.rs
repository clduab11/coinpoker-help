//! State adapters — exactly two implementations, per PLAN §1.2 (amended by the
//! Phase 0 verdict, `docs/PHASE0.md` §10):
//!
//! - [`cdp`] reads the Electron **lobby surface** (listing, identity, join,
//!   wallet) over Chrome DevTools Protocol on loopback. The felt is *not* DOM.
//! - [`cv`] enumerates the per-table **Unity windows** (`UnityWndClass`,
//!   800x613); felt fields come from the existing capture/Laya pipeline behind
//!   this seam. CV never runs for lobby fields while CDP is attached.
//!
//! `read` is a pure observation: adapters never advance hidden baselines here;
//! change detection is carried by `seq`/`captured_at_ms` in the returned
//! [`RawRead`]. Capability flags are per surface x field, so the engine can
//! gate on trust instead of guessing.

pub mod cdp;
pub mod cv;
pub mod ws;

use std::collections::BTreeMap;

/// Per-field trust level. `Unavailable` must never be guessed over.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Trust {
    Exact,
    Heuristic,
    Unavailable,
}

/// Which surface a capability set describes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Surface {
    Lobby,
    Felt,
}

/// Capability table: for each surface, the fields and their trust.
#[derive(Debug, Clone, serde::Serialize)]
pub struct Capabilities {
    pub adapter: &'static str,
    pub entries: Vec<(Surface, &'static str, Trust)>,
}

impl Capabilities {
    pub fn trust(&self, surface: Surface, field: &str) -> Trust {
        self.entries
            .iter()
            .find(|(s, f, _)| *s == surface && *f == field)
            .map(|(_, _, trust)| *trust)
            .unwrap_or(Trust::Unavailable)
    }

    pub fn by_surface(&self, surface: Surface) -> BTreeMap<&'static str, Trust> {
        self.entries
            .iter()
            .filter(|(s, _, _)| *s == surface)
            .map(|(_, field, trust)| (*field, *trust))
            .collect()
    }
}

/// Lobby fields CDP supplies exactly; felt fields stay CV's job.
pub fn cdp_capabilities() -> Capabilities {
    Capabilities {
        adapter: "cdp",
        entries: vec![
            (Surface::Lobby, "tables", Trust::Exact),
            (Surface::Lobby, "user", Trust::Exact),
            (Surface::Lobby, "wallet", Trust::Exact),
            (Surface::Felt, "identity", Trust::Exact),
            (Surface::Felt, "cards", Trust::Unavailable),
        ],
    }
}

/// The felt is Unity-rendered; visuals are heuristic until measured per field.
pub fn cv_capabilities() -> Capabilities {
    Capabilities {
        adapter: "cv",
        entries: vec![
            (Surface::Lobby, "tables", Trust::Unavailable),
            (Surface::Felt, "identity", Trust::Heuristic),
            (Surface::Felt, "cards", Trust::Heuristic),
            (Surface::Felt, "board", Trust::Heuristic),
            (Surface::Felt, "pot", Trust::Heuristic),
            (Surface::Felt, "stacks", Trust::Heuristic),
            (Surface::Felt, "actions", Trust::Heuristic),
            (Surface::Felt, "timer", Trust::Heuristic),
        ],
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TableTargetKind {
    /// Electron lobby/listing page (CDP).
    LobbyPage,
    /// Unity table window (CV).
    FeltWindow,
}

/// One addressable entity of the client.
#[derive(Debug, Clone)]
pub struct TableTarget {
    pub kind: TableTargetKind,
    pub id: String,
    pub title: Option<String>,
    pub url: Option<String>,
    pub pid: Option<u32>,
    pub hwnd: Option<u64>,
}

impl TableTarget {
    pub fn label(&self) -> String {
        self.title
            .clone()
            .or_else(|| self.url.clone())
            .unwrap_or_else(|| self.id.clone())
    }
}

/// One pure observation from an adapter.
#[derive(Debug, Clone)]
pub struct RawRead {
    pub fields: serde_json::Value,
    pub seq: Option<u64>,
    pub captured_at_ms: u64,
    pub provenance: &'static str,
}

#[derive(Debug)]
pub enum AdapterError {
    /// The adapter surface is currently unreachable (client closed, no target).
    Unavailable(String),
    /// Reachable but the exchange did not follow the contract.
    Protocol(String),
}

impl std::fmt::Display for AdapterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unavailable(message) => write!(f, "adapter unavailable: {message}"),
            Self::Protocol(message) => write!(f, "adapter protocol: {message}"),
        }
    }
}

impl std::error::Error for AdapterError {}

/// The two-impl seam. `read` must be pure; `attach` must be idempotent and
/// re-establish itself after a client relaunch (new targetId / hwnd).
pub trait TableAdapter {
    /// Enumerate current candidates. Cheap; called on a slow cadence.
    fn targets(&mut self) -> Result<Vec<TableTarget>, AdapterError>;

    /// Attach to one target (idempotent; re-attach after relaunch).
    fn attach(&mut self, target: &TableTarget) -> Result<(), AdapterError>;

    /// Pure read of the whole state for one target.
    fn read(&self, target: &TableTarget) -> Result<RawRead, AdapterError>;

    /// Trust table for this adapter kind.
    fn capabilities(&self) -> Capabilities;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capability_lookup_is_per_surface() {
        let caps = cdp_capabilities();
        assert_eq!(caps.trust(Surface::Lobby, "tables"), Trust::Exact);
        assert_eq!(caps.trust(Surface::Felt, "cards"), Trust::Unavailable);
        assert_eq!(caps.trust(Surface::Lobby, "nonsense"), Trust::Unavailable);
        let cv = cv_capabilities();
        assert_eq!(cv.trust(Surface::Lobby, "tables"), Trust::Unavailable);
        assert_eq!(cv.trust(Surface::Felt, "pot"), Trust::Heuristic);
        assert_eq!(cv.by_surface(Surface::Felt).len(), 7);
    }
}
