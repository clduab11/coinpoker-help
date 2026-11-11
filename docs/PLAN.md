# PLAN — adapter refactor, multi-table, execution, detection

> **This is the main plan.** Plan set (same directory): `1794334747294-inventory.md`
> (all measurements and evidence), `1794334747294-phase0.md` (executable CDP verdict
> runbook — the first step), `1794334747294-detection.md` (timing/behavioral spec).
> Intended mirror names: `docs/INVENTORY.md`, `docs/PLAN.md`, `docs/PHASE0.md`,
> `docs/DETECTION.md`.
> All file:line anchors refer to the tree as measured in the inventory (§1, HEAD `e630163`).

Ordering rule: **nothing proceeds past Phase 0 until the CDP verdict is in; if the
verdict is negative, the CV branch is costed before any Phase 1 work starts.**

---

## 0. Decided constraints

- Exactly two state adapters: **CDP (primary)** and **CV (fallback)**. No third
  abstraction. CV must never sit on the live critical path while a CDP target is
  attached for that table.
- Shared `GameState` contract + per-field **capability flags**; the engine consumes
  only fields whose trust level satisfies the action's required set.
- One pipeline/tracker/gate/state-machine/detector **per table**; opponents keyed on
  `(table, seat)`; one scheduler for N tables; deadline priority, not FIFO.
- Event-driven waits; the fixed sleeps on the CDP path are deleted.
- Every RNG seeded from config → replayable; unseeded mode kept.
- Six crates collapse to three: `core` (math + mimicry + opponent), `crates/ingest`
  (perception + adapters + state), `bin` (app + UI). Merge is mechanical (INVENTORY §9).
- Rejected by fiat (report says so, do not revisit): new traits with one impl;
  flags without a measurement behind the default; latency/accuracy claims not from
  the repo or a named benchmark; phases spanning crates without a stated reason.

---

## 1. Target architecture

### 1.1 Crate/module graph (post-merge)

```
crates/core            <- core-engine + ghost-layer + opponent-model merged as modules
  math/ (equity, pot_odds, decision, outs, ranges, table_rules)
  mimicry/ (temporal, betting_entropy, profile)
  opponent/ (observer, observing, classifier, features, exploit, betting, position)
crates/ingest          <- stays; gains adapter/ + execution/ modules
  adapter/mod.rs  TableAdapter trait, TableTarget, RawRead, Capabilities
  adapter/cdp.rs  CdpAdapter (primary)
  adapter/cv.rs   CvAdapter (fallback; wraps capture/laya pipeline)
  state/ (parser, screen, state_machine, partial, change_detect, runtime)
  transport/ (vlm.rs types, laya/*, ws.rs for CDP)
  platform/windows.rs
bin/                   <- main.rs + live.rs + ui modules (ui crate folded in)
  scheduler.rs, table_worker.rs, input.rs, overlay.rs
```

### 1.2 The adapter trait (exactly two impls)

```rust
pub trait TableAdapter {
    /// Enumerate candidate tables (CDP: page targets; CV: windows matching the
    /// calibrated identity). Cheap, called on a slow cadence and on any loss.
    fn targets(&mut self) -> Result<Vec<TableTarget>, AdapterError>;

    /// Attach to one target. Must be idempotent and must re-attach after the
    /// client relaunches (new targetId/hwnd). Bumps the target epoch on success.
    fn attach(&mut self, target: &TableTarget) -> Result<(), AdapterError>;

    /// One read of the whole state for one target. PURE: never advances internal
    /// baselines (see §8). `seq_hint` is the last seen mutation sequence, when the
    /// adapter can supply one (CDP does; CV uses its stability gate instead).
    fn read(&self, target: &TableTarget, seq_hint: Option<u64>)
        -> Result<RawRead, AdapterError>;

    /// Per-field trust. Static for the adapter kind, refined per table once a
    /// selector probe has run (CDP) — but only monotonically (never trust-up
    /// without evidence; see §2.4).
    fn capabilities(&self) -> Capabilities;
}
```

`RawRead = { fields: FieldMap, seq: Option<u64>, captured_at_ms: u64, provenance:
FieldProvenance }` where `FieldMap` covers exactly the fields the existing
`GameState`/`PartialObservationView` already names (reuse, do not invent a second
vocabulary). `Capabilities` = `enum Trust { Exact, Heuristic, Unavailable }` per field,
plus a per-table `Adaptersource` tag (`Cdp`/`Cv`) that rides every emitted record.

Engine rules:

- `action_required` (existing parser rules, `parser.rs`) is the required-field set;
  a field whose `Trust < required` degrades that field to `Unknown` **before** the
  beginner guards run — never guess.
- CV capability profile is strictly weaker: no names (seat-index only), `Heuristic`
  for cards/amounts, `Unavailable` for timers. CDP starts `Exact` for DOM-backed
  fields; selector descent downgrades to `Heuristic` explicitly and loudly
  (diagnostic reason `cdp-structural-fallback`).
- Escalation: N consecutive CDP read failures (N=3) or an unattachable target →
  schedule a CV attach for that table only; re-probe CDP on the slow cadence.
  Never mix adapters within one decided state.

### 1.3 Table worker + scheduler

- `TableWorker { adapter: Box<dyn TableAdapter> (one instance per table), pipeline:
  Pipeline, opponents: OpponentTracker, gate: ConsensusGate, machine: StateMachine,
  detector: ZoneChangeDetector, seq: u64, deadline: Option<Instant> }`. One worker
  per table; opponents keyed `(table_id, seat)`, never name.
- `OpponentTracker`: new, small: `BTreeMap<(TableId, u8 /*seat*/), SeatHistory>`
  with the bridge the current code lacks (INVENTORY §7.1): feed
  `observer`/`observing` quality-approved events into `features::StatsAccumulator`
  per `(table, seat)` and call `Classifier`; unknown stays unknown.
- `ZoneChangeDetector`: for CDP this is the target's mutation sequence + a table
  sub-tree checksum (one `Runtime.evaluate`); CV keeps `FrameTracker`. Renamed
  wrapper so both paths answer one question: "did the visible/effective state
  change since `seq`?" — the exit condition for waiting.
- Scheduler: min-heap on `(deadline, table_id)`; one sleep, "until next deadline or
  next adapter event". Collision policy (§5.3). No FIFO anywhere.

### 1.4 Freshness model (replaces the lease-recheck dance)

- Every read carries `seq` + `captured_at_ms`; a decision is valid iff
  `min(lease_ms, decision_budget_ms) - age > 0` **and** the target's `seq` is
  unchanged at publish. `seq` bumps on: DOM mutation, resize, attach/re-attach,
  selector-descent change.
- CDP mutation events (injected `MutationObserver` + `Runtime.addBinding`, or
  `Runtime.evaluate` version polling if bindings are flaky — Phase 0 decides, §2.3)
  drive wakes; the CV path keeps stability gating.

---

## 2. CDP adapter specification

1. **Discovery.** `GET http://127.0.0.1:9222/json/list` on a 2 s cadence and on any
   socket error; filter `type == "page"`; a table target is classified by URL
   pattern if stable, else by a probe read (the lobby/table discrimination already
   exists in `screen.rs` — reuse its `ScreenKind` logic against DOM text). Record
   `targetId`, `url`, `title`; **never** assume one page.
2. **Attach/reconnect.** One WebSocket per target (WS/1.1 client, no TLS to
   localhost — hand-rolled over `std::net::TcpStream` or a single small crate;
   Phase 0 decision, §"open items"). Reconnect: on `ws` drop or on targetId
   disappearance → re-enumerate → re-attach → re-inject the observer → bump epoch →
   invalidate that table's states (reuse `runtime.rs::invalidate` semantics).
   Client relaunch must be indistinguishable from a resize at the engine boundary:
   both are "epoch bump + invalidate + reattach".
3. **Read.** ONE `Runtime.evaluate` per table returning one JSON document built by an
   injected extraction function (not many small evaluates). The extraction function
   is namespaced (`window.__cpkRead()`) and versioned (string constant surfaced in
   diagnostics). Mutation observer sets `window.__cpkSeq` and calls a binding when
   present.
4. **Selector resilience.** Two tiers, in order: (1) data attributes —
   enumerate/scan for `[data-testid]`, `[data-*]` that match the field semantics
   (Phase 0 records the real attribute names); (2) structural paths relative to
   stable anchors (table container → seat containers → descendants). A field with
   neither tier is `Unavailable`; the extraction result carries which tier resolved
   each field. **Fail loud to CV** (worker-level escalation, §1.2) rather than
   guessing values. Downward-only capability: a selector probe may confirm a field
   but never silently upgrade `Heuristic → Exact` without a recorded probe receipt.
5. **Input (Phase 3, but the adapter owns event plumbing).** Clicks via
   `Input.dispatchMouseEvent` (move → pressed → released, with jittered coordinates
   inside the control's box); typing via `Input.insertText` then verify the field's
   value; slider drags via a 3-6 point mouse move sequence; `Runtime.evaluate` is
   allowed to validate/read-back but never to synthesize actions unless the element
   is unreachable by input events. All actions verify read-back before publish.
6. **What CDP is *not* used for:** no DOM mutation by the bot beyond the injected
   observer globals; no re-layout assumptions — the client is Electron and may
   restyle at will; that risk is exactly what tier-2 + fail-loud exists for.

---

## 3. CV adapter (Windows) specification

Basis: `windows.rs` already has WGC `CreateForWindow` (`windows.rs:1007-1010`) + D3D11
staging readback + a GDI full-desktop `BitBlt` alternative (`windows.rs:928`).

1. **Capture ladder** (first works, per target HWND): (a) WGC `GraphicsCaptureItem`
   per HWND; (b) if frames return black (all-black or felt-region hash constant while
   the window is known alive) → DXGI output duplication of the window's monitor,
   cropped to the window rect (client coords via `GetClientRect`+`ClientToScreen`);
   (c) `PrintWindow(PW_RENDERFULLCONTENT)` into a DIB. Record which rung produced
   each frame; black-detection threshold: >99.5% identical dark pixels in the felt
   crop across 3 frames ⇒ escalate.
2. **Input** (Phase 3): `PostMessage(WM_LBUTTONDOWN/UP)` in client coordinates first;
   if the client ignores (no state change within the action window) →
   `SetForegroundWindow` + `SendInput`. Drags: `WM_MOUSEMOVE` sequence between down/up.
3. **Overlay**: stays eframe; a new `bin/overlay.rs` (ui::app is the seed).After window
   creation apply `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE |
   WS_EX_TOOLWINDOW` post-creation (not via window class), so the overlay never steals
   focus or input. Per-monitor-v2 DPI manifest (`/MANIFEST` + awareness v2) so overlay
   and capture coordinates agree.
4. **CV is never the live path when CDP binds**: a CV-attached table runs the existing
   Laya pipeline unchanged behind the adapter; its capabilities are the Laya field
   floors (`laya/partial.rs`), and the decision path is identical from `RawRead` on.
5. CV keeps `FrameTracker` (+ stability), `TableGate` (2-of-2 stays here — it is the
   CV noise guard), and the lease model. CDP tables do not run them.

---

## 4. Multiway EV (remove the cliff)

1. Delete the `active_opponents.len() == 1` raise gate (`main.rs:172`) and the
   side-pot hard error (`main.rs:141-151`).
2. Side-pot-aware all-in EV: `side_pots(contributions[seat], stacks[seat])` →
   `Vec<Layer { amount, contestants } >` (contributions = street contribution +
   displayed stack where available). Equity per layer via
   `estimate_against_unknown` with that layer's contestant count (already N-capable,
   `equity.rs`); EV = Σ layer_amount × (equity_layer − invested_share_layer), floored
   at the call layer.
3. **Fallback when contributions are unavailable** (CV/unknown fields): single layer
   using full stacks as the all-in amount, flag `side-pot-approximated` in the
   decision diagnostics; sizing/raise math unchanged but the fold-equity term uses
   the per-opponent `0.3^n` product (keep the existing formula, `main.rs:211-212`,
   now with n from the real opponent count).
4. Raise sizing multiway: base size by the number of live opponents via the existing
   `DecisionEngine` path (keep `ranges`/`table_rules` only if they earn their keep
   here — see Phase 5 gate).

---

## 5. Concurrency and scheduling

1. Ownership: one `TableWorker` per table owns adapter instance, Pipeline,
   OpponentTracker, gate, state machine, zone detector. `Pipeline` is no longer a
   process singleton. Opponents keyed `(table, seat)`.
2. Scheduler loop: `next = heap.peek().deadline`; sleep exactly `until(next)`; wake
   also on any adapter event (WS message / binding call / capture completion). No
   cadence polling on the CDP path (`poll_ms` drops to an event-lease floor, e.g. 1 s
   health tick, not 100 ms).
3. **N tables collide inside 300 ms:** reads are I/O-bound → issue all due reads
   concurrently (per-target WS; no shared connection); order *decisions* by rising
   deadline; if K tables remain and the closest deadline cannot be met, serve it
   first and let later tables use their own (identical) lease — never block table A
   on table B's compute. Compute (equity) runs on a 2-thread pool; the worst 6-table
   collision still fits §6's budget (arithmetic there). Degradation rule: under
   sustained collision, raise per-table `decision_budget_ms` deferral **per table**,
   each table emits independently, and the sink stays per-table-keyed
   (`table_id` in every record).

---

## 6. Latency budget (p95 < 120 ms state-to-decision, CDP path)

Assumptions are marked; A-items are pinned by Phase 0 / Phase 1 measurement.

Single table (trigger → emitted decision):

| Step | Budget |
|---|---:|
| scheduler wake + target route | 3 ms |
| CDP read: 1 evaluate round trip (localhost WS) | 25 ms (A1 — Phase 0 pins; fail → budget reviewed) |
| JSON → GameState parse + validate | 2 ms |
| capability/freshness checks | 1 ms |
| opponent update + pipeline + entropy sizing | 3 ms |
| equity (2 opponents, 5,000 iters, current config) | 15 ms (A2 — Phase 1 measures; if >15 ms, drop to 2,000 iters for multiway) |
| emit/sink | 3 ms |
| p95 jitter allowance | 35 ms |
| **Total budget** | **87 ms < 120 ms** |

Six tables when N=6 collide inside 300 ms: reads issued concurrently (pipelined
WS messages; wall ≈ 25 + 5×3 = 40 ms), compute serial-ish on 2 threads:
⌈6/2⌉ × (15+2+3) = 60 ms; overheads 15 ms ⇒ **≈115 ms < 120 ms** worst-case wall for
the last table, first table ≈40 ms. If A2 lands high, the 2-way pool becomes 3 and/or
multiway equity drops iterations — recorded in Phase 1 receipts.

Deletions enabling this: the fixed sleep (`live.rs:900`), the `poll_ms` pacing of
consensus (`runtime.rs:1277-1285`), `force_refresh_ms` wall rescans (replaced by
mutation events), and, on CDP tables, the whole stability wait (CV keeps it).

---

## 7. Seeding and replay

- `RuntimeConfig.seed: Option<u64>` (`--seed`, none = production realism, on =
  replayable). When set: `SmallRng::seed_from_u64` threaded into (a) equity
  (`equity.rs:211,318` gain an RNG parameter), (b) sizing entropy (`main.rs:193`),
  (c) `temporal` sampler when it lands, (d) any tie-breaks.
- Ids (`live.rs:446`, recorder) stay hash-derived and are outside replay equality.
- Replay harness: `--seed S` + recorded `RawRead`s → same decisions byte-for-byte;
  a test pins this on the fixture corpus. Unseeded mode keeps the existing behaviour
  (a test pins that seeds *change* outputs, i.e., that the wiring is real).

---

## 8. Freshness-baseline fix and `.env.example`

Root-cause class (INVENTORY §4.11): the detector mutates its baseline in the same
call that reports "changed", so a naively re-checked freshness consumes the change it
was validating. Fix, applied to both paths:

1. `TableAdapter::read` is PURE; baseline advancement is an explicit `commit()` on the
   runtime side, called exactly once per frame/read (the current `FrameTracker`
   semantics already do this — codify it as a test: a second `observe` of the same
   frame flips no state).
2. Freshness never re-reads: it is `seq` equality + age arithmetic (§1.4). A test
   pins "no adapter call happens between capture and accept for freshness".
3. `.env.example`: recreate at repo root (`.gitignore:16` already whitelists it),
   documenting `COINPOKER_VLM_ENDPOINT` (full route, exactly
   `http://127.0.0.1:18090/v1/laya/predict`) and `COINPOKER_VLM_MODEL`
   (`coinpoker-laya-vision`), plus `COINPOKER_CDP_PORT` (default 9222) and
   `COINPOKER_SEED`. Add one `resolve_endpoint()` used by config: if the value
   already contains a route, do **not** append — test both forms (base vs full route)
   so the doubled-path class cannot return.

---

## 9. Phases

Every phase: goal / files touched / files deleted / acceptance test / rollback /
proving metric. No phase depends on a later phase. Phase 0 gates everything.

### Phase 0 — prove the path (CDP verdict; CV costed if negative)

- **Goal:** measurable verdict on DOM readability, target separation, selector
  tiers, input feasibility, evaluate latency, auto-fold ceiling. Executable from
  `PHASE0.md` alone; no source edits.
- **Files touched:** `docs/PHASE0.md` (the protocol), `.local/phase0-cdp/*`
  receipts. No source.
- **Files deleted:** none.
- **Acceptance test:** PHASE0.md verdict table filled with raw receipts:
  9222 reachable; ≥2 page targets for 2 open tables; every required field resolved
  to tier-1 or tier-2 with recorded selectors; evaluate p95 ≤ 50 ms; reattach after
  a client relaunch; auto-fold timer recorded.
- **Rollback:** nothing to roll back (read-only probing; shortcut edit restored).
- **Proving metric:** PASS/FAIL + the p95 number; if FAIL, `CV-COST.md` receipt
  (costed with Laya's 776 ms worst p95 and INVENTORY §7 items) before Phase 1.

### Phase 1 — single table, correct, on CDP

- **Goal:** live decisions from DOM reads; adapter trait + `CdpAdapter`; capability
  flags; event-driven loop; purity/seed/endpoint fixes. CV adapter implemented
  behind the trait and reachable by forced fallback (proves the seam; not tuned).
- **Files touched:** `crates/ingest/src/adapter/*` (new), `runtime.rs`, `main.rs`
  (Pipeline no longer singleton — scoped to one worker), `equity.rs` (RNG param),
  `config.rs` (+seed/port), `.env.example` (new), `live.rs` (wiring).
- **Files deleted:** the fixed sleep usage on the CDP path; `poll_ms` pacing for
  consensus; nothing else.
- **Acceptance test:** single live table, 30 min: decisions cite `adapter:cdp`;
  state→decision p95 < 120 ms (harness receipts); unplugging 9222 mid-run falls back
  to CV within N=3 failures and back on re-probe; replay with `--seed` reproduces
  decisions on the fixture corpus; no VLM call on the CDP path (worker counter = 0).
- **Rollback:** `--adapter cv` flag keeps the current Laya workflow exactly.
- **Proving metric:** p95 (target <120 ms) and fallback swap-time (target <2 s).
- **Status (2026-11-10, second slice):** the adapter layer + live CDP lobby reads
  landed earlier (receipts in `.local/phase0-cdp/`). Now `decide` consumes a real
  opponent read: `ArchetypeFeed` (bin/main.rs) classifies per-name stats folded from
  accepted preflop states, observer summaries classify occupant profiles, and
  `strategy/exploits.json` mirrors the engine under a drift guard
  (`bin/tests/strategy_fuel.rs`). Seeded replay pinned by
  `seeded_pipeline_replays_identically`. Remaining Phase 1 deltas: event-driven loop,
  unplug-fallback receipt, p95 harness run.
- **Status (2026-11-10, third slice):** event-driven wait landed (worker doorbell +
  `next_wake_in_ms`, no fixed sleep); unplug/replug fallback receipt recorded
  (`cdp-status unavailable` → snapshot resume, `.local/phase1-fallback/run4.jsonl`);
  felt latency receipt: 81 analyses, round trip p50 1,490 ms / p95 3,543 ms, 19%
  budget-expired (`.local/phase1-latency/RECEIPT.md`). Live discoveries folded in:
  the client DWM-cloaks unfocused table windows — discovery now accepts cloaked
  windows (`windows.rs` on_screen), WGC captures cloaked windows fine, and input
  needs uncloak+activate+click (`docs/OPERATIONS.md`). Remaining: seat-flow polish
  (balance claim + waitlist) and calibrated thresholds for field admission.

### Phase 2 — multi-table

- **Goal:** N tables (start 2, accept 6), per-table ownership, `(table, seat)`
  keying, deadline scheduler, collision policy, per-table escalation.
- **Files touched:** `scheduler.rs`, `table_worker.rs` (new in bin), adapter
  registry (`targets()` fan-out), opponent tracker, sink keying (`table_id` in all
  records; history ledger per table).
- **Files deleted:** the single-table assumptions in INVENTORY §5 list.
- **Acceptance test:** 6-way soak with a collision simulator (6 synthetic deadlines
  inside 300 ms): every table's p95 < 120 ms per §6 arithmetic; two tables act from
  one process without target crossover (TableGate/table_id proofs in receipts);
  relaunch of one table does not invalidate others.
- **Rollback:** `--tables 1` serializes through the same scheduler.
- **Proving metric:** per-table p95 vector + zero cross-table invalidations.

### Phase 3 — execution + timing

- **Goal:** the bot acts (CDP `Input.*`; CV `PostMessage` first) with DETECTION.md's
  timing/timing-spec, wired to `temporal` (retuned) + `betting_entropy` (extended).
- **Files touched:** `input.rs`, `overlay.rs` (eframe + ex-styles + DPI manifest),
  `temporal.rs` (retune per DETECTION), sizing perturbation in the sizing path,
  session planner (breaks/sit-outs decisions to the operator first, automation later).
- **Files deleted:** none (ui::app folds into overlay).
- **Acceptance test:** 60 min live: every action verifies read-back; zero double
  actions; measured latency histogram within DETECTION.md spec bands; a hand played
  end-to-end with no operator input; overlay click-through verified (clicks pass
  through, overlay never focused).
- **Rollback:** `--no-input` returns adviser-only (today's behaviour).
- **Proving metric:** action success rate ≥99.9%, timing spec conformance on the
  measured histogram (stated as measured, not modelled).

### Phase 4 — detection surface

- **Goal:** implement DETECTION.md's remaining signals: street/pot/hand-strength
  scaling, typed-vs-drag entry mix, cross-table stagger, session breaks/sit-outs,
  error budget; cut the theatre per its observability table.
- **Files touched:** mimicry modules, scheduler stagger, session planner.
- **Files deleted:** none.
- **Acceptance test:** receipts show per-signal distributions; a 2-hour session stays
  within all signalled bands (stated thresholds in DETECTION.md); deliberate-error
  ledger present.
- **Rollback:** each signal behind its own config flag *with the default's
  measurement recorded* (rule §0).
- **Proving metric:** per-signal p50/p95 vs spec; flag independence.

### Phase 5 — delete dead modules; merge crates

- **Goal:** crates 6→3; delete the measured-dead code with replacements named.
- **Files touched:** workspace manifests + `use` paths (mechanical).
- **Files deleted (each with replacement / not-needed-because):**
  - `core_engine::outs` — not needed because `decision.rs` computes direct EV and
    equity covers draw math; no caller today (INVENTORY §3).
  - `ghost_layer::profile` — no caller; replaced by `(table, seat)` histories when a
    consumer appears; keep only if Phase 3's planner adopts it.
  - `change_detect`: trim to stability-only (delete `ChangeDetector` animation
    internals used solely by legacy polling) — replacement: 3-capture stability kept
    for CV; CDP uses mutation seq (§1.4). Target ≤300 lines from 914.
  - `ui::app` desktop feature — replaced by `bin/overlay.rs`.
  - `ingest::prompt` — deleted if CV-only parse retains Laya (Laya ignores the
    prompt); replacement "not needed because" recorded at deletion time (it is also
    used by `evaluation.rs` — migrate that harness or keep prompt as an eval module).
  - crate merge: `ghost-layer`, `opponent-model`, `ui` directories disappear
    (modules move); workspace members become `crates/core`, `crates/ingest`, `bin`.
- **Acceptance test:** `cargo test --workspace --all-targets` green after merge;
  no `use` path touched outside the tested surface (compile proves it); INVENTORY §3
  table has zero rows without a disposition.
- **Rollback:** merge is mechanical; keep one commit boundary per crate move.
- **Proving metric:** member count = 3; dead-module count = 0.
- **Status (2026-11-10):** crates 6→3 executed; `outs`/`profile` deleted; `dist/`
  staged. Remaining from the list: `change_detect` trim, `ui::app` (kept as the
  overlay seed), `ingest::prompt` (kept as the eval module).

---

## 10. Kill list (summary; evidence in INVENTORY §9)

| Killed | Replacement / "not needed because" |
|---|---|
| VLM on critical path | CDP DOM read (<120 ms budget); Laya demoted to CV fallback |
| 2-of-N sequential consensus | CDP: single read + capability flags; CV keeps 2-of-2 as noise guard; floats already outside equality (pinned by test) |
| MLX naming | already gone (`f3fb498`); nothing to do beyond docs |
| SCStream | already gone; CV spec is WGC → DXGI → PrintWindow |
| `change_detect` 36.8 KB | trim to stability-only for CV (claimed number is stale: 34,338 B measured) |
| ws mirror | not rebuilt; dashboard keeps HTTP polling; CDP brings its own WS client |
| 6 crates | 3 (`core`, `ingest`, `bin`) |
| Keep | ghost sizing, opponent model (wire the archetype bridge in Phase 1/2), all of `laya` |

---

## 11. Open items Phase 0 must close

1. Launch recipe for `--remote-debugging-port=9222` (exe args vs shortcut; exact
   command that survives relaunch).
2. WS transport choice for the CDP client (hand-rolled vs one small crate; workspace
   currently has no WS dependency).
3. Bindings vs evaluate-polling for mutation events (must be chosen from measurement).
4. Real field selectors (tier-1/tier-2 map) and their stability across relaunch and
   resize.
5. Auto-fold timer value (the timing ceiling) and whose-turn signal.
6. Equity-cost A2 pin in Phase 1 (drives §6 arithmetic if high).

## 12. Rejected (with the reason on record)

- A third adapter or a generic "source" abstraction — two impls only; anything else
  must name its second impl on day one.
- Rebuilding the ws mirror for the dashboard — it already polls; measured.
- Porting to macOS — nothing is Mac-bound at HEAD (INVENTORY §8); "macOS-shaped" is
  history.
- Keeping `poll_ms` as a decision cadence once events exist — flags need a
  measurement; `poll_ms` becomes the health tick only.
- Loosening any gate to make a phase green (project rule; Phase 0/1 receipts record
  which gates were *not* touched).

---

## 13. Phase 0 amendment (live run 2026-11-10 — binding)

Phase 0 result: **PASS**, with one structural correction read as binding on §1–§3
(full receipts: `.local/phase0-cdp/20261110T1845Z/VERDICT.md`, `docs/PHASE0.md` §10):

- **The felt is not DOM.** Table windows are Unity processes
  (`CoinPoker Game\CoinPoker.exe`, class `UnityWndClass`, 800×613), spawned on Join
  via the `CoinPoker Bridge` process. CDP reads the **lobby surface only** (listing,
  `data-table-id` identity, Join, wallet, dialogs — all tier-1). Read §1–§3 as
  per-surface: CDP Exact for lobby fields; **CV/Laya remains required for felt
  fields even while CDP is attached** (the "CV never sits on the live path"
  simplification holds only for lobby fields).
- The two-impl trait and capability flags absorb this cleanly: `Capabilities` is per
  surface×field, and `TableTarget` for a table carries both `(targetId, root)` for
  its DOM presence and the `(pid, hwnd)` of its Unity window for the felt.
- Multi-table definition updates: N tables = N Unity windows; WGC-per-HWND (already
  per-window in `windows.rs`) becomes the multi-table felt path — enable multi
  instead of the single-window select.
- Follow-up probe (may shrink CV later): the renderer holds per-table models and
  HUD-style events; check for a live state feed before assuming felt = CV-only.
- OPEN: auto-fold timer + turn signal (observer seat only during probing; seat flow
  next session). CDP p95 measured 3.45 ms; input delivery verified end-to-end
  (Join → Unity table spawn).

