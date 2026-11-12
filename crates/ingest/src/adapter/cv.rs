//! CV adapter: the per-table Unity windows (`UnityWndClass`).
//!
//! Phase 0 established that each opened table is a separate
//! `CoinPoker Game\CoinPoker.exe` process with an 800x613 window; the felt
//! (cards/pot/buttons/timer) renders there, not in the DOM. This adapter
//! enumerates those windows for identity and leaves the felt fields to the
//! existing capture + Laya pipeline (`read` returns the window geometry as the
//! felt-side observation, marked heuristic).
//!
//! No input simulation here (Phase 3): windows.rs captures, execution adds
//! input. Classification is by visible size for now (both the lobby and the
//! table windows carry the process name `CoinPoker.exe`; the lobby is
//! `Chrome_WidgetWin_1` at ~1280x778, tables are `UnityWndClass` at 800x613).

use super::{
    cv_capabilities, AdapterError, Capabilities, RawRead, TableAdapter, TableTarget,
    TableTargetKind,
};
use std::time::{SystemTime, UNIX_EPOCH};

/// Lobby windows run wider than this; table windows (800x613) do not.
const FELT_MAX_WIDTH: u32 = 1100;
const FELT_MIN_WIDTH: u32 = 400;

#[derive(Debug, Default)]
pub struct CvAdapter;

impl CvAdapter {
    pub fn new() -> Self {
        Self
    }
}

impl TableAdapter for CvAdapter {
    fn targets(&mut self) -> Result<Vec<TableTarget>, AdapterError> {
        let windows = crate::capture::WindowCapturer::list_windows()
            .map_err(|error| AdapterError::Unavailable(error.to_string()))?;
        Ok(windows
            .into_iter()
            .filter(|window| window.on_screen)
            .filter(|window| (FELT_MIN_WIDTH..=FELT_MAX_WIDTH).contains(&window.width))
            .map(|window| TableTarget {
                kind: TableTargetKind::FeltWindow,
                id: format!("hwnd:{}", window.hwnd),
                title: window.title.clone(),
                url: None,
                pid: Some(window.process_id),
                hwnd: Some(window.hwnd as u64),
            })
            .collect())
    }

    fn attach(&mut self, _target: &TableTarget) -> Result<(), AdapterError> {
        // Window handles are re-validated at capture time; nothing to hold.
        Ok(())
    }

    fn read(&self, target: &TableTarget) -> Result<RawRead, AdapterError> {
        let hwnd = target
            .hwnd
            .ok_or_else(|| AdapterError::Protocol("felt target without hwnd".into()))?;
        Ok(RawRead {
            fields: serde_json::json!({ "hwnd": hwnd, "title": target.title, "interface": "laya-cv" }),
            seq: None,
            captured_at_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_millis() as u64)
                .unwrap_or(0),
            provenance: "cv",
        })
    }

    fn capabilities(&self) -> Capabilities {
        cv_capabilities()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{Surface, Trust};

    #[test]
    fn capabilities_mark_felt_heuristic_lobby_absent() {
        let caps = CvAdapter::new().capabilities();
        assert_eq!(caps.trust(Surface::Felt, "cards"), Trust::Heuristic);
        assert_eq!(caps.trust(Surface::Lobby, "tables"), Trust::Unavailable);
        assert_eq!(caps.adapter, "cv");
    }

    #[test]
    fn read_requires_hwnd() {
        let adapter = CvAdapter::new();
        let target = TableTarget {
            kind: TableTargetKind::FeltWindow,
            id: "hwnd:0".into(),
            title: None,
            url: None,
            pid: None,
            hwnd: None,
        };
        assert!(adapter.read(&target).is_err());
        let target = TableTarget {
            hwnd: Some(1234),
            ..target.clone()
        };
        let read = adapter.read(&target).unwrap();
        assert_eq!(read.provenance, "cv");
        assert_eq!(read.fields["hwnd"], 1234);
    }
}
