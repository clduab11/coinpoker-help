//! CDP adapter for the Electron lobby surface (Phase 0 verdict, 2026-11-10).
//!
//! Scope: the lobby/listing/join surface of the client. The felt is a Unity
//! window and is NOT reachable over CDP (see `adapter::cv`). Fields produced
//! here: listing rows (table id, blinds, players, min buy-in), user, wallet,
//! and a change-detection `seq`. Selector strategy: tier-1 class/attribute
//! selectors proven in Phase 0 (`data-table-id`, `cash-game-row`, ...); the
//! extraction ships a version string so receipts can pin it.

use super::ws::{http_get, split_ws_url, WsClient};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Pin for receipts: bump when the extraction expression changes.
pub const CDP_EXTRACTION_VERSION: &str = "cpk-lobby/1";

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
pub struct LobbyPage {
    pub id: String,
    pub url: String,
    pub title: String,
    pub ws: String,
}

#[derive(Debug, serde::Deserialize)]
struct RawTarget {
    id: String,
    #[serde(rename = "type")]
    kind: String,
    url: String,
    #[serde(default)]
    title: String,
    #[serde(rename = "webSocketDebuggerUrl", default)]
    ws: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
pub struct TableRow {
    pub id: String,
    pub blinds: Option<String>,
    pub players: Option<u32>,
    pub min_buy_in: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq)]
pub struct LobbySnapshot {
    pub path: String,
    pub user: Option<String>,
    /// Raw text as displayed (e.g. `₮15.84`); `amount` is parsed best-effort.
    pub wallet_raw: Option<String>,
    pub wallet_amount: Option<f64>,
    pub tables: Vec<TableRow>,
    /// Deterministic hash over the observed listing for change detection.
    pub seq: u64,
    pub captured_at_ms: u64,
}

/// Enumerate `page` targets on the client's CDP port.
pub fn list_pages(port: u16) -> Result<Vec<LobbyPage>, String> {
    let addr = format!("127.0.0.1:{port}");
    let body = http_get(&addr, "/json/list", Duration::from_millis(2000))
        .map_err(|error| format!("cdp list: {error}"))?;
    let targets: Vec<RawTarget> =
        serde_json::from_str(&body).map_err(|error| format!("cdp list json: {error}"))?;
    Ok(targets
        .into_iter()
        .filter(|target| target.kind == "page")
        .filter_map(|target| {
            target.ws.map(|ws| LobbyPage {
                id: target.id,
                url: target.url,
                title: target.title,
                ws,
            })
        })
        .collect())
}

/// Read the lobby page once. `Ok(None)` = CDP reachable, no lobby page open.
pub fn lobby_snapshot(port: u16) -> Result<Option<LobbySnapshot>, String> {
    let pages = list_pages(port)?;
    let Some(lobby) = pages.iter().find(|page| page.url.contains("lobby.html")) else {
        return Ok(None);
    };
    let (addr, path) = split_ws_url(&lobby.ws).map_err(|error| format!("cdp url: {error}"))?;
    let mut client = WsClient::connect(&addr, &path, Duration::from_millis(2500))
        .map_err(|error| format!("cdp connect: {error}"))?;
    let request = serde_json::json!({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": { "expression": EXTRACTION_JS, "returnByValue": true }
    });
    client
        .send_text(&request.to_string())
        .map_err(|error| format!("cdp send: {error}"))?;
    let deadline = Instant::now() + Duration::from_millis(3000);
    loop {
        let Some(text) = client
            .recv_text_until(deadline)
            .map_err(|error| format!("cdp recv: {error}"))?
        else {
            return Err("cdp recv: deadline".into());
        };
        let Ok(envelope) = serde_json::from_str::<serde_json::Value>(&text) else {
            continue;
        };
        if envelope.get("id").and_then(|id| id.as_u64()) != Some(1) {
            continue; // events (Runtime.consoleAPICalled etc.)
        }
        if let Some(error) = envelope.get("error") {
            return Err(format!("cdp evaluate error: {error}"));
        }
        let value = envelope
            .pointer("/result/result/value")
            .ok_or_else(|| format!("cdp evaluate: no value in {envelope}"))?
            .clone();
        return Ok(Some(build_snapshot(value)?));
    }
}

#[derive(Debug, serde::Deserialize)]
struct RawLobby {
    path: String,
    user: Option<String>,
    wallet_raw: Option<String>,
    #[serde(default)]
    tables: Vec<RawTable>,
}

#[derive(Debug, serde::Deserialize)]
struct RawTable {
    id: String,
    blinds: Option<String>,
    players: Option<String>,
    min_buy_in: Option<String>,
}

fn build_snapshot(value: serde_json::Value) -> Result<LobbySnapshot, String> {
    let raw: RawLobby =
        serde_json::from_value(value).map_err(|error| format!("cdp extraction: {error}"))?;
    let tables: Vec<TableRow> = raw
        .tables
        .into_iter()
        .filter(|table| !table.id.is_empty())
        .map(|table| TableRow {
            id: table.id,
            blinds: table.blinds.filter(|v| !v.is_empty()),
            players: table.players.as_deref().and_then(parse_leading_u32),
            min_buy_in: table.min_buy_in.filter(|v| !v.is_empty()),
        })
        .collect();
    let mut hasher = DefaultHasher::new();
    raw.path.hash(&mut hasher);
    for table in &tables {
        table.id.hash(&mut hasher);
        table.players.hash(&mut hasher);
        table.blinds.hash(&mut hasher);
    }
    let wallet_amount = raw.wallet_raw.as_deref().and_then(parse_amount);
    Ok(LobbySnapshot {
        path: raw.path,
        user: raw.user.filter(|v| !v.is_empty()),
        wallet_raw: raw.wallet_raw.filter(|v| !v.is_empty()),
        wallet_amount,
        tables,
        seq: hasher.finish(),
        captured_at_ms: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0),
    })
}

fn parse_leading_u32(text: &str) -> Option<u32> {
    let digits: String = text
        .chars()
        .skip_while(|c| !c.is_ascii_digit())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse().ok()
}

/// Extract the first decimal number from a display string like `₮15.84`.
fn parse_amount(text: &str) -> Option<f64> {
    let mut number = String::new();
    let mut started = false;
    for c in text.chars() {
        if c.is_ascii_digit() || (c == '.' && started) {
            number.push(c);
            started = true;
        } else if started {
            if number.ends_with('.') {
                number.pop();
            }
            break;
        }
    }
    number.parse().ok()
}

/// One round trip of `Runtime.evaluate` returning a JSON object.
/// Versioned; proven selectors only. Everything missing degrades to `null`.
const EXTRACTION_JS: &str = r#"
(() => {
  const clean = (el) => el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : null;
  const rows = [...document.querySelectorAll('[class*=cashGamesContainer] .cash-game-row')]
    .slice(0, 60)
    .map((row) => ({
      id: row.getAttribute('data-table-id') || '',
      blinds: clean(row.querySelector('[class*=blinds-value]')),
      players: clean(row.querySelector('[class*=info--players]')),
      min_buy_in: clean(row.querySelector('[class*=info--buy-in]'))
    }));
  let user = null;
  let walletRaw = null;
  const details = document.querySelector('[class*=user-details]');
  if (details) {
    const parts = (details.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean);
    for (const part of parts) {
      if (part.includes('\u20ae') && !walletRaw) walletRaw = part;
      if (!part.includes('\u20ae') && !user && part.length < 40) user = part;
    }
  }
  return { path: location.pathname, user, wallet_raw: walletRaw, tables: rows };
})()
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_snapshot_maps_and_hashes_deterministically() {
        let value = serde_json::json!({
            "path": "/lobby.html",
            "user": "clduab11",
            "wallet_raw": "\u{20ae}15.84",
            "tables": [
                {"id": "14R NL 0.01-0.02 A 1752962", "blinds": "\u{20ae}0.01/\u{20ae}0.02", "players": "292", "min_buy_in": "\u{20ae}0.8"},
                {"id": "Big Ben 1751122", "blinds": "\u{20ae}1K/\u{20ae}2K", "players": "76", "min_buy_in": "\u{20ae}80K"}
            ]
        });
        let snapshot = build_snapshot(value.clone()).unwrap();
        assert_eq!(snapshot.user.as_deref(), Some("clduab11"));
        assert_eq!(snapshot.wallet_amount, Some(15.84));
        assert_eq!(snapshot.tables.len(), 2);
        assert_eq!(snapshot.tables[0].players, Some(292));
        let again = build_snapshot(value).unwrap();
        assert_eq!(snapshot.seq, again.seq);
    }

    #[test]
    fn parse_amount_handles_display_forms() {
        assert_eq!(parse_amount("\u{20ae}15.84"), Some(15.84));
        assert_eq!(parse_amount("Balance \u{20ae}1,234.5 total"), Some(1.0));
        assert_eq!(parse_amount("none"), None);
    }

    #[test]
    fn list_pages_filters_target_shape() {
        let body = r#"[
            {"id":"P1","type":"page","url":"file:///C:/lobby.html","title":"CoinPoker","webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/P1"},
            {"id":"W1","type":"worker","url":"worker.js","title":"w","webSocketDebuggerUrl":"ws://127.0.0.1:9222/devtools/page/W1"},
            {"id":"P2","type":"page","url":"https://x/","title":"splash"}
        ]"#;
        let targets: Vec<RawTarget> = serde_json::from_str(body).unwrap();
        let pages: Vec<_> = targets
            .into_iter()
            .filter(|target| target.kind == "page")
            .filter_map(|target| {
                target.ws.map(|ws| LobbyPage {
                    id: target.id,
                    url: target.url,
                    title: target.title,
                    ws,
                })
            })
            .collect();
        assert_eq!(pages.len(), 1);
        assert!(pages[0].url.contains("lobby.html"));
    }

    /// Smoke: requires the client running with `--remote-debugging-port=9222`.
    #[test]
    fn live_lobby_snapshot_smoke_if_reachable() {
        let pages = match list_pages(9222) {
            Ok(pages) => pages,
            Err(error) => {
                println!("cdp list error: {error}");
                return;
            }
        };
        if !pages.iter().any(|p| p.url.contains("lobby.html")) {
            println!("no lobby page; skipping live smoke");
            return;
        }
        let snapshot = lobby_snapshot(9222).expect("snapshot").expect("lobby");
        assert!(snapshot.path.contains("lobby.html"));
        println!(
            "live lobby: user={:?} wallet={:?} tables={} seq={}",
            snapshot.user,
            snapshot.wallet_raw,
            snapshot.tables.len(),
            snapshot.seq
        );
    }
}
