# Plan of attack — seated admission, then Phase 4b Gate F

**Goal.** Move from "the emission defect is fixed and a valid receipt is obtainable" (already true,
HEAD `11407bee`) to "the live observer actually admits observations while the operator sits at a
table", then — and only then — make progress on the Phase 4b recognition gate that is the real
blocker (Gate F board accuracy).

**Definition of done for this plan.**
1. The reason `ActivityGate` never left `verifying` in session `2912b458…` is *measured and
   reported*, with a stated verdict among: static tracked regions / flicker+reset / capability gap /
   bug — and no gate was changed to reach it.
2. At least one live session at this revision reaches `activity_state: active` and emits `history`,
   with its receipts verified (bounded and sustained).
3. The diagnostics trim is re-measured on an activating session and recorded in
   `.local/preflight/PHASE2-RECEIPT.md`, replacing the currently-flagged unverified figure.
4. `it2_gatef.py` records every input path and either consumes `--labels` as a fail-closed
   cross-check or drops it; the report is re-run and its fail-closed rules are intact.
5. Gate F's blockers are stated as an inventory with an explicit list of operator-only actions.

**Non-negotiable constraints (any green result obtained by breaking one of these is a task failure).**
- No gate is loosened: not the activity gate, the admission gate (`quality_approved`), the receipt
  gate, the label/training gates. `ActivityGate` widening is lowering a gate.
- `crates/ingest/assets/laya/question-set.json` stays `{"initial": 0.8, "calibrated": false}`; no
  fitted floor is promoted.
- `MAX_LOG` stays 64 MiB (`scripts/laya_capture.py:40`). Invalid/oversized native records keep
  failing closed.
- Do not touch the browser/DOM boundary, `crates/ingest/src/parser.rs`, or the decision engine.
- No input automation; no table interaction. `it2` GPU training is not started; no advice wiring.
- `.local/` is gitignored — never committed. Commits only for tracked source, tests, docs.
- A session ending with zero `history` records is **inconclusive**, never a pass.

---

## 1. Verified starting state (do not re-derive)

- HEAD `11407bee6f9a23ecd8c73c63397e4155f768853f`, worktree clean, branch
  `checkpoint/seated-read-mechanism-2-20261002`. Do not push.
- Already fixed (do not redo): delta `history` emission (`9969bbd`, `c2da3f9`), `MAX_LOG` 64 MiB
  (`6e2d16d`), diagnostics trim (`2de01d2`), `receipt_complete` semantics (`bd8c796`). Frozen A4
  identity in `.local/preflight/PHASE2-RECEIPT.md`.
- Shell constraints: PowerShell 5.1, no `&&`, no `|`, no `;`, no `$( )`, no `>`/`<`. `touch`,
  `head`, `wc`, `grep`, `python` are **not** invocable in this shell. Use `.local/laya-runtime/env/python.exe`
  from a script file, `jq -s -f <program.jq> <file>` (program files, not shell pipes), and
  `rg -c -e <pattern> <file>` / `rg --count-matches -o -e <pattern> <file>`. Note: PowerShell strips
  `"` from native-command arguments, so **no jq program may be passed inline** — put it in a file.
- Private helpers to reuse (do not invent new instrumentation): `.local/analysis/stdout-bytes.jq`,
  `receipt-fields.jq`, `last-record.jq`, `diag-parts.jq`, `diag-shape.jq`, `dashboard-history.jq`.

### 1.1 Measured today: the gate's own session

Session `2912b4589da44b519fbee7bf7a7b9988` (171 s, 275 frames, `automatic-bounded`,
`activity_state: verifying` for the whole run). `stdout.jsonl` = 603 records:

| event | count |
|---|---|
| `manual_capture` (progress) | 276 |
| `capture_health` | 136 |
| `perception_diagnostics` | 121 |
| `partial_observation` | 55 |
| `partial_observation_invalidated` | 13 |
| `status` | **1** |
| `observation_invalidated` | 1 |
| `history` | **0** |

The single `status` record is the startup `activity_status()` emit; every later `Status` event is
suppressed by `bin/manual_inference.rs:624-631` while `!active`. Contrast the two same-day sessions
that did activate on this table and this decision path: `643b5049…` (600 s) 830 `history` / 2281
`status`; `01e5cbfc…` (372 s) 517 `history` / 1454 `status`. **`status` count is therefore a usable
activation proxy, and 1 means no activation ever occurred.**

Diagnostics reason census for `2912b458…` (occurrences, over 121 records): `source-region-changed`
419, `occluded` 330, `below-floor` 88, `awaiting-consensus` 66, `pass-unavailable` present in all
121, `missing-source-witness` **0**. Both `reason` and `admission_reason` are counted, so ~6/record
split ~3.4/2.7 — i.e. the three whole-frame fields (`role`, `hero_seated`, `game_phase`, bound to the
`p0` whole-window witness) account for essentially all of it. `missing-source-witness` = 0 proves
frame binding succeeded, so this is not a bind failure.

### 1.2 Two prompt premises are wrong in the code — correct them in the report

1. **`stdout.jsonl` does not contain region digests.** `rg -c -e digest` and `-e witness` over the
   session stream return 0; `sha256` matches (330) are only frame/PNG receipt hashes. `TableContentWitness`
   is deliberately non-serialisable and its `Debug` is `<in-memory>` (`crates/ingest/src/partial.rs:578-604`,
   `606-620`). The gate's inputs are therefore **not journaled anywhere** — `manual_capture`
   progress carries only `activity_state` / `activity_reason` (`bin/manual_inference.rs:302-327`).
   This is itself a finding: item A cannot be closed from logs alone, which is why §2.1 replays the
   recorded pixels instead.
2. **The tracked crop bounds are recoverable.** `readouts.jsonl` / `perception.jsonl` carry the live
   `crop_bounds` actually used at 957x727 (e.g. `p3_pot` `[[382,260,613,289]]`, `p5_seat_1_stack`
   `[[416,169,542,195]]`, `p0_full` `[[0,0,957,727]]`). Use these, not re-derived geometry, so the
   replay hashes exactly the rectangles the witness hashed.

### 1.3 Theme is no longer a gap

`.local/laya/probe/phase0b-20261025/PHASE0B-RECEIPT.md` §3: felt green fraction `0.781 / 0.792 /
1.000` — the current client renders **green felt**, the 2026-10-13 "near-black" was the glitch.
`.local/laya/dataset/it2-baseline/PHASE4B-READINESS.md:51-54` still says "no local dataset contains
the near-black rendering the client shows now"; that statement is **superseded** and must be
corrected in `.local/` evidence so item E is not planned against a stale premise. The real corpus
gaps are **geometry** (957x727/958x728 is not in the frozen set) and **seated content**.

---

## 2. Task A — diagnose the activity gate (measure first; change nothing)

### 2.1 A1. Offline replay of the recorded pixels (primary measurement — no source change, no live run)

The session recorded 275 PNGs plus `manifest.jsonl` in
`.local/captures/utc-1792967636-765427900-practice/`. Write one private script
`.local/analysis/activity-crop-replay.py` that:

1. reads the per-region `crop_bounds` at 957x727 from
   `.local/laya/manual-capture/2912b458…/{readouts.jsonl,perception.jsonl}` (union over records;
   `board_slot_*` from any `p2_board` pass, `pot` from `p3_pot`, `seat_*_stack` from `p5_*`);
2. walks `.local/captures/utc-1792967636-765427900-practice/manifest.jsonl` in `frame_index` order,
   verifies each PNG's `sha256` against the manifest, and SHA-256-digests the raw bytes of each of
   the 12 tracked crops per frame (same rectangles, same raw-bytes rule as
   `region_digest`, `crates/ingest/src/partial.rs:628-647`);
3. reports per region: distinct digests, count of change events, first change (frame + elapsed s),
   longest run of identical digests, and whether it ever satisfied the gate's precondition
   (two consecutive identical, then a change); plus the whole-window verdict "did any of the 12 ever
   change", and the count of frames byte-identical to their predecessor.

**Stated approximation (put this in the report).** The live witness compares the *bound analyzed*
frame with the *latest* frame (`bin/manual_inference.rs:583-595`, `crates/ingest/src/runtime.rs:1010-1017`),
one sample per inference completion (~1.6 completions/s, 121 completions here). The replay compares
consecutive recorded frames. So: replay showing **zero** crop changes is decisive (the live witness
cannot have seen one); replay showing changes bounds the question further and needs the sample
cadence to decide, which §2.3 supplies if needed.

Corroborating (cheap): a `.local/analysis/partial-values.jq` program that projects the 55
`partial_observation` records' `verified_fields`, `pot_size`, and `seats[*].displayed_stack`. A
constant accepted value across all 55 admissions is supporting evidence that the tracked regions
were static; a changing value rules static out immediately.

### 2.2 A2. Decision rule (state the verdict explicitly before any code change)

| Observed | Verdict | Action |
|---|---|---|
| ≤1 distinct digest for every one of the 12 crops, whole window | **static tracked regions** (cause b) — the gate correctly refused a static/foreign surface | No code change. Record A as a *correct refusal*. The gate is not to be widened; the operating condition must change (a table with real action, or the seated phase). |
| Crops change, but replay shows no run of two consecutive identical samples per changed region | **baseline flicker / no stable pair** (cause a) | Report measured cause. Fix only if it is a genuine defect (see §2.3); cadence or sampling must be characterised, never the gate threshold. |
| Crops change and stable pairs exist, yet the gate stayed `verifying` | **bug or sampling starvation** (cause d) | Escalate to §2.3 instrumentation, then a targeted Rust test reproducing the gate against the replayed digest sequence. |
| Zero `core_accepted` witnesses were ever producible | capability gap (cause c) | Already contradicted (55 admitted partials; 0 `missing-source-witness`). If replay contradicts, treat the gap as the finding and stop. |

Do **not** proceed to §2.3 unless §2.1 lands in row 2 or 3, and do not change `ActivityGate`
semantics under any row.

### 2.3 A3. Conditional instrumentation (only if A1 is ambiguous)

Add a private, **digest-free, transition-only** diagnostic to **stderr** (the channel already used for
`{"event":"inference-recovery",…}` at `bin/manual_inference.rs:609-613`; stderr is privately captured
and accounted in `run.json` `diagnostic_streams.stderr`, cadence-unaffected). Emit one line **on
transition only** — first witness, `repeats` reaching 2, a region change observed, and each reset
reason (`witness-none`, `stale-age`, `identity/epoch`, `geometry`) — with counts and booleans, never
digests. This is additive instrumentation, not a gate change; it must not alter
`activity_state`/`activity_reason` or any DTO. Because it touches tracked Rust, the full §6 baseline
must run, and the change must keep `receipt_complete` achievable (bounded lines, complete lines).

### 2.4 A4. Report

Write the measured cause and verdict to `.local/preflight/PHASE2-RECEIPT.md` (new section
"Activity gate diagnosis") with the replay artifact path and the raw numbers. If the verdict is
"correct refusal", say so plainly and note that the earlier same-revision sessions activated, so the
gate is functioning and the variable is table dynamism during the window.

---

## 3. Task B — re-measure the diagnostics trim on an *activating* session

Prerequisite: a bounded run that actually reaches `active` (§5 logistics). If it does not, report it
as inconclusive and retry; do not record a number from a `verifying` session.

1. Run the bounded launcher (§5). Confirm from `stdout.jsonl` that `history` count > 0 **and** at
   least one `manual_capture` record shows `activity_state: active`; capture that transition's
   `elapsed_ms`.
2. Record: `jq -s -f .local/analysis/stdout-bytes.jq <stdout.jsonl>` — per-event count/bytes/max;
   `receipt-fields.jq` over `run.json`; `last-record.jq` over the stream.
3. Re-measure the trimmed `perception_diagnostics` payload **and** the `history` path together —
   average/max bytes per diagnostics record, plus `history` count/bytes, on this activating session.
   Compare against the `2912b458` (trimmed, verifying) and `643b5049` (untrimmed) columns already in
   `PHASE2-RECEIPT.md`.
4. Update `.local/preflight/PHASE2-RECEIPT.md`: move the "trimmed payload measured only on a
   `verifying` session" bullet out of *Not verified under this revision*, replacing it with the new
   table row and the session id. Do not restate the old -33 % figure as validated until it is
   re-derived here.

---

## 4. Task C — one sustained (`-ContinuousObservation`) run at this revision

Still untested live, so the `len(pipes) == 2` accounting and the sustained drain in
`scripts/laya_capture.py:725-733`, `831-860`, `900-906` are unexercised.

1. Confirm port 18090 is free and stop any background launcher first (§5).
2. Run the sustained launcher. Let it run long enough to exercise the drain (a manual `STOP` file is
   fine; it is the session-scoped stop).
3. Verify, and record:
   - `run.json` via `receipt-fields.jq`: `receipt_complete`, `forced_stop`, `stop_acknowledged`,
     `stop_reason`, `diagnostics_complete`, `exit_code`, and
     `diagnostic_streams.{stdout,stderr}.{bytes_seen,bytes_dropped,truncated,accounting_complete,cap_bytes,cap_exceeded}`.
   - the sustained branch actually taken: `len(pipes) == 2`, no `pipe.failed`, and
     `accounting_complete` not forced false by `(not sustained or len(pipes) == 2 …)` at line 905-906.
   - cap behaviour: `bytes_seen` vs 67108864, `cap_exceeded` false, no dropped bytes; and that
     `history` suppression at the cap still holds (`manual_inference.rs:433-442`) without inventing a
     pass.
   - `visual_frame`/`live_frame` fields present in the sustained stream (they are sustained-only,
     `manual_inference.rs:426-432`, `705-714`).
4. Append a "Sustained run" row to `.local/preflight/PHASE2-RECEIPT.md` and remove the corresponding
   bullet from *Not verified under this revision*.

---

## 5. Live-run logistics (shared by B and C)

- Bounded: `pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -PracticeConfig .local/practice-table.json`.
- Sustained: the same plus `-ContinuousObservation -ManualStart`.
- Free port 18090 first (the launcher refuses if occupied); stop the background launcher between runs.
- Stop = create a `STOP` file **with the editor tool** in the session directory (`touch` does not exist).
- To make B possible the operator must be watching a table where cards are actually being dealt; an
  empty/wait-list surface is the leading explanation for `2912b458` (see §2.2). The operator acts
  manually — nothing in the repo drives the table.
- Seated hero/control frames cannot exist while spectating (`Join Wait List` / `Find Seat` on screen),
  so neither B nor C can move the Gate F hero criterion. Only §7's operator actions can.

---

## 6. Validation baseline

Run the full baseline **only after a tracked-source change** (i.e. §2.3 instrumentation, a §2.2-row-3
fix, or any `docs/` edit is fine to run it too; `.local/` script edits do not require it):

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-targets --all-features --locked
& .local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests
& .local/laya-runtime/env/python.exe -B scripts/validate.py --output-dir ".local/validation/$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
& C:/Users/cld-main/AppData/Local/Temp/kilo/readiness-browser-env-20261015/Scripts/python.exe -B scripts/browser_smoke.py --channel msedge
pwsh -NoProfile -File download-model.ps1 -Verify
```

Never substitute synthetic results for live ones.

---

## 7. Task D — fix the `it2_gatef.py` provenance defect, then re-run

`it2_gatef.py` (`.local/laya/train/it2_gatef.py`, gitignored) records `--raw` and `--calibration` but
not `--labels` (`:129-130`), and `by_number` (`:127`) is dead — correctness comes from the dump's own
`label` field.

1. Record **every** input in the report with its sha256: `inputs: {raw, calibration, labels}` each as
   `{path, sha256}` (do not only echo the CLI strings).
2. Consume `--labels` as a fail-closed cross-check (preferred) rather than deleting it:
   - dump rows are `{frame, pass, qid, type, keys, logits, label}` where `frame` is
     `.local/captures/<session>/frame-<N:010>.png` (`it2_dump.py:79-80`);
   - map `(session_id from the dir name, frame number N)` to the labels entry with matching
     `number`/`session_id` in `labels-adjudicated.json`;
   - compare per qid: `screen_kind` ↔ `screen`, `board_slot_i` rank/suit ↔ `board[i-1]`,
     `pot_size` ↔ `pot`, `seats.i.displayed_stack` ↔ `stacks[i-1]`; skip `null` labels.
   - report `label_cross_check: {compared, matched, mismatched, unmatched}` and force
     `result: FAIL` if `mismatched > 0` or if the cross-check could not be completed.
   - If the mapping proves genuinely ambiguous, **drop `--labels`** and record the removal in the
     report; never keep an input that is loaded but unused.
3. Keep the fail-closed rules byte-for-byte: `measure()` (zero confident units → `FAIL`; no items →
   `INCOMPLETE`), `gate_block()` (`MEASURED` required for a pass), `hero_cards` (`UNMEASURED` when no
   labeled hero units), and the final `all(gates)` conjunction.
4. Re-run:
   ```powershell
   .local/laya-runtime/env/python.exe -B .local/laya/train/it2_gatef.py `
     --raw .local/laya/dataset/it2-baseline/raw-it1-heldout.json `
     --calibration models/laya-vision/finetuned/20261009T190322Z-it1/calibration.json `
     --labels .local/laya/datasets/observing-20261010-v2-staging/human-review-20261025/labels-adjudicated.json `
     --out .local/laya/dataset/it2-baseline/gatef-it1-heldout-<UTC>.json
   ```
   Expect the same FAIL verdict and byte-identical criteria; anything else means the harness changed
   behaviour, which must be explained, not accepted.
5. Append a "harnes provenance" note and the new report path to
   `.local/laya/dataset/it2-baseline/PHASE4B-GATEF-*.md` conventions already in use. Because the
   script is gitignored, no commit and no Rust baseline are required.

---

## 8. Task E — Gate F: what would unblock it, and the inventory the live sessions just gave us

### 8.1 Standing result (do not re-run to change it)

`.local/laya/dataset/it2-baseline/PHASE4B-GATEF-20261025T2218Z.md`: **FAIL**. Board raw accuracy
**0.40** over 30 units, 0 admitted at the fitted threshold 1.0; hero cards UNMEASURED; screen
precision 1.00 at coverage 0.875; worst p95 776.1 ms. **Latency is not the blocker** (776 ms is far
inside the 5 s budget); board accuracy is. The earlier root cause stands
(`human-review-20261025/PHASE3-RECEIPT.md` §4): calibration fixes confidence, not accuracy; it2
retraining is the only path.

### 8.2 Inventory today's captures against the frozen set

Enumerate the 2026-10-25 `.local/captures/utc-*` dirs (489, 836, 1050, 655, 275 frames) and, for
each: PNG count; **verified** geometry from the PNG headers (do not assume — `PHASE0B-RECEIPT.md` §1
records 958x728 while later sessions report 957x727; the discrepancy must be resolved, not smoothed);
felt green fraction using the frozen set's method (`felt.py`: crop 30-70 % x 34-58 %, green
fraction); count of frames with a visible board; count of frames with seated hero/control content
(expected 0).

| Frozen 72-frame set | Today's captures |
|---|---|
| 900x686 (16), 879x670/800x613 (48), 1280x778 (8) | 957x727 (or 958x728 — verify) |
| green felt 0.85-0.95 | green felt (same family) |
| 82 board positives / 21 frames; seated hero: none | board positives only if hands were dealt in-window |

**Plain statement to put in the report:** these frames can seed a **current-geometry** corpus
(board/pot/stack at the live window size) at the **same theme**, and are a distribution control for
the stale-geometry frozen set. They **cannot** seed a "current-theme" corpus in the sense of
`PHASE4B-READINESS.md:51-54`, because that premise is superseded — the current theme *is* the green
felt already in the frozen set (§1.3). Correct that sentence in `.local/` evidence.

Dashboard context for the byte/volume story only: `.local/analysis/dashboard-history.jq`.

### 8.3 What still requires the operator (human-only, cannot be inferred)

1. **Seated session.** Hero cards and action controls cannot exist while spectating. Gate F's hero
   criterion is unreachable until a session is run while seated in a hand, and the frozen set's
   `hero_cards: available_crops: 0` (`spot-check/board-pack.json:204-208`) stays at 0 until then.
2. **The 20-crop spot check** — `.local/laya/datasets/observing-20261010-v2-staging/human-review-20261025/spot-check/board-pack.json`
   (20 board crops; contact sheet alongside). This is a human judgement call and the cheapest gate to
   clear for `training_eligible`; it must not be inferred or auto-filled. Reply with any wrong spot
   numbers (omitted spots are unverified, per the pack's own instruction).
3. **Verified region boxes at the new geometry.** `it2_build.py regions` output is
   `agent_proposed_unverified` and stack-text boxes are estimates
   (`PHASE4B-READINESS.md:11`, `:57-58`); Gate F's amount/stack criteria cannot be measured until the
   board/pot/stack regions are established from a captured frame and verified.

### 8.4 Precisely what unblocks Gate F

- Board: a retrained it2 on a current-geometry corpus that reaches ≥0.99 precision at ≥0.85
  coverage, then a fresh Gate F pass. Data, not calibration.
- Hero: ≥1 seated session with labeled hero-card units, so the criterion becomes measurable at all.
- `training_eligible`: the 20-crop spot check passing.
- Only after a real Gate F pass may `thresholds.calibrated` be promoted / a fitted floor written.
  That remains out of scope here.

---

## 9. Order of operations

1. A1/A2 (offline replay + verdict) — no live run needed; do this first.
2. B (bounded live run) while the operator is watching a table with deals in progress; if it does not
   activate, record inconclusive and repeat once.
3. C (sustained live run).
4. D (harness fix + re-run) — parallelisable with 2/3; no live run needed.
5. E inventory + the operator-ask list; only then start planning 4b work (out of scope here).
6. A3/A4 only if A2 lands in row 2 or 3 of the decision table.

## 10. Risks and stop conditions

- **Widening `ActivityGate` to force `active`.** Hard stop; that is gate loosening. If A1 says
  static, the correct output is the finding, not a code change.
- **Reporting a `verifying` session as a pass for B or C.** Hard stop; such a session proves nothing
  about the emission path.
- **Inferring the 20-crop spot check or the hero labels.** Hard stop; both are human judgements.
- **Raising the cap, promoting a floor, or flipping `thresholds.calibrated` to make a run or gate
  look green.** Hard stop.
- **Adding regressions to tracked Rust** while instrumenting A3: run the §6 baseline and keep
  `receipt_complete` achievable.
- Environment traps: PowerShell quote-stripping breaks inline jq programs; `|`, `;`, `$( )`,
  redirects are policy-blocked; `head`/`wc`/`grep`/`python` are absent from the shell.

## 11. Open questions (recommended answer given)

1. **Should A3 stderr instrumentation be added pre-emptively for the B run, in case B's live session
   also fails to activate?** Recommended: no — do A1's offline replay first; it is a strict subset of
   what A3 would tell us and needs no source change. Add A3 only if A1 is ambiguous or if B once
   again fails to activate and A1 could not settle it.
2. **Which session should B be run against to maximise the chance of activation?** Recommended: the
   same six-max table while an actual hand is in progress (that is what distinguishes `643b5049`/`01e5cbfc`
   from `2912b458`); a longer bounded window is preferable to a second short one.
3. **If A2 says "static tracked regions", is anything else required for this plan?** Recommended: no
   code change — record the finding, proceed to B/C, and treat "a table with live action" as the
   precondition for any future seated admission measurement.
