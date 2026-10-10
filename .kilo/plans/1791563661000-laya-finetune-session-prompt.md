# PROMPT — coinpoker-help: fine-tune Laya Vision, then make it the sole live perception backend

> Written 2026-10-09T16:35Z for a clean session with no prior context.
> Edit the AUTHORIZATIONS block before pasting.

## Project and repository

- **Repo:** `C:\Users\cld-main\Desktop\github-projects\coinpoker-help`. Rust workspace, toolchain 1.95.0, Windows.
- **Shells:** pwsh 7 is available, but Windows PowerShell 5.1 is the default shell.
  - In 5.1, `>` writes UTF-16. Write files from Python, or use `Out-File -Encoding utf8`.
  - Put multi-statement Python in `.py` files. PowerShell mangles inline `python -c` with f-strings and braces.
- **Branch:** `checkpoint/seated-read-mechanism-2-20261002`.
  - HEAD **4ccad18** is pushed and CI run 37957205975 is green.
  - `scripts/validate.py` passes 12/12 with 303 Rust tests.
- **Uncommitted from the previous session:** keep and extend these; do not revert them.
  - `scripts/laya-pins.json`
  - `MODEL_LICENSES.md` (Laya section)
  - `docs/LAYA_VISION_PHASE_A.md` (§7 Phase B-lite status, §8)
  - `crates/ingest/assets/laya/question-set.json` and `regions.json`
  - `.kilo/` is untracked by design.

**Read first, and only these:**
1. `.kilo/plans/1791560010000-laya-live-backend.md`, the integration plan. Its sections 3-7 (assembly rules, geometry, server API, config, tests) are still the target design.
2. `.local/laya/phase-b/SUMMARY-20261009T1650Z.md`, the measured failure that this session must fix.
3. `docs/LAYA_VISION_PHASE_A.md` sections 2, 3, 6 and 7.
4. `.kilo/plans/1791496776779-repo-readiness-and-next-steps.md`, addendum 9 only.

Do not re-derive what these establish. Use explore subagents for code mapping. Write long tool output to files and quote only the numbers that matter.

## Goal

Make Laya Vision (`thaitea/laya-vision`, 201M) the **sole live perception backend** and remove Gemma, as the user decided on 2026-10-09.

To get there, **domain-adapt Laya** (research, data, fine-tune, calibrate) so that on real CoinPoker tables it produces **confident and correct** typed answers. Those answers assemble into schema-valid envelopes with non-null states instead of `unknown`/null.

**Non-negotiable.** Uncertain answers still map to null or unreadable. You may **never** reach the goal by:
- lowering thresholds below a calibrated value,
- relaxing assembly rules, or
- repairing inconsistent answers.

The model has to become right, and that has to be shown on a human-verified held-out set.

## Why this session exists (measured 2026-10-09)

The pinned checkpoint, zero-shot, failed the Phase B-lite gate on the three saved captures:

- **Screen classification:** `screen_kind` called the lobby `poker_table@0.41`, and the tables `poker_table@0.72` and `@0.66`.
- **Cards:**
  - The 54-option card questions were truncated by the 256-token option budget.
  - Splitting each card into rank and suit, on the whole board crop or per-slot crops, still misread `8c 4d 9d 5d`.
- **Amounts:** the pot digit slots read `1111111` for "1.05" and `5555555` for "0.55".
- **Confidence:** 0 of 138 crop questions reached 0.8.
- **Cross-check:** `game_phase` said preflop@0.92 on a turn image.
- **Latency (warm):**
  - p0 (17 questions, full window): 250-320 ms; target < 300 ms.
  - Full six-max battery (11 passes, 155 questions): 2.1-2.8 s; target < 2 s, ideally < 1 s.
  - Tier 0+1: 0.92-1.05 s.
  - bf16 peak memory is 542 MiB.

The user's position: classifier models like Laya are used for game decisions (the Laya repo reports Atari, ViZDoom and grid games, and the user cites Pac-Man), so the technology is capable. Find out how that works and bake it in.

## Environment (already installed and pinned; see `scripts/laya-pins.json`)

- **Python env:** `.local\laya-runtime\env\python.exe`
  - Python 3.12.15, torch 2.11.0+cu128, torchvision 0.26.0+cu128, transformers 5.19.0, pillow 12.3.0.
  - laya 0.1.7 from `github.com/r33drichards/laya-vision@9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c`.
  - CUDA works on the RTX 4060 Ti (8 GB, driver 610.88).
- **conda:** run it as `& "C:\Users\cld-main\AppData\Local\KiloDesktop\app-0.1.11\resources\bridge\python\python.exe" -m conda ... -c conda-forge --override-channels`. `Scripts\conda.exe` is a broken uv trampoline.
- **Weights:** `HF_HOME=models\laya-vision\hf` (gitignored).
  - Checkpoint `thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc`: full fp32 weights, with the processor and backbone config bundled.
  - Load with `laya.load_vlm("thaitea/laya-vision", revision=<sha>, device="cuda", dtype="bf16")`.
  - Use `HF_HUB_OFFLINE=1` for every load.
  - Set `TRANSFORMERS_VERBOSITY=error` and redirect stderr; transformers 5.19 floods deprecation warnings.
- **Laya API:**
  - Call `predict({"image": PIL, "note": str}, {qid: {type, instructions, criteria}}, n_permutations=1, batch_size=8, prefix_cache=None, strict=False)`.
  - Each answer carries `choice`, `probabilities`, `confidence`, `noul` (P(true)) and `truncated`.
  - The checkpoint config: image resized to one 512 px tile (`image_size` 512, `image_split_edge` 0), `head_max_len` 256 tokens shared by all options, `max_len` 1024, `option_attention` block, `readout` terminator, `dtype` fp32.
  - Library modules include `vlm_train.py`, `calibration.py`, `atari_train.py`, `games.py`, `gridgames.py` and `controlgames.py`.
  - The repo docs include a fine-tuning how-to (commit 2026-10-01) and a calibration how-to.
- **Phase B tooling:** under `.local/laya/phase-b/`.
  - `run_phase_b.py` produces p0 and the battery as JSON. `summarize.py` prints its key numbers.
  - `refine_round1.py` and `show_refine.py` cover the refinement experiments.
  - `.local/laya/geometry_probe.py` is the numeric landmark probe; it never saves pixels.
- **Gemma (to be removed):**
  - llama.cpp b10964 server, PID 24812, at 127.0.0.1:18080, alias `coinpoker-gemma-4-e2b`. It uses about 6.2 GB of the 8 GB VRAM.
  - Port 8080 is held by Docker.

## Product facts the integration depends on (see the integration plan for details)

### Perception contract
- `crates/ingest/src/vlm.rs`: `VlmBackend::analyze(&Frame, &prompt) -> VlmOutput{text}`.
- The text goes through the unchanged `parser.rs` and `screen.rs` (`parse_screen_output`) strict envelope validation, then the unchanged state machine, consensus and lease. Laya never bypasses validation.

### Envelope
- Amounts are u32. Laya encodes them in hundredths of the displayed unit.
- `players[{name, chips, last_action, bet_amount}]` uses the names `Hero` and `Seat{i}`.
- `evidence.hero_cards` must equal `hero_cards.len()==2`.
- A table with `state:null` requires `readable:false`.

### Table gate and state machine
- The gate needs TableTitle metadata.
- It needs `has_table_evidence`: readable, table_layout, board_area and pot.
- It needs two identical consecutive observations.
- After the inter-hand marker, only preflop is accepted.

### Runtime
- Poll every 100 ms. A frame is stable after 300 ms and 3 captures.
- Lease `max_frame_age_ms` 8000; `force_refresh_ms` 5000. Leave both as they are.
- Measured on a live table: real changes every few hundred ms, quiet windows 1.6-7 s.

### Frames and geometry
- Frames are whole windows (WGC) and include an unscaled 28 px title bar drawn by the app.
- The content area below it scales uniformly and is aspect-locked at 1.3677.
- Boxes are fractions of the content rect, per `crates/ingest/assets/laya/regions.json`. The board, pot, title bar and card columns were verified numerically.
- Seat, hero-card and action-button boxes are provisional; no seated capture exists.
- The rule (`T = H - round(W/aspect)`, else a centred fit) must work at any window size up to at least 1280x720, and at any size other than the lobby.
- Assert that the frame size is not the lobby size before any table pass.

### Window discovery
- The lobby and table windows are both titled "CoinPoker".
- The table is the window with the same title and a size other than the calibrated lobby, 1280x778.
- Live args: `--exe-name CoinPoker.exe --lobby-title CoinPoker --lobby-size 1280x778`.

### Captures
- Use only the existing harness:
  - `python .local/proof-harness/operations.py`, or
  - `.local/proof-harness/target/debug/seated-proof.exe capture --exe CoinPoker.exe --lobby-title CoinPoker --lobby-size 1280x778 --role table|lobby --out .local/captures/<stamp>-<label>/<name>.png`
- Existing captures:
  - `.local/captures/20261008T232842Z-new-calibration/{table.png (800x613), lobby.png (1280x778)}`
  - `.local/captures/20261009T062531Z-new-calibration/table.png` (1015x770, six-max, user unseated)

### Live evidence tool
- `.local/acceptance/20261009T061624Z-starvation/run-timed.ps1` (`-Label`, `-Seconds`, `-ExtraArgs`).
- Baseline run E (Gemma): 28 submissions, 13 obsolete, 14 fresh (recounted), zero valid table readings.

### Question set
- Version 0.3.0: rules R1-R18 (R15 unseated hero, R16 players all-or-nothing, R17 observation-only until `thresholds.calibrated`, R18 lobby-size guard).
- Source: `.local/laya/question-set.json`. Validator and expander: `.local/laya/validate_phase_a.py`, which writes the vendored copy.
- The human worksheet `.local/laya/human-worksheet.md` is still unfilled.

## Decisions already made by the user

- **D1:** Laya is the sole backend and Gemma is removed. There is no `--vlm-backend` selector. `scripts/vlm-pins.json` stays unchanged as history.
- **D2:** observation-only until calibrated. While `thresholds.calibrated` is false, `action_on_hero` being confidently true gives `readable:false, state:null`.
- **D3:** game_phase stays strict. Relax it to "skip the cross-check when uncertain" only if data shows uncertainty is the sole blocker.
- Release packaging and workflows stay unchanged. Record the resulting gap: a release would not ship the Laya server.
- Files in the release allowlist keep existing and are repurposed for Laya: `download-model.ps1` (root), `scripts/setup-windows.ps1`, `start-vlm.ps1`, `doctor.py`, `vlm-pins.json`.
- Add **no new `.ps1` files**, so validate.py stays at 12/12.

## AUTHORIZATIONS (edit before pasting)

**Allowed:**
- Use the existing conda env, or create one for training (Python 3.11/3.12). pip-install pinned training dependencies, and record them in `scripts/laya-pins.json`.
- Install Unsloth / Unsloth Studio (Desktop) **only if** research shows it can train Laya's architecture.
- Read and download Hugging Face resources: the pinned checkpoint, public datasets used for pretraining or augmentation, with licences recorded.
  - **Never push or upload** any model, dataset or pixels: the weights are CC-BY-NC-SA-4.0, for personal local use, and derived weights inherit NC+SA.
- Run laya inference and training on the local GPU.
- Stop the Gemma llama-server (PID 24812) when you start removing Gemma or need its VRAM for training. Do not restart it.
- Take captures only through the harness, into `.local/captures/<UTC>-laya-train/`.
  - A capture loop that calls the harness every N seconds is fine while the user leaves a table open.
  - Derived crops and synthetic training images may be written **only** under `.local/captures/<UTC>-laya-train/derived/` (gitignored).
  - Evidence files and logs contain no pixels.
- Run Laya on the saved captures and on the live table window, read-only.

**Not authorized:**
- Commits and pushes; the user commits.
- Release or workflow changes.
- Any client input: clicks, keys, window resizing, seating.
- Pixels outside `.local/captures`.
- Uploads of any kind.

## Work plan (gated; record every phase in addendum 10 of the readiness plan, with UTC times)

### Phase R — agentic research → `.local/laya/research/RESEARCH.md` (cite file:line or URL for every claim)

**1. Laya training stack.** Use deepwiki or github reads of `r33drichards/laya-vision` at the pinned commit:
- the fine-tuning how-to and the JSONL dataset format;
- `laya.vlm_train.train` arguments (`init_from` checkpoint, frozen vs trainable vision tower, LR, epochs, batch, bf16, gradient checkpointing);
- the RLCD objective and how the `choice`/`noul`/`score` heads train;
- `agent.calibrate` (calibration how-to): temperature or threshold fitting, data needed;
- whether `image_size`, `image_split_edge` or tiling can raise effective resolution;
- the `head_max_len` limit and option design;
- `n_permutations` and `prefix_cache` costs;
- VRAM needs on 8 GB.

**2. Games.** How "the screen is the image and the buttons are the options" works:
- `games.py`, `gridgames.py`, `controlgames.py`, `atari_train.py`;
- how game frames enter the training mix;
- why game scores rose after in-domain frames were added;
- the reported vision-tower-training variant (0.54 games score at a cost on VQA).

Find any Pac-Man or Atari evidence the user referenced and state what transfers to reading a poker UI. Reading text and digits is not the same as choosing an action.

**3. Unsloth / Unsloth Studio.** Can it fine-tune this architecture (SmolVLM backbone cut to 20 layers, plus Laya's custom head and objective)? If it only trains generative VLMs, say so and use laya's trainer.

**4. Options to compare honestly** (precision, coverage, latency on this GPU):
- (a) Laya fine-tuned on full crops.
- (b) Laya on per-slot card crops and per-glyph digit crops, segmented by classical connected components with a 13-way glyph `choice`.
- (c) Deterministic template matching against the client's fixed card and digit sprites.

Option (c) is a strong **auto-labeler** for (a) and (b). If it also beats Laya at runtime, report it; the user decides. Laya stays the plan.

**5. Public HF datasets** for card or digit pretraining, with licences. Use them only if the licences are compatible with local, non-commercial use.

**Gate R:** a written training recipe that fits 8 GB, with the expected data volume and question-design changes. Present a summary to the user. Continue unless the research shows fine-tuning Laya is infeasible; in that case **stop and ask**.

### Phase D — data (no pixels outside `.local/captures`)

**1. Capture loop** (harness only), while the user keeps a table open:
- at least 400 table frames spanning preflop, flop, turn, river and showdown, and different pots and stacks;
- at least 40 lobby frames;
- other CoinPoker windows if the user opens them;
- six-max first, plus window sizes the user picks (no resizing by you).

Record the window size, timestamp and capture SHA-256 in `.local/laya/dataset/manifest.jsonl`.

**2. Labels:**
- `screen_kind` comes free and exact from the capture role (lobby vs table window).
- Board cards, pot and stack amounts, the dealer button, "Find Seat"/"Join Wait List" (unseated) and seat occupancy come from deterministic auto-labelers (template matching, connected components), seeded from a small exemplar set.
- Every auto-label carries its method and a match score. Ambiguous ones are excluded, never guessed.

**3. Splits:** by time and hand (no leakage between consecutive frames), into train, calibration and eval.

**4. Human step, batched once:** the user verifies a random **eval sample of at least 60 frames**. Generate a compact checklist from `human-worksheet.md`. Gate accuracy is measured only on human-verified labels.

### Phase F — question design 0.4.0 and fine-tune

**1. Redesign questions so that every option list fits in 256 tokens**, guided by Phase R:
- per-slot card crops, each with rank (15 options) and suit (6 options);
- per-glyph or per-character amount reading;
- tighter p0 evidence questions;
- an explicit `ev_seat_controls`;
- drop or replace questions the model cannot answer from a 512 px tile.

Update the source set, the expander and the vendored copy. `validate_phase_a.py` must pass.

**2. Fine-tune** from the pinned checkpoint with laya's trainer, bf16, within 8 GB:
- Log the config, data hashes and loss curves.
- Save to `models/laya-vision/finetuned/<UTC>-<run>/` (gitignored).
- Record SHA-256s in `scripts/laya-pins.json` under `model.finetuned`, with the CC-BY-NC-SA-4.0 note.
- At most 3 training iterations before reporting.

**3. Calibrate** on the calibration split (`agent.calibrate`). Fit per-pass thresholds.

**Gate F**, on the human-verified eval split, at the chosen thresholds:

| Measure | Target |
|---|---|
| screen_kind | ≥ 98% precision, ≥ 95% coverage |
| card rank and suit | ≥ 99% precision among confident answers, ≥ 85% coverage |
| amounts | ≥ 99% precision, ≥ 85% coverage |
| p0 warm | < 300 ms |
| tier-0+1 battery (unseated) | < 1000 ms |
| full six-max battery | < 2000 ms |

- **Only when Gate F passes:** set `thresholds.calibrated:true` with the per-pass thresholds. That flips D2.
- **If Gate F fails after 3 iterations:** stop, report the precision/coverage/latency table, and ask the user.

### Steps 4-8 of the integration plan, re-tied to the fine-tuned checkpoint

**Step 4: `scripts/laya-server.py`** (serve / fetch / verify):
- `127.0.0.1:18090`, alias `coinpoker-laya-vision`.
- Pin-verifies the fine-tuned weights.
- Never logs images; bounded body, questions and timeouts.
- Optional `--answers-log` without pixels.
- stdlib-only tests in `scripts/tests/test_laya_server.py`.

**Step 5: Rust**
- `crates/ingest/src/laya.rs` plus `laya/{geometry,questions,assembly,client}.rs`. Assets via `include_str!`, no new crates.
- Assembly implements R1-R18 and the 0.4.0 changes, and self-validates with `parse_screen_output` (degrade, never repair).
- Pass order: p0, then the lobby-size guard, then R15, then tier 1, then tier 2 only if not unseated. Early exit once the state is already null.
- Remove `OpenAiServerBackend`, chat parsing and `VlmError::Truncated`.
- Config:
  - `--vlm-endpoint` default `http://127.0.0.1:18090/v1/laya/predict`, loopback only.
  - `--vlm-model` default `coinpoker-laya-vision`.
  - `--timeout-secs` default 5.
  - new `--laya-threshold` in [calibrated value, 0.99].
  - remove `--allow-remote-vlm`.
- Add the configuration-event fields: `perception`, `question_set_version`, `laya_threshold`, `laya_calibrated`.
- Focused tests:
  - geometry at 800x613, 1015x770, 1280x720 (pillarbox), 1280x963 and the lobby size;
  - each assembly rule;
  - a seeded loop of 1000 random answer maps that must all pass `parse_screen_output`;
  - client hygiene: loopback only, no redirects, body cap, timeout, no payload echo;
  - config.

**Step 6: Scripts, repurposed**
- `start-vlm.ps1`, `download-model.ps1`, `setup-windows.ps1`:
  - Laya env: conda + exact pip pins + `laya-server.py fetch/verify`.
- `doctor.py`:
  - lazy pins;
  - checks `runtime_asset`, `cuda_device`, `model_files_sha256`, `vlm_models`, and `multimodal_api` (red/blue choice probe);
  - offline-skip names unchanged.
- `lobby-observation.ps1`: Laya defaults.
- No new `.ps1` files.

**Step 7: Validation**
- `validate.py` 12/12 and record the test count.
- `validate_phase_a.py` PASS.
- `cargo build --release --locked`.
- `doctor.py` online and `--offline`, both exit 0.

**Step 8: Live run**
- Copy `run-timed.ps1` into `.local/acceptance/<UTC>-laya/`, dropping the Gemma args.
- Run 90 s on the unseated table, with the server answers log on.
- Write `analyze.py` (numbers only) and re-analyse run E with the same script.

**Success, all of:**
- fresh, schema-valid `poker_table` envelopes with non-null state and `action_required=false`;
- ≥ 50% of fresh table completions non-null;
- battery p95 inside the 1.6 s shortest quiet window;
- zero decisions (unseated, plus D2 until calibrated);
- the lobby classified as lobby.

During the run, take harness spot-check captures and label them afterwards, to measure live precision.

### Step 9 — docs and records
- Update:
  - `docs/LAYA_VISION_PHASE_A.md` (Phases B and C done, results, D1-D3);
  - `README.md`;
  - `docs/INSTALL_WINDOWS.md`, `docs/VLM_COMPATIBILITY.md`, `docs/WINDOWS_ACCEPTANCE_V1.md` (gate 3 re-baselined), `docs/EVENTS_V2.md`;
  - `CONTRIBUTING.md`, `SECURITY.md` (loopback 18090);
  - `MODEL_LICENSES.md` (fine-tuned weights);
  - addendum 10.
- Known gaps to record:
  - release packaging;
  - seated geometry still provisional;
  - six-max only;
  - cursor composited into frames (`windows.rs:449-458`).

## Stop and ask only for

- Install or training-stack problems you cannot solve.
- Phase R concluding that fine-tuning is infeasible.
- The batched human verification step (Phase D.4).
- A failed Gate F after 3 iterations.
- Anything needing a seated hero or window changes.

Report progress only at phase gates, with numbers.
