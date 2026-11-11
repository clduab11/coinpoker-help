# OPERATIONS — autonomous runs on Chris's workstation

Contract for any agent session that drives this machine. Read before touching the
client. The machine is shared: Chris works on it while agents run.

## Lanes (how much you interfere)

| Lane | Actions | Interference | Announce? |
|---|---|---|---|
| QUIET | file edits, `cargo`, tests, HTTP GETs (`/json/list`, `/json/version`), CDP `Runtime.evaluate` reads | none (no input, no window changes) | no |
| INPUT | `SendInput` clicks/moves (cursor jumps), `PostMessage`, table-window restore/move | cursor + focus | **YES, before** |
| CLIENT | launching/closing CoinPoker, opening/leaving tables | his desktop, session state | **YES, before** |

Rules:

1. Before an INPUT or CLIENT phase: one line — what you'll click/launch, expected
   seconds, and "taking input now". When done: "machine free".
2. Keep INPUT bursts short and grouped; never leave the cursor parked on his screen
   mid-flow if avoidable (it is fine parked).
3. Never touch non-CoinPoker applications. Prefer `PostMessage` where it works, but
   on this client **PostMessage is not consumed by Unity** — SendInput is the only
   working rung. Two extra rules learned live (2026-11-10): (a) the client
   **re-cloaks table windows when unfocused** — before an input burst run
   `ShowWindow(SW_HIDE)` then `SW_SHOW` to clear the cloak, or the click lands on
   the desktop; (b) a first click only activates the window — verify foreground
   (or click twice) before treating an action as delivered. Kill/restart the client
   by **path filter** (`... | Where-Object { $_.Path -like "C:\Program Files\CoinPoker\*" }`)
   so the same-named run binary is never killed by accident.
4. The CoinPoker client stays RUNNING with `--remote-debugging-port=9222`
   (CDP needs it). Close/relaunch only when asked or when a recipe says so.
5. A first client launch after an update relaunches WITHOUT the flag — always
   (re)launch explicitly with the flag.
6. Chris can pause you by saying so in chat; commands are atomic (worst case one
   cargo/click burst finishes, ≤ ~60 s — say so if a batch is longer).

## Relaunch recipe (one line for Chris if needed)

```
Start-Process "C:\Program Files\CoinPoker\CoinPoker.exe" -ArgumentList "--remote-debugging-port=9222"
```
Success check (agent): `Invoke-RestMethod http://127.0.0.1:9222/json/version` shows
`CoinPoker/2.2.0`. If a stale instance runs without the flag: stop `CoinPoker`
processes first (they are single-instance; a second launch without stopping exits
silently).

## Current known state (2026-11-10, evening)

- Client running, debug port up (CDP verified live: lobby read returns user/wallet).
- Two table windows open (`CoinPoker Game` Unity processes, 800×613): one cash table
  where **the hero seat auto-acts (~15 s clock)** — small play balance drift is normal
  (₮15.84 → ₮15.78 observed); one practice table in observer mode.
- Windows sit at (2480, 209) on DISPLAY1; window class `UnityWndClass`; capture via
  WGC/PrintWindow (PrintWindow renders when backgrounded, blacks out when
  foregrounded — use WGC or on-screen copy then).
- Chris may close tables/client anytime; the CDP poller is fail-quiet
  (`cdp-status` record with `unavailable`).

## Receipts

Phase 0 receipts: `.local/phase0-cdp/20261110T1845Z/` (verdict, target digests,
probe/click/key scripts, screenshots). Do not edit them; add new stamp dirs.
