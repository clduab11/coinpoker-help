# Bound the observer `history` emission (unblock a valid bounded receipt) + A4 re-freeze

## Goal

Bring a bounded live observer session from `receipt-invalid` to a valid receipt
(`receipt_complete: true`, `diagnostics_complete: true`, stdout well under `MAX_LOG`,
same `unvalidated_source` accounting), **without** relaxing any admission,
calibration, cap or accuracy gate, then re-freeze the A4 build identity.

The admission gate stays closed. That is correct behaviour, not a regression.

## Verified context (do not re-derive)

- `HEAD` = `76714f0`, worktree clean, branch `checkpoint/seated-read-mechanism-2-20261002`, ahead 21 of origin. **Do not push.**
- Windows / PowerShell 5.1. No `&&`; use `;` and `if ($?) {}`. Python for all tooling: `.local/laya-runtime/env/python.exe`.
- Failing receipt: `.local/laya/manual-capture/5a484646efd645129e34a8a5ebf5e114/run.json` —
  `diagnostic_streams.stdout.bytes_seen = 21,001,152` vs `cap_bytes = 20,971,520`,
  `cap_exceeded: true`, `forced_stop: true`, `receipt_complete: false`,
  `stop_reason: "receipt-invalid"`. `status.json` in the same directory: `mode: inference-enabled`,
  `source_policy: automatic-bounded`, 489 frames, `readability: full`, `distinct_opportunities: 0`.
- That `stdout.jsonl` holds **2406 records, of which 349 are `event: history`** (measured).
- Root cause: `bin/live.rs:638-641` `history_record()` serializes `observer.summary()` in full;
  `bin/live.rs:643-687` `emit_with_history()` emits it after every admitted `observation`,
  `partial_observation` and fresh-`capture_health` emission. `crates/opponent-model/src/observer.rs:1111`
  bounds each emission to the ledger tail (`MAX_EVENT_VIEW = 200`, observer.rs:15), so each record
  re-sends the whole bounded view → cost is `O(emissions × view)`, ~57 KiB per record at saturation.
  The ledger itself is never near its cap (`MAX_SESSION_EVENTS = 10_000`): this is emission economy.
- Every accepted capture becomes `GapReason::UnvalidatedSource`: `bin/live.rs:499-513` observes with
  `quality_approved: false` and `Snapshot::default()` (no hero/seat evidence). The gate is
  `bin/live.rs:176` + `crates/ingest/src/laya.rs:629` → `crates/ingest/assets/laya/question-set.json`
  `{"initial": 0.8, "calibrated": false}`. **Out of scope; do not flip.**
- `history` is emitted **only while `activity.active` is true** (`bin/manual_inference.rs:676-679`),
  and `ActivityGate` (`bin/manual_inference.rs:36-132`) starts **inactive** for every `automatic-*`
  policy: two consecutive identical region witnesses set a baseline, then one *changed* tracked
  readout region (board/pot/stack) flips it active. **No hero seating is required**; a table with
  visible content change qualifies, a static table does not.
- `--capture-only` never reaches the observer (`bin/manual_capture.rs:494-506` → `capture_loop`), so
  `laya_capture.py`'s `MAX_RECORD = 16 KiB` line bound is **not** a constraint on `history` records.
  All history-emitting modes are `inference-enabled` and use `MAX_FEED_RECORD = 256 KiB`;
  `bin/manual_inference.rs:552-558` also rejects any single record > 256 KiB.
- Only `scripts/laya_dashboard.py` parses the native `history` record. `scripts/laya_capture.py`
  only counts bytes/line length and forwards the event name; `scripts/laya_server_validation.py`
  has no `history` handling; `scripts/dashboard/app.js` consumes the dashboard's normalized
  `snapshot.history.events`; `scripts/measure_observer.py` only counts `row["event"]` kinds.

## Design decision: cursor/delta `history` record

Keep `summary` (and every `Observer` invariant) intact; change only what the `history` **record**
carries, plus the consumer's merge rule.

New sibling fields on the `history` record (next to `emitted_at_unix_ms`):

| Field | Meaning |
|---|---|
| `history_since` | `u64`. Cursor the consumer had before this record (`0` for a snapshot). |
| `history_through` | `u64`. `event_sequence` of the newest ledger event represented here; `0` if the ledger is empty. |
| `history_snapshot` | `bool`. `true` ⇒ `summary.events` is the complete bounded view (consumer **replaces**); `false` ⇒ `summary.events` is exactly the contiguous run with sequence in `(history_since, history_through]` (consumer **appends**). |
| `history_omitted` | `u64`. Ledger events appended after `history_since` that this record does **not** represent; `0` in normal operation. Non-zero ⇒ the reconstructed list is discontinuous before its oldest entry. |

`summary.events` is the **only** field whose content changes:
- snapshot: exactly what `observer.summary()` returns today (ledger tail, ≤ 200).
- delta: the newly appended events only, ascending and contiguous.

`session_id`, `table_id`, `hand_id`, `counts`, `gaps`, `coverage` (incl. `event_limit` = 10,000),
`occupants` stay absolute in every record, unmodified.

Rules:
1. `event_sequence` remains strictly ascending and contiguous in the ledger; a delta is a contiguous
   run and is never reordered, dropped, invented or truncated.
2. Snapshot triggers: first emission of a session; change of `(session_id, table_id, hand_id)`;
   every `HISTORY_SNAPSHOT_INTERVAL = 64` emissions; or a pending run larger than `MAX_EVENT_VIEW`.
3. Snapshot-on-overflow is truthful: `history_omitted = pending − view_len` (only reachable if far
   more than 200 events accumulate between emissions, which the current call sites cannot produce).
4. Legacy tolerance: a record with `history_snapshot` absent is treated as a snapshot. This keeps
   the existing dashboard/`test_laya_dashboard.py` fixtures valid with no edit.
5. Caps are untouched: `MAX_LOG`, `MAX_FEED_RECORD`, `MAX_RECORD`, `MAX_SESSION_EVENTS`,
   `MAX_EVENT_VIEW`, `TARGET` and every receipt rule in `scripts/laya_capture.py` are unchanged.

Bound arithmetic to assert in tests: per session, bytes ≈ `emissions × ~600 B` +
`floor(emissions / 64) × ~60 KiB`. For 1200 emissions: ≈ 0.7 MB + 19 × 60 KiB ≈ **1.9 MB**, versus
≈ 68 MB for the current re-emission. Worst case per record stays ≤ ~60 KiB, far under 256 KiB.

## Why this is not a truncation

- `crates/opponent-model/src/observer.rs` is **not modified**; the ledger, `event_limit` reserve and
  `RecordingStopped` behaviour are untouched, so `ordered_prefix`, `complete`, `partial_hands`,
  `accepted_captures` and `unvalidated_source` semantics are bit-identical.
- Every ledger event is delivered exactly once: either inside the snapshot that covers it or inside
  the delta that follows it. Nothing is dropped silently; `history_omitted` counts any event that a
  single record could not carry, and `coverage.complete`/`gaps` still tell the truth about the ledger.
- No cap is raised and no `.local/` evidence is rewritten; the child still fails closed if it ever
  really exceeds `MAX_LOG`.

## Tasks (ordered)

1. **Emitter — `bin/live.rs`.**
   - Add cursor state to `AdmittedHistory` (e.g. `history_since: u64`,
     `history_snapshot_countdown: u32`, `history_key: Option<(Id, Id, Option<Id>)>`).
   - Replace `history_record(observer, emitted_at)` with a form that takes `&mut` cursor state and
     builds the record described above; source the delta from the existing public
     `Observer::events()` (`crates/opponent-model/src/observer.rs:467`) filtered by
     `event_sequence > history_since`, and everything else from `observer.summary()` (overwriting
     its `events`). Do **not** add or change `Observer` APIs.
   - Call it from `emit_with_history` (all three branches: `observation`, `partial_observation`,
     fresh `capture_health`). Keep emission cadence unchanged (one record per trigger).
   - Accepted cost: `observer.summary()` still clones the ≤200-event view that a delta discards;
     a `Summary::without_events()` micro-optimisation is explicitly out of scope.

2. **Emitter tests — `bin/live_tests.rs`.**
   - Update the two `history_record(&history.observer, 12_345)` call sites (lines ~629, ~804) for the
     new signature. `history_record` is not used anywhere else.
   - Keep `admitted_observation_emits_one_opaque_gap_summary_after_successful_write`
     (lines 572-652) green; add the assertion that the first record is
     `history_snapshot: true`, `history_since: 0`, `history_through: 1`.
   - Add `history_delta_reconstructs_the_same_bounded_view_as_a_snapshot`: drive M admissions,
     merge (`history_snapshot` ⇒ replace, else append), and assert the merged list equals
     `observer.summary().events`.
   - Add the long-session regression test: drive `MAX_FRAMES` = 1200 fresh admissions (clone the
     `history_source` ticket, `generation += 1`, `captured_at_ms += 1`, advance the clock so
     `age < min(max_frame_age_ms, decision_budget_ms)`, e.g.
     `invalidation_blocks_old_sources...` at lines 729-813 shows the pattern) into a byte-counting
     sink and assert: actual total < 4 MiB **and** the per-emission full-`summary` re-serialization
     total > 25 MiB (this is the previously-blowing-cap case) and `actual * 10 < naive`.
   - Add: table/hand identity change forces `history_snapshot: true`; the 64-emission cadence fires a
     snapshot; a pending run > `MAX_EVENT_VIEW` yields a snapshot with `history_omitted > 0`.
   - Untouched and expected to stay green: `bin/manual_inference_tests.rs` (asserts event *names*
     only), `crates/opponent-model` observer tests (no source change).

3. **Consumer — `scripts/laya_dashboard.py`** (native `ingest`, `event == "history"`, lines 1569-1618).
   - Read `history_snapshot`/`history_since`/`history_through`/`history_omitted` from the *record*.
     Absent `history_snapshot` ⇒ snapshot (legacy).
   - Snapshot ⇒ replace the retained raw list with `summary["events"]`; delta ⇒ append.
     Merge/dedupe by `event_sequence`, then keep the newest ≤ 200 before sanitizing.
   - Keep the existing per-event sanitizer and the resulting `self.history["events"]` (sanitized,
     merged, bounded) so `GET /api/state` and `scripts/dashboard/app.js` are unchanged.
   - Keep resetting the merged list on `begin_stream` (line 735) and on `invalid-history-record`
     (line 1572). Record `history_omitted` truthfully (e.g. into `saved["history"]`) rather than
     claiming a continuous prefix when it is non-zero.
   - `saved["history"]` (private ledger row) keeps carrying the merged bounded list, so
     `.local/history/<session>/ledger.jsonl` stays bounded and its cap semantics are unchanged.

4. **Consumer tests — `scripts/tests/`** (extend `test_laya_dashboard.py`).
   - Snapshot + two deltas reconstruct the same list as three snapshots.
   - Legacy record without cursor fields still replaces (existing tests at
     `test_laya_dashboard.py:127, 589, 622`, `test_laya_dashboard_stage2.py:441`,
     `test_manual_inference.py:700` must pass unedited).
   - Delta after a stream reset does not leak the previous session's events.
   - `history_omitted > 0` is surfaced, not silently presented as complete.
   - Also add a Python record-size guard test: a synthetic snapshot with 200 ledger events
     serializes to < `laya_capture.MAX_FEED_RECORD`, so a `history` line can never trip
     `invalid-native-receipt` in an `inference-enabled` session.

5. **Docs — `docs/EVENTS_V2.md`.**
   - Update the `history` row (line 79) to state: bounded `summary` plus a monotonic cursor; `events`
     is a delta between snapshots and a complete bounded view on snapshots.
   - Add a short subsection stating field meanings, the ordering rule (ascending, contiguous
     `event_sequence`; snapshot replaces, delta appends), the completeness rule (`history_omitted`),
     the snapshot triggers, that aggregates stay absolute, and that caps/evidence policy are
     unchanged (`MAX_EVENT_VIEW = 200`, ledger 10,000 events / 25 MiB).
   - No other doc describes this event (verified); `docs/SEATED_DIAGNOSTIC.md` needs no change.

6. **Validation baseline** (run every command; do not substitute synthetic for live):

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-targets --all-features --locked
& .local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests
& .local/laya-runtime/env/python.exe -B scripts/validate.py --output-dir ".local/validation/$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
& C:/Users/cld-main/AppData/Local/Temp/kilo/readiness-browser-env-20261015/Scripts/python.exe -B scripts/browser_smoke.py --channel msedge
pwsh -File download-model.ps1 -Verify
```

   Expected: 633 Rust tests (5 ignored) + the new tests; 968 Python tests (26 skipped) + the new
   tests; clippy clean with `-D warnings`; browser smoke 60/60 with 0 page errors and 0 unexpected
   requests; `download-model.ps1 -Verify` → `ok: true`.

7. **A4 re-freeze (gitignored evidence, not committed).**
   - `cargo build --locked --bin coinpoker`; `cargo build --locked --release --bin coinpoker`.
   - Run `.local/preflight/collect.py`; confirm `complete: true`, `dirty: false`, `model_all_match: true`,
     `listener_18090: false`.
   - Rewrite the frozen-identity table in `.local/preflight/PHASE2-RECEIPT.md` with the new revision
     and the new debug/release SHA-256s, and record the explicit delta against the old identity
     (debug `5ec1f3a8…6757b7`, release `a2e0e8d9…e7aa9`, revision `67508fc`/`e2d3a69`) — the old
     identity is invalidated by this Rust source change. `/.local/` is gitignored: nothing here is staged.

8. **Commits** (imperative sentence case, concise, tracked files only, no push).
   - Commit 1: emitter + its Rust tests + the dashboard consumer + its Python tests (the wire change
     and its only consumer must land together to keep the tree coherent).
   - Commit 2: `docs/EVENTS_V2.md`.
   - Never stage `.local/` or secrets. Do not touch `crates/ingest/assets/laya/question-set.json`.

## Out of scope (do not do)

- Do not set `thresholds.calibrated` to `true` and do not promote fitted floors (Phase 4b, Gate F).
- Do not touch the browser/DOM boundary, `crates/ingest/src/parser.rs`, or the decision engine.
- Do not raise `MAX_LOG`/`MAX_FEED_RECORD`/`MAX_RECORD`, truncate the ledger, or change
  `scripts/laya_capture.py` receipt semantics.
- Do not begin it2 GPU training or wire advice. No table interaction; no input automation.

## Risks

- **Silent partial render.** If the dashboard merge is wrong, the Monitor could show a truncated
  history. Mitigated by the reconstruction test (delta merge ≡ snapshot) and by keeping
  `history_omitted` explicit.
- **Feed record growth.** A snapshot is ~60 KiB; asserted < 256 KiB so `invalid-native-receipt`
  cannot trigger from record size.
- **Live evidence gap.** The byte reduction is *that reduction* only if `activity` activates; a run
  with zero `history` records proves nothing about the cap.

## Acceptance and remaining unknowns

Automated (delivered by this task): the long-session regression test proves the emitter's bounded
byte behaviour for a 1200-emission session and shows the pre-fix re-emission would have exceeded
`MAX_LOG`; the recorded `21,001,152`-byte real run is the pre-fix baseline (measured, not modelled).

Operator-gated (not verifiable here, state plainly in the report):

1. `pwsh -File download-model.ps1 -Verify` → `ok: true`; port 18090 free.
2. `pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -PracticeConfig .local/practice-table.json`
   with the client visible/unobscured at a table whose readout regions visibly change.
3. Stop on `operator-stop` / `duration-limit` / `frame-limit` and check: `run.json`
   `receipt_complete: true`, `diagnostics_complete: true`, `cap_exceeded: false`,
   `bytes_seen` < 20,971,520; `stdout.jsonl` size and its `"event":"history"` count **> 0**
   (the failed run had 349) — zero history records ⇒ inconclusive, not a pass; `summary.json`
   unchanged `unvalidated_source` accounting; `distinct_opportunities` reported honestly (may stay 0;
   the admission gate is expected to stay closed).
4. `-ContinuousObservation` (`automatic-sustained`) follows the same loop; verify the
   `len(pipes) == 2` accounting at `scripts/laya_capture.py:885-888` is untouched and
   `diagnostic_streams.stdout.cap_exceeded: false`.

Operator gates that remain (state, do not assume away): the 20-crop label spot check in
`.local/laya/datasets/observing-20261010-v2-staging/human-review-20261025/spot-check/board-pack.json`
still gates `training_eligible`; Phase 4a seated captures and the GPU-training GO are separate;
live/physical acceptance is always separate from the automated suites.

## Open questions

- None blocking implementation. Live bounded-session acceptance is explicitly operator-gated per
  your decision; the report must mark it unverified and name the next gate (Phase 4b Gate F).
