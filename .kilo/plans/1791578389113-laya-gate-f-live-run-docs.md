# Plan — coinpoker-help: finish Laya Gate F, live run, docs (continuation)

Planned 2026-10-09T20:40-21:05Z from the handoff prompt and a read of the repo. Execute in order; stop only where a gate fails. Keep cost low: no new workstreams, no iteration 2-3 without user approval.

## 0. Rules (unchanged, verbatim from the handoff)

- Repo `C:\Users\cld-main\Desktop\github-projects\coinpoker-help`, branch `checkpoint/seated-read-mechanism-2-20261002`, HEAD `4ccad18`. Everything is uncommitted; keep it. The user commits.
- Windows PowerShell 5.1: `>` writes UTF-16, so write files from Python; no heredocs. The bash tool in these sessions denies `;`, `|`, `>`, `&`; run long/compound commands through `desktop-commander_start_process` (one command per call) or a small Python helper under `.local/`.
- Python env `.local\laya-runtime\env\python.exe` (call it `$PY` below). `evaluate.py` sets `HF_HOME`/`HF_HUB_OFFLINE` itself; `start-vlm.ps1` sets them for the server. For anything else set `HF_HOME=models\laya-vision\hf`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_VERBOSITY=error`; capture stderr to a file.
- Not authorized: commits, pushes, uploads, release/workflow changes, client input, new `.ps1` files in the repo, pixels outside `.local/captures`.
- Gemma server PID 24812 stays stopped. Do not restart it.
- Gate rule: never reach a gate by lowering thresholds, relaxing assembly rules or repairing answers.
- Read first: `.local/laya/research/RESEARCH.md` §6, `.local/laya/rust-spec.md`, `.local/laya/question-set.json` → `assembly_rules` R1-R19.
- MemPalace MCP is not configured in this session; no palace search was possible. Note that in the addendum.

## 1. Facts verified against the repo that change the handoff text

| Handoff assumption | Verified reality |
|---|---|
| "Start the server after filling in the pins" | `scripts/laya-server.py serve` runs `verify(pins)` first and **exits 2** while `model.finetuned` is absent (`laya-server.py:352-354`). `doctor.py` `model_files_sha256` also fails without it (`doctor.py:125-127`). Pins must be filled before any server step. |
| `validate_phase_a.py` | Lives at `.local/laya/validate_phase_a.py` (not `scripts/`). It re-vendors `crates/ingest/assets/laya/{question-set,regions}.json` from `.local/laya/question-set.json`, requires `version` `0.4.*`, `thresholds.calibrated` bool, `thresholds.per_pass` dict, pass `calibration` in `trained/untrained_provisional/calibrated`, and `dataset/regions-<version>.json` (so keep version `0.4.0`). |
| `evaluate.py dump/fit/score` | CLI: `cmd --ckpt DIR [--split S] [--frames FILE]`. Outputs go **into the checkpoint dir**: `raw-<split>.json`, `laya-calibration.json` (temperatures, loadable by the server), `calibration.json` (per-metric thresholds), `score-<split>.json` / `score-<split>-verified.json`. `fit` reads `raw-calib.json` only. `--frames` is a JSON list of frame paths. |
| raw-eval.json | Does not exist. `raw-calib.json` exists in `models/laya-vision/finetuned/20261009T190322Z-it1/`. No fit/score outputs exist. `examples/late.jsonl` exists (407 frames). |
| `run-timed.ps1` | Only copy is `.local/acceptance/20261009T061624Z-starvation/run-timed.ps1` (needs `pwsh` 7, present at `...\WindowsApps\pwsh.EXE`); lines 21-22 still carry Gemma endpoint/model. Copying it under `.local/acceptance/<UTC>-laya/` is explicitly authorized by the handoff (not a repo script). |
| `bench_server.py` | Arg is an integer N (last N table frames of the manifest) or a JSON list; hits `127.0.0.1:18090`; prints `{p0,tier01,battery:{n,p50,p95}}`; "warm" = first two frames discarded. |
| Rust tests | Three tests assert the uncalibrated state and will fail once `calibrated:true` is vendored: `crates/ingest/src/laya/questions.rs:186`, `crates/ingest/src/laya.rs:141`, `bin/live.rs:383`. |
| Lobby | `.local/captures/20261009T170508Z-laya-train/lobby/` exists and is empty. `manifest.jsonl` has no `source` key and no lobby lines. `build_examples.py` puts every `role: lobby` label into **train** (lines 107-132), so the user screengrab must never enter `labels.jsonl`, and `build_examples.py` must not be re-run (it would rewrite `train.jsonl`). |
| `scripts/vlm-pins.json` | Orphaned (nothing reads it) but listed in `.github/workflows/release-windows.yml:73`; removing it is a workflow change → keep it, document as history (decision D1 of the earlier plan). |
| `.local/validation/report.json` | Last run: 12 checks, `rust_tests_passed: 303`, pwsh available. |

## 2. Decisions (confirmed with the user 2026-10-09T21:00Z)

- **D-A Gate F scoring is pass-level.** Per-pass threshold = max of the fitted per-metric thresholds of the metrics that pass consumes on the unseated path; every metric is scored at its pass threshold (raise only, never lower).
  - `p0_full` ← max over `screen_kind`, `game_phase`, `p0:ev_table_layout`, `p0:ev_hero_cards`, `p0:ev_board_area`, `p0:ev_pot`, `p0:ev_action_controls`, `p0:ev_readable`, `p0:ev_seat_controls`, `p0:hero_seat_index`, `p0:action_on_hero`.
  - `p2_board` ← `card:p2_board`; `p3_pot` ← `amount:pot`; `p5_seat_1..6_stack` ← `amount:seat_stack`.
- **D-B `thresholds.calibrated:true` requires**, on the human-verified eval rows: `screen_kind` precision ≥ 0.98 and coverage ≥ 0.95; `game_phase` and the nine p0 path questions precision ≥ 0.98 (coverage reported, not gated); `card:p2_board` ≥ 0.99 / ≥ 0.85; `amount:pot` ≥ 0.99 / ≥ 0.85; `bench_server.py` p95 < 2000 ms for p0, tier01 and battery. `precision: None` (no confident items) is a fail.
- **D-C p5 seat stacks are non-blocking** (tier 2 never runs in 0.4.0, R16): fitted and scored; if `amount:seat_stack` misses 0.99/0.85 the six p5 passes keep `calibration: "trained"` and the miss is recorded.
- **D-D Late split is a drift check**: scored and reported; if a gated metric misses its precision target on `late`, do not set `calibrated:true` without explicit user approval (report both tables and ask).
- **D-E Unverified branch** (user declines the checklist): no `calibrated:true`, question set untouched; the live run passes `--laya-threshold T` with `T = min(0.99, max(per_pass[p0_full], per_pass[p2_board], per_pass[p3_pot]))` so it runs at the fitted thresholds (raising only). Record T.
- **D-F Seated gap wording** (user, 2026-10-09): seated play is one mechanism for practice and cash tables alike; the only difference is the currency displayed. Never describe a "practice-mode" variant. The gap is "seated passes have no training data"; its follow-up is "seated captures + seated passes", user-approved, separate session.
- **D-G Gate F failure** (step 4): report the table, write the records (addendum 10, `LAYA_VISION_PHASE_A.md` §7 status, pins `status` string), skip steps 5-6 and the remaining docs, stop. Human-check declined ≠ failure: continue with D-E.
- **D-H Question set version stays `0.4.0`** (Rust asserts it; `regions-0.4.0.json` is keyed by it). Provenance of the fit goes into `calibration.json` and the addendum, not into new question-set keys.
- **D-I No live spot-check captures** (cost): live precision is not separately measured; Gate F eval/late plus the answers log are the evidence. Record as a gap.

## 3. Tasks, in order

Record the UTC start/end of every task for addendum 10 (`Get-Date -AsUtc` or Python `datetime.now(timezone.utc)`).

### T1. Lobby screengrab import (eval-only)
1. `Copy-Item lobby-screengrab.png .local\captures\20261009T170508Z-laya-train\lobby\lobby-user-screengrab.png`.
2. Python helper `.local/laya/dataset/add_lobby_eval.py` (new, under `.local`): read the PNG size/sha256/bytes; append to `manifest.jsonl`: `{"file": ".local/captures/20261009T170508Z-laya-train/lobby/lobby-user-screengrab.png", "role": "lobby", "source": "user-screengrab", "use": "eval-only", "utc": "<import ISO ms Z>", "captured_at_unix_ms": null, "width": W, "height": H, "window": null, "hwnd": null, "sha256": "...", "bytes": N}`; add `"<file>": "eval"` to `splits.json`; append 8 `p0_full` rows to `examples/eval.jsonl` built like `build_examples.py` `rec()` with `split: "eval"`, `dataset: "lobby"`, labels `screen_kind: lobby`, `ev_table_layout/ev_board_area/ev_pot/ev_hero_cards/ev_action_controls/ev_seat_controls: false`, `ev_readable: true` (label index via the vendored question set, as `label_index()` does).
3. Do **not** touch `labels.jsonl`; do **not** run `build_examples.py`.
4. Record W×H. If it is not 1280x778, note that it does not validate R18's `--lobby-size`.
5. Tell the user (final report): delete `lobby-screengrab.png` at the repo root; the agent did not delete it. Lobby eval precision rests on this single frame (the harness lobby capture is train-only).

### T2. Gate F iteration 1 — scoring (GPU, no server running)
Checkpoint `CK = models/laya-vision/finetuned/20261009T190322Z-it1`.
1. Edit `.local/laya/train/evaluate.py` `fit()` after `thresholds` is built (line 111): compute `per_pass` per D-A (missing metric → 1.0), then for every metric key that is `screen_kind`, `game_phase` or starts with `p0:` set `thresholds[m] = max(thresholds[m], per_pass["p0_full"])`; store `out["thresholds_per_pass"] = per_pass` and `out["path_metrics"]` (the list). No other behaviour change. `score` needs no change (it reads `cal["thresholds"]`).
2. `$PY .local\laya\train\evaluate.py dump --ckpt $CK --split eval` (after T1) → `CK/raw-eval.json`.
3. `$PY .local\laya\train\evaluate.py dump --ckpt $CK --split late` → `CK/raw-late.json` (407 frames; longest step).
4. `$PY .local\laya\train\evaluate.py fit --ckpt $CK` → `CK/laya-calibration.json`, `CK/calibration.json`. Record temperatures, per-metric and per-pass thresholds. Any per-pass value of 1.0 means "never confident" and is reported as such; never edit it down.
5. `score --ckpt $CK --split calib`, `--split eval`, `--split late` → `score-*.json`. Build the table: metric, threshold, n, coverage, precision, errors_confident, raw_accuracy, plus `latency_ms` medians.
6. Do not run the server while dumps run (8 GiB GPU; peak train was 4.96 GiB).

### T3. Pins, server, latency bench
1. Python helper `.local/laya/train/pin_finetuned.py`: load `scripts/laya-pins.json`; set `model.finetuned = {"path": "models/laya-vision/finetuned/20261009T190322Z-it1", "run_log": ".local/laya/train/run-20261009T190322Z-it1.json", "init": "thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc", "train_data_sha256": "c6e8c99be0f70b0792766343cc002bdd783aeb68729758079cc690b3945e55a4", "train_data_sha256_note": "hashed after train.jsonl changed by ~2 examples; train.py now hashes at start", "calibration_file": "laya-calibration.json", "files": [...]}` where `files` = `{path,size,sha256}` for `model.safetensors`, `vlm_agent_config.json`, `laya-calibration.json`, every file under `backbone/` and `processor/` (computed now, after T2.4; exclude `raw-*.json`, `calibration.json`, `score-*.json`, `train-log.json`). Set `server.dtype: "bf16"`, `server.batch_size: 32`, `server.implemented: true`. Replace `status` with the current state (fine-tuned it1 wired; gate result filled in after T5). Extend `license.weights` with the fine-tuned derivative (same CC-BY-NC-SA-4.0, trained on private captures, never redistributed). Write with `json.dump(..., indent=2, ensure_ascii=False)` + trailing newline. Expected sha256 of `model.safetensors` is `84c008b976e72445ae07c58678af542b63f79548ad0a314f836f210bda3195a1` (run log); verify it matches.
2. `$PY scripts\laya-server.py verify` → exit 0.
3. Start the server in the background: `powershell -NoProfile -File scripts\start-vlm.ps1` (foreground script; use `desktop-commander_start_process`). Wait for the `{"event":"ready",...}` line; record `warmup_ms`. Check `GET http://127.0.0.1:18090/v1/models` reports `calibrated: true` in `meta`.
4. `$PY .local\laya\train\bench_server.py 30` → record p50/p95 for p0, tier01, battery (n=28 warm). Gate value is p95 < 2000 ms each.
5. Run `$PY -m unittest discover -s scripts/tests -v` (16 + doctor tests) to confirm the pins change breaks nothing.

### T4. Human check (ask once)
1. Use the question tool once. Present `.local/laya/dataset/human-check/checklist.md` (66 rows; frames under `.local/captures/20261009T170508Z-laya-train/table/`) and the unverified eval table from T2.5. Options: (a) "All 66 rows correct as listed" (plus confirm amounts use `.` as decimal point); (b) corrections in the checklist's format (`12: pot 1.25; board 9♥ not 9♦`, `n: unsure`); (c) decline → Gate F reported unverified (D-E).
2. If corrections: Python helper `.local/laya/dataset/apply_corrections.py` that takes the corrections JSON and updates, consistently, `labels.jsonl`, `examples/eval.jsonl` and `CK/raw-eval.json` `label` fields for those frames only (board: slot rank/suit; pot/stack text: 1:1 onto `g1..gn`; a text whose length differs from the segmented `n` → treat the frame as `unsure`). Never touch `train.jsonl`. Log every change to `human-check/corrections-<UTC>.json`.
3. Verified frame list = the 66 sample files (`human-check/sample.json`) minus `unsure` rows → `human-check/verified-frames.json` (JSON list of frame paths as they appear in `eval.jsonl`). Add the lobby screengrab path to the list (it is user-provided ground truth).
4. `score --ckpt $CK --split eval --frames .local/laya/dataset/human-check/verified-frames.json` → `CK/score-eval-verified.json`. This is the Gate F table.

### T5. Gate F decision
- PASS iff D-B holds on `score-eval-verified.json` and the bench; D-C/D-D apply. Otherwise FAIL (D-G) or UNVERIFIED (declined, D-E).
- On PASS:
  1. `.local/laya/question-set.json`: `thresholds.calibrated: true`; `thresholds.per_pass` = the 14 fitted per-pass values that exist (p0_full, p2_board, p3_pot, p5_seat_1..6; untrained passes are omitted and keep `initial_threshold` 0.8); `calibration: "calibrated"` on `p0_full`, `p2_board`, `p3_pot`, and on the p5 passes only if `amount:seat_stack` met its target. Leave p1/p3_to_call/p3_hero_chips/p4_* as `untrained_provisional` (R17 unchanged). Edit from Python.
  2. `$PY .local\laya\validate_phase_a.py` → `PHASE A VALIDATION PASSED`; this re-vendors `crates/ingest/assets/laya/question-set.json` (+ regions).
  3. Flip the three assertions to the shipped state: `questions.rs:186` → `assert!(set.thresholds.calibrated);`, `laya.rs:141` → `assert!(calibrated());`, `live.rs:383` → `assert_eq!(event["laya_calibrated"], true);` (comment: encodes the vendored asset state after Gate F). Check `assembly.rs` tests still pass with the raised vendored thresholds (they use p=0.99 for confident answers and `at(0.85)` in `threshold_override_only_raises_pass_thresholds`; if a vendored threshold exceeds 0.85 that test's fixture must use a value above the new threshold, not a lowered threshold).
  4. Restart the server (new vendored thresholds do not affect it, but `/v1/models` `meta.calibrated` reads the pinned calibration; confirm unchanged).
- On FAIL: fill the pins `status`, write records (T8 addendum + `LAYA_VISION_PHASE_A.md` §7 status only), report the table, stop. Iterations 2-3 need user approval.

### T6. Step 7 — validation
1. `python scripts\validate.py` (system Python, as before) → 12/12; record `rust_tests_passed` from `.local/validation/report.json` (was 303 + the `wire_criteria` test).
2. `$PY .local\laya\validate_phase_a.py` → PASS (run again even on the unverified branch; it must still pass unchanged).
3. `cargo build --release --locked` (needed anyway if T5 touched tests).
4. `$PY scripts\doctor.py` with the server up → exit 0; `$PY scripts\doctor.py --offline` → exit 0 (`vlm_models`/`multimodal_api` blocked). Save both reports under `.local/acceptance/<UTC>-laya/doctor-{online,offline}.json`.

### T7. Step 8 — live run (90 s, unseated table, read-only)
Precondition (user action; the agent never sends input to the client): CoinPoker open at a six-max table at a trained size (1015x770 or 800x613), hero **not seated**, for the whole 90 s; the lobby window at its usual 1280x778 may be open. State this to the user before starting and wait for the go-ahead.
1. `RUN = .local/acceptance/<yyyyMMddTHHmmssZ>-laya/`; `Copy-Item` `run-timed.ps1` from the starvation dir into `RUN`; edit lines 21-22 (from Python) to `'--vlm-endpoint', 'http://127.0.0.1:18090/v1/laya/predict', '--vlm-model', 'coinpoker-laya-vision'`; keep `--exe-name CoinPoker.exe --lobby-title CoinPoker --lobby-size 1280x778`.
2. Restart the server with the answers log: `powershell -NoProfile -File scripts\start-vlm.ps1 -AnswersLog <RUN>\answers.jsonl`; wait for `ready`.
3. `pwsh -NoProfile -File <RUN>\run-timed.ps1 -Label laya-unseated -Seconds 90` (+ `-ExtraArgs @('--laya-threshold','<T>')` on the unverified branch, D-E).
4. `python .local\acceptance\analyze.py <RUN> laya-unseated --answers <RUN>\answers.jsonl --out <RUN>\analysis.json`.
5. Success, all of: fresh, schema-valid `poker_table` envelopes with non-null state and `action_required=false`; `nonnull_fraction_of_table` ≥ 0.50; `latency_ms.p95` < 2000; `decisions` = 0; lobby completions (if any) classified `lobby` — if no lobby frame was submitted, say so and cite the screengrab eval instead. Compare with `.local/acceptance/E-reanalysis.json` (28 submissions, 0 table readings).
6. Append the run to `.local/acceptance/evidence-index.md`. Stop the server when done (record the stop time).

### T8. Step 9 — docs and records
All edits must reflect the actual branch outcome (PASS / UNVERIFIED / FAIL) and D-F wording. Concrete edits:
- `docs/LAYA_VISION_PHASE_A.md`: §3 (Laya is the sole backend; Gemma removed; D1-D3), §7 (Phase B wired; fine-tune it1: 1,469 steps, 70 min, loss 1.77→0.04, peak 4.96 GiB; Gate F table; bench latencies; replace "Gemma stays the backend"/"evaluation-only" at 220-221), §8 (seated gap per D-F; currency-glyph risk; lobby eval on 1 frame), §9 (dataset, `train.py`, `evaluate.py`, `bench_server.py`, checkpoint, pins, acceptance run dir).
- `README.md`: 98-100 → endpoint default `http://127.0.0.1:18090/v1/laya/predict`, alias `coinpoker-laya-vision`, drop `--allow-remote-vlm` row, add `--laya-threshold`/`COINPOKER_LAYA_THRESHOLD` (0.80-0.99, raise-only) and `--timeout-secs` default 5; one paragraph: perception = locally fine-tuned Laya Vision, observation-only, seated play gives no advice yet (D-F).
- `docs/INSTALL_WINDOWS.md` §2-3 (lines 40-82): Laya runtime (`setup-windows.ps1` → `.local/laya-runtime/env`; `download-model.ps1` fetches the base checkpoint and verifies the fine-tuned one; `start-vlm.ps1` serves `127.0.0.1:18090`; `curl http://127.0.0.1:18090/v1/models`); line 49 `vlm-pins.json` → `laya-pins.json`; state that fine-tuned weights are produced locally and are not downloadable (gap).
- `docs/VLM_COMPATIBILITY.md`: replace the GGUF/llama.cpp table with base checkpoint, fine-tuned checkpoint, laya code commit, torch/transformers pins from `scripts/laya-pins.json`; wire format `/v1/laya/predict` (criteria as ordered `[label, description]` pairs); loopback only, no redirects, 1 MiB response cap; `scripts/vlm-pins.json` retained as history (release allowlist).
- `docs/WINDOWS_ACCEPTANCE_V1.md`: gate 3 re-baselined (Laya server on 18090, `/v1/models` alias, doctor colour probes, bench warm p50/p95); keep "12 checks", update the Rust test count; gate 8 evidence from the live run; new row/notes for the Laya run dir.
- `docs/EVENTS_V2.md` line 17: `configuration` gains `perception:"laya-vision"`, `question_set_version`, `laya_threshold` (null or value), `laya_calibrated`; cross-check the error-code list (line 73) against `VlmError::code()` in `crates/ingest/src/vlm.rs` (Truncated removed, `invalid-vlm-schema`, `unsupported-model-api`).
- `CONTRIBUTING.md:30-33`: pin consistency now spans `scripts/laya-pins.json`, `download-model.ps1`, `scripts/setup-windows.ps1`, `start-vlm.ps1`, `doctor.py`, `laya-server.py`; dataset/labels/captures under `.local/` stay private.
- `SECURITY.md:13-17`: loopback-only `127.0.0.1:18090`, no remote opt-in exists (`COINPOKER_ALLOW_REMOTE_VLM` removed); the server never logs images; `--answers-log` holds answers and timings only.
- `MODEL_LICENSES.md`: Laya section first (base + fine-tuned `models/laya-vision/finetuned/20261009T190322Z-it1`, sha256s, CC-BY-NC-SA-4.0, derived from the pinned revision, trained on private captures, never redistributed); Gemma table demoted to "historical, removed from the product 2026-10-09; `scripts/vlm-pins.json` kept as history"; fix line 7 (it is no longer the manifest the scripts use).
- `scripts/laya-pins.json` `status` final text.
- **Addendum 10** of `.kilo/plans/1791496776779-repo-readiness-and-next-steps.md` (append after line 481, same heading style as addendum 9): UTC times for every phase of both sessions. Previous-session sources: `1791563661000-laya-finetune-session-prompt.md:3` (16:35Z), capture dir `20261009T170508Z`, first/last `utc` in `manifest.jsonl`, mtimes of `labels-round1..9.json`/`labels.jsonl`/`features.jsonl`/`splits.json`/`examples/*.jsonl` (use `desktop-commander_get_file_info`), smoke runs 18:42:40Z and 18:54:05Z, `TRAIN_CUTOFF_UTC` 18:50:30Z, checklist 19:03Z, it1 19:03:22Z + 70.56 min wall, `raw-calib.json` mtime, handoff 20:40Z. This session: planning 20:39-21:05Z, then each task's recorded times. Include: Gate F table (calib/eval/eval-verified/late), per-pass thresholds, bench numbers, validate/doctor results, live-run analysis, decisions D-A..D-I, the known gaps below, and "MemPalace not available this session".

## 4. Must be stated plainly in the final report (gaps; do not build)

- **Seated play gives no advice yet — practice or cash alike.** Both run through the same mechanism; the only difference is the currency displayed. The seated passes (p1 hero cards, p3_to_call, p3_hero_chips, p4 raise bounds, seat bets) have no training data, their regions are provisional, no seated capture exists, and they are never run. A seated frame always yields `readable:false, state:null` (R17), with no action guidance even after `calibrated:true`.
- Enabling seated advice needs a separate, user-approved session: seated harness captures (the user sits; no agent input), seated region measurement, auto-labels and training for those passes, and its own Gate F. It is not a separate mode of the tool.
- Release packaging does not ship the Laya server (`laya-server.py`, `laya_prep.py`, `laya-pins.json` are not in the release allowlist; workflow changes not authorized).
- Six-max only. Lobby eval rests on one user frame (train lobby = 1 harness capture + 24 augmentations). The cursor is composited into frames (WGC session at `windows.rs:449-458` never disables cursor capture). Deterministic template matching (the auto-labeler) would be faster and exact at known window sizes — the user's call.
- Fine-tuned weights are local and not distributable; a fresh install cannot obtain them. Live precision was not separately measured (D-I). `scripts/vlm-pins.json` is orphaned but kept.
- Cash-table risk (from the currency difference): if a cash table renders a currency glyph inside the pot/stack crops, R5 yields "not visible" → state null. Untested; needs one cash capture to confirm. No change now.

## 5. Risks and failure modes

- Any per-pass threshold of 1.0 → that pass is never confident → coverage 0 → honest FAIL; do not edit.
- GPU contention: never run `dump` while the server is up; bench only with a warm, idle server.
- Corrections that change a glyph count invalidate segmentation for that frame → `unsure`.
- Raised vendored thresholds can break `assembly.rs` fixtures (fix fixtures upward, never thresholds).
- `--laya-threshold` is clamped to 0.99; if the fitted max exceeds it, note the gap between the live run and the fit.
- The live run needs the user's client at a trained size; a different size means regions are unvalidated — record and do not retry with other sizes.

## 6. Validation checklist (end of session)

- [ ] `CK/{raw-eval,raw-late,laya-calibration,calibration,score-calib,score-eval,score-late}.json` exist; `score-eval-verified.json` if the checklist was answered.
- [ ] `scripts/laya-pins.json` has `model.finetuned` (with `laya-calibration.json` hash), `server.dtype`, `server.batch_size`, `server.implemented: true`; `laya-server.py verify` exit 0.
- [ ] bench JSON recorded; `validate.py` 12/12 with the test count; `validate_phase_a.py` PASS; release build; doctor online/offline exit 0.
- [ ] On PASS: vendored set has `calibrated: true` and the per-pass thresholds; the three Rust assertions flipped; `cargo test` green.
- [ ] Live run dir with `laya-unseated.{live.jsonl,timed.tsv,stderr.txt,run.json}`, `answers.jsonl`, `analysis.json`, doctor reports; evidence index updated.
- [ ] Docs edited per T8; addendum 10 written with UTC times; final report lists §4 verbatim and tells the user to delete `lobby-screengrab.png`.
