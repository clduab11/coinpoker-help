# HANDOFF PROMPT — Self-Sufficient Play

Paste this entire document into Kilo Code Desktop, workspace root
`C:\Users\cld-main\Desktop\github-projects\coinpoker-help`.

---

## 0. Operating rules for this task

1. Read `AGENTS.md`, `docs/OPERATIONS.md`, `docs/PLAN.md` (§1–§3, §13) and `docs/PHASE0.md` (§10) before touching anything. `AGENTS.md` governs; do not add policy-derived gates or restrictions of your own.
2. The machine is shared with the operator. Follow the QUIET / INPUT / CLIENT lanes in `docs/OPERATIONS.md`: before any click, focus change, launch or close, say what you will do and for how long; afterwards say the machine is free. Prefer reads and offline work. Never touch non-CoinPoker applications.
3. Work phase by phase. Each phase ends with a **real run** and a receipt, not a claim. Do not start phase N+1 until phase N's acceptance test passes. If a phase is blocked by something you cannot do (a genuine missing fact, an operator-only action, an external failure), stop that phase, write down the exact blocker and everything you proved, and continue with the next independent phase.
4. Do not commit or push. Leave the diff and the receipts. No co-author or generated-by lines if you are later asked to commit.
5. Soft-delete only. Never overwrite an existing receipt directory: every run gets a new UTC-stamped directory under `.local/`.
6. Report honestly: what worked, what didn't, what is unverified. A 200, a passing unit test or a clean build proves nothing about live behaviour.

---

## 1. Mission and definition of done

**Mission.** Make the system play poker on the live CoinPoker client without a human clicking: it must see the felt, decide, act, verify the action landed, and stop safely when anything is uncertain.

**Definition of done — "self-sufficient play" (one table):**

- A full hand is played from deal to result with **zero operator input**: the program chooses fold/check/call/raise, clicks it, and the client registers it.
- Every action is verified by read-back before the next decision; a failed or ambiguous read-back aborts the hand instead of clicking again.
- No double actions, no clicks while it is not the hero's turn, no clicks on a stale decision.
- The run produces one receipt directory containing: the decision stream, the action log, the before/after evidence for each action, and a pass/fail summary.
- The same command sequence can be repeated for a second hand without editing files or hardcoded window handles.

**Stretch (only after the above):** a 20-minute session across multiple hands, and then N tables concurrently.

"Self-sufficient" does **not** mean uninterrupted grinding. It means the loop closes without a human in it, with fail-closed behaviour.

---

## 2. Measured ground truth (2026-11-11, HEAD `0e516ec`, clean tree)

Verify these yourself before relying on them; re-measure anything older than a few days.

**Build and tests.** `cargo test --workspace --offline --locked` → **661 passed, 0 failed, 6 ignored** (the 6 are opt-in private-capture replays). Toolchain `rustc 1.95.0`. Python env `.local/laya-runtime/env/python.exe` (3.12.15).

**Surfaces.**

- The lobby is Electron and CDP-readable on `127.0.0.1:9222` (`lobby-snapshot` records: tables, wallet, `data-table-id`).
- **The felt is not DOM.** Each table is a separate Unity process, window class `UnityWndClass`, **800×613**, spawned when you join (`docs/PLAN.md` §13, `.local/phase0-cdp/20261110T1845Z/VERDICT.md`).
- Therefore CDP gives you the lobby, and the felt is always CV/Laya. No DOM shortcut exists for cards, pot, stacks or buttons.

**What is already wired in the Rust binary.**

- `Mode::Capture` (`bin/main.rs:82`) runs the live loop in `bin/live.rs:857`.
- Live loop: per-region field tracking is enabled unconditionally (`bin/live.rs:938` → `runtime.rs:1403-1410`), so a content change now does `clear("frame-changed")` (`runtime.rs:704`) instead of bumping the epoch; the old whole-frame `invalidate("frame-changed")` path (`runtime.rs:706`) is unreachable from `live`.
- Gate: identity + metadata + classification + transition checks, with a **seated acting fast-path** that accepts on the acting transition instead of waiting for a second identical read (`screen.rs:378-409`).
- Partial lane: independent per-field reads (pot, six stacks, wagers, seat scene) admit through their own two-candidate consensus and are published as `partial_observation` (`runtime.rs:1111-1144`).
- Decision: when `action_required` and `Pipeline::decide` succeeds, a `decision` record with `action`, `amount`, `ev`, `pot_odds`, `equity`, `expires_at_unix_ms` is emitted (`runtime.rs:1221-1235`, `bin/ui/widgets.rs:11-28`).
- Execution exists **outside** the binary: `scripts/action-executor.ps1` tails the live JSONL for `"event":"decision"` and clicks via `scripts/table-input.ps1`.

**What the artifacts show.** `.local/phase1-latency/run3.jsonl` (the real 800×613 felt run) is the most useful receipt:

- 225 capture-health records at **800×613**, no capture failures; 81 analyses.
- `screen_kind` **accepted 63/79** (scores 0.9815–0.9989), rejected 16 `below-floor`; `ev_table_layout` and `ev_readable` true whenever classification passed.
- **47 of 81** analyses then ended `status: unknown — "screen content is unreadable"`: the assembled state failed (missing pot on 16 frames, missing layout on 13, hidden cards/controls on others), so `evidence.readable` is false and the gate rejects at `screen.rs:329-331`.
- `action_on_hero` **false in all 79** (observer, not seated) → no actionable state, no decisions.
- **252** `observation_invalidated(frame-changed)` records. That reason can only come from the `field_observation == false` branch (`runtime.rs:706`), so run3 too ran on a pre-field-mode binary.
- **Zero** `partial_observation` and **zero** `decision` records.

`.local/phase1-fallback/run4.jsonl` is the client-restart fallback receipt: it bound a **1280×778** window (the relaunched lobby, not a table), so its `screen_kind` scored 0.28–0.40 and it proves nothing about the felt.

**Every live receipt predates the current code.** run3/run4 were written 16:42; the field-mode, seated-read and acting-frame commits are `d39c572` (20:19), `ee8f02d` (21:39), `87f8d96` (22:03); `runtime.rs` was last modified 21:58. Anything you read in `.local/` describes a binary that no longer exists. **Re-baseline before diagnosing further.**

---

## 3. Why it fails while gameplay is running — ranked

### R1. No calibrated table title → nothing can be admitted (primary blocker)

`LiveRuntime::metadata()` (`runtime.rs:1298-1309`) returns `TableTitle` only when `DiscoveryConfig::is_calibrated_table` (`discovery.rs:97-103`) is true, which needs `--table-title` to be a **case-sensitive substring** of the Unity window title (or the lobby-title-at-another-size rule, which does not apply because Unity windows carry table names, not "CoinPoker").

Without it:

- the gate rejects every table read at `screen.rs:357-359` (`table-title-calibration-required`);
- the partial lane filters the candidate out at `runtime.rs:990-996` (`metadata == MetadataEvidence::TableTitle`);
- so pot/stack reads, which otherwise work, are discarded.

This exactly matches run3: classification passes at 800×613, yet zero partials and zero decisions. It is **one CLI flag**, not a model or floor problem.

### R2. Two open tables → `ambiguous_multiple_tables`

`select_window` (`discovery.rs:210-265`) ranks candidates `Table > Unknown > Lobby`; a tie at the top returns `AmbiguousMultipleTables` with no window (`discovery.rs:228-243`), which is what run4 recorded. With `--exe-name CoinPoker.exe` alone, the Electron lobby, the cash table and the practice table can all be candidates. A unique `--table-title` fragment fixes both R2 and R1 at once; `--window-hwnd` / `--pid` are a hard pin that does **not** survive window recreation.

### R3. Frame churn and epoch invalidation (partly fixed, unverified)

The whole-frame detector fires on **one** changed pixel in one 16×16 tile (`local_changed_fraction 0.003`, `change_detect.rs:206-219`) or 0.1 % of the frame; live tabletops measured 297/298 consecutive changed captures. In pre-field mode every change bumped the epoch and every in-flight completion became `obsolete-observation` (`runtime.rs:830-866`). HEAD's per-region tracking avoids that on the felt path, but this has **never been measured live**. Do not conclude it is fixed until a run shows epochs flat while the table animates.

### R4. Two completions inside a 5 s lease (the cadence wall)

Partial admission needs two candidates with the same identity/epoch, growing generation and captured_at, both younger than `min(max_frame_age_ms, decision_budget_ms)` = 5 s, and agreeing on at least one field (`runtime.rs:1112-1144`). The full battery measured **p50 1.49 s / p95 3.54 s** per analysis on one serialized worker (`bin/live.rs:912-920`, `runtime.rs:152-202`). Two p95 analyses do not fit in 5 s, so even with R1 fixed, admission will be intermittent. This is the phase-2 engineering problem.

### R5. The action path is a thin, unsafe script

`scripts/action-executor.ps1`:

- hardcodes `$Hwnd = '0xd11f36'` (line 9) and one 800×613 button layout: fold (525,581), check/call (635,581), raise/all-in (746,581) (lines 18-20);
- maps **raise and all-in to the single raise-button click** and ignores the decision's `amount` (lines 50-51) — the raise size is whatever the client's default is;
- clicks through `table-input.ps1 -Action clicktop` (line 78), and `clicktop` **does not uncloak** (lines 166-176, "no-uncloak"); the client DWM-cloaks unfocused tables, and a cloaked/background window swallows the click — `clickrel` is the variant that uncloaks (`table-input.ps1:158-165`);
- has no read-back, no idempotency beyond the observation key, and no turn check;
- stops on nothing: it keeps clicking every decision until the process is killed.

### R6. Decision preconditions can silently produce nothing

`Pipeline::decide` (`bin/main.rs:201-258`) errors unless there are exactly two hero cards, and refuses multiway all-in states entirely (`main.rs:226-238`); raises are only considered with exactly one active opponent (`main.rs:257`). Seat stacks come from tier-2 passes; if they are missing, `players` is empty and equity is computed against zero opponents. So a "successful" decision can be built on almost no opponent information. Treat that as a diagnostic, not a green light.

### R7. Server startup is brittle

`.local/monitor.err` records `Laya server exited with code -1`; `start-vlm.ps1:66-70` refuses to start if port 18090 is occupied and never kills an unowned listener. Check the port and the private stderr file before blaming the pipeline.

### R8. The seated regions a decision needs are provisional and unmeasured

`crates/ingest/assets/laya/regions.json` lists `hero_card_1`, `hero_card_2`, `action_buttons`, `to_call`, `hero_chips`, `min_raise_to`, `max_raise_to` under `provisional`, with the note *"Seated regions are provisional: no seated capture exists."* Board slots, pot and the six seat stacks are measured at 800×613 and 1015×770; the seated lanes are not.

So even with a perfect binding and a confident p0, the passes that build an actionable state (p1, p3_to_call, p3_hero_chips, p4_min/max) crop unverified boxes. Expect `below-floor`, `pass-unavailable` or wrong glyphs there until those seven boxes are measured from a real seated 800×613 capture and promoted in the asset. This is a data/measurement task, not a threshold task.

---

## 4. Work order

### Phase 0 — Prove you can bind the felt (no code)

1. `target/debug/coinpoker.exe --list-windows` with the client running and one table open. Record every window's `exe_name`, `pid`, `hwnd`, title, size. Identify the 800×613 `UnityWndClass` window. The title is the key: take a fragment that is unique to **that** table (the trailing table id is usually the safest).
2. Start the inference server on 18090 (it blocks; run it in the background):
   `pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ManualStart`
   If it exits non-zero, read the private stderr path it prints first.
3. Run the live loop with a table title:
   `target/debug/coinpoker.exe --exe-name CoinPoker.exe --table-title "<unique fragment>" --cdp-port 9222`
   Add `--window-hwnd 0x...` only if two windows still tie; add `--pid` only if the exe name is shared and the hwnd is not enough. Do not reuse any historical hwnd from `.local/`.
4. Capture 3–5 minutes of stdout to a new `.local/self-play/<UTC>/live.jsonl` and inspect it.

**Acceptance:** the stream shows `status: capturing_table`, `identity` with the 800×613 hwnd, **at least one `partial_observation`** carrying a pot or stack field with `quality_approved`/source-current semantics intact, and **no** `ambiguous_multiple_tables` after the first refresh.

**Rollback:** nothing changed.

### Phase 1 — Re-baseline HEAD and instrument the funnel

1. Rebuild (`cargo build --offline --locked -p coinpoker`).
2. Run Phase 0 for 10 minutes while the table is actually playing.
3. Count, per minute: captures, analyses started, analyses completed, `obsolete-observation`, `publication-expired`, `screen-not-accepted`, partials published, decisions emitted.
4. If the funnel is still all zeros, add **diagnostics only** (extra fields on existing status/diagnostic records), never new gates or floors. The question you are answering is: which of R1–R4 is biting now?

**Acceptance:** a table of those counts with the first zero point named, plus the epoch trace showing whether epochs stay flat during animation.

**Rollback:** revert the diagnostic commit.

### Phase 2 — Make admission reliable under animation

Fix the binding issue found in Phase 1, then attack R4. Note first that submission still requires `progress.stable` (`runtime.rs:768-771`); in field mode that is the OR of the twelve per-region trackers (`runtime.rs:681-697`), so a frame is submittable when *any* readout crop is stable. Identify which region is gating before choosing a fix — a region-scoped submission beats loosening 3/300. Ranked options, cheapest first:

1. **Per-frame pass subsetting.** When `action_required` is false, run only the passes needed for the fields you publish (p0 + pot + stacks). The question set already has tiered passes (`crates/ingest/assets/laya/question-set.json`); do not invent new thresholds. Measure the new round trip.
2. **Second analysis worker** (bounded, no busy-preemption) so a queued stable frame is not serialized behind a p95 job. Keep one capture owner.
3. **Debounce consensus breaks** in field mode: `runtime.rs:703` currently breaks gate consensus on any tracked-region change, including pot count-up. Break only on board/hero-region changes, or require the change to persist `stable_captures`. Risk: a missed board change could admit stale consensus — the per-region freshness check (`runtime.rs:718-754`) and the transition gate (`state_machine.rs`) must stay in front of it.

Do **not** touch `stable_captures`/`stable_ms`, the fitted floors, `observation_is_current`, or `leased_record`.

**Acceptance:** on a live animating table, ≥3 `partial_observation` records per minute with at least one field verified against its source frame (same capture timestamp, same region), and epochs not incrementing per capture.

**Rollback:** each option is a separate commit/flag.

### Phase 3 — Seated, actionable state

Goal: `action_required: true` with a full, honest state.

0. **Measure the seated regions first.** Take a real seated 800×613 capture (hero dealt in, action bar visible), measure `hero_card_1`, `hero_card_2`, `action_buttons`, `to_call`, `hero_chips`, `min_raise_to`, `max_raise_to` numerically the same way the board/pot/stack boxes were measured, record the evidence, and promote them in `crates/ingest/assets/laya/regions.json` out of `provisional`. Until that exists, any actionable read is cropping guessed boxes — do not tune floors or thresholds to compensate for geometry.
1. Confirm from diagnostics that p0 returns `action_on_hero: true` on the hero's turn, a confident `hero_seat_index`, `ev_hero_cards`, `ev_action_controls`, and that p1/p3/p4 passes return confident glyphs at 800×613.
2. If a pass is systematically failing, fix the crop/geometry or the glyph contract — never the floor and never by substituting a default. `0` is a value; missing is unknown.
3. Check the `players` array: tier-2 seat stacks must be present, otherwise `Pipeline::decide` sees zero opponents (`bin/main.rs:215-225`) and the equity is meaningless. Withhold the decision (`clear("decision-suppressed")`) rather than emit a decision on an empty opponent set.
4. Verify the multiway rules: `active_opponents.len() == 1` for raises and the side-pot refusal are known limitations (`bin/main.rs:226-258`). Either implement side-pot-aware EV per `docs/PLAN.md` §4, or explicitly suppress raising multiway and let fold/call through. Do not silently pretend a raise is legal.

**Acceptance:** during the hero's turn, a `decision` record appears with a legal `action`, a non-zero `amount` when raising, `pot_odds`/`equity`, and an expiry. It must be reproducible across at least five hero decisions.

**Rollback:** `--no-input` semantics; the adviser stream alone is unchanged.

### Phase 4 — Harden execution

Replace the thin script with a fail-closed executor. Keep it external (a small Rust `bin/executor.rs` or a hardened PowerShell) that consumes the JSONL; do not bloat `live`.

Minimum behaviour:

1. **Identity from the stream**, not a constant: take hwnd/pid from the decision's `observation.identity`; refuse if it does not match the intended table. Delete `$Hwnd = '0xd11f36'`.
2. **Uncloak + activate before clicking** (`table-input.ps1:158-165` clickrel path), then click. A first click only activates — verify foreground or click twice, as `docs/OPERATIONS.md` says.
3. **Scale coordinates** from the 800×613 reference to the actual window rect; refuse if the size is not the calibrated felt size.
4. **Honour `amount`.** A raise is not one click: open the raise control, set the amount (slider or typed value), confirm, and verify the wager/stack read-back. If the decision is all-in, use the all-in control and its confirmation dialog.
5. **Read-back + idempotency.** One action per decision key; after clicking, require the next `partial_observation`/`decision` state to show the expected change (hero stack/wager/pot/action bar) within a bounded window; otherwise abort the hand and log `action-unverified`.
6. **Turn guard.** Never click unless the decision is current (`expires_at_unix_ms`), `action_required` is true in the newest state, and the hero clock is above a safety floor. A stopped or expired stream means no clicks.
7. **Abort switch.** A single file/signal that stops all clicking immediately; the executor must also exit on stream EOF.

**Acceptance:** a dry-run replay of a recorded decision stream clicks nothing; a live run with `--dry-run` logs the exact planned click with identity and amount; a live run performs one action and proves read-back.

**Rollback:** the executor is a separate process; killing it leaves the adviser running.

### Phase 5 — One hand, no operator input

Run the full loop: server → live → executor. Seat the hero first (see traps). Play one hand to completion.

**Acceptance (the definition of done):**

- one hand starts and ends with no operator input after launch;
- every action has a read-back receipt;
- zero double actions, zero clicks outside the hero's turn;
- the bot aborts cleanly if the source is lost, the classification drops, or the read-back disagrees;
- the receipt directory contains `live.jsonl`, `executor.log`, per-action before/after crops or hashes, and `RESULT.md` with the pass/fail per criterion.

**Rollback:** stop the executor; the client stays as it is.

### Phase 6 — Multi-table (only after Phase 5 passes)

`LiveRuntime` is structurally single-table: one `selected`, one `queued`, one `active`, one gate, one tracker set, one `Pipeline`, one `AdmittedHistory` (`runtime.rs:459-492`, `bin/live.rs:895-940`). N tables require the per-table worker + scheduler refactor in `docs/PLAN.md` §5: one runtime/Pipeline/gate per felt, `(table, seat)` opponent keys, deadline-ordered scheduling, per-table sinks and history. Do not fake it with one process round-robining windows.

---

## 5. Invariants — do not break these

- **No floor lowering, no fabricated values, no relabelled guesses, no defaults for missing fields.** `laya_calibrated` stays false until a real Gate F pass; `quality_approved` stays false. That does not block partial reads — do not "fix" it by setting it true.
- **Source identity and freshness stay exact**: `observation_is_current` (`runtime.rs:114-121`), `leased_record` (`bin/live.rs:198-243`), per-region `retain_source_current_fields` (`runtime.rs:718-754`). No re-stamping, no lease extension, no replay presented as live.
- **The gate's metadata requirement is evidence, not bureaucracy.** If you change `MetadataEvidence` semantics, you must replace it with an equally strong, measured signal (e.g. a calibrated felt-layout classifier), not delete it. `screen.rs:901-905` pins the current rejection.
- **Private data stays private**: raw provenance, answers, diagnostics and PNGs under `.local/`; no images in state DTOs; no secrets in logs.
- **One writer per resource.** One capture owner, one bounded analysis worker, one executor. No retry storms.
- **Preserve failures.** A failed receipt is evidence; do not delete or overwrite it.

---

## 6. Commands

```bash
# build / test / lint (run from the repo root)
cargo build --offline --locked -p coinpoker
cargo test --workspace --offline --locked
cargo clippy --workspace --all-targets --offline --locked -- -D warnings
cargo fmt --all -- --check
.local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests

# window inventory (read-only, no pixels)
target/debug/coinpoker.exe --list-windows

# inference server on 18090 (blocks; run in background)
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ManualStart

# live felt loop (stdout JSONL)
target/debug/coinpoker.exe --exe-name CoinPoker.exe --table-title "<unique fragment>" --cdp-port 9222

# optional private recording
target/debug/coinpoker.exe --exe-name CoinPoker.exe --table-title "<fragment>" --record-dir .local/captures --record-interval-ms 500
```

The VLM endpoint is fixed at `http://127.0.0.1:18090/v1/laya/predict` (`bin/config.rs:377-379`); alternate ports are refused by design.

---

## 7. Traps and field notes

- **`--table-title` is a case-sensitive substring**, not a regex, and not the lobby title (`discovery.rs:148-154`). The Unity titles look like `<table name> <blinds> <table id>`; use the id.
- **`on_screen` is only `IsWindowVisible && !IsIconic`** (`windows.rs:217-228`); DWM cloak does not make a window ineligible, but it does make a naive click land on the desktop.
- **PostMessage is not consumed by Unity.** `SendInput`/`mouse_event` is the only working rung (`docs/OPERATIONS.md:20-26`).
- **A first click only activates the window.** Verify foreground or click twice.
- **The client re-cloaks tables when unfocused**; `SW_HIDE` → `SW_SHOW` clears it.
- **`--window-hwnd`/`--pid` pins die with the window.** They are for deterministic single runs, not for a loop that must survive a relaunch.
- **Seven of the regions a decision needs are unmeasured** (`regions.json` → `provisional`: hero cards, action buttons, to_call, hero chips, min/max raise). A decision attempted before that measurement is built on guessed crops, however good the model is.
- **Decision vocabulary** is `fold | check | call | raise | allin` (`bin/main.rs:322-333`, `bin/ui/widgets.rs:11-13`). `scripts/laya_actions.py` uses `all_in` for a different (perception) subsystem — do not mix them.
- **`decide` needs exactly two hero cards** and returns nothing otherwise (`bin/main.rs:206-212`). No cards means no decision; that is correct, not a bug to route around.
- **`players: []` is not "no opponents".** It means tier-2 reads were unavailable; suppress the decision.
- **Seat flow is real work**: a fresh table can show `Insufficient funds` before the in-game `Claim Chips`, and seat buttons can hide behind a waitlist (`.local/phase1-latency/RECEIPT.md`). Verify seating from the felt state (`hero_seat_index`, `ev_seat_controls`), never from a title or a hunch.
- **Port 18090 is single-instance.** `start-vlm.ps1` will refuse rather than kill a listener; find the owner instead of forcing a restart.
- **The `.local/` receipts are stale** (pre-`d39c572`). Use them for shape and history, never as current behaviour.
- **The 2026-10-14 blocker** (`TABLE CLOSED` / near-black client) was a client graphics glitch cleared by a restart; if the felt renders black, restart the client before debugging the pipeline.

---

## 8. What to report back

For each phase: the receipt path, the acceptance criterion, the measured numbers, and what is still unproven. Then a single status block:

```
PHASE: n/6
BINDING: exe=<...> title=<...> hwnd=<...> size=<...>
PARTIALS: <n/min>  DECISIONS: <n>  ACTIONS: <n>  READBACK_FAIL: <n>
DOUBLE_ACTIONS: 0
BLOCKERS: <one line each, with the exact predicate or error>
UNVERIFIED: <what you did not measure>
```

Do not declare self-sufficient play achieved unless Phase 5's acceptance test passed on a live hand. If it did not, say which criterion failed and what the evidence shows.
