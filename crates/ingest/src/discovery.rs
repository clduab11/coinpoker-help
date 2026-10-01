//! Platform-neutral window selection and an optional, caller-driven capture lifecycle.
//!
//! No application identity or title is assumed. Call [`CaptureManager::refresh`]
//! periodically (for example, once per second), and again after capture errors.
//! Discovery alone never proves that pixels contain a playable poker table.

use serde::{Deserialize, Serialize};

pub use crate::capture::WindowInfo;
use crate::capture::{CaptureError, CaptureSource, Frame};

/// A window handle is only meaningful together with its owning executable/process.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TableIdentity {
    pub exe_name: String,
    pub process_id: u32,
    #[serde(with = "hwnd_serde")]
    pub hwnd: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApplicationInfo {
    pub exe_name: String,
    pub process_id: u32,
}

/// Applications are independent of windows: an app can be running with no table.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DiscoverySnapshot {
    pub applications: Vec<ApplicationInfo>,
    pub windows: Vec<WindowInfo>,
}

/// All selectors must come from explicit calibration, not guessed client metadata.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DiscoveryConfig {
    /// Exact executable basename, compared using Windows case-insensitive rules.
    pub exe_name: Option<String>,
    /// Optional exact PID restriction.
    pub process_id: Option<u32>,
    /// Pin one window within the matching application. If it disappears, wait.
    pub window_hwnd: Option<usize>,
    /// Calibrated, case-sensitive substring that ranks table windows above unknowns.
    pub table_title: Option<String>,
    /// Calibrated lobby substring. Vetoes table classification, even on a title overlap.
    pub lobby_title: Option<String>,
}

impl DiscoveryConfig {
    pub fn has_identity(&self) -> bool {
        nonempty(self.exe_name.as_deref()).is_some()
    }

    fn matches_application(&self, exe_name: &str, process_id: u32) -> bool {
        self.exe_name.as_deref().is_some_and(|expected| {
            !expected.trim().is_empty() && expected.eq_ignore_ascii_case(exe_name)
        }) && self.process_id.is_none_or(|pid| pid == process_id)
    }

    pub(crate) fn matches_window(&self, window: &WindowInfo) -> bool {
        self.matches_application(&window.exe_name, window.process_id)
            && self.window_hwnd.is_none_or(|hwnd| hwnd == window.hwnd)
    }
}

/// Stable external encoding for pointer-width HWND values. Never round-trip
/// through a JSON number, which loses precision in JavaScript consumers.
pub mod hwnd_serde {
    use serde::{de::Error, Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(hwnd: &usize, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&format!("0x{hwnd:x}"))
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<usize, D::Error> {
        let value = String::deserialize(deserializer)?;
        let digits = value
            .strip_prefix("0x")
            .ok_or_else(|| D::Error::custom("HWND must be a 0x-prefixed hex string"))?;
        if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(D::Error::custom("HWND must be a 0x-prefixed hex string"));
        }
        usize::from_str_radix(digits, 16)
            .map_err(|_| D::Error::custom("HWND exceeds pointer width"))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiscoveryState {
    ConfigurationRequired,
    WaitingForCoinPoker,
    WaitingForTable,
    LobbyDetected,
    CandidateTable,
    CapturingTable,
    AmbiguousMultipleTables,
    PermissionRequired,
    Recovering,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Selection {
    pub state: DiscoveryState,
    pub window: Option<WindowInfo>,
    pub reason: &'static str,
}

fn nonempty(value: Option<&str>) -> Option<&str> {
    value.filter(|value| !value.trim().is_empty())
}

fn contains(value: Option<&str>, selector: Option<&str>) -> bool {
    nonempty(selector).is_some_and(|needle| value.is_some_and(|value| value.contains(needle)))
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum WindowKind {
    Lobby,
    Unknown,
    Table,
}

fn window_kind(window: &WindowInfo, config: &DiscoveryConfig) -> WindowKind {
    if contains(window.title.as_deref(), config.lobby_title.as_deref()) {
        WindowKind::Lobby
    } else if contains(window.title.as_deref(), config.table_title.as_deref()) {
        WindowKind::Table
    } else {
        WindowKind::Unknown
    }
}

/// Select without IO or dependence on enumeration order.
///
/// An explicit HWND is a hard pin, not permission to switch windows if it vanishes.
/// Otherwise a calibrated table title outranks unknown windows, which outrank
/// lobbies. Ties never select an arbitrary window. A single lobby may be observed,
/// but is never a table. Both title matches and unknowns are `CandidateTable` here;
/// `CapturingTable` is a lifecycle state, not evidence supplied by discovery.
pub fn select_window(snapshot: &DiscoverySnapshot, config: &DiscoveryConfig) -> Selection {
    let result = |state, window, reason| Selection {
        state,
        window,
        reason,
    };
    if !config.has_identity() {
        return result(
            DiscoveryState::ConfigurationRequired,
            None,
            "configure an exact executable name",
        );
    }

    let application_found = snapshot
        .applications
        .iter()
        .any(|app| config.matches_application(&app.exe_name, app.process_id))
        || snapshot
            .windows
            .iter()
            .any(|window| config.matches_application(&window.exe_name, window.process_id));
    if !application_found {
        return result(
            DiscoveryState::WaitingForCoinPoker,
            None,
            "configured executable/process is not present",
        );
    }

    let candidates: Vec<_> = snapshot
        .windows
        .iter()
        .filter(|window| {
            config.matches_window(window)
                && window.on_screen
                && window.width > 0
                && window.height > 0
        })
        .map(|window| (window_kind(window, config), window))
        .collect();
    let Some(best_kind) = candidates.iter().map(|(kind, _)| *kind).max() else {
        return result(
            DiscoveryState::WaitingForTable,
            None,
            "application is present but no eligible on-screen window matches",
        );
    };
    let mut best = candidates.iter().filter(|(kind, _)| *kind == best_kind);
    let window = best.next().expect("best kind comes from a candidate").1;
    if best.next().is_some() {
        return if best_kind == WindowKind::Lobby {
            result(
                DiscoveryState::LobbyDetected,
                None,
                "only lobby windows are present; no arbitrary observation window selected",
            )
        } else {
            result(
                DiscoveryState::AmbiguousMultipleTables,
                None,
                "multiple equally valid windows; calibrate an HWND or narrower table title",
            )
        };
    }

    let (state, reason) = match best_kind {
        WindowKind::Lobby => (
            DiscoveryState::LobbyDetected,
            "calibrated lobby title; observation only",
        ),
        WindowKind::Unknown => (
            DiscoveryState::CandidateTable,
            "unclassified application window; table classification required",
        ),
        WindowKind::Table => (
            DiscoveryState::CandidateTable,
            "calibrated table-title match; awaiting capture",
        ),
    };
    result(state, Some(window.clone()), reason)
}

/// Optional mockable lifecycle; scheduling and pixel classification belong to the caller.
///
/// Each refresh reselects from fresh metadata and reconstructs the backend filter,
/// even for the same identity (window size/display scale may have changed). Errors,
/// disappearance, and ambiguity discard the previous capture source immediately.
/// Unknown windows and lobbies can be captured for classification/observation, but
/// only a calibrated, non-lobby table title advances this manager to `CapturingTable`.
pub struct CaptureManager<S: CaptureSource> {
    source: S,
    config: DiscoveryConfig,
    selection: Selection,
}

impl<S: CaptureSource> CaptureManager<S> {
    pub fn new(source: S, config: DiscoveryConfig) -> Self {
        let selection = select_window(&DiscoverySnapshot::default(), &config);
        Self {
            source,
            config,
            selection,
        }
    }

    pub fn selection(&self) -> &Selection {
        &self.selection
    }

    pub fn refresh(&mut self) -> Result<Selection, CaptureError> {
        let snapshot = if self.config.has_identity() {
            match self.source.discover() {
                Ok(snapshot) => snapshot,
                Err(error) => {
                    self.failed(&error);
                    return Err(error);
                }
            }
        } else {
            DiscoverySnapshot::default()
        };
        let mut next = select_window(&snapshot, &self.config);
        self.source.reset();
        if let Some(window) = &next.window {
            if let Err(error) = self.source.select(window) {
                self.failed(&error);
                return Err(error);
            }
            if self.selection.state == DiscoveryState::CapturingTable
                && self.selection.window.as_ref() == Some(window)
                && window_kind(window, &self.config) == WindowKind::Table
            {
                next.state = DiscoveryState::CapturingTable;
                next.reason = "capturing calibrated table window";
            }
        }
        self.selection = next;
        Ok(self.selection.clone())
    }

    pub fn capture(&mut self) -> Result<Frame, CaptureError> {
        let window = self
            .selection
            .window
            .as_ref()
            .ok_or(CaptureError::NoWindowSelected)?;
        match self.source.capture() {
            Ok(frame) => {
                if window_kind(window, &self.config) == WindowKind::Table {
                    self.selection.state = DiscoveryState::CapturingTable;
                    self.selection.reason = "capturing calibrated table window";
                }
                Ok(frame)
            }
            Err(error) => {
                self.failed(&error);
                Err(error)
            }
        }
    }

    fn failed(&mut self, error: &CaptureError) {
        self.source.reset();
        let (state, reason) = match error {
            CaptureError::PermissionDenied => (
                DiscoveryState::PermissionRequired,
                "allow Windows Graphics Capture and retry discovery",
            ),
            CaptureError::ConfigurationRequired => (
                DiscoveryState::ConfigurationRequired,
                "configure the application identity before capture",
            ),
            _ => (
                DiscoveryState::Recovering,
                "capture source invalidated; retry discovery before capture",
            ),
        };
        self.selection = Selection {
            state,
            window: None,
            reason,
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashSet, VecDeque};

    fn app() -> ApplicationInfo {
        ApplicationInfo {
            exe_name: "test.example.client".into(),
            process_id: 10,
        }
    }

    fn window(id: usize, title: Option<&str>) -> WindowInfo {
        WindowInfo {
            hwnd: id,
            process_id: app().process_id,
            exe_name: app().exe_name,
            title: title.map(str::to_owned),
            on_screen: true,
            width: 900,
            height: 600,
        }
    }

    fn config() -> DiscoveryConfig {
        DiscoveryConfig {
            exe_name: Some(app().exe_name),
            table_title: Some("Test Table".into()),
            lobby_title: Some("Test Lobby".into()),
            ..DiscoveryConfig::default()
        }
    }

    fn snapshot(windows: Vec<WindowInfo>) -> DiscoverySnapshot {
        DiscoverySnapshot {
            applications: vec![app()],
            windows,
        }
    }

    #[test]
    fn default_and_title_or_pid_only_configs_require_identity() {
        for cfg in [
            DiscoveryConfig::default(),
            DiscoveryConfig {
                table_title: Some("Test Table".into()),
                ..DiscoveryConfig::default()
            },
            DiscoveryConfig {
                process_id: Some(10),
                window_hwnd: Some(1),
                ..DiscoveryConfig::default()
            },
            DiscoveryConfig {
                exe_name: Some(String::new()),
                ..DiscoveryConfig::default()
            },
        ] {
            assert_eq!(
                select_window(&snapshot(vec![window(1, Some("Test Table"))]), &cfg).state,
                DiscoveryState::ConfigurationRequired
            );
        }
    }

    #[test]
    fn executable_basename_and_pid_are_exact() {
        let target = window(1, Some("Test Table"));
        for exe in [
            "test.example",
            "test.example.client.extra",
            " test.example.client",
        ] {
            let cfg = DiscoveryConfig {
                exe_name: Some(exe.into()),
                ..config()
            };
            assert_eq!(
                select_window(&snapshot(vec![target.clone()]), &cfg).state,
                DiscoveryState::WaitingForCoinPoker
            );
        }
        let mut cfg = config();
        cfg.process_id = Some(11);
        assert_eq!(
            select_window(&snapshot(vec![target.clone()]), &cfg).state,
            DiscoveryState::WaitingForCoinPoker
        );
        cfg.process_id = Some(10);
        assert_eq!(
            select_window(&snapshot(vec![target.clone()]), &cfg).state,
            DiscoveryState::CandidateTable
        );
        cfg.exe_name = Some("TEST.EXAMPLE.CLIENT".into());
        assert_eq!(
            select_window(&snapshot(vec![target]), &cfg).state,
            DiscoveryState::CandidateTable
        );
    }

    #[test]
    fn application_without_windows_is_distinct_from_absent_application() {
        assert_eq!(
            select_window(&DiscoverySnapshot::default(), &config()).state,
            DiscoveryState::WaitingForCoinPoker
        );
        assert_eq!(
            select_window(&snapshot(vec![]), &config()).state,
            DiscoveryState::WaitingForTable
        );
        let snap = DiscoverySnapshot {
            applications: vec![],
            windows: vec![window(1, None)],
        };
        assert_eq!(
            select_window(&snap, &config()).state,
            DiscoveryState::CandidateTable
        );
    }

    #[test]
    fn offscreen_and_zero_sized_windows_are_not_observation_candidates() {
        let mut windows = vec![window(1, None), window(2, None), window(3, None)];
        windows[0].on_screen = false;
        windows[1].width = 0;
        windows[2].height = 0;
        let result = select_window(&snapshot(windows), &config());
        assert_eq!(result.state, DiscoveryState::WaitingForTable);
        assert!(result.window.is_none());
    }

    #[test]
    fn calibrated_table_outranks_unknowns_and_lobbies_in_any_order() {
        let table = window(3, Some("Test Table 42"));
        let mut windows = vec![
            window(1, Some("Test Lobby")),
            window(2, None),
            table.clone(),
        ];
        for _ in 0..windows.len() {
            let selected = select_window(&snapshot(windows.clone()), &config());
            assert_eq!(selected.state, DiscoveryState::CandidateTable);
            assert_eq!(selected.window, Some(table.clone()));
            windows.rotate_left(1);
        }
    }

    #[test]
    fn unknown_window_is_not_proven_table_and_outranks_lobby() {
        let result = select_window(
            &snapshot(vec![window(1, Some("Test Lobby")), window(2, None)]),
            &config(),
        );
        assert_eq!(result.state, DiscoveryState::CandidateTable);
        assert_eq!(result.window, Some(window(2, None)));
        assert!(result.reason.contains("classification required"));
    }

    #[test]
    fn lobby_veto_wins_over_overlapping_table_title() {
        let lobby = window(1, Some("Test Lobby - Test Table preview"));
        let result = select_window(&snapshot(vec![lobby.clone()]), &config());
        assert_eq!(result.state, DiscoveryState::LobbyDetected);
        assert_eq!(result.window, Some(lobby));
    }

    #[test]
    fn equally_ranked_tables_or_unknowns_are_ambiguous() {
        for titles in [
            [None, Some("Uncalibrated")],
            [Some("Test Table 1"), Some("Test Table 2")],
        ] {
            let result = select_window(
                &snapshot(vec![window(1, titles[0]), window(2, titles[1])]),
                &config(),
            );
            assert_eq!(result.state, DiscoveryState::AmbiguousMultipleTables);
            assert!(result.window.is_none());
        }
        let result = select_window(
            &snapshot(vec![
                window(1, Some("Test Lobby 1")),
                window(2, Some("Test Lobby 2")),
            ]),
            &config(),
        );
        assert_eq!(result.state, DiscoveryState::LobbyDetected);
        assert!(result.window.is_none());
    }

    #[test]
    fn explicit_id_resolves_ambiguity_without_bypassing_identity_or_lobby() {
        let mut cfg = DiscoveryConfig {
            window_hwnd: Some(2),
            ..config()
        };
        let snap = snapshot(vec![window(1, Some("Test Table")), window(2, None)]);
        assert_eq!(select_window(&snap, &cfg).window, Some(window(2, None)));
        cfg.window_hwnd = Some(99);
        assert_eq!(
            select_window(&snap, &cfg).state,
            DiscoveryState::WaitingForTable
        );
        cfg.window_hwnd = Some(2);
        let mut other = window(2, Some("Test Table"));
        other.exe_name = "test.example.other".into();
        assert_eq!(
            select_window(&snapshot(vec![other]), &cfg).state,
            DiscoveryState::WaitingForTable
        );
        assert_eq!(
            select_window(&snapshot(vec![window(2, Some("Test Lobby"))]), &cfg).state,
            DiscoveryState::LobbyDetected
        );
    }

    #[test]
    fn empty_titles_never_match_everything_and_titles_cannot_supply_identity() {
        let cfg = DiscoveryConfig {
            table_title: Some(String::new()),
            lobby_title: Some("  ".into()),
            ..config()
        };
        let result = select_window(&snapshot(vec![window(1, Some("anything"))]), &cfg);
        assert_eq!(result.state, DiscoveryState::CandidateTable);
        assert!(result.reason.contains("classification required"));
        let mut other = window(1, Some("Test Table"));
        other.exe_name = "test.example.other".into();
        assert!(select_window(&snapshot(vec![other]), &config())
            .window
            .is_none());
    }

    #[test]
    fn identity_tracks_executable_pid_and_hwnd_but_not_title() {
        let original = window(1, Some("Test Table"));
        let mut changed = original.clone();
        changed.title = None;
        assert_eq!(original.identity(), changed.identity());
        let mut identities = HashSet::from([original.identity()]);
        changed.process_id += 1;
        identities.insert(changed.identity());
        changed = original.clone();
        changed.exe_name.push_str(".other");
        identities.insert(changed.identity());
        changed = original.clone();
        changed.hwnd += 1;
        identities.insert(changed.identity());
        assert_eq!(identities.len(), 4);
        let encoded = serde_json::to_string(&original.identity()).unwrap();
        assert_eq!(
            serde_json::from_str::<TableIdentity>(&encoded).unwrap(),
            original.identity()
        );
        assert!(encoded.contains("\"hwnd\":\"0x1\""));
        assert!(serde_json::from_str::<TableIdentity>(
            r#"{"exe_name":"TestClient.exe","process_id":1,"hwnd":1}"#
        )
        .is_err());
    }

    #[derive(Default)]
    struct MockSource {
        snapshots: VecDeque<Result<DiscoverySnapshot, CaptureError>>,
        selected: Option<TableIdentity>,
        filters: Vec<TableIdentity>,
        resets: usize,
        selection_error: Option<CaptureError>,
        capture_error: Option<CaptureError>,
    }

    impl CaptureSource for MockSource {
        fn discover(&mut self) -> Result<DiscoverySnapshot, CaptureError> {
            self.snapshots.pop_front().expect("scripted discovery")
        }
        fn select(&mut self, window: &WindowInfo) -> Result<(), CaptureError> {
            if let Some(error) = self.selection_error.take() {
                return Err(error);
            }
            self.selected = Some(window.identity());
            self.filters.push(window.identity());
            Ok(())
        }
        fn capture(&mut self) -> Result<Frame, CaptureError> {
            if let Some(error) = self.capture_error.take() {
                return Err(error);
            }
            self.selected
                .as_ref()
                .ok_or(CaptureError::NoWindowSelected)?;
            Ok(Frame::new(1, 1, vec![0; 4]).unwrap())
        }
        fn reset(&mut self) {
            self.selected = None;
            self.resets += 1;
        }
    }

    fn manager(snapshots: Vec<DiscoverySnapshot>) -> CaptureManager<MockSource> {
        CaptureManager::new(
            MockSource {
                snapshots: snapshots.into_iter().map(Ok).collect(),
                ..MockSource::default()
            },
            config(),
        )
    }

    #[test]
    fn lifecycle_appearance_disappearance_and_restart_reconstruct_filters() {
        let first = window(1, Some("Test Table"));
        let mut restarted = first.clone();
        restarted.process_id += 1;
        let mut lifecycle = manager(vec![
            DiscoverySnapshot::default(),
            snapshot(vec![]),
            snapshot(vec![first.clone()]),
            snapshot(vec![]),
            snapshot(vec![restarted.clone()]),
        ]);
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::WaitingForCoinPoker
        );
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::WaitingForTable
        );
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::CandidateTable
        );
        lifecycle.capture().unwrap();
        assert_eq!(lifecycle.selection().state, DiscoveryState::CapturingTable);
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::WaitingForTable
        );
        assert!(lifecycle.source.selected.is_none());
        assert_eq!(lifecycle.capture(), Err(CaptureError::NoWindowSelected));
        lifecycle.refresh().unwrap();
        assert_eq!(
            lifecycle.source.filters,
            vec![first.identity(), restarted.identity()]
        );
    }

    #[test]
    fn every_refresh_rebuilds_filter_including_resize_and_same_identity() {
        let first = window(1, Some("Test Table"));
        let mut resized = first.clone();
        resized.width += 100;
        let mut lifecycle = manager(vec![
            snapshot(vec![first.clone()]),
            snapshot(vec![resized.clone()]),
            snapshot(vec![resized]),
        ]);
        for _ in 0..3 {
            lifecycle.refresh().unwrap();
        }
        assert_eq!(lifecycle.source.filters, vec![first.identity(); 3]);
    }

    #[test]
    fn ambiguity_invalidates_previously_selected_filter() {
        let mut lifecycle = manager(vec![
            snapshot(vec![window(1, None)]),
            snapshot(vec![window(1, None), window(2, None)]),
        ]);
        lifecycle.refresh().unwrap();
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::AmbiguousMultipleTables
        );
        assert!(lifecycle.source.selected.is_none());
        assert_eq!(lifecycle.capture(), Err(CaptureError::NoWindowSelected));
    }

    #[test]
    fn observation_capture_does_not_promote_unknown_or_lobby_to_table() {
        for (title, state) in [
            (None, DiscoveryState::CandidateTable),
            (Some("Test Lobby"), DiscoveryState::LobbyDetected),
        ] {
            let mut lifecycle = manager(vec![snapshot(vec![window(1, title)])]);
            lifecycle.refresh().unwrap();
            lifecycle.capture().unwrap();
            assert_eq!(lifecycle.selection().state, state);
        }
    }

    #[test]
    fn permission_and_stale_errors_clear_selection_then_allow_recovery() {
        let target = window(1, Some("Test Table"));
        let mut lifecycle = manager(vec![snapshot(vec![target.clone()]); 4]);
        lifecycle.refresh().unwrap();
        lifecycle.source.capture_error = Some(CaptureError::StaleWindow { hwnd: 1 });
        assert_eq!(
            lifecycle.capture(),
            Err(CaptureError::StaleWindow { hwnd: 1 })
        );
        assert_eq!(lifecycle.selection().state, DiscoveryState::Recovering);
        assert!(lifecycle.source.selected.is_none());
        lifecycle.source.selection_error = Some(CaptureError::PermissionDenied);
        assert_eq!(lifecycle.refresh(), Err(CaptureError::PermissionDenied));
        assert_eq!(
            lifecycle.selection().state,
            DiscoveryState::PermissionRequired
        );
        assert!(lifecycle.selection().window.is_none());
        lifecycle.refresh().unwrap();
        lifecycle.capture().unwrap();
        assert_eq!(lifecycle.selection().state, DiscoveryState::CapturingTable);
        lifecycle
            .source
            .snapshots
            .push_front(Err(CaptureError::PermissionDenied));
        assert_eq!(lifecycle.refresh(), Err(CaptureError::PermissionDenied));
        assert!(lifecycle.source.selected.is_none());
        lifecycle.refresh().unwrap();
        assert_eq!(lifecycle.source.selected, Some(target.identity()));
    }

    #[test]
    fn configuration_required_does_not_query_platform_or_capture() {
        let mut lifecycle = CaptureManager::new(MockSource::default(), DiscoveryConfig::default());
        assert_eq!(
            lifecycle.refresh().unwrap().state,
            DiscoveryState::ConfigurationRequired
        );
        assert_eq!(lifecycle.capture(), Err(CaptureError::NoWindowSelected));
    }
}
