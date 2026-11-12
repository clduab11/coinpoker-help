# Sustained native numeric freshness: measure, backcheck, then optimize

## Objective and pinned decisions

Make the existing sustained Monitor show accurate native Pot/stack values with measured end-to-end freshness. This packet is a **600-second live measurement and verdict**, not a speculative production rewrite.

Pinned with the operator:
- **Native numbers first:** Pot and at least two supported stacks; Board/history remain separate tracks.
- **Sustained observation:** `-ContinuousObservation` is the operating path; bounded runs remain smoke/regression runs.
- **Latency target:** native capture-to-first-current-DOM p95 **strictly below 3,000 ms**.
- **Freshness target:** admitted-ticket inter-update gap p95 **strictly below 5,000 ms** for Pot and at least two supported stacks, derived from the existing five-second reading lease.

## Why this is the next step

The activity-lease fix is present in the worktree and a bounded session activated at 18,853 ms with 814 history records. Transport is already bounded and relatively fast: 500 ms target capture cadence, 50 ms native-feed poll, 250 ms browser `/api/state` poll. What remains unverified is physical numeric accuracy and capture-to-DOM latency.

The sustained scheduler is an eight-job cycle (`bin/manual_inference.rs:791-824`): three seat pairs, each repeated, then two BoardReadout jobs. A seat can therefore wait a full cycle while every job must retain its original five-second lease. Treat this as a **hypothesis to measure**, not permission to rewrite scheduling before evidence exists.

Existing tooling already measures the required path:
- `scripts/measure_observer.py` collects producer/feed/API evidence and computes `native_numeric_timing` stages.
- `window.coinpokerMonitor.renderReceipts()` exports actual first-current-DOM receipts.
- `scripts/dashboard/app.js` retains bounded render receipts; repeated polls do not create new samples.

## Boundaries

- Preserve the current uncommitted activity-gate and documentation changes; do not revert, commit, or push them.
- No production source edits in this packet. New files are limited to private measurement evidence and, only if needed, one private read-only gap analyzer under `.local/analysis/`.
- No changes to confidence floors, fitted floors, five-second leases, activity/admission gates, witness rules, model pins, `question-set.json`, or `MAX_LOG`.
- No WebSocket/SSE conversion, scheduler rewrite, model training, Board calibration, advice wiring, or input automation.
- Do not kill an unknown listener or use another port. Do not commit `.local/`.

Replace `STAMP`, `SESSION_ID`, `CAPTURE_DIR`, `START_UNIX_MS`, and `END_UNIX_MS` with literal values before running commands; do not use shell subexpressions or redirection.

## 1. Freeze identity and preflight

1. Record `git status --short` and `git diff --stat`; confirm the expected five modified tracked files and no unrelated edits.
2. Build the exact worktree binary and verify the pinned model:

   ```powershell
   cargo build --locked -p coinpoker
   pwsh -NoProfile -File download-model.ps1 -Verify
   .local/laya-runtime/env/python.exe -B scripts/measure_observer.py self-test
   ```

3. Confirm port 18090 is free and no previous owned launcher is running. If it is occupied, stop only an identified owned launcher; otherwise stop and report.
4. If any production source differs from the reviewed worktree, stop and rerun the full validation baseline before live measurement.

## 2. Start one sustained, browser-observed session

Launch with a unique private answers log and explicit Monitor start:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation -ManualStart -AnswersLog .local/laya/train/native-freshness-STAMP.answers.jsonl -PracticeConfig .local/practice-table.json
```

1. Wait for `model_state: ready`; record the service instance and binary/build identity.
2. Open `http://127.0.0.1:18090/` in a visible browser tab. Keep the CoinPoker table and Monitor visible side by side without overlap; the current GDI path needs real visible pixels.
3. Click **Start monitor**. Record `SESSION_ID` from the active session and `CAPTURE_DIR` from its `status.json`; verify 957x727, green felt, full readability, one source owner, and one inference worker.
4. At collection start, call `window.monitorRenderReceipts.reset()` once in the actual Monitor tab. Do not reset it again during the window.

## 3. Collect the frozen 600-second window

```powershell
.local/laya-runtime/env/python.exe -B scripts/measure_observer.py collect --session SESSION_ID --answers .local/laya/train/native-freshness-STAMP.answers.jsonl --manifest .local/captures/CAPTURE_DIR/manifest.jsonl --out .local/laya/train/native-freshness-STAMP --seconds 600 --poll-ms 1000
```

Use 1000 ms API sampling: it is independent of the browser's 250 ms polling and avoids the harness's 32 MiB output cap seen by faster long-window sampling.

During collection:
- The operator acts manually; add no automation. Seek ordinary natural Pot/stack changes, but never manufacture or relabel evidence.
- Keep the tab visible and the source unobscured. Save Monitor screenshots after the first admitted native values and near the end.
- Do not restart to obtain a better sample. Source loss, an unowned process, or collection caps invalidate the affected verdict.

Before stopping the session, export the actual browser object `window.coinpokerMonitor.renderReceipts()` verbatim to:

```text
.local/laya/train/native-freshness-STAMP/ui-receipts.json
```

Then create `STOP` in the session directory with the editor tool, wait for `run.json`, and stop the owned launcher. Verify with the existing filters:

```powershell
jq -f .local/analysis/receipt-fields.jq .local/laya/manual-capture/SESSION_ID/run.json
jq -s -f .local/analysis/stdout-bytes.jq .local/laya/manual-capture/SESSION_ID/stdout.jsonl
```

Required receipt facts: `receipt_complete: true`, `stop_acknowledged: true`, `forced_stop: false`, `exit_code: 0`, both sustained pipes accounting-complete, `cap_exceeded: false`, `bytes_dropped: 0`, activity activated, and `history > 0`.

## 4. Analyze full and stable windows

Run the full report and summary:

```powershell
.local/laya-runtime/env/python.exe -B scripts/measure_observer.py analyze --out .local/laya/train/native-freshness-STAMP --report timing.json --ui-receipts .local/laya/train/native-freshness-STAMP/ui-receipts.json
.local/laya-runtime/env/python.exe -B scripts/measure_observer.py summary --out .local/laya/train/native-freshness-STAMP --report timing.json
```

Before reading latency results, freeze the stable window:
- `START_UNIX_MS` = first `activity_state: active` timestamp plus 5,000 ms stabilization margin.
- `END_UNIX_MS` = the earlier of collector end and the last manifest frame's `source_utc_unix_ms`, so every accuracy claim has an original recorded frame.
- The window must span at least 60 seconds; otherwise the run is inconclusive.

Analyze that exact window without changing it after seeing results:

```powershell
.local/laya-runtime/env/python.exe -B scripts/measure_observer.py source --out .local/laya/train/native-freshness-STAMP --report timing-stable.json --session SESSION_ID --answers .local/laya/train/native-freshness-STAMP.answers.jsonl --manifest .local/captures/CAPTURE_DIR/manifest.jsonl --start-unix-ms START_UNIX_MS --end-unix-ms END_UNIX_MS --ui-receipts .local/laya/train/native-freshness-STAMP/ui-receipts.json
```

Report `native_numeric_timing.sample_count`, `complete_stage_sample_count`, `complete_coverage`, `counts`, `unknown_records`, per-field results, and all five stages: `capture_to_emit`, `emit_to_ingest`, `ingest_to_api`, `api_to_dom`, and `capture_to_dom`. Missing stages remain unknown; never backfill them from later publication.

## 5. Measure admitted-field gaps without counting static pixels or polls

The gap metric is **not** the interval between visible value changes: an unchanged Pot need not repaint. For each field, use `ledger.jsonl` entries with `disposition: admitted`, require the field's accepted status and non-null value, and deduplicate by source/epoch/original `captured_at_ms`. Use the first DashboardState admission (`recorded_utc`) per distinct native capture, sort by admission time, and include stable-window edges. Repeated API polls, same-capture relabelling, provisional values, last-read values, rejected/expired tickets, and duplicate bundles do not count.

Report nearest-rank p95 gaps for Pot and every supported stack, plus raw counts, rejected/expired tickets, unsupported/below-floor intervals, and the maximum gap. If `timing-stable.json` does not expose this exact series, implement one small private read-only analyzer under `.local/analysis/`; do not add production telemetry. Self-check it with frozen rows proving that same-capture duplicates are removed, unchanged values on new captures still count, rejected tickets do not count, and window edges are included.

## 6. Backcheck physical accuracy

For at least three source-backed accepted display updates spanning at least 60 seconds, including a naturally occurring numeric change:
- Backcheck Pot and at least two supported stacks against the **exact original capture** identified by the render/ledger receipt and manifest hash.
- Normalize only documented units/formatting; no tolerance, nearest-frame substitution, or plausible-value correction.
- Preserve the complete verification sample and every mismatch. Any known incorrect current native value fails the run.
- Confirm expired/source-invalidated/stopped values clear or become explicitly last-read, never current.

## Verdict

Report separate **evidence integrity, functional, accuracy, latency, freshness, and receipt** verdicts; overall `pass`, `fail`, or `inconclusive`.

Pass requires all of:
1. Complete collection and UI receipts, no unexplained API/projection failures, no caps/dropped receipts, and a complete sustained terminal receipt.
2. The functional three-update/60-second demonstration and exact original-frame numeric backchecks.
3. Stable-window native capture-to-first-current-DOM p95 **< 3,000 ms**, with sample and stage coverage disclosed.
4. Stable-window admitted-ticket gap p95 **< 5,000 ms** for Pot and at least two supported stacks; a field with no admissions has a full-window gap, not a pass.
5. No stale/current mislabelling and no known incorrect current value.

No natural change gives an inconclusive functional/latency verdict, not a pass. Incomplete evidence gives an inconclusive corresponding verdict; do not convert missing samples into success.

## Decision after the measurement

- **All pass:** make no optimization. Freeze this as the sustained native-number baseline.
- **Evidence failure:** fix only collection/evidence mechanics and rerun the same build/window protocol.
- **Capture/inference or admitted-gap failure:** inspect per-pass timings and the fixed eight-job schedule; choose one minimal scheduler/batch change in a follow-up patch. Do not loosen leases/floors or hide unsupported intervals.
- **Emit-to-ingest failure:** profile supervisor/feed work before changing transport.
- **Ingest-to-API or API-to-DOM failure:** profile snapshot construction/browser normalization before considering push transport or payload changes.

Any follow-up production change gets its own regression tests, full validation baseline, new binary identity, and a new sustained run under this same frozen protocol. Never relabel the old session as the new build's result.

Write the verdict and exact evidence paths to `.local/laya/train/native-freshness-STAMP/RECEIPT.md`; leave tracked documentation unchanged in this packet.
