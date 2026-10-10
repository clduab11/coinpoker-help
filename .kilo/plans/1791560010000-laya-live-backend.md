# coinpoker-help — Laya Vision as the sole live perception backend

Planned 2026-10-09T15:33Z-16:10Z on `checkpoint/seated-read-mechanism-2-20261002` @ 3f525a4
(+ uncommitted addendum-8 diff). Execution record goes to addendum 9 of
`.kilo/plans/1791496776779-repo-readiness-and-next-steps.md`.

## 0. Decisions (user, 2026-10-09T15:4xZ)

| # | Decision |
|---|---|
| D1 | **Remove Gemma now.** Laya is the only backend; no `--vlm-backend` selector. `scripts/vlm-pins.json` stays unchanged as history (nothing reads it). The running llama.cpp server (PID 24812, :18080) is left alone; the user may stop it. |
| D2 | **Observation-only until calibrated.** Without Phase C calibrated thresholds, Laya never emits an actionable state (R17). |
| D3 | **game_phase stays strict** (0.2.0 R12). It may be relaxed to "skip when uncertain" only if Phase B-lite shows it is the sole blocker (see 3.4). |
| D4 | **Commit and push the addendum-8 diff first**, with a thoughtful message. This authorization covers only that one commit. All Laya work stays uncommitted for the user. |

The brief's authorizations still apply: conda env, pinned torch/laya/weights, Laya runs on the
saved captures and the live table. Still not authorized: release packaging or workflow edits,
any client input (including resizing windows), and pixels outside `.local/captures`.

**Ordering safety.** Gemma code is deleted only after the Phase B-lite gate passes (Step 3).
If Laya fails the gate, the tree still has a working Gemma path.

## 1. Facts this plan relies on (verified in planning)

- **Frame = whole window.** WGC `CreateForWindow` and `ContentSize` (capture.rs:45-52,
  windows.rs:280-282, 368-376) give packed RGBA with no client crop. CoinPoker draws its own
  title bar, and the frame includes it. lobby.png is exactly 1280x778, the lobby
  `GetWindowRect` size, so frame size equals window size.
- **Uniform scaling with a fixed title bar.** I viewed both table PNGs (±3 px; A = 800x613,
  B = 1015x770, s = 1.269, T ≈ 29 px). Predicted B = (x·s, T + (y−T)·s):
  - pot label (400,235) → (507,290); observed (507,290)
  - Find Seat (737,583) → (935,732); observed (935,732)
  - Join Wait List (594,583) → (754,732); observed (753,732)
  - top plate (400,146) → (507,178); observed (507,178)
  - lower-left plate (95,437) → (120,547); observed (120,546)
  - lower-right plate (705,437) → (895,547); observed (895,546)
  - bottom plate (400,548) → (507,688); observed (507,686)
  - table rim x 50/750 → 63/952; observed 63/950
  - chat icon (25,540) → (32,677); observed (32,678)
  - The title bar is 0-28 px in both, with the same font size and control spacing, so it is
    **not scaled**.
  - The content area is aspect-locked: 800/584 = 1.3699 and 1015/741 = 1.3698.
  - Hero cards and the seated action buttons are not visible (unseated in both).
  - The board is visible only in A: 4 cards at x 250-488, y 250-328, slot pitch 61 px, so a
    5th card would end near x 549.
  - "Fractions of the window client area" is therefore refined to **fractions of the content
    rect below the title bar** (section 4).
- **Envelope** (screen.rs, parser.rs):
  - Amounts are u32.
  - `players[{name,chips,last_action,bet_amount}]` needs unique non-empty names; Laya cannot
    read names, so it uses `Hero` / `Seat{i}` (prompt.rs:41 convention).
  - A fold is recognized by `last_action` = "fold" (case-insensitive).
  - `evidence.hero_cards` must equal `hero_cards.len()==2`.
  - Table with `state:null` requires `readable:false`.
  - Inter-hand marker = preflop, no hero/board cards, not actionable, no actions, to_call 0,
    no raise bounds (state_machine.rs:66-74). After a marker, only preflop is accepted.
  - TableGate needs TableTitle metadata, `has_table_evidence` (readable, table_layout,
    board_area, pot), and two identical consecutive observations (screen.rs:301-407).
  - Gate reasons map to statuses at runtime.rs:526-534 (`candidate_table`, `lobby_detected`,
    `unknown`).
- **Laya API** (github r33drichards/laya-vision, HEAD `9e1e2419` 2026-10-01 at planning;
  site-docs/reference/predict.md):
  - `load_vlm(id, device, revision=, backbone_revision=)`. The backbone
    `HuggingFaceTB/SmolVLM-256M-Instruct` must also be pinned.
  - `predict(state, questions, n_permutations=1, batch_size=8, prefix_cache=None, strict=False)`.
  - Answers carry `choice` + `probabilities`, `noul` (P(true)), `confidence` and `truncated`.
  - Options share a 256-token `head_max_len`, so the 54-option card vocab may truncate.
  - Needs `torchvision` (image processor) and Pillow. Python ≥3.8, `transformers>=4.45`.
  - Weights are CC-BY-NC-SA-4.0; code is Apache-2.0.
- **Environment.** `.conda/` is Python 3.13.16 with ipykernel only, so it cannot be reused
  (the brief requires 3.11/3.12). Create a new env. The Kilo plugin conda base exists at
  `C:\Users\cld-main\AppData\Local\KiloDesktop\app-0.1.11\resources\bridge\python`.
- **Validation and CI constraints:**
  - `scripts/validate.py` has one syntax check per root/`scripts` `*.ps1`. Any new `.ps1`
    makes it 13 checks, so **no new .ps1 files**.
  - The 26-case synthetic evaluation uses recorded envelopes and never calls `analyze`. It
    constructs the backend and needs a loopback endpoint.
  - CI runs `scripts/tests` on stdlib Python 3.11, so new Python tests must not import
    torch or PIL.
  - `test_doctor.py:165-173` locks the offline skips to `{vlm_models, multimodal_api}`.
- **Release allowlist** (release-windows.yml:63-74) and ci.yml:41 reference
  `download-model.ps1` (repo root), `scripts/setup-windows.ps1`, `start-vlm.ps1`,
  `vlm-pins.json`, `doctor.py`, `windows-acceptance.ps1` and `MODEL_LICENSES.md`. These
  files must keep existing. They are **repurposed for Laya**, not deleted.
- **Question-set 0.2.0 defects to fix:**
  - The expanded file leaves `pass: "p5_seat_{i}"` and `<i>` unsubstituted and drops the
    per-pass region, note and threshold.
  - Digit instructions are the short text, and their alignment contradicts R5 (left-to-right
    vs "leading none").
  - 7 slots can overflow on "1,234.56".
  - `amounts_center` holds only the pot (worksheet note).
  - The annotation board box (x 240-500 @800) misses the 5th slot.
  - The top-seat bet chip in B (u 0.394) falls outside seat_1.
- **Run E recount.** `E-motion0-cap30.live.jsonl` has 28 submissions, 27 completions and 13
  obsolete, so **14 fresh**, not the 15 in summary.md. Re-analyse it with the new script; do
  not re-run it.

## 2. Steps and gates

Economy: use explore subagents for mapping. Send long outputs to files (Python, or
`Out-File -Encoding utf8`, never `>`). Quote only key numbers. Do not re-run the churn probe
or the starvation proofs.

### Step 0 — verify, commit and push addendum 8 (D4)
1. Check `git status --short`: exactly the 4 modified files plus untracked `.conda/`,
   `.kilo/`, `environment.yml`, the PDF and the screenshots.
2. Run `python scripts/validate.py`: expect 12/12 and 303 tests. Write the summary to
   `.local/validation/`.
3. Stage exactly `README.md`, `crates/ingest/src/change_detect.rs`,
   `crates/ingest/tests/live_runtime.rs` and `docs/WINDOWS_ACCEPTANCE_V1.md`.
4. Commit with `git commit -F <msg file in %TEMP%\kilo>`. Draft below; check every claim
   against `git diff` first.
   ```
   Suppress persistently animated tiles so live tables reach fresh analysis

   Live CoinPoker tables animate seat avatars, badges and plate glows every
   ~200 ms, so change detection flagged nearly every 100 ms capture
   (297/298 in the probe) and every inference finished obsolete.

   ChangeDetector now tracks per-tile motion over the last 20 captures and
   suppresses tiles that moved in at least 6 of them (release at 3,
   8-neighbour dilation, motion counted at any byte difference, at most 30%
   of tiles suppressed). A suppressed tile never replaces the baseline on
   its own and is compared again once it stops; a change in any
   unsuppressed tile still invalidates in-flight work, and staleness inside
   suppressed tiles stays bounded by the forced refresh.

   New validated config fields animated_window, animated_hits,
   animated_channel_delta and animated_max_fraction (defaults 20/6/0/0.30)
   are echoed additively in the configuration event; no CLI flags.
   Diagnostics-only accessors suppressed_tiles() and trigger_tiles().

   Adds 9 unit tests and the persistently_animated_tile_does_not_starve_inference
   integration test (303 Rust tests). README limits and acceptance gates
   14/15 updated. A 90 s run on a 1015x770 six-max table produced the first
   fresh completions on a live table; force_refresh_ms is unchanged.
   ```
5. `git push origin checkpoint/seated-read-mechanism-2-20261002`.
6. Record the SHA and the CI run id (`gh run list --branch … --limit 1`). Check the CI result
   at the end of the session; do not wait for it.

### Step 1 — runtime environment, pins, licence
1. Find conda: `Get-Command conda`, then `<plugin base>\Scripts\conda.exe` /
   `condabin\conda.bat`, then the desktop conda tool (named env). If none works,
   **stop and ask**.
2. Create the prefix env `.local/laya-runtime/env` with Python 3.12.
3. Run `nvidia-smi` to record the driver and VRAM. Pick the CUDA wheel tag the driver
   supports (cu128, else cu126).
4. Install pinned `torch` and `torchvision` from `https://download.pytorch.org/whl/<tag>`.
   Then install `laya @ git+https://github.com/r33drichards/laya-vision@<HEAD sha, record it>`
   and `pillow`. Freeze to `.local/laya-runtime/freeze.txt`.
5. `torch.cuda.is_available()` must be true; otherwise **stop and ask**.
6. Weights go to `HF_HOME=models/laya-vision/hf` (confirm `git check-ignore`, else
   `.local/laya-runtime/hf`).
   - Resolve the `thaitea/laya-vision` sha and the backbone sha (from the checkpoint config,
     else current).
   - Do one online `load_vlm(..., revision=, backbone_revision=)`, then reload with
     `HF_HUB_OFFLINE=1` to prove offline operation.
7. `scripts/laya-pins.json` (new, tracked, format 1) records:
   - `runtime{python, env_prefix, torch_index_url, packages{torch, torchvision,
     transformers, safetensors, huggingface_hub, numpy, pillow}, laya{repository, commit}}`
   - `model{repository, revision, backbone{repository, revision}, hf_home, files[{path,
     size, sha256}]}` for every snapshot file of both repos
   - `server{host:"127.0.0.1", port:18090, alias:"coinpoker-laya-vision"}`
   - `license`
8. `MODEL_LICENSES.md`:
   - Add a Laya table (checkpoint, backbone, code commit, SHA-256).
   - Licence text: weights CC-BY-NC-SA-4.0, personal local use only, never redistributed;
     backbone and code Apache-2.0.
   - The pin manifest is now `laya-pins.json`.
   - Move Gemma to a "Historical (removed 2026-10-09)" section.

### Step 2 — question set 0.3.0 and regions (data only, no Rust)
1. Fix the expander in `.local/laya/validate_phase_a.py`:
   - concrete `p5_seat_1..9` passes;
   - substitute `<i>`;
   - full digit template;
   - emit `passes[{id, tier, region, note, threshold, questions[]}]`.
2. Source edits (version 0.3.0):
   - R5 rewritten (3.2);
   - R15-R18 added and R6 made explicit (3.3);
   - `thresholds.calibrated:false`;
   - a changelog entry.
3. Write the vendored output to tracked `crates/ingest/assets/laya/question-set.json`
   (schema `coinpoker-laya-question-set-vendored/1`, with `generated_from{path,sha256}`)
   and keep the `.local` expanded copy. `validate_phase_a.py` must PASS.
4. `crates/ingest/assets/laya/regions.json` holds the geometry from section 4, with
   `status:"agent_numeric_verified; human_unverified"` and the capture SHA-256s.
5. Numeric landmark probe, `.local/laya/geometry_probe.py` (numbers only):
   - title-bar boundary row in A and B (expected T = 28 or 29; use that T and recompute the
     aspect);
   - "Pot" blue-text bounding box lies inside `amounts_center` in A and B;
   - white-card pixel count inside `board`: A ≈ 4 cards, B ≈ 0;
   - plate dark-box centroids inside each seat box.
   - Adjust boxes until all pass. Output: `.local/laya/phase-b/<UTC>/geometry.json`.

### Step 3 — Phase B-lite (in-process laya, before any Rust wiring)
1. Run `.local/laya/phase-b/run_phase_b.py` from the env Python. It reads the vendored set
   and `regions.json`, so the question text matches what Rust will send.
2. Output to `.local/laya/phase-b/<UTC>/` (JSON, no pixels):
   - `env.json`: versions, GPU, dtype, VRAM.
   - `p0.json`: for each of lobby.png, A and B, per question the choice or P(true),
     top-option probability, confidence and truncated; latency for cold load, cold first
     predict and warm median of 5. Use `torch.cuda.synchronize` timing.
   - `battery.json`: the six-max battery on A and B (p0, p1, p2, p3, p4 and seats 1-6 = 11
     passes, 155 questions). Per-pass cold/warm latency, sum, wall time, crop boxes in px.
     Compare `batch_size` 8/32/64 and keep the fastest.
   - `summary.md`: numbers against the targets.
3. Sanity anchors (agent-read, **unverified**, for gross-failure detection only, never for
   thresholds): lobby = lobby; A = poker_table, turn, board 8c 4d 9d 5d, pot 1.05, hero
   unseated, 6 seats; B = poker_table, preflop, pot 0.55, hero unseated, 6 seats.
4. **Gate:**
   - G1: API returns all 17 p0 answers.
   - G2: top `screen_kind` is lobby / poker_table / poker_table. If wrong, allow one
     criteria-description refinement round (record both); if still wrong, **stop and
     report** (Gemma is still intact).
   - G3: tier-0 latency measured.
   - Flag (do not block): `screen_kind` p < 0.8; tier-0 warm ≥ 300 ms; battery ≥ 2000 ms.
5. Pre-decided adjustments, each recorded as 0.3.1:
   - (a) If any card question is truncated or indistinguishable, split each card into rank
     (15 options) + suit (6 options) questions.
   - (b) If `hero_seat_index`=not_seated is not confident on A/B, add the tier-0 noul
     `ev_seat_controls` ("Find Seat / Join Wait List buttons visible"). R15 then uses it
     (3.3).
   - (c) D3 relaxation: only if game_phase is the sole low-confidence input that nulls
     otherwise confident A/B reads.
6. Report the numbers to the user in chat and in `summary.md`. Continue unless a stop
   condition hit.

### Step 4 — `scripts/laya-server.py` (section 5) and Python tests
- Add `scripts/tests/test_laya_server.py`: stdlib only, fake predictor and decoder.
- Measure HTTP overhead: 20 warm p0 calls through the server. Output:
  `phase-b/<UTC>/http.json`.

### Step 5 — Rust: LayaBackend and Gemma removal (sections 3, 4, 6)
- New `crates/ingest/src/laya.rs` (module root) with `laya/{geometry,questions,assembly,client}.rs`:
  - assets loaded via `include_str!`;
  - `pub mod laya` in lib.rs;
  - no new crates (`Cargo.lock` unchanged).
- `vlm.rs` keeps the `VlmBackend` / `VlmOutput` / `VlmError` contract.
  - Delete `OpenAiServerBackend`, chat-completions parsing and `VlmError::Truncated`.
  - Keep loopback validation (remote path removed), the agent builder (no proxy, no
    redirects, timeout), the bounded body read and PNG/base64 helpers as `pub(crate)`.
- `prompt.rs` is unchanged. The `prompt` argument stays in the contract; Laya ignores it
  (documented).
- `bin/live.rs` and `bin/evaluation.rs` construct `LayaBackend::new(config, lobby_size)`;
  construction does no network I/O.

### Step 6 — scripts (no new .ps1)
- **`scripts/start-vlm.ps1`** becomes the Laya launcher:
  - `param([string]$AnswersLog)`; StrictMode; Windows check; pins format check;
  - calls `download-model.ps1 -Verify`;
  - sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
    `DO_NOT_TRACK=1`, `HF_HOME`;
  - runs `<env>\python.exe scripts\laya-server.py serve` in the foreground and throws on a
    nonzero exit.
  - If the server script or pins are missing, the error says Laya is not packaged in this
    build.
- **`download-model.ps1`** (root): `-Verify` calls `laya-server.py verify`; with no switch
  it calls `laya-server.py fetch` (pinned revisions plus hash check).
- **`scripts/setup-windows.ps1`**:
  - optional `-Conda` path;
  - create the env from pins if absent;
  - pip-install the exact pins (torch/torchvision from `torch_index_url`, laya from the git
    commit);
  - verify versions and CUDA;
  - then run `download-model.ps1`. Idempotent.
- **`scripts/doctor.py`:**
  - Load `laya-pins.json` lazily; a missing file gives a check result, not an import crash.
  - `loopback_endpoint` accepts `/v1/laya/predict`; `/v1/models` is derived from it.
  - Default endpoint `http://127.0.0.1:18090/v1/laya/predict`, alias from pins.
  - Checks:
    - `runtime_asset`: env Python plus package and laya-commit versions via `run_command`;
    - `cuda_device`: replaces `vulkan_device`;
    - `model_files_sha256`: both snapshots;
    - `vlm_models`: alias;
    - `multimodal_api`: red and blue generated PNG, one choice question
      `[red, blue, green]`; the expected colour must be the top choice.
  - Offline-skip names are unchanged. Update `test_doctor.py` only where check names or
    semantics changed.
- **`scripts/lobby-observation.ps1`**: defaults become the Laya alias and endpoint.
- **`windows-acceptance.ps1`**: unchanged.

### Step 7 — validation
1. `python scripts/validate.py`: **12/12**, record the new test count.
2. `python .local/laya/validate_phase_a.py`: PASS.
3. Release build: `cargo build --release --locked`.
4. With the server running: `python scripts/doctor.py` (online) and `--offline`, both
   exit 0.

### Step 8 — live verification (unseated table)
1. Start the server: `pwsh -File scripts/start-vlm.ps1 -AnswersLog
   .local/acceptance/<UTC>-laya/answers.jsonl` (background process). Wait for
   `/v1/models`. Record VRAM; the Gemma server stays up.
2. Copy `run-timed.ps1` to `.local/acceptance/<UTC>-laya/`.
   - Drop the Gemma `--vlm-endpoint` / `--vlm-model` base args (defaults are Laya now;
     `--vlm-backend` no longer exists, per D1).
   - Record the `laya-pins.json` hash in `run.json`.
   - Run `-Label L1 -Seconds 90`, and L2 if L1 is inconclusive.
3. `analyze.py` (numbers only) reads `<label>.timed.tsv` and the answers log:
   - submissions, completions, obsolete, fresh;
   - fresh completions by status/reason;
   - `table_valid_nonactionable`: `candidate_table` with "waiting for a second matching
     observation" / "community cards agree; no advice" / a transition reason, or
     `capturing_table` followed by `action-not-required`;
   - `table_state_null` ("screen content is unreadable" with `screen_kind`=poker_table in
     the answers log);
   - lobby/unknown counts;
   - battery latency (submission → completion) p50/p95/max against 1.6 s (shortest
     measured quiet window) and 2000 ms;
   - the questions most often below threshold.
   Re-run the same script on run E's files for the comparison (E: 28 / 13 / 14, zero valid
   table readings).
4. **Success:** at least one fresh, schema-valid `poker_table` envelope with a non-null
   state and `action_required=false`, and battery p95 inside the quiet windows.
   - Zero decisions is expected (unseated, D2); any decision event is a defect.
   - No claims about decisions or seated reads.

### Step 9 — docs and records
- `docs/LAYA_VISION_PHASE_A.md`:
  - §3 now says Laya is the sole backend (D1), observation-only (D2);
  - §7 gets Phase B status (B-lite numbers, pins, evidence paths, UTC; accuracy unmeasured;
    Phase C still blocked);
  - landmark table; 0.3.0 rule changes.
- README (98-99, 119-123, 166-169), `docs/INSTALL_WINDOWS.md` (§2-3: Laya setup/fetch/start,
  port 18090), `docs/VLM_COMPATIBILITY.md` (Laya, with Gemma history),
  `docs/WINDOWS_ACCEPTANCE_V1.md` (gate 3 re-baselined for Laya: PENDING, Gemma result kept as
  history; still "12 checks"), `docs/EVENTS_V2.md` (new configuration fields),
  `CONTRIBUTING.md:30-33`, `SECURITY.md:13-17` (unauthenticated loopback :18090, no image
  logging), and the vlm.rs module docs.
- Addendum 9 in the readiness plan: commit SHA and CI run, pins, evidence paths, numbers,
  UTC times, gaps (section 7).

## 3. Assembly (Rust `laya/assembly.rs`)

### 3.1 Confidence
- Threshold `t` = per-pass threshold (0.8), optionally raised by `--laya-threshold`.
- `choice` is accepted iff `probabilities[choice] ≥ t` and the answer is not truncated.
- `noul` is true iff P ≥ t, false iff P ≤ 1−t; otherwise low confidence.
- Low confidence applies the question's `on_low_confidence`.
- Laya's entropy `confidence` is logged, not used.

### 3.2 R5 (amended) — amounts
- Slots d1..d7 are **left-aligned**: characters run until the first `none`, and every later
  slot must be `none`.
- Any low-confidence slot makes the amount not visible.
- If d7 is a character, the amount may be overflowing, so it is not visible.
- ',' may only separate digit groups and is stripped. At most one '.', with at most 2
  decimals.
- Value = round(decimal × 100) as u32 (hundredths). The decimal display format still awaits
  human confirmation.
- All-`none` means not visible (pot/chips), except for bets (R16).

### 3.3 New and clarified rules (0.3.0)
- **R6** (explicit): before returning, the assembled text is checked with
  `parse_screen_output`. On error the backend returns the same `screen_kind`/evidence with
  `readable:false, state:null`. It degrades; it never repairs.
- **R15 unseated** — applies when all of these hold:
  - `hero_seat_index` = `not_seated` with p ≥ t (the low-confidence fallback does **not**
    count);
  - `action_on_hero` is confidently false;
  - if 0.3.1(b) is applied: `ev_seat_controls` confidently true **and** `hero_seat_index`
    not confidently `seat_k`.

  Then:
  - p1 is not run and `hero_cards` = [];
  - `to_call` = 0, `hero_chips` = 0, there is no Hero player;
  - p3 asks only the pot slots;
  - tier 2 is skipped and `players` = [].

  Otherwise p1, the full p3 and tier 2 run, and R2 applies as written. Preflop unseated reads
  equal the inter-hand marker; that is expected.
- **R16** (non-actionable `players`): either every present seat fully read, or [] — never
  partial.
  - A bet that is confidently all-`none` gives `bet_amount` 0 (visible absence).
  - `last_action` `none_visible` gives null; `bet` maps to "raise".
  - Actionable states follow R2/R8 unchanged.
- **R17** (D2): if `thresholds.calibrated` is false and `action_on_hero` is confidently true,
  return `readable:false, state:null`.
- **R18** (lobby-size guard): if the frame size equals `--lobby-size`, no tier-1/2 pass runs.
  A `poker_table` p0 gives `readable:false, state:null`.

### 3.4 Strictness
- R12 stays strict (D3). Adjustment 0.3.1(c), when triggered: a low-confidence `game_phase`
  skips the cross-check; a confident disagreement still gives null; 5 cards still need a
  confident river/showdown answer.
- Card mapping: `As` gives {rank "A", suit "spades"}; s/h/d/c map to spades/hearts/diamonds/clubs.

### 3.5 Pass order
1. p0.
2. Not `poker_table` → apply R1 and stop.
3. Apply R18.
4. Apply R15.
5. Run p2, then p3, then p1 (if seated or seating unknown), then p4 (only if `act_raise` is
   confidently true; otherwise the bounds are null).
6. Run seats 1-6 (layout `six_max`; seats 7-9 have no box and are skipped), unless R15
   applied.

- Early exit as soon as the state is already determined to be null (an unreadable board
  slot, the pot not visible).
- Any HTTP error aborts the battery with `VlmError`.
- The per-request timeout is `timeout_secs`.

## 4. Geometry (`laya/geometry.rs`, `regions.json`)

### Content rect
- Defaults: `T0` = 29 (or the measured value), `r` = 1.3698 (re-derived from the measured T).
- Compute `T = H − round(W/r)`.
  - If 20 ≤ T ≤ 48 (aspect-locked window, any DPI), the content rect is (0, T, W, H).
  - Otherwise fit aspect `r` centred inside (0, T0, W, H): pillarbox or letterbox.
- A box (u0,v0,u1,v1) maps to px as x = x0 + u·cw and y = y0 + v·ch, with floor for the
  start, ceil for the end, clamped to the frame.
- A crop under 8x8 px means the pass is not run (all answers low confidence).
- Initial normalized boxes (refined in Step 2.5):
  - board 0.300,0.370,0.700,0.525
  - amounts_center (pot) 0.380,0.320,0.620,0.372
  - hero_cards (provisional) 0.400,0.620,0.600,0.830
  - action_buttons (provisional) 0.600,0.880,1.000,1.000
  - seat_1 0.370,0.027,0.5875,0.336
  - seat_2 0.700,0.113,0.9375,0.353
  - seat_3 0.700,0.533,0.950,0.755
  - seat_4 0.400,0.515,0.600,0.935
  - seat_5 0.044,0.515,0.294,0.764
  - seat_6 0.0625,0.113,0.306,0.353
- Seats, hero_cards and action_buttons are provisional. They do not run on the unseated live
  table.

### Unit tests (exact integer px)
- 800x613 and 1015x770: T = 29, no bars.
- 1280x963: aspect-locked.
- **1280x720**: T out of range, so pillarbox with x0 = 167 and cw = 946.
- 800x700: letterbox.
- Lobby 1280x778: refused for table passes.
- Board and pot px at all of the sizes above.
- Real CoinPoker behaviour at 16:9 is **unverified**: no capture exists and resizing is client
  input. If the user resizes the table, capture it with the harness and re-run the probe.

## 5. Laya server (`scripts/laya-server.py`)

Subcommands: `serve` (default), `fetch`, `verify`.

- **Binding:** `127.0.0.1:18090` only. There is no host flag; the port is fixed from pins.
- **Server model:** stdlib `HTTPServer`, single-threaded (serialises GPU use). Handler socket
  timeout 10 s.
- **Logging:** `log_message` is a no-op. Errors are `{"error":"<code>"}` and never echo input.
- **GET `/v1/models`:** `{"object":"list","data":[{"id":"coinpoker-laya-vision","object":"model",
  "meta":{"checkpoint","revision"}}]}`.
- **POST `/v1/laya/predict`:**
  - Request: `{model, pass, note, image_png_b64, questions:{qid:{type, instructions,
    criteria?}}}`.
  - Responses: alias mismatch → 404; malformed → 400; body over 8 MiB → 413.
  - Limits:
    - at most 64 questions and 64 options;
    - ids match `[a-z0-9_]{1,64}`;
    - instructions at most 2000 characters;
    - PNG only, at most 4096² pixels (`MAX_IMAGE_PIXELS`).
  - Calls `predict(..., strict=False, n_permutations=1, batch_size=<pins/flag>)`.
  - Response: `{model, answers:{qid:{type, choice?, probabilities?, noul?, confidence,
    truncated}}, timing_ms:{decode, predict}}`.
- **Startup:**
  - set the HF offline env before importing laya;
  - verify pins (snapshot SHA-256, package versions, laya commit via `direct_url.json`);
    exit 2 on any mismatch;
  - load the pinned revisions on CUDA;
  - warm up on a generated image;
  - print one `ready` JSON line (no pixels).
- **`--answers-log PATH`** (off by default): JSONL with utc, pass, timing, and
  `{qid: {v, p, truncated}}`. No image data.
- torch, laya and PIL are imported lazily so the tests stay stdlib-only.

## 6. Config and CLI (`bin/config.rs`, `bin/live.rs`)

- Kept flags:
  - `--vlm-endpoint` / `COINPOKER_VLM_ENDPOINT`: default
    `http://127.0.0.1:18090/v1/laya/predict`, loopback only, no remote opt-in.
  - `--vlm-model` / `COINPOKER_VLM_MODEL`: default `coinpoker-laya-vision`.
  - `--timeout-secs`: default 5 (range 1..=120), per request.
- New flag: `--laya-threshold` / `COINPOKER_LAYA_THRESHOLD`, range [0.80, 0.99]. It can only
  tighten the threshold while uncalibrated.
- Removed: `--allow-remote-vlm`, `COINPOKER_ALLOW_REMOTE_VLM`, and the temperature and
  max-tokens fields.
- `VlmConfig` becomes {endpoint, model, timeout_secs, threshold}.
- Configuration event: existing fields keep their names. Add `perception:"laya-vision"`,
  `question_set_version`, `laya_threshold` and `laya_calibrated:false`.
- Doctor env forwarding is unchanged.

## 7. Tests (focused; replace the removed Gemma tests)

- **Rust geometry:** section 4 list.
- **Rust questions:**
  - vendored set parses;
  - tier counts;
  - no `{i}` or `<i>` left;
  - every crop pass has a region;
  - card vocab = 54 and digit vocab = 13.
- **Rust assembly:**
  - R1 lobby;
  - R4 order, absent and unreadable;
  - R5 cases (zero, overflow, separators, decimals, bet zero);
  - R12 strict, and 0.3.1(c) if applied;
  - R15, including that the fallback does not count, and that preflop equals the marker;
  - R16 all-or-nothing;
  - R17;
  - R18;
  - R6 degrade;
  - a seeded loop of 1000 random answer maps, where every output passes
    `parse_screen_output`.
- **Rust client** (TcpListener mock):
  - happy path;
  - non-loopback rejected;
  - redirect rejected;
  - 1 MiB body cap;
  - bounded timeout;
  - errors never contain the base64;
  - 404 → `unsupported-model-api`.
- **Rust config/live:**
  - defaults;
  - threshold range;
  - removed flag gives a usage error;
  - configuration event fields;
  - `ScriptedBackend` unchanged.
- **Python:**
  - `test_laya_server.py`: validation, limits, alias, no-echo, no logging, loopback
    constant, fake predict round trip.
  - `test_doctor.py`: updated checks.

## 8. Stop conditions

- Conda, torch, CUDA or laya install problems → ask.
- G1/G2 failure after one refinement round → stop and report; do not delete Gemma.
- Anything needing a seated hero or window resizing → document, do not attempt.
- Any need to edit workflows or release packaging → document, do not do it.

## 9. Known gaps (record in addendum 9 / final report)

- **Release packaging is unchanged**, so a release built from this tree omits
  `laya-server.py` and `laya-pins.json`. With Gemma removed, a release would have no working
  backend until packaging is separately authorized.
- **Seated geometry is unknown.** p3 to_call/hero_chips do not sit in the pot crop, and the
  hero cards and action buttons are provisional. Seated reads are therefore expected to be
  state-null until seated captures exist (human step). No advice before Phase C (D2), and
  Gemma's real-table rate was 0/12 anyway.
- Only six-max geometry is supported, at 100%-DPI captures (the aspect rule covers other DPI
  values only when the window is aspect-locked). 16:9 is unverified.
- Accuracy is unmeasured (the worksheet is unfilled). Phase C (`agent.calibrate`) is still
  blocked.
- The WGC cursor is composited into frames (windows.rs:449-458) and may lower confidence on
  a crop.
- Phase D cleanup: `prompt.rs` and `vlm-pins.json` remain as contract/history; move the
  question-set source and expander into the repo.
