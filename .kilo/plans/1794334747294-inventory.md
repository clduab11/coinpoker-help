# INVENTORY — measured from the working tree

Measured 2026-11-10 against the checkout in this repository. Method: file-by-file line
counts (`rg -c "^"`), direct source reads with `file:line` anchors, `rg` call-graph
searches, and `git log -S/-G` archaeology. Nothing here is estimated; where a number
comes from a doc receipt it says so.

**Checkout under measurement**

| Item | Value |
|---|---|
| Branch | `checkpoint/seated-read-mechanism-2-20261002` |
| HEAD | `e630163` (2026-10-27) |
| Worktree | dirty: 13 modified tracked files + 2 untracked plan files (list below) |
| Rust toolchain | 1.95.0 (`rust-toolchain.toml`) |
| Platform | Windows-only live capture; no macOS path remains (see §8) |

Modified in worktree (in-flight work, not committed): `HANDOFF.md`, `README.md`,
`bin/manual_inference.rs`, `bin/manual_inference_tests.rs`, `crates/ingest/src/laya.rs`,
`crates/ingest/src/laya/client.rs`, `docs/LAYA_VISION_PHASE_A.md`,
`docs/SEATED_DIAGNOSTIC.md`, `scripts/laya-server.py`, `scripts/laya_attach.py`,
`scripts/laya_server_validation.py`, `scripts/tests/test_laya_attach.py`,
`scripts/tests/test_laya_server.py`. The laya diffs are a new `ReadoutAll` batched pass
(p0+pot+6 stacks); unrelated to this refactor but present.

**Important:** the brief's "verified repo facts" describe an earlier state of this
repository. The names `run_live_loop`, `zone_detector`, `ConsensusTracker`, `SCStream`,
`MLX`, `.env.example` and `completions_url` do not exist anywhere in this checkout.
§4 maps every claimed fact to its measured status with evidence, and names the
successor symbol in this tree where one exists.

---

## 1. Workspace map and LOC (measured)

Workspace members (`Cargo.toml:8-15`): `crates/ingest`, `crates/core-engine`,
`crates/ghost-layer`, `crates/opponent-model`, `crates/ui`, `bin`. Six members.

### 1.1 Crate totals (lines of Rust)

| Crate | src lines | test lines | note |
|---|---:|---:|---|
| `crates/ingest` | 19,366 | 5,032 (`tests/`) | perception, capture, runtime, Laya client |
| `crates/core-engine` | 2,460 | 0 | pure math kernel |
| `crates/ghost-layer` | 678 | 0 | temporal + sizing mimicry |
| `crates/opponent-model` | 4,742 | 0 | observer ledger + partial tracking |
| `crates/ui` | 385 | 0 | egui panel (unwired) + headless JSON |
| `bin` | 3,870 | 5,295 | live/CLI/harness binaries |
| **Total** | **31,501** | **10,327** | **41,828 lines of Rust** |

### 1.2 Per file (test modules inside files counted; `tests/` dirs listed separately)

`crates/ingest/src`: `windows.rs` 2,029 · `laya.rs` 1,751 · `runtime.rs` 1,719 ·
`client.rs` (laya/) 1,604 · `recorder.rs` 1,590 · `screen.rs` 1,233 · `partial.rs` 1,188 ·
`assembly.rs` (laya/) 1,177 · `change_detect.rs` 914 · `discovery.rs` 842 · `parser.rs` 795 ·
`experimental.rs` (laya/) 779 · `laya/partial.rs` 736 · `scene.rs` (laya/) 590 · `capture.rs` 539 ·
`state_machine.rs` 527 · `vlm.rs` 349 · `questions.rs` (laya/) 281 · `geometry.rs` (laya/) 245 ·
`wager.rs` (laya/) 239 · `prompt.rs` 210 · `lib.rs` 29.
`crates/ingest/tests`: `live_runtime.rs` 2,422 · `seat_scene.rs` 1,093 · `partial_observation.rs` 1,056 ·
`saved_capture_schedule.rs` 461. Assets: `question-set.json` 4,409 lines, `regions.json` 36.

`crates/core-engine/src`: `ranges.rs` 736 · `equity.rs` 577 · `table_rules.rs` 424 ·
`decision.rs` 401 · `outs.rs` 163 · `pot_odds.rs` 138 · `lib.rs` 21.

`crates/ghost-layer/src`: `betting_entropy.rs` 263 · `temporal.rs` 246 · `profile.rs` 156 · `lib.rs` 13.

`crates/opponent-model/src`: `observer.rs` 2,085 · `observing.rs` 1,519 · `betting.rs` 416 ·
`position.rs` 268 · `features.rs` 183 · `classifier.rs` 146 · `exploit.rs` 106 · `lib.rs` 19.

`crates/ui/src`: `widgets.rs` 164 · `headless.rs` 122 · `app.rs` 83 · `lib.rs` 16.

`bin`: `main.rs` 409 · `live.rs` 973 · `config.rs` 698 · `evaluation.rs` 367 · `manual_capture.rs` 511 ·
`manual_inference.rs` 912; test files: `manual_inference_tests.rs` 2,689 · `live_tests.rs` 1,486 ·
`manual_capture_tests.rs` 524 · `tests/cli.rs` 437 · `tests/pipeline_smoke.rs` 159.

### 1.3 Outside Rust (context, not a crate)

`scripts/` is a second product: ~19,290 lines non-test + ~19,666 lines test
(`dashboard/app.js` 2,972 · `laya_dashboard.py` 2,613 · `measure_observer.py` 2,314 ·
`laya_visual.py` 1,706 · `laya-server.py` 1,344 · `laya_capture.py` 1,132, plus tests).
`docs/` is 8 files (largest: `EVENTS_V2.md` 727 lines / 50 KB, `LAYA_VISION_PHASE_A.md`
773 / 51 KB, `SEATED_DIAGNOSTIC.md` 620 / 41 KB). The Python/JS perimeter is as large
as the entire Rust workspace — size the refactor's blast radius accordingly.

---

## 2. The live path (exact, with anchors)

`coinpoker` (no mode flag) → `main.rs` `run()` → `Mode::Capture` → `live::run`
(`bin/live.rs:784`). Loop at `bin/live.rs:835-901`:

1. `runtime.tick(&clock)` (`crates/ingest/src/runtime.rs:541`) — discovery refresh,
   capture via `RecordingCapturer` over `PlatformCapture` (= `windows::WindowsCapturer`),
   `tracker.observe(&frame)` (`change_detect.rs::FrameTracker`) plus per-field trackers
   (`runtime.rs:744-760`), submit only a stable frame to the single worker slot.
2. Worker (`ThreadWorker`, `bin/live.rs:817-819`) runs `analyze_laya_frame`
   (`live.rs:70`) → `LayaBackend::analyze_observation_with_deadline` (`laya.rs:115`) →
   region passes p0/p2/p3/p5 (+opt-in wager/scene) → `assemble_partial`
   (`laya/partial.rs:257`).
3. `finish_laya_analysis` (`live.rs:82`) → `finish_analysis` (`live.rs:131`) →
   `parse_screen_output` (`screen.rs`) → deadline check → `Pipeline::decide`
   (`bin/main.rs:115`).
4. `gate.observe` (`screen.rs:301`): requires two identical `ScreenObservation`s
   (`screen.rs:382`), calls `validate_transition` (`screen.rs:374`, body in
   `state_machine.rs`) and requires `MetadataEvidence::TableTitle` (`screen.rs:357-359`).
5. Accepted state → `LiveEvent::Observation`/`Recommendation` (`runtime.rs:1231-1243`) →
   `event_record` (`live.rs:238`) → `leased_record` (`live.rs:191`, lease =
   `min(max_frame_age_ms, decision_budget_ms) - age`) → `emit_with_history` → stdout
   JSON-lines (`live.rs:28`); observer ledger emitted as bounded `history` records
   (`live.rs:656`).

**Nothing executes an action.** No input API exists: no `SendInput`, `PostMessage`,
or `dispatchMouseEvent` anywhere in Rust. `windows.rs` captures only. Adviser-only.

Budget constants: `PUBLICATION_RESERVE_MS`, `CAPTURE_HEALTH_INTERVAL_MS`
(`runtime.rs`); defaults `poll_ms 100`, `retry_ms 2000`, `force_refresh_ms 5000`,
`max_frame_age_ms 8000`, `decision_budget_ms 5000` (`runtime.rs:65-70`, bounds
`runtime.rs:80-85`).

---

## 3. Modules with no caller on the live path (call-graph evidence)

| Module / symbol | Callers found by `rg` | Status |
|---|---|---|
| `ghost_layer::temporal` (`TemporalSampler`, `DecisionComplexity`) | none outside its own tests | **no caller at all** — complete, property-tested, unwired |
| `ghost_layer::profile` (`GhostProfile`, `ProfileSampler`) | none | no caller at all |
| `core_engine::outs` | none | not reached |
| `core_engine::ranges` | `table_rules.rs:44` only | not reached from bin |
| `core_engine::table_rules` | nothing in Rust; only `question-set.json` prose names it | not reached |
| `opponent_model::classifier::Classifier` | `bin/tests/pipeline_smoke.rs:12,81` only | **not wired**; `main.rs:30` imports only the `Archetype` enum, hardcoded `Unknown` (`main.rs:118`) |
| `opponent_model::features` (`StatsAccumulator`) | `classifier.rs` only | transitively unwired |
| `ui::app` (+ `desktop` feature) | nothing; `--ui` returns `Err` (`config.rs:118`, `main.rs:11`) | dead mode |
| `ingest::prompt::build_analysis_prompt` | `live.rs:65` (inside `#[cfg(test)]`), `evaluation.rs:219` | inert on the shipped Laya path |
| `state_machine::StateMachine`, `TableEvent` | `bin/main.rs:341` (stdin path only) | off the capture path; `validate_transition` *is* on it (`screen.rs:374`) |
| `change_detect::ChangeDetector` | internal to `FrameTracker` + tests | indirect only |
| `laya::wager`, `laya::scene` | opt-in via `.local` registries (`live.rs:806-815`) | live only when configured |
| `laya::experimental` | diagnostics projection | opt-in |

Wired and live (do not delete): `betting_entropy` (`main.rs:193`), `exploit`
(`main.rs:119` — but see §7.1), `observer` + `observing` (`live.rs:21-22`, via
`AdmittedHistory`), `equity`/`decision`/`pot_odds` (`main.rs`), `recorder`,
`discovery`, `runtime`, `screen`, `parser`, `partial`, `vlm` (types + `VlmBackend`
seam implemented by `LayaBackend`, `laya.rs:658`), all of `laya/*`, all of `windows.rs`.

---

## 4. The brief's facts vs. the measured tree

| # | Claim in the brief | Measured status | Evidence |
|---|---|---|---|
| 1 | `bin/main.rs::run_live_loop` is the live path with stages capture → detect → VLM → freshness → parse → gate → consensus → state_machine → decide → sink | **Holds with different names/locations.** Loop = `live.rs:835-901`; `run_live_loop` does not exist at HEAD (it lived on the `origin/main` history line, added `e700df7`, 2026-09-20). Stage mapping: detect ≈ `FrameTracker.observe`; freshness ≈ `observation_is_current` (`runtime.rs:114`) + epoch/lease checks; gate ≈ pass floors (`laya/partial.rs:174-189`) + `TableGate`; consensus ≈ the two-identical-observation rule (`screen.rs:382`); state_machine ≈ `validate_transition`; sink ≈ stdout JSONL. "Nothing executes an action" holds | §2 |
| 2 | `capture.rs` keeps `CaptureConfig`/`Frame`/`WindowBounds`/`WindowInfo` neutral; only private `mod macos` is SCStream | **Half holds.** `Frame`, `WindowInfo`, `CaptureSource` etc. are neutral in `capture.rs`; `CaptureConfig`/`WindowBounds` do not exist by those names; no `mod macos` — the platform impl is `crates/ingest/src/windows.rs` (2,029 lines, WGC + GDI). SCStream was removed in `f3fb498` (2026-10-01); `screencapturekit` absent from `Cargo.lock` | `capture.rs`, `Cargo.lock` |
| 3 | `ghost_layer::betting_entropy` wired in `Pipeline::decide` (sizing only) | **Holds** — `main.rs:193` (`humanize_bounded(thread_rng(), …)`) | `main.rs:187-194` |
| 3b | `ghost_layer::temporal` complete + property-tested, no caller | **Holds** — zero production callers; medians 500–2,500 ms by complexity, `sigma_log` 0.35, range `[10, 3000] ms` (`temporal.rs:4,34-42,61`) | §3 |
| 4 | `opponent_model::Classifier` and `ExploitEngine` wired; feed `raise_size_multiplier`, `fold_equity_multiplier` | **ExploitEngine wired but inert; Classifier not wired.** `main.rs:118` pins `Archetype::Unknown`; `exploit.adjust(Unknown)` returns neutral multipliers; `Classifier` instantiated only in a smoke test | `main.rs:118-119,211-212`; `pipeline_smoke.rs:81` |
| 5 | `ui::app` portable; `run_ui_overlay` runs loop on a thread, overlay on main | **`ui::app` exists behind the `desktop` feature, never enabled by default, never run; no `run_ui_overlay` symbol in this tree** (overlay.rs/ws.rs lived on the `origin/main` line, commits `c2424b2`/`4a91af9`). `--ui` returns an error | `ui/Cargo.toml:13`; `config.rs:118` |
| 6 | `equity.rs::estimate_against_unknown` handles N opponents | **Holds** — `opponent_count: usize` param; called with `active_opponents.len()` (`main.rs:157`) | `equity.rs` |
| 7 | `.env.example` sets `COINPOKER_VLM_ENDPOINT` with `/v1/chat/completions`; `completions_url()` appends again — doubled path | **File absent at HEAD** (deleted in `f3fb498`; `.gitignore:16` still whitelists it). No `completions_url()`. Today the endpoint must be exactly `http://127.0.0.1:18090/v1/laya/predict` (validated in `config.rs`); env var `COINPOKER_VLM_ENDPOINT` survives and is passed to `doctor.py` (`live.rs:925`) | `config.rs`; `live.rs:925` |
| 8 | `VlmConfig::default()` model `qwen2-vl-7b`; `.env.example` says `gemma-4-e2b-it-OptiQ-4bit`; reconcile | **Default is now `coinpoker-laya-vision`** on `http://127.0.0.1:18090/v1/laya/predict`, timeout 5 s (config tests). Gemma is historical (`VLM_COMPATIBILITY.md:81-100` lists `gemma-4-E2B-it-Q4_0.gguf`, retired 2026-10-09); `qwen2-vl-7b` was the pre-Windows default | `config.rs` defaults+tests; `docs/VLM_COMPATIBILITY.md` |
| 9 | Loop sleeps 100 ms every iteration, 100 ms after every Pending consensus, 100 ms at loop end | **One sleep remains** (`live.rs:900`, `poll_ms` default 100). Consensus wait is a reschedule, not a sleep (`runtime.rs:1277-1285` selects `poll_ms` when awaiting a second match) | `live.rs:900`; `runtime.rs:1277-1285` |
| 10 | Consensus compares `GameState` by derived `PartialEq`; confidence part of `GameState`; exact float equality gates acceptance | **GameState has no confidence field.** Whole-observation equality is over typed values (ints, bools, strings, enums); no float participates. Floats gate **admission** earlier: `Reading::diagnostic` accepts iff `p >= floor` (choices) or `p >= floor || p <= 1 - floor` (noul) (`laya/partial.rs:51-62`); pinned floors 0.995/1.0/0.8 (`laya/partial.rs:174-181`). Partial-path consensus is per-field equality (`partial.rs:861-951`) | `parser.rs`; `screen.rs:382`; `laya/partial.rs:51-62` |
| 11 | Freshness check re-calls `zone_detector.detect`, mutating its baseline, consuming the change | **Symptom superseded.** One `observe` per frame; the change detector *is* the gate (a changed frame is consumed and only re-submitted after stability: `stable_ms 300`, `stable_captures 3`, `change_detect.rs:399-405`). Freshness = `observation_is_current` + epoch checks; no re-detect | `change_detect.rs`; `runtime.rs:114-121` |
| 12 | `pipeline.rs` raise gate `len() == 1`; hard error on multiway all-in | **Holds, file is `bin/main.rs`** — gate `active_opponents.len() == 1` (`main.rs:172`), hard error string "multiway all-in state requires side-pot-aware EV and is not supported" (`main.rs:141-151`) | `main.rs` |
| 13 | Pipeline owns OpponentTracker keyed on player name; one Pipeline per process | **No `OpponentTracker` type exists.** Opponents are ad-hoc `player.name != "Hero"` filters (`main.rs:134`); one `Pipeline` per process (`main.rs:105`, `live.rs:816`, `main.rs:309` stdin) | §7.2 |
| 14 | 6 crates to 3 | **Holds** — six members, `Cargo.toml:8-15` | §5.4 |

Adjacent claims, measured:

- "change_detect's 36.8KB": actual `change_detect.rs` is **34,338 bytes / 914 lines**
  (≈33.5 KiB; ~40% tests). 36.8 KB matches no current file; treat as stale.
- "ws mirror": absent from the tree; added and removed entirely on the `origin/main`
  line (`c2424b2` added `crates/ui/src/ws.rs` 318 lines + `overlay.rs`; `origin/main`
  froze at `4a91af9`, 2026-09-20). The only mirror today is the Python dashboard
  polling `http://127.0.0.1:18090/api/state` (`scripts/laya-server.py:910`).
- "MLX client naming": present until `f3fb498`; no `mlx` string at HEAD.
- `origin/main` (frozen 2026-09-20) carries the macOS/Gemma-era feature set the brief
  names (SCStream, `.env.example`, MLX, ws mirror, `run_live_loop`); local `main`
  (`f3fb498`, 2026-10-01) is its Windows rewrite. The current branch descends from
  `f3fb498` and kept evolving (Laya backend Oct 8-10; partials/sustained Oct 25-27).

---

## 5. Hardcoded single-table assumptions (with evidence)

1. **One window selected.** `discovery.rs::select_window` returns the single match;
   multiple equally valid matches block with an ambiguity error. No table list.
2. **One gate.** `LiveRuntime.gate: TableGate` (`runtime.rs`), one consensus window.
3. **One tracker set.** Single `tracker` + `field_trackers` bound to one window
   geometry (`runtime.rs`).
4. **One worker slot.** `ThreadWorker` single queue, latest-wins.
5. **One table namespace for history.** `AdmittedHistory.table_id = hash(session_id,
   process_id, hwnd)` (`live.rs:504-511`); the observer ledger is global to the process.
6. **Six seats everywhere.** `PHYSICAL_SEATS = 6` (`observer.rs:17`);
   `SCENE_VERIFIED_FIELDS [[_;7];6]` (`partial.rs:228`); seat arrays `[_;6]`;
   passes `p5_seat_1..6`.
7. **One calibrated identity.** `DiscoveryConfig` single `exe_name/pid/hwnd/title`;
   single lobby size pair (`live.rs:163`).
8. **One practice profile.** `.local/practice-table.json`, one selector regex
   (e.g. `^NLH\s*[0-9]+`, `EVENTS_V2.md:32-41`), one `user_scope`.
9. **One geometry.** `assets/laya/regions.json` + `laya/geometry.rs` region table for
   the six-max window (live sizes seen: 957×727 / 958×728; frozen corpus
   800×613 / 879×670 / 900×686 / 1280×778 per `.kilo/plans`).
10. **Fixed endpoint/port.** `18090`, path `/v1/laya/predict` hard-validated
    (`config.rs`).
11. **One capture session/recorder.** `.local/captures/<utc>-practice/` single writer.
12. **Hero identified by literal name `"Hero"`** — model-side convention
    (`prompt.rs:41`), enforced in parser (`parser.rs:246,294`) and consumed by name
    filters (`main.rs:134,177`). DOM/real names will collide with this.

---

## 6. Unseeded RNG sites (every one)

| Site | Use | Seeded? |
|---|---|---|
| `bin/main.rs:193` `rand::thread_rng` | raise sizing jitter (`humanize_bounded`) | unseeded — **decision-affecting** |
| `crates/core-engine/src/equity.rs:211`, `:318` `StdRng::from_entropy` | Monte Carlo equity (5,000 iterations configured, `main.rs:109`) | unseeded — **decision-affecting** |
| `bin/live.rs:446` `RandomState::new` | session/table id hashing | unseeded, ids only |
| `crates/ingest/src/recorder.rs:7` `RandomState` | recorder identity | unseeded, ids only |

Seeded only in tests: `temporal.rs`, `betting_entropy.rs`, `pipeline_smoke.rs`
(`seed_from_u64`). Net: two identical runs of the live loop can differ in sizing and
equity; there is no `--seed`.

---

## 7. Where the brief's bugs touch live behaviour today

1. **Opponent model is inert.** `Archetype::Unknown` (`main.rs:118`) → exploit
   multipliers stay at defaults; `DecisionView.opponent` is the constant string
   `"unknown"` (`main.rs:269`) and `DecisionView.confidence` is always `None`
   (`main.rs:270`). The observer ledger *does* run (`live.rs`) but never feeds the
   classifier.
2. **Hero-name coupling.** `active_opponents` = `players.iter().filter(name != "Hero")`
   (`main.rs:130-140`); parser consumes `"Hero"` by name (`parser.rs:246,294`).
3. **Multiway cliff.** Any all-in with ≥2 opponents discards the whole decision
   (`main.rs:141-151`); raises are forced to a single opponent even though the equity
   call already supports N (`main.rs:157` vs `:172`). Fold-equity fallback for sizing
   is `0.3^n` (`main.rs:211-212`).
4. **Every accepted state pays two full perceptions.** `TableGate` demands two
   identical observations (`screen.rs:301-390`), preceded by stability (3 unchanged
   captures / 300 ms, `change_detect.rs:399-405`) and `poll_ms 100` pacing
   (`runtime.rs:1277-1285`); one worker slot ⇒ strictly sequential. With the docs'
   own warm p95s (p0 271 ms, tier01 1,497.9 ms, full battery 3,027.3 ms —
   `VLM_COMPATIBILITY.md:59-62`) two batteries push decisions into seconds, against a
   5,000 ms decision budget (`runtime.rs:70`) and the 5 s reading lease.
5. **Latency is not the current *gate* problem, accuracy is.** Gate F rerun
   2026-10-25: board raw accuracy 0.40, 0/30 admitted at threshold 1.0, hero cards
   UNMEASURED, worst-pass p95 776.1 ms (`.kilo/plans/1792972074381…:288-293`).
6. **Quality flags are pessimistic by design and quiet.** All `Capability`s are
   `TrainedUnapproved`, `held_out_approved: false` (`partial.rs:497-540`);
   `quality_approved` effectively false everywhere; `thresholds.calibrated: false`
   ships (`question-set.json`).
7. **Single fixed sleep** `live.rs:900`; retry/refresh timers (`retry_ms 2000`,
   `force_refresh_ms 5000`) are wall-clock rescans, not events.
8. **Capture has no recovery ladder.** WGC `CreateForWindow` (`windows.rs:1007-1010`)
   with a full-desktop GDI `BitBlt` alternative (`windows.rs:928`); **no black-frame
   detection, no DXGI duplication, no `PrintWindow` fallback, no input simulation.**
9. **Recorder** writes PNG+manifest at 500 ms default (`recorder.rs:41-49`), capped
   (7,200 frames / 1 GiB defaults; 20,000 / 2 GiB hard) — CPU+disk cost on capture.
10. **`--ui` is a dead end** (`config.rs:118`); the real dashboard is the Python
    server on :18090.
11. **Doctor spawns Python** (`live.rs:917-968`); interpreter picked by
    `cfg!(windows) { "python" }`.
12. **`.env.example` absent** while `.gitignore:16` expects it; endpoint strictness
    means any reintroduced "append route" helper must be tested for the doubled-path
    class of bug.
13. **stdin path** (`main.rs:309-369`) is legacy; the only user of
    `StateMachine`/`TableEvent`.
14. **`manual_inference.rs`** (912 lines) duplicates startup/selection policy
    (`SourcePolicy`, `find_approved_window`) used by the Monitor workflow — reconcile
    with `live.rs::run` when the adapter lands.

---

## 8. Port-surface table

Everything is Windows-only-or-neutral; **nothing is mac-bound at HEAD**.

**Platform-neutral already (no change needed):** all of `core-engine`, `ghost-layer`,
`opponent-model`, `ui`; `ingest`: `parser.rs`, `screen.rs`, `state_machine.rs`,
`partial.rs`, `change_detect.rs`, `discovery.rs`, `runtime.rs`, `recorder.rs`,
`prompt.rs`, `vlm.rs`, `laya.rs` + `laya/*`, `lib.rs`; `bin`: `main.rs` logic,
`config.rs`, `evaluation.rs`, `manual_capture.rs` (except one test sleep shim),
`manual_inference.rs` logic.

**Windows-bound (the whole port surface):**

| Symbol | Where | Kind |
|---|---|---|
| `windows.rs` (WGC session, D3D11 staging, GDI BitBlt, enumeration, DWM bounds, DPI) | `crates/ingest/src/windows.rs` | full module |
| `PlatformCapture` alias + cfg dispatch | `capture.rs` | alias only |
| live hard-guard `target_os = "windows"` ("use --stdin on this platform") | `bin/live.rs:785-790` | guard |
| doctor interpreter pick | `bin/live.rs:919` | trivia |
| target deps (`windows 0.62.2` features) | `crates/ingest/Cargo.toml:26-48` | manifest |

**Mac-bound symbols: none.** "macOS-shaped" is a property of the pre-`f3fb498`
history, not of this checkout. The port task is therefore not a port: it is a
Windows-native extension (input, overlay, capture fallbacks, DPI).

---

## 9. Kill-list evidence (each item, with numbers)

- **VLM on the critical path.** One accepted state = ≥2 battery runs (`screen.rs:382`)
  on one worker. Docs' warm p95s per battery: full unseated 3,027.3 ms; tier01
  1,497.9 ms; p0 271.0 ms (`VLM_COMPATIBILITY.md:61-62`); 2026-10-25 worst-pass p95
  776.1 ms (seated plan §8.1). CDP read cost is unmeasured until Phase 0.
- **2-of-N consensus (sequential, not fan-out).** Confirmed sequential: the second
  observation is scheduled only after the first completes (`runtime.rs:1277-1285`),
  one worker slot (`live.rs:817`). Cost = 2× round trip + stability (300 ms / 3
  captures before *each* eligible frame, `change_detect.rs:399-405`) + pacing.
  Confidence floats are **not** in the equality today (§4.10); equality is over
  model-invented typed values (evidence bools included, `screen.rs:382`). On the CDP
  path: drop strict 2-of-2 to single-read + capability flags; keep floats out of any
  equality by test.
- **MLX naming.** Gone (`f3fb498`); no `mlx` string at HEAD.
- **SCStream.** Gone (`f3fb498`); no `screencapturekit` in `Cargo.lock`.
- **`change_detect` 36.8 KB.** Measured 34,338 B / 914 lines. Not deletable wholesale:
  `FrameTracker`+stability is the CV path's trigger. Plan: trim to stability-only
  (≤ ~300 lines, delete the animation-suppression `ChangeDetector` internals used only
  by legacy polling) once CDP is primary; delete outright only if the CV adapter
  proves an equivalent stability check inline.
- **ws mirror.** Not in tree; today's mirror is Python `/api/state` polling
  (`laya-server.py:910`); CDP brings its own WS client — do not rebuild a mirror.
- **6 crates → 3.** Merge target: `core-engine` + `ghost-layer` + `opponent-model` →
  `core`; `ingest` → perception; `bin` + `ui` → `app`. All merge candidates are pure
  and portable; `bin` already depends on all five.
- **Keep:** ghost sizing (wired, `main.rs:193`), opponent ledger + exploit (wired;
  becomes effective when `Archetype` stops being `Unknown`), all of `laya` (CV
  backend), recorder, observer/observing.

---

## 10. Latency baseline numbers (all from repo receipts)

| Number | Value | Source |
|---|---|---|
| p0 warm p95 | 271.0 ms | `VLM_COMPATIBILITY.md:61` |
| tier01 warm p95 | 1,497.9 ms | `VLM_COMPATIBILITY.md:61` |
| full unseated battery warm p95 | 3,027.3 ms | `VLM_COMPATIBILITY.md:62` |
| worst-pass p95 (Gate F rerun 2026-10-25) | 776.1 ms | seated plan §8.1 |
| decision budget / frame age | 5,000 / 8,000 ms defaults | `runtime.rs:69-70` |
| stability gate | 300 ms / 3 captures | `change_detect.rs:402-404` |
| poll pacing | 100 ms default | `runtime.rs:65` |
| capture cadence target / feed poll | 500 ms / 50 ms | sustained-freshness plan |

No repo-measured CDP number exists (no CDP code today); Phase 0 produces it. No
measured per-table budget exists anywhere; PLAN §6 is the first, anchored to the
numbers above.

---

## 11. Posture (what the workspace is, today)

Adviser-only, single-table, six-max practice scope, Laya-only perception, Gate F FAIL,
`quality_approved:false`, `thresholds.calibrated:false`, no input automation. The
Python launcher/dashboard is the operating surface the operator actually uses
(`start-vlm.ps1`, Monitor, `SEATED_DIAGNOSTIC.md`). Any refactor must keep that
workflow runnable while adapters land — see PLAN rollback rules.

---

## 12. Decruft pass — 2026-11-10 (PLAN §9 Phase 5, executed)

- **Crates 6 → 3**: workspace members are now `crates/core-engine`, `crates/ingest`,
  `bin`. `ghost-layer` → `core_engine::mimicry`; `opponent-model` →
  `core_engine::opponent`; `ui` → `bin/ui` (egui/eframe became a bin-optional
  `desktop` feature; the integration smoke test includes the module via `#[path]`).
- Deleted with reason: `core_engine::outs` (no caller; decision/equity cover draw
  math — the full outs table now lives in `strategy/odds_tables.json`);
  `ghost_layer::profile` (no caller).
- Root: `dist/` staged to `.local/archive/dist-20260923`; `lobby-screengrab.png`
  removed; `screenshot-1/2.png`, `download-model.ps1`, `environment.yml` kept
  (referenced by README/docs).
- Deliberately untouched (with reasons): `change_detect` trim (live CV path);
  `ingest::prompt` kept as the eval module; `ui::app` kept as the overlay seed;
  the `core-engine` package name kept (the plan's "core" shorthand).
- Reference sweep: zero `ghost_layer`/`opponent_model`/`outs::` references remain
  outside this note; `cargo check --workspace --all-targets --locked` and the full
  test suite stay green.

---

## 13. Phase 1 slice — archetype bridge + fuel guard (2026-11-10)

- `bin/main.rs::ArchetypeFeed` (session-scoped, `RwLock` map) folds each accepted
  preflop action-required state into `features::StatsAccumulator` per opponent name;
  `Pipeline::decide` reads the first active opponent's archetype (Unknown fallback).
  The worker feeds it in `live.rs::finish_analysis` before deciding — the §3 row
  "Classifier not wired" and §7.1 "opponent model inert" are superseded.
- `observer::Summary` occupants now compute `profile` via the classifier (was a
  constant `Unknown`); the old guard test is renamed to
  `full_raise_outcomes_classify_as_lag_after_the_minimum_hand_count`.
- Fuel guard `bin/tests/strategy_fuel.rs`: ranges tokens parse with the engine
  dialect, exploit multipliers equal `ExploitEngine::adjust` exactly (JSON aligned
  to the engine), odds-table break-even and monotonicity checked.
- Determinism pinned by `seeded_pipeline_replays_identically`; feed behaviour by
  `feed_classifies_villains_and_changes_sizing`.
- Suite: 652 passing / 0 failing (6 hardware-gated ignores), `--locked` clean.

---

## 14. Live findings — cloak, seat flow, felt latency (2026-11-10)

- **Cloak reality:** the client re-cloaks `UnityWndClass` table windows whenever
  unfocused (`DWM_CLOAKED=2`). Cloaked windows are invisible to `WindowFromPoint`/
  SendInput and were ineligible in discovery (`on_screen:false`). Two consequences,
  both handled: `windows.rs` no longer gates `on_screen` on cloak (patched; WGC +
  PrintWindow render cloaked windows — live-verified in `run3`), and input bursts
  must uncloak (`SW_HIDE`→`SW_SHOW`) then click twice (activation + action).
- **Seat flow:** join via CDP spawns the Unity window; the first hand-side blocker is
  the in-game `Insufficient funds → Claim Chips` modal (claimed 500,000); after that
  "Find Seat" leaves the window in a waitlist-style state on a full table. Receipts:
  `.local/phase1-fallback/*.png`.
- **Felt latency receipt (`run3`):** 81 analyses, capture→diagnostics p50 1,490 ms /
  p95 3,543 ms / max 4,721 ms at full battery on an animating table; 19/100
  publications budget-discarded; 349 invalidation churn records. No partial/decision
  admissions yet (thresholds uncalibrated; role below-floor).
- **Fallback receipt (`run4`):** kill → `cdp-status unavailable (10054)` → relaunch →
  snapshot resume; felt loop survived throughout. See `.local/phase1-latency/RECEIPT.md`.
