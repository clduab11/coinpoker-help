# coinpoker-help — Readiness Assessment and Validation Plan

Plan ID: 1791496776779. Baseline established Phase 0, 2026-10-08 UTC.
Companion artifact: `.local/acceptance/evidence-index.md` (full evidence inventory).

## 1. Executive summary

Late-stage engineering prototype, **not production-ready**. Core pipeline (ingest →
screen gate → state machine → decision → JSON-lines) is implemented and hardened;
synthetic validation passes; all 20 physical Windows acceptance gates remain UNRUN;
release decision is NO-GO.

Readiness toward "validated candidate for controlled evaluation":
- Core logic (Rust crates): ~90%
- Pipeline integration: ~85% (mechanism-1/2 fixes committed at f97ca44; live re-test pending)
- Synthetic validation: ~70%
- Windows capture/real-hardware: ~40% (design solid, physically unverified)
- Physical acceptance gates: 0% closed (gate 8 partial only)
- **Overall: ~55-65%. Critical path is physical validation, not new features.**

## 2. Phase 0 — COMPLETE (2026-10-08 UTC)

Baseline facts (verified this phase):
- Commit `f97ca441937b2662fdbf6365a954feef97e80e76` (2026-10-02 15:54 UTC,
  "Harden live capture, discovery, freshness, and privacy-safe events").
- Working tree **CLEAN** (empty `git status --porcelain`; describe = `f97ca44`, no
  `-dirty`). Contradicts acceptance doc's "working tree remains dirty" — candidate
  commit is now recordable as f97ca44 with no diff hash needed.
- Branch `checkpoint/seated-read-mechanism-2-20261002`; no tags; remote
  `origin = github.com/clduab11/coinpoker-help`. `main` exists; checkpoint branch
  is the work head. A second worktree holds `codex/clduab11/op-paperclip-foxtrot`.
- Workspace v0.1.0, edition 2021, rust-version 1.95; rust-toolchain pins 1.95.0
  minimal + rustfmt/clippy; rs_poker pinned 4.1 (arena off).
- Evidence consolidated into `.local/acceptance/evidence-index.md` with per-gate
  coverage matrix. Zero-evidence gates: 1, 4, 10, 11, 12, 17, 18 (13 effectively).
- Phase 1 prerequisites verified present: install doc, vlm-pins.json (hashes match
  VLM_COMPATIBILITY.md), all scripts, GGUF model + projector binaries on disk
  (GGUF magic confirmed; exact size/SHA enforced by tooling), llama.cpp b10964
  runtime extracted under `.local/vlm-runtime/b10964/`, candidate ZIP + SHA256SUMS
  in `dist/` (`fd3d97db...f57e`), ci.yml + release-windows.yml workflows,
  26-case synthetic manifest (format 2, incl. 4 staleness veto cases).

## 3. Phase 1 readiness — prerequisites verified, flagged items

All Phase 1 inputs exist. Four flagged items to resolve before/during execution:

1. **Endpoint drift**: docs and `scripts/vlm-pins.json` standardize on
   `127.0.0.1:8080`, but all 2026-10-01+ local evidence used `127.0.0.1:18080`
   (`vlm-color-probes.json` notes 8080 was occupied by an unrelated container).
   Before gate 3: either free 8080 or standardize the run on 18080 via
   `COINPOKER_VLM_ENDPOINT` and record the deviation in evidence.
2. **Table title unverified**: `windows-client-calibration.json` has
   `table_title_verified: false`; 2026-10-02 evidence shows the table window shares
   the exact lobby title `CoinPoker` (NLH label/table id are painted, not in the
   title). Gate 9 planning must assume title alone cannot select the table —
   size/identity discrimination is the current mechanism.
3. **Latency gap**: real 800x613 table-frame latency is 0/5 measured
   (`notes/latency.md`); original image bytes unavailable. Gate 3 requires
   capturing fresh frames and measuring cold/warm table-sized latency + memory.
4. **Suite drift check**: mechanism2-proof recorded 258 workspace tests passing at
   a dirty revision with a clippy failure at `bin/config.rs:210`; the tree is now
   clean at f97ca44. Gate 20 must re-run `scripts/validate.py` and record counts
   and CI run links at exactly f97ca44.

## 4. Phase 1 — Prerequisites & calibration (gates 1-3) [READY TO EXECUTE]

- [ ] Gate 1: clean Windows account, follow `docs/INSTALL_WINDOWS.md` literally;
      log prerequisites, Defender/firewall prompts, undocumented steps →
      `.local/acceptance/<UTC>/install-log.md`.
- [ ] Gate 2: `pwsh -File download-model.ps1 -Verify`; delete/rename one artifact
      and confirm startup refusal; record hashes + refusal evidence.
- [ ] Gate 3: `pwsh -File scripts/setup-windows.ps1` (runtime verify) then
      `pwsh -File scripts/start-vlm.ps1`; confirm `/v1/models` alias
      `coinpoker-gemma-4-e2b`; run doctor online probes; capture fresh table-sized
      frames and record cold/warm latency + peak RAM/VRAM.
- [ ] Calibration: `coinpoker --list-windows` before/after opening a table; record
      exe name, lobby/table title fragments, PID/HWND patterns, DPI. No pixels saved.

## 5. Phase 2 — Capture fidelity & lifecycle (gates 4-17) [BLOCKED on Phase 1]

- [ ] Gate 4: capture denied/unavailable → actionable reason, no advice visible.
- [ ] Gate 5: selected-window native pixels vs adjacent-window exclusion (critical).
- [ ] Gates 6-7: helper-first startup, bounded polling, client discovery without
      restart, updater behavior + `update.log` via real install evidence.
- [ ] Gate 8: all lobby views/previews → zero recommendations (extend 2026-10-02 records).
- [ ] Gates 9-13: table open/close/reopen lifecycle, fresh HWND/consensus, ambiguity
      handling, client relaunch recovery.
- [ ] Gates 14-16: unreadable/occluded/animated states; slow-inference discard
      (re-test mechanism-1 fix live); small-change clear before completion;
      EOF/expiry clear (first live clear event ever recorded).
- [ ] Gate 17: DPI 100/125/150, resize/move/multi-display, aspect/crop, pixel exclusion.

## 6. Phase 3 — Corpus & candidate validation (gates 18-20) [BLOCKED on Phase 2]

- [ ] Gate 18: held-out authorized real-image corpus vs `docs/VISUAL_EVALUATION_V2.md`
      thresholds; independent review of actionable states and coverage.
- [ ] Gate 19: download checksummed candidate ZIP into clean account; verify
      allowlist, execution, Authenticode status if requested, model setup.
- [ ] Gate 20: `python scripts/validate.py` + `pwsh -File scripts/windows-acceptance.ps1`
      at exact candidate revision; record test counts and CI run links.

## 7. Phase 4 — Remediation & closeout

- [ ] Any gate FAIL → file concrete issue with evidence, minimal targeted fix,
      re-run affected gates only. No broad refactors without evidence.
- [ ] Consolidate evidence under `.local/acceptance/`; update
      `docs/WINDOWS_ACCEPTANCE_V1.md` gate rows from UNRUN to PASS/FAIL/BLOCKED
      with UTC + sanitized paths.
- [ ] Update final recommendation (GO/NO-GO). GO = validated for controlled
      evaluation within stated constraints only.

## 8. Risks & assumptions

- Physical Windows host with the real client is required; CI cannot close gates 1-19.
- Client UI/title drift can break discovery; table-only title requirement is
  intentionally conservative.
- VLM requires pinned GGUF + llama.cpp b10964; GPU/VRAM affects gate 3 latency.
- Privacy: sanitized evidence only; personal titles not shared; `.local/` gitignored.
- Scope: validation + minimal remediation only; no new features.

## 9. Validation of this plan

- Plan file written to `.kilo/plans/1791496776779-repo-readiness-and-next-steps.md`.
- Phase 0 artifacts: this file + `.local/acceptance/evidence-index.md`.
- No source files modified; no mutating commands run; two read-only explore agents
  used for evidence/prerequisite inventory; git state captured read-only.

## 10. Out of scope

New features, refactors beyond gate-driven minimal fixes, commits (user controls),
release publication, non-Windows platforms.

---

## Appendix A — Phase 1 execution log (2026-10-08 UTC, run `20261008T224705Z-phase1`)

Executed the automatable portions of Phase 1 in-session. Evidence dir:
`.local/acceptance/20261008T224705Z-phase1/`.

- **Gate 2 — PARTIAL PASS.** `download-model.ps1 -Verify` exit 0 (pinned model +
  projector). Missing-artifact refusal: renamed projector -> verify exit 1 with
  "Missing model artifact: mmproj-gemma-4-E2B-it-BF16.gguf"; file restored.
  Evidence: `gate2-verify.txt`, `gate2-missing-refusal.txt`. Not separately tested:
  wrong-bytes corruption (only absence).
- **Gate 3 — PARTIAL PASS.** Pinned llama.cpp b10964 started on loopback
  `127.0.0.1:18080` (deviation: :8080 held by Docker/WSL) with alias
  `coinpoker-gemma-4-e2b`. First doctor run `multimodal_api` FAIL = cold-start
  timeout (cold prompt eval 52.3 s > PROBE_TIMEOUT_SECS). Warm re-run: `vlm_models`
  PASS, `multimodal_api` PASS, `model_files_sha256` PASS, `runtime_asset` PASS.
  Memory: llama-server WS 1748 MiB / peak 3731 MiB; GPU +~455 MiB (partial offload).
  Warm probe latency 1.27-1.99 s (64x64). Evidence: `gate3-doctor-online*.txt`,
  `gate3-server-log.txt`, `probe_debug.py`.
  **Unresolved:** table-sized (800x613/1280x1032) cold+warm latency and peak memory.
- **Gate 20 — PASS (after remediation).** Initial run FAILED clippy at
  `bin/config.rs:210`. Minimal fix applied (`.split(['x','X','×'])`, one line,
  behavior-preserving). Final `scripts/validate.py`: all 11 checks exit 0
  (259 Rust tests). Diff SHA256 `59A52540...`. Evidence: `gate20-summary.md`,
  `gate20-remediation.diff`, `gate20-report.json`.
  **Remaining:** CI run links at the candidate revision.
- **Calibration — BLOCKED.** CoinPoker client not running (no `CoinPoker*`
  processes); `--list-windows` calibration and table-frame capture require the
  installed client. Human step.
- **Open flagged item:** endpoint drift — docs/pins use :8080, live evidence uses
  :18080. Decide before the clean-account run.

### Appendix A addendum — scripted acceptance run (2026-10-08T22:58Z)
`pwsh -File scripts/windows-acceptance.ps1` -> `20261008T225802Z/`:
source-validation PASS, release-build PASS, synthetic-evaluation PASS,
doctor-offline FAIL, live-api-probes BLOCKED; all 20 gates UNRUN.
The doctor-offline FAIL is solely `coinpoker_discovery` blocked (needs
`COINPOKER_EXE_NAME` calibration) — no code defect. Calibration remains the single
in-session blocker for Phase 1; it needs the CoinPoker client running (human step).

### Appendix A addendum 2 — calibration + real-table latency blocker (2026-10-08T23:23Z)
Evidence: `.local/acceptance/20261008T232304Z-calibration/`, corpus
`.local/captures/20261008T232842Z-new-calibration`.

**Calibration works.** Client windows both titled `CoinPoker` (table 800x613 PID 32012
HWND 0x261ea4; lobby 1280x778 PID 68808). Config `exe=CoinPoker.exe`,
`lobby-title=CoinPoker`, `lobby-size=1280x778` selects the table via "same title as the
calibrated lobby at a different size". doctor `coinpoker_discovery` PASS.
(`lobby_metadata`/`table_metadata` remain BLOCKED — doctor.py expects distinct titles;
this client shares one. Doctor-script limitation, not a calibration error.)

**BLOCKER (functional).** Real 800x613 table-frame inference is 11.0-20.9 s (5/5 runs),
far above the 5000 ms `max_frame_age_ms` lease. Live pipeline discards every observation
as `observation-expired`; zero `table` events. Server breakdown: vision prefill ~0.2 s
(NOT the bottleneck); generation 520-1591 tokens at ~90 tok/s IS the bottleneck — the
model emits a long `reasoning_content` chain-of-thought before the JSON.

**Remediation options (need a decision; not applied):**
1. Suppress model thinking (server chat-template kwarg / `--reasoning-format`, or a
   request `chat_template_kwargs`/`/no_think`). Expected generation drop to ~150-300
   tokens (~2-4 s) → within lease. Requires re-validation of recognition (gate 18).
2. Lower `max_tokens`: truncation maps to `VlmError::Truncated` (safe rejection) — no
   reading, so not viable alone.
3. Raise `max_frame_age_ms`: allowed max 10000 ms < observed 11-21 s; insufficient, and
   the harness README forbids increasing the lease.
4. Different model/quant/hardware: out of scope.

User is in the room but not seated, so `action_required` is false → observation only
(no recommendations) even once latency fits; the fix would enable `table`/card readings.

### Appendix A addendum 3 — remediation applied and live-verified (2026-10-08T23:45Z)
Approved remediation implemented (working-tree diff SHA256
`D8BAD92FACFEA118A547299D43FBB8A97633FA2F4AC414D0822B42F30933DACB`, 4 files):
- `crates/ingest/src/vlm.rs`: request now sets `chat_template_kwargs:
  {enable_thinking:false}` (tested: 19.1 s/1683 tok -> 6.3 s/514 tok, same valid JSON).
- `crates/ingest/src/runtime.rs`: default `max_frame_age_ms` 5000 -> 8000 (range 500..10000).
- `crates/ingest/tests/live_runtime.rs`: 4 expiry tests pinned to explicit 5000 lease.
- `bin/config.rs`: earlier clippy fix.
`validate.py`: all 11 checks exit 0 (259 tests). Release rebuilt.

Live re-run (calibrated): NO `observation-expired` discards; analysis cycles complete and
classify. During the run only the lobby window was open (the table had been closed), and
the VLM correctly returned `lobby_detected` ("lobby title; no table recommendations") —
zero decisions/clears. A `table` event requires the table window to be open.

Calibration drift noted: a same-title window whose size != calibrated lobby size is
treated as the table, so re-list/re-calibrate after any lobby resize.

### Appendix A addendum 4 — Laya Vision Phase A executed (2026-10-09T02:00Z)

User approved the Laya Vision perception prototype; Phase A (question set +
calibration corpus) executed. Full spec: `docs/LAYA_VISION_PHASE_A.md`.

- Question set: 202 typed questions (16 tier-0 / 42 tier-1 / 144 tier-2) across
  region-crop passes, assembled into the unchanged strict envelope;
  `.local/laya/question-set.json` (validated by `.local/laya/validate_phase_a.py`,
  PASS; expanded set emitted for Phase B).
- Model facts corrected against the HF card: `thaitea/laya-vision` (201M),
  weights **CC-BY-NC-SA-4.0** (not Apache 2.0 as earlier research claimed);
  noul = yes/no probability (uncertainty via calibrated thresholds +
  `agent.calibrate`); score = ordinal rubric (amounts redesigned as digit-slot
  choice questions incl. '.'/','); one 512px image per pass (region crops
  mandatory).
- Baseline evidence (`.local/laya/baseline/`): table.png 6138/5811 ms — first
  recorded Gemma table envelope is schema-invalid (preflop with 4 board cards,
  boolean hero_cards, float amounts 1.05/12.45, no Hero, action_required without
  readable cards) and would be discarded by the live validator; lobby.png
  1318/1395 ms, schema-valid lobby/null. Decimal amounts indicate 2-decimal
  currency display (pending human confirmation).
- Pending human step: `.local/laya/human-worksheet.md` — region boxes, amount
  format, ground-truth answers, baseline verification. Phase B is blocked on it.
- No pipeline code modified; new files only (docs/ + gitignored .local/laya/).

### Appendix A addendum 5 — reference-sheet content folded into core-engine + 6-max position vocab (2026-10-09T02:35Z)

Implemented the screenshot-content plan (poker-info-sheet.pdf + screenshot-1/2):

- **`crates/core-engine/src/outs.rs`** (new): rule of two and four, exact
  turn/river combinatorics (47 unseen), and the five memorized draws with
  printed percentages kept verbatim (flush 9 outs 19/35, OESD 8 outs 17/32,
  two overcards 6/13/24, gutshot 4/9/17, set draw 2/4/8). The sheet rounds
  loosely (8-out two-card 32% is the rule-of-four value, exact 31.45%);
  flagged as suspect in code. Tests assert every printed value sits within
  one percentage point of exact.
- **`crates/core-engine/src/ranges.rs`** (new): six-handed preflop opening
  ranges as deterministic lookups — `Position6max` (UTG/HJ/CO/BTN/SB/BB),
  `HoleClass`, notation parser (`77+`, `AJs+`, `ATo+`, exact tokens),
  cumulative tiers (UTG 17 classes, HJ/CO 34, SB/BTN 49, BB never opens),
  and `RANGE_SUSPECTS`. Ranges transcribed from screenshot-2 via the pinned
  Gemma VLM (two runs, identical output). Three transcription inconsistencies
  flagged verbatim pending human verification: `K5s` and `QJo` print in both
  tier 2 and tier 3; `ATo` in tiers 2/3 is subsumed by tier 1's `ATo+`.
- **`crates/core-engine/src/equity.rs`**: `Rank` gains `Hash` (needed by
  `HoleClass`).
- **Question set**: `hero_position` now uses the new 6-max vocabulary
  `hero_position_6max` (UTG/HJ/CO/BTN/SB/BB/unknown, instructions updated);
  the 9-hand vocabulary is kept reserved as `hero_position_9max`.
  `validate_phase_a.py` still PASS (202 questions, 16/42/144 tiers).
- **Docs**: `docs/LAYA_VISION_PHASE_A.md` section 6 + new 6.1 (range/odds
  provenance); worksheet hero_position row updated to 6-max names.
- **Validation**: `scripts/validate.py` all 11 checks exit 0 — now **281
  Rust tests** (was 259); clippy `-D warnings` clean.

Seating-convention note: the sheet's tiers name hijack and cutoff, fixing
six seats as UTG/HJ/CO/BTN/SB/BB. If the reference table seats an MP
position, treat MP as opening the tier-1 base range like UTG (documented in
`ranges.rs` and the Phase A doc).

### Appendix A addendum 6 — Gate 20 CI evidence + state check (2026-10-09T03:45Z)

- **State re-verified:** HEAD f97ca44, 15 uncommitted/untracked entries matching
  addenda 3-5. The Laya worksheet and both annotation JSONs are unchanged since
  02:30Z / 01:57Z (human labels still `pending`), so **Phase B stays blocked**.
- **Gate 20 CI links recorded** (in `gate20-summary.md`): the only CI run at f97ca44,
  37030966828, **failed** on both Quality jobs (windows exit 1, ubuntu exit 101).
  All tests passed. The single error is clippy `manual-pattern-char-comparison` at
  `bin/config.rs:210`, the lint already fixed locally. Gate 20's remote half closes
  green only after the working-tree diff is committed and pushed (user-controlled).
- **Open human steps (all blocking):** (1) fill `.local/laya/human-worksheet.md` or
  the annotation JSONs → unblocks Laya Phase B; (2) verify the three `RANGE_SUSPECTS`
  against screenshot-2; (3) commit/push the candidate diff → CI re-run for gate 20;
  (4) open a table window while the calibrated pipeline runs → first live table
  event; (5) settle the :8080 vs :18080 endpoint before the gate-1 clean-account run.

### Appendix A addendum 7 — plan implementation pass (2026-10-09T04:08Z-06:05Z)

- **Endpoint (user decision: 18080):** runtime default (`crates/ingest/src/vlm.rs`),
  `scripts/start-vlm.ps1`, `scripts/doctor.py`, README, INSTALL_WINDOWS,
  VLM_COMPATIBILITY and the acceptance report now use `127.0.0.1:18080`. The plan's
  claim that `scripts/vlm-pins.json` pins 8080 was wrong; it has no endpoint. Remaining
  8080 strings are loopback-validation fixtures and the historical 2026-09 record.
- **PDF drives the Laya logic (user directive):** new `core-engine::table_rules` derives
  nine-handed positions (sheet p.6, anchored BTN/SB/BB/UTG/CO/HJ, then UTG+1/MP1/MP2;
  heads-up and invalid layouts are errors, never guesses) and the street from the board
  count (p.3-4). Laya question set **0.2.0** (203 questions, 17/42/144): new
  `dealer_button_seat`; `hero_position` (sheet's nine names) and `game_phase` demoted
  to cross-checks with `derived_by`; Bet maps to `raise`; rules R4/R9 rewritten and
  R11-R14 added. `validate_phase_a.py` pins the PDF SHA-256 `5ce3a3f8…7de6` and
  enforces the derivation inputs: PASS. Worksheet and Phase A doc section 6 rewritten.
- **Provenance correction:** the PDF contains neither the opening ranges nor the odds
  table; they come from screenshot-2 / screenshot-1.
- **Ranges corrected (supersedes addendum 5's tiers and RANGE_SUSPECTS):** the Gemma
  transcription dropped dash ranges and misread tokens (8.7% coverage vs printed 14%).
  Re-read at 3x: tier 1 `22+ ATs+ A5s-A2s KTs+ QTs+ JTs T9s 98s AJo+ KQo`, etc. Exact
  190/338/574 combos = 14.33/25.49/43.29% vs printed 14/26/43. Parser gained dash
  notation; tests pin the combos, percentages ±1 pt and tier disjointness. UTG 33,
  HJ/CO 58, SB/BTN 89 classes. RANGE_SUSPECTS removed (resolved).
- **Region boxes:** agent proposals (geometry only) for board, pot, 6 seat plates and
  provisional hero_cards/action_buttons, drawn and checked on table.png. Recorded in the
  worksheet and `table.annotation.json` (`proposed_unverified`). Human ground truth is
  still pending, so **Phase B stays blocked**.
- **Validation:** `scripts/validate.py` 12/12 checks exit 0, **293 Rust tests**.
- **Commits/pushes (checkpoint branch):** c5a145a (endpoint/lease/thinking/clippy +
  acceptance evidence), 81f5998 (table_rules, ranges, outs, Laya doc) = **candidate**,
  3f525a4 (acceptance report: gate 20 PASS). Untracked by design: PDF, screenshots,
  `.conda/`, `.kilo/`, `environment.yml`.
- **Gate 20 PASS:** CI run 37883810315 success at 81f5998 (windows 293 / ubuntu 294
  tests), completed 2026-10-09T04:36:30Z.
- **First calibrated live table run** (20261009T055858Z, 90 s): the resized 1015x770
  table was selected by size. 3/3 completions were discarded as obsolete (the frame
  animated during inference); model readings were 2 non-table, 1 schema-invalid. Zero
  table events. Gate 9/14/15 rows updated with partial evidence; still UNRUN.
- **New open decisions:** (a) animated-table starvation: mask timer/animation regions
  or use per-region change thresholds (the lease cannot rise); (b) Gemma real-table
  perception 0/4 valid: Laya Phase B/C, or a prompt/model change. Neither applied.
- **Still human-blocked:** worksheet ground truth (Phase B), gates 1, 4-19 physical runs.

## Appendix A addendum 8 — animated-table starvation: root causes, remediation, live verification (2026-10-09T06:05Z-07:35Z)

Evidence dir: `.local/acceptance/20261009T061624Z-starvation/` (summary.md, timed runs
A-E, probes 1-7, offline simulator, deterministic repro). No pixels in evidence; one
verification PNG via the existing proof harness under
`.local/captures/20261009T062531Z-new-calibration/`. Working tree at 3f525a4 + this diff.

- **Timed live runs.** A wrapper (`run-timed.ps1`) stamps every helper event with UTC and
  elapsed ms (the helper's events carry no time). Run A (defaults): 5/5 completions
  obsolete; the frame changed 330-470 ms after every submission; inference for the
  model's short non-table envelopes was only 1.25-1.37 s.
- **Per-tile churn probe** (`change-probe`, gitignored `.local/diag/`, public
  `ingest::capture` API, geometry and counts only): the live 1015x770 table changed in
  297/298 consecutive 100 ms captures; longest quiet window 91 ms; churn confined to
  seat avatars/badges (two ~64x80 px clusters changing every ~200 ms at 20-60% of a
  16x16 tile), their anti-aliased fringe, and slowly pulsing seat-plate glows. With
  `local_changed_fraction` 0.003 on 16x16 tiles any single pixel > 8 flags the frame.
  Threshold tuning cannot separate this from a card/amount change.
- **Second, independent cause (deterministic repro):** `force_refresh_ms` 5000 <
  measured 5.8-6.3 s table inference; `runtime.rs:323-329` bumps the epoch mid-flight,
  so a perfectly static table is never accepted (`forced_refresh_starvation.rs`: 0
  decisions, all obsolete; 8000 publishes). Not changed: the user questioned raising it
  given Laya's latency target. Facts: Laya is not in the pipeline yet; the shipped
  perception is Gemma; on an active table there were no quiet windows >= 6.6 s in four
  minutes of probes, so the forced refresh is only binding for a static table (hero's
  own turn with everyone waiting). Decision still open.
- **Decision (a) approved: adaptive per-tile animation suppression**, implemented in
  `crates/ingest/src/change_detect.rs` in five measured iterations (table in
  summary.md): tiles changing in >= 6 of the last 20 captures are suppressed, with
  hysteresis (release at 3), 8-neighbour dilation, motion counted at any byte
  difference (slow glows step 2-5 levels per capture, below `channel_delta` 8, and drift
  past the baseline every ~300 ms without ever registering as motion), and a 30% cap
  (15% released everything in 144 of 897 live captures). New config fields
  `animated_window`, `animated_hits`, `animated_channel_delta`, `animated_max_fraction`
  (defaults 20 / 6 / 0 / 0.30, validated, echoed additively in the configuration
  event; no CLI flags per the decision). Diagnostics-only accessors
  `suppressed_tiles()` and `trigger_tiles()`. Semantics: a suppressed tile never
  replaces the baseline on its own and is compared again once it stops; a change in an
  unsuppressed tile still invalidates in-flight work; staleness inside suppressed tiles
  is bounded by the forced refresh. 9 unit tests + 1 integration test
  (`persistently_animated_tile_does_not_starve_inference`). `scripts/validate.py` 12/12
  exit 0, 303 Rust tests (was 293). README architecture/limits and gate 14/15 rows updated.
- **Live verification (run E, 90 s):** 28 submissions, 13 obsolete, **15 completions
  accepted fresh — the first on a live table**. Readings: non-table / invalid /
  schema-invalid (three full table envelopes took 5.6-6.4 s and were obsolete). Zero
  decisions (unseated view; real-table Gemma readings now 0/12 valid).
- **Hard limit:** real state changes on an active six-max table arrive every few
  hundred ms; longest quiet windows 4-7 s. A ~6 s envelope cannot be published on an
  active table regardless of masking. Sub-2 s perception (Laya Phase C target) is a
  requirement for live advice, not an optimisation.
- **User questions answered in-session:** no UI exists yet (`--ui` exits 2; the
  `decision` JSON already carries action, amount, ev, pot_odds, equity, break_even and
  the lease; an unwired egui panel in `crates/ui` renders exactly those fields behind the
  `desktop` feature; wiring it is a separately scoped feature). Laya status: Phase A
  design only — no weights downloaded, no inference run, no backend; by design it would
  emit the same strict envelope and could be the sole backend if Phase C clears targets.
  Blocked on the human worksheet; a Phase B-lite latency/API smoke on the two saved
  captures needs no labels but needs approval for downloads/installs.
- **Also observed, not acted on:** `windows.rs:449-458` never disables WGC cursor
  capture (pointer composited into frames; property needs Windows 10 2004+).
- **Still human-blocked:** worksheet ground truth (Laya Phase B), seated/actionable
  view, gates 1, 4-19 physical runs, commit/push of this diff (user-controlled).

## Addendum 9 — Laya Phase B-lite executed; gate failed, Laya not wired (2026-10-09T15:33-16:40Z)

Plan: `.kilo/plans/1791560010000-laya-live-backend.md`.

**User decisions (15:4xZ):**
- D1: remove Gemma now, Laya sole backend.
- D2: observation-only until calibrated.
- D3: strict game_phase.
- D4: commit and push the addendum-8 diff.

D1 depended on the Phase B-lite gate passing. It did not pass, so D1 was not applied.

**Step 0 (16:10Z): done.**
- Verified 4 modified files.
- `scripts/validate.py` 12/12, 303 Rust tests.
- Committed **4ccad18** "Suppress persistently animated tiles so live tables reach fresh
  analysis" and pushed to `origin/checkpoint/seated-read-mechanism-2-20261002`.
- CI run **37957205975**: success (10m50s).
- Run E recount from its jsonl: 28 submissions / 27 completions / 13 obsolete → 14 fresh
  (summary.md says 15).

**Step 1 (16:12-16:20Z): done.**
- `conda.exe` from the Kilo plugin failed ("uv trampoline"). `python -m conda` with
  `-c conda-forge --override-channels` worked.
- Env: Python 3.12.15 at `.local/laya-runtime/env`.
- Packages: torch 2.11.0+cu128, torchvision 0.26.0+cu128, transformers 5.19.0, pillow
  12.3.0, laya `9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c`.
- CUDA OK: RTX 4060 Ti, driver 610.88.
- Weights: `thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc` (full fp32
  checkpoint, processor and backbone config bundled, so no separate backbone download)
  in `models/laya-vision/hf`. Offline load verified.
- Pins and SHA-256: `scripts/laya-pins.json` (new, status evaluation-only).
- `MODEL_LICENSES.md` gained a Laya section (CC-BY-NC-SA-4.0, personal local use).
- VRAM: 6.2 GB of 8 GB was already used by the Gemma server; Laya bf16 peak is 542 MiB.

**Step 2 (16:15-16:20Z): done.**
- Question set 0.3.0: R5 left-aligned digits with overflow guard; R6 explicit; R15-R18;
  `thresholds.calibrated:false`; model notes.
- Expander bugs fixed: `p5_seat_{i}`, `<i>`, short digit text. Passes are now emitted.
- `validate_phase_a.py`: PASS, 203 questions (17/42/144).
- Vendored to `crates/ingest/assets/laya/question-set.json`, plus `regions.json`. Both
  are untracked new files with no Rust consumer.
- Numeric geometry probe: T = 28 px unscaled, content aspect 1.3677, pot label and
  board cards inside their boxes. Evidence: `.local/laya/phase-b/geometry-v2.json`.

**Step 3 (16:22-16:35Z): GATE FAILED → stop condition.**
- Evidence: `.local/laya/phase-b/SUMMARY-20261009T1650Z.md`.
- G1 API: pass.
- **G2 screen_kind: fail.**
  - lobby → `poker_table@0.41`; tables → `poker_table@0.72` / `@0.66`.
  - One refinement round (descriptions, 2 permutations, 2 noul forms) did not fix it.
- G3 latency:
  - p0 250-320 ms warm.
  - Six-max battery 2.1-2.8 s (target < 2 s).
  - Tier 0+1 0.92-1.05 s.
- Reads:
  - Card questions are truncated (54 options exceed the 256-token budget).
  - Rank/suit split and per-slot crops are still wrong.
  - Pot digits read `1111111` and `5555555`.
  - 0 of 138 crop questions are confident.

**Not done, as the plan requires once the gate fails:**
- Steps 4-8: no server, no Rust backend, no Gemma removal, no script or doctor changes,
  no live run.
- The Gemma backend, scripts and `vlm-pins.json` are unchanged. The Gemma server (PID
  24812) was not touched.

**Uncommitted (user commits or discards):**
- `scripts/laya-pins.json`
- `MODEL_LICENSES.md`
- `docs/LAYA_VISION_PHASE_A.md` (§7 B-lite status, §8)
- `crates/ingest/assets/laya/{question-set.json,regions.json}`

**Decision needed:**
- **(a)** Domain fine-tune plus calibrate Laya. Needs labeled captures (worksheet) and
  has licence implications.
- **(b)** A different perception model.
- **(c)** Keep Gemma and attack its latency.

## Addendum 10: Laya it1 continuation completed; Gate F FAIL (2026-10-09 UTC)

**Gate F FAIL; human verification UNVERIFIED; `thresholds.calibrated:false`.**
The existing sequential pipeline completed successfully at `22:00:15.956Z`,
including fine-tuned pin verification. Board abstention and full-battery
latency independently fail acceptance. The continuation stopped without
iteration 2-3, downstream validation, release build, doctor invocation, or
the 90-second live run. No commit, push, upload, release/workflow change,
client input, new PowerShell file, or Gemma restart was made.

The implementation request was `21:10:59Z`; `21:28:12Z` was a documentation
checkpoint, not the request time or session end. The resume handoff was
`21:53:39Z`. Earlier Gemma live runs in addenda 7-8 are not Laya Step 7 evidence.
This addendum extends, rather than retroactively rewrites, addendum 9's B-lite
failure. Existing uncommitted work is preserved; the user commits.

### Evidence Basis and Time Semantics

The detailed chronology was collected from local artifacts: command records,
logs, raw/score/calibration files, embedded stamps, hashes, and file metadata.
User messages supply request times and scope, not the detailed phase chronology. A
manifest or checklist **stamp** is an embedded recorded time; **mtime** is a
file modification time, not proof of a phase start or completion. **Derived**
endpoints use the reported start plus wall duration and are approximate.
Where exact start/end times are unknown they remain unknown. All times below
are on **2026-10-09 UTC**, with `Z` denoting UTC; no planning end time is inferred.
The current MemPalace MCP query was available and returned only low-relevance
October 3 Laya-text model records, with no supportive Gate F drawer. The earlier
planning claim of unavailability is not the current state. No external citation
or memory record is substituted for this local evidence.

### Prior Session: Phase Timeline

| Phase / artifact | UTC evidence | Status / interpretation |
| --- | --- | --- |
| Earlier prompt / planning | Prompt written `16:35Z` | Written-prompt time only; exact planning start/end unknown. |
| Research | `RESEARCH.md` mtime `17:07:28.026Z` | Research artifact exists; exact research interval unknown. |
| Original capture collection | Manifest stamps `17:05:43.075Z` to `19:19:43.192Z`; actual capture timestamps `17:05:42.646Z` to `19:19:42.735Z` | 1,406 original frames, all table; not a claim of uninterrupted capture. |
| Original geometry segments | First segment through `17:21:43Z`; second from `18:23:42Z` | 199 frames at 1015x770, then 1,207 at 800x613; exact gap activity unknown. |
| Dataset splitting | Original eval/splits mtimes unavailable after import | 630 train / 173 calibration / 114 eval / 407 late / 82 dropped = 1,406 originals. |
| Question-set 0.4.0 source | Source artifact mtime `18:26:51.039Z` | Artifact time, not an exact design-phase boundary. |
| Feature / autolabel implementation | `features.py` mtime `18:36:17.107Z`; `autolabel.py` mtime `18:39:08.565Z` | Exact implementation start/end unknown. |
| First smoke training | Start `18:42:40Z`; wall 10.92 min; derived end approximately `18:53:35.2Z`; log mtime `18:53:36.1Z` | Smoke only, not Gate F acceptance. |
| Second smoke training | Start `18:54:05Z`; wall 1.90 min; derived end approximately `18:55:59Z`; log mtime `18:56:00.101Z` | Smoke only, not a later full training iteration. |
| Example builder | `build_examples.py` mtime `18:59:01.009Z` | Exact implementation interval unknown. |
| Human checklist | Embedded stamp `19:03Z`; original mtime `19:03:43.847Z` | 66 rows generated; no human validation. Later response requested agentic review, not certification. |
| Full training it1 | Start `19:03:22Z`; wall 70.56 min; derived end approximately `20:13:55.6Z`; log mtime `20:13:57.763Z` | 1,469 steps; reported loss 1.7742 to 0.0373; no later train iterations. |
| Rust / backend implementation | Source mtimes approximately `19:15Z` to `19:24Z`; server `19:22:51Z`; question-set/assets `19:23:47Z` | Implementation evidence only; exact phase start/end unknown. |
| Dataset materialization | `features.jsonl` mtime `19:45:32.471Z`; `labels.jsonl` `19:49:13.609Z` | Artifact modification times; not independent label truth. |
| Original example outputs | Train `19:49:16.212Z`; calibration `19:49:16.343Z`; late `19:49:16.711Z` mtimes | Original eval/splits mtimes cannot be reconstructed after import. |
| Offline calibration dump | Raw-calibration mtime `20:30:08.704Z` | Raw scores alone do not establish calibrated thresholds or Gate F. |
| Prior handoff | Reported written `20:40Z` | Handoff time; exact session end unknown. |

Label-round artifact mtimes, not assumed start/end times or human approval:

| Artifact | UTC mtime |
| --- | --- |
| `labels-round1` | `17:15:18.389Z` |
| `labels-round2` | `18:28:35.097Z` |
| `labels-round3` | `18:30:24.782Z` |
| `labels-round4` | `18:31:34.352Z` |
| `labels-round5` | `18:34:33.749Z` |
| `labels-round6` | `18:35:36.163Z` |
| `labels-round7` | `18:39:10.466Z` |
| `labels-round8` | `19:02:31.674Z` |
| `labels-round9` | `19:48:24.502Z` |

The it1 peak of **4,960.8 MiB is 4.8445 GiB**, not the handoff's 4.96 GiB.
The training JSONL changed by approximately two examples after training began;
the final file hash must not be presented as proof of the exact bytes read
throughout it1. Low training loss is not held-out accuracy or calibration.
The prior handoff reported 332 tests, 39 targeted Laya option-order tests, and a
release build; those prior results were not rerun for this addendum and do not
prove that the continuation server is the release artifact.

### Continuation: Actual Phase Timeline

| Phase / artifact | UTC evidence | Status / interpretation |
| --- | --- | --- |
| User implementation request | `21:10:59Z` | Current-session request time; exact planning interval unknown. |
| Server / doctor tests | `21:13:28.843Z` to `21:13:31.314Z` | 29/29 tests; logs under `.local/laya/train/continuation-20261009/`. |
| User lobby screengrab import | `21:14:18.555Z` | Eval-only import, `screen_kind` ONLY, one label row; no seated annotations inferred. |
| Scoring-helper tests, pinned environment | `21:16:33.823Z` to `21:16:34.119Z` | 20/20 tests; continuation logs in the same directory. |
| Sequential offline pipeline: `dump-eval` | `21:17:05.728Z` to `21:28:19.770Z` | Exit 0; 115 frames, 965 groups, 6,182 predictions / 6,154 labeled examples. |
| Addendum continuation checkpoint | User message `21:28:12Z` | Documentation checkpoint only, not a pipeline or session end. |
| Sequential offline pipeline: `dump-late` | `21:28:20.080Z` to `22:00:03.788Z` | Exit 0; 407 frames, 3,370 groups, 21,406 predictions / 21,346 labeled examples. |
| Resume handoff / process inspection | User message `21:53:39Z`; original PID `71688` still active | Original late dump reused; no duplicate pipeline, dump, training, or model instance. |
| Temperature and pass-threshold fit | `22:00:03.948Z` to `22:00:10.078Z` | Exit 0; choice `3.7963288600952434`, noul `4.100601186779291`; fitted board threshold `1.0` retained. |
| Calibration score | `22:00:10.205Z` to `22:00:10.626Z` | Exit 0; 173 frames, 1,327 raw groups, 8,704 predictions / 8,684 labels. |
| Eval score (all auto-labeled frames) | `22:00:10.737Z` to `22:00:11.016Z` | Exit 0; not human-verified accuracy. |
| Late score (auto-labeled sensitivity split) | `22:00:11.127Z` to `22:00:11.871Z` | Exit 0; board precision undefined because no confident units. |
| Fine-tuned pinning | `22:00:11.978Z` to `22:00:13.333Z` | Exit 0; checkpoint files and temperature calibration pinned; question-set calibration remains false. |
| Checkpoint pin verification | `22:00:13.428Z` to `22:00:15.956Z` | Exit 0, `ok:true`, no problems; all preceding pipeline phase stderr files empty. |
| Sole loopback server | Started `22:01:21.371Z`; ready recorded in `server-bench.stdout.txt` | `scripts/start-vlm.ps1`, alias `coinpoker-laya-vision`, 127.0.0.1:18090; generated warm-up 986.2 ms. |
| Loopback model endpoint | `22:02:04.366Z` to `22:02:04.412Z` | Exit 0; correct fine-tuned path and base revision. `meta.calibrated:true` means loaded temperatures only, not Gate F approval. |
| `bench_server.py 30` | `22:02:10.953Z` to `22:03:05.348Z` | Exit 0, stderr empty; 28 warm samples after 2 warm-up frames. Full-battery p95 3,027.3 ms FAIL. |
| One human-verification question | Prepared `22:04:03.504Z`; response recorded `22:07:41.425Z` | Response: "Make the check for me agentically." No table frame or decimal convention was human-certified; no gate exception approved. These are local observations, not exact message timestamps. |
| Intentional server shutdown | `22:08:29.195Z` to `22:08:30.914Z` | Recorded stop exit 0; launcher then ended `22:08:32.146Z`, exit 1 due to intentional termination. No predict/benchmark failure is inferred from that shutdown code. |
| Read-only artifact audit | `22:10:07.207Z` to `22:10:09.609Z` | Exit 0; all three scores reproduced without GPU, complete split groups/frames checked, protected dataset and vendored-question hashes unchanged. |
| Final checkpoint pin verification after status edit | `22:14:53.127Z` to `22:14:55.472Z` | Exit 0, `ok:true`, no problems. |
| Independent agentic visual review | Rows 45-66 result received `22:10:17Z`; rows 23-44 / 1-22 persistence clock observations `22:22:04Z` / `22:22:15.046Z`; results aggregated `22:25:48.590Z` | All 66 original PNGs inspected individually; all claimed fields matched, no corrections or unsure claimed fields. Review-start/end times were not recorded; persistence times are not completion times. |
| Agent-reviewed frame-filter audit | `22:28:53.125Z` to `22:28:54.838Z` | Exit 0; all 66 IDs exactly covered by disjoint reviews; every filtered path matches the canonical sample. |
| Supplemental filtered agent-review score | `22:29:02.972Z` to `22:29:03.459Z` | Exit 0; explicit `--frames`, 66/115 frames, 3,589/6,182 predictions selected, 2,593 excluded; not human acceptance. |
| Final read-only score / preservation audit | `22:29:52.053Z` to `22:29:53.468Z` | Exit 0; all original and filtered scores reproduced; protected hashes unchanged, source/vendor calibrated false, exact agent-reviewed filter checked. |
| Live run / validation Step 7 | No start/end | NOT RUN; blocked by failed Gate F, not passed or silently waived. |
| Later training iterations | No start/end | NONE; no it2/it3 or retraining. |

The lobby import is `lobby-user-screengrab.png` under
`.local/captures/.../lobby/`, source `user-screengrab`, 1278x785, 316,282 bytes,
SHA-256 `666bd9835d7f41fcfe37cd393fc424796b7d4681b7d072447bc3c931c06d2e90`.
Provenance: `.local/laya/dataset/human-check/lobby-user-screengrab-import.json`.
The updated eval set contains **115 frames (114 table + 1 lobby), 6,154 examples**.
Train remains **34,297 examples**, SHA-256
`c6e8c99be0f70b0792766343cc002bdd783aeb68729758079cc690b3945e55a4`;
calibration **8,684** and late **21,346** examples are unchanged. This unchanged
continuation train hash does not remove the separate it1 input-mutation caveat.

The scoring helper's previous `--frames` bug was fixed; unknown frames and
incomplete glyph units are rejected. The 20 scoring and 29 server/doctor unit
test passes are retained, not rerun and not live acceptance. Fine-tuned pins are
now complete and verified in `scripts/laya-pins.json`; `status` records Gate F
FAIL and `model.finetuned.question_set_calibrated` remains false. Fitted
thresholds remain local in `calibration.json`, not activated in source/vendor.

Checkpoint: `models/laya-vision/finetuned/20261009T190322Z-it1`. Model SHA-256:
`84c008b976e72445ae07c58678af542b63f79548ad0a314f836f210bda3195a1`;
temperature calibration SHA-256:
`6efe677c0171d7af94cfb9d171d93499f25f76418f2b2d3f05c34e5801b82170`.
The run log reports 34,487 loaded examples (including synthetic examples),
while the preserved train JSONL has 34,297 rows; neither count removes the
separate historical post-start input-mutation caveat.

### Fitted Thresholds and Observed Scores

Accepted thresholds are pass-level and never below fitted values: p0 `0.995`,
board `1.0`, pot `0.8`, and all six p5 stack passes `0.8`. Targets are
screen_kind precision >=98% / coverage >=95%; game_phase and nine p0 path
questions precision >=98%; board and pot precision >=99% / coverage >=85%.
p5 precision/coverage is reported separately and is non-blocking. No confident
items is not a pass. A late-split gated precision failure cannot authorize
`calibrated:true` without an explicit user exception; none was requested or
approved. A fitted threshold of `1.0` was NOT clamped to `0.99`.

Below: **precision / coverage in %**, on original auto-labels. These are
diagnostic split scores, NOT a human-verified Gate F result. Zero confident
board units means undefined precision, not 100% precision.

| Metric | Calibration | Eval (115 frames) | Late (407 frames) |
| --- | --- | --- | --- |
| screen_kind | 100 / 100 | 100 / 100 | 100 / 100 |
| game_phase | 98.86 / 56.05 | 100 / 54.29 | 99.19 / 70.49 |
| p0 ev_table_layout | 100 / 100 | 100 / 100 | 100 / 99.75 |
| p0 ev_hero_cards | 100 / 100 | 100 / 100 | 100 / 100 |
| p0 ev_board_area | 100 / 93.64 | 100 / 99.12 | 99.75 / 97.54 |
| p0 ev_pot | 98.80 / 95.95 | 99.09 / 96.49 | 100 / 97.05 |
| p0 ev_action_controls | 100 / 99.42 | 100 / 100 | 100 / 100 |
| p0 ev_readable | 100 / 100 | 100 / 100 | 100 / 100 |
| p0 ev_seat_controls | 100 / 95.38 | 100 / 98.25 | 99.75 / 98.03 |
| p0 hero_seat_index | 100 / 96.53 | 100 / 96.49 | 100 / 87.47 |
| p0 action_on_hero | 100 / 100 | 100 / 100 | 100 / 100 |
| Board rank+suit units | undefined / 0 | undefined / 0 | undefined / 0 |
| Pot complete-glyph units | 100 / 97.39 | 100 / 97.03 | 100 / 98.25 |
| p5 seat stacks (non-blocking) | 99.88 / 96.86 | 100 / 98.74 | 100 / 99.59 |

Confident errors, calib/eval/late: game_phase `1/0/2`; p0 ev_pot `2/1/0`;
p0 ev_board_area `0/0/1`; p0 ev_seat_controls `0/0/1`; p5 stacks `1/0/0`;
other listed metrics `0/0/0`. Board denominators are `863/568/2034`, with
zero confident units on every split. Board raw accuracy `90.50/92.78/96.02%`
does not rescue the confidence-gated failure. Nonempty late gated metrics
meet their precision targets, but the undefined board precision is blocking.

One warm latency run, including HTTP and battery crop/encode work as implemented
by the benchmark, with 28 samples per metric:

| Path | Warm p50 ms | Warm p95 ms | Gate: p95 <2000 ms |
| --- | --- | --- | --- |
| p0 | 213.2 | 271.0 | PASS |
| tier01 (p0 + board + pot) | 904.7 | 1497.9 | PASS |
| Full unseated six-max battery (+ six p5 stacks) | 1467.0 | 3027.3 | FAIL |

### Human Verification and Agent Review

The question tool was used once. Request/response evidence is retained in
`.local/laya/dataset/human-check/request-20261009T220403Z.json`. The user's
agentic-review request is not human certification or a waiver of board/latency
failure. Omitted rows and silence are never verified. Original labels and
train/calib/late examples are preserved; agent review does not retrain or repair
their labels. The completed agent-review score is supplemental, clearly marked
non-human, and cannot set `thresholds.calibrated:true`.

Three disjoint reviewers independently opened every original PNG in rows 1-22,
23-44, and 45-66, including similar frames. **66/66 matched the checklist's
claimed fields; 0 corrections and 0 unsure claimed fields.** The unknown phase
entries in rows 1, 5, and 6 were retained, not assigned. Evidence is stored in
`.local/laya/dataset/human-check/agent-review.json` and its three referenced
`agent-review-{1-22,23-44,45-66}.json` artifacts. Only the displayed checklist
fields were checked, not every original p0 auto-label or live timing assumption.

The explicit `--frames .local/laya/dataset/human-check/agent-reviewed-frames.json`
score selected **66 frames and 3,589 raw predictions**, excluding 49 frames and
2,593 predictions. Its standard `score-eval-verified.json` output was renamed
to checkpoint `score-eval-agent-reviewed.json` and annotated `human_verified:false`
and `gate_f_acceptance:false` to prevent a false human-approval claim. No human
66-row score or full held-out human acceptance is claimed. The stored latency
medians remain from the unfiltered raw dump, explicitly `raw_dump_unfiltered`;
warm p50/p95 acceptance uses the independent 30-frame server benchmark above.

Filtered supplemental results, **precision / coverage in %**:

| Metric | Threshold | Labeled units | Confident units | Precision / coverage |
| --- | --- | --- | --- | --- |
| screen_kind (table only; lobby excluded) | 0.995 | 66 | 66 | 100 / 100 |
| game_phase (3 abstentions excluded) | 0.995 | 63 | 39 | 100 / 61.90 |
| p0 ev_table_layout / ev_hero_cards / ev_board_area / ev_action_controls / ev_readable / action_on_hero, each | 0.995 | 66 | 66 | 100 / 100 |
| p0 ev_pot / ev_seat_controls, each | 0.995 | 66 | 65 | 100 / 98.48 |
| p0 hero_seat_index | 0.995 | 66 | 63 | 100 / 95.45 |
| Board rank+suit units | 1.0 | 330 | 0 | undefined / 0: FAIL |
| Pot complete-glyph units | 0.8 | 61 | 59 | 100 / 96.72 |
| p5 seat stacks, non-blocking | 0.8 | 371 | 367 | 100 / 98.92 |

There were no confident errors in this subset; board raw accuracy 93.03% is
not gated precision and does not overcome zero confident units. This review
does not waive the independent board and full-battery latency failures.

Review caveats: the worksheet's board-defined phase at pot collection/award
does not prove betting is active (notably rows 34, 43, 64). Amounts were read
as displayed, never recalculated from blinds (row 14 pot `0.05`). Pot/stack
targets use dot decimals with variable precision; row 64's separate winnings
annotation `+0,22` demonstrates the whole UI is not uniformly dot-decimal.
This is an observation, not a currency-glyph test or human decimal confirmation.

### Acceptance and Remaining Gaps

- Gate F uses the accepted **pass-level, p5-nonblocking** interpretation:
  **FAIL** for board abstention and full-battery latency; **human UNVERIFIED**.
  `docs/LAYA_VISION_PHASE_A.md` section 7 and pins status record this stop.
- Practice and cash share the same repo, representation, and mechanism; there
  is no separate practice-mode implementation.
  **Both give NO seated advice: seated frames are `readable:false`, `state:null`.**
  Seated live validation remains unrun for both practice and cash.
- There is no hero-seated capture supporting trained p1 / `to_call` / `hero_chips` /
  raise / bets reads. Those regions and behaviors remain provisional/untrained
  and unrun. Enabling seated advice requires a separately approved seated-data
  session in THIS repo: user-controlled seating, harness captures, region
  measurement, labels/training, and its own Gate F; never a separate repo.
- Coverage is six-max only. One eval-only lobby image does not establish lobby
  generalization; 1278x785 does not validate the configured 1280x778 lobby guard.
- The Laya server/pins/prep are absent from the release packaging allowlist;
  there was no release/workflow change or new release build. Cursor compositing
  remains a known capture limitation. Currency-glyph handling is untested.
  Template matching is an alternative for the user's decision, not an
  implemented or validated replacement; no new workstream was started.
- Weights remain local and nonredistributed. No license/distribution clearance,
  physical acceptance closure, or production readiness follows from this work.
- Root `lobby-screengrab.png` remains untouched; the user must delete that root
  file. The byte-identical eval-only copy remains under `.local/captures/`.

### Final Artifact Index

| Result | Evidence / outcome |
| --- | --- |
| Calibration raw predictions | Checkpoint `raw-calib.json`; SHA-256 `8c09b079d50b75633f926b75a37396d02a59b7d30c0b00d3a959740a6e4dd9a2`; reused, not dumped again. |
| Eval raw predictions | Checkpoint `raw-eval.json`; SHA-256 `6166900a4bf68b605254225353673113ba8d62d7706dc8d0000496013874fdb2`. |
| Late raw predictions | Checkpoint `raw-late.json`; SHA-256 `a18bb147d5c3d5577351face75cdd02b43cd4778dacf32563f31d5e9e9c19db8`. |
| Fitted temperatures and thresholds | Checkpoint `laya-calibration.json`, `calibration.json`; no downward threshold override. |
| Split scores | Checkpoint `score-calib.json`, `score-eval.json`, `score-late.json`; auto-label diagnostics, not human certification. |
| Recorded commands and stderr | `.local/laya/train/continuation-20261009/{label}.run.json`, `.stdout.txt`, `.stderr.txt`; UTC starts/ends and actual exit codes. |
| Artifact and preservation audit | `artifact-review.stdout.txt` / `.run.json` in the continuation logs; complete group/frame checks, score reproduction, protected hashes. |
| Fine-tuned checkpoint / pins | `scripts/laya-pins.json`; verification `ok:true`; final failure status, `question_set_calibrated:false`. |
| Warm p50/p95 | `bench-server-30.stdout.txt` / `.run.json`; full-battery FAIL, not retried for a favorable sample. |
| Human checklist | `request-20261009T220403Z.json`; human UNVERIFIED; agentic visual review requested instead. |
| Completed agent review / filtered score | `human-check/agent-review.json`, three disjoint review artifacts, explicit `agent-reviewed-frames.json`, checkpoint `score-eval-agent-reviewed.json`; 66 matched frames, supplemental non-human evidence. |
| Final filtered-score and data-preservation audit | Continuation `artifact-review-final.stdout.txt` / `.run.json`; exit 0 at `22:29:53.468Z`, exact subset and scores reproduced, protected hashes unchanged. |
| Machine-readable gate closeout | Continuation `gate-f-result.json`; failed gate, no human approval or calibrated flag activation. |
| Gate F / downstream acceptance | **FAIL; calibrated:false; validation, release build, doctor, and live run NOT RUN.** |
| Additional training | **NONE** beyond previously recorded smoke, smoke2, and it1. |

## Addendum 11: Practice-dashboard infrastructure (2026-10-10 UTC)

**First software phase implemented and tested; manual-data checkpoint reached.**
Implementation request: `01:33:43Z`, for
`.kilo/plans/1791590483000-practice-sandbox-dashboard-and-history.md`.
Read-only browser and API are available at **http://127.0.0.1:18090/**. The model
is loaded, capture is idle, and advice remains unavailable. This is actual
Practice Games development scope, not cash/public-deployment acceptance or a
separate practice-mode repo/representation.

### Implemented Boundaries

- Active README, license, installation, compatibility, contribution/security and
  current acceptance instructions identify Laya and 18090. Historical Gemma
  hashes/ports/receipts are marked historical, not globally falsified/deleted.
  Product CLI/doctor reject retired or alternate endpoints; hostile/ephemeral
  transport tests and third-party dependencies are not treated as product defaults.
- Same-port local dashboard, model-loading/status separation, bounded concurrent
  HTTP, one GPU admission slot, no browser process/poker controls. A slow or failed
  model cannot turn status into advice. Replay is explicitly synthetic; references
  are facts, not positive seated images. No raw images/responses/names are served.
- Fresh admitted full-state observation versus weak legacy table reading; ticket,
  source timestamps and expiry; no-advice invalidation and capture heartbeat;
  source/stream/order/expiry/hide/disconnect clearing without lease renewal.
- Pure bounded history observer with opaque identities, occurrences, partial-hand
  and missed-action gaps, trustworthy full-aggression prefixes and known-only
  denominators. Private 10,000-record/25 MiB prefix-preserving per-session ledger.
  Current baseline hook records unvalidated-source gaps, not player actions or
  inferred profiles. Live badge/bet recognition and history-conditioned ranges
  are not represented as completed capabilities.
- Explicit 5000-ms total decision deadline (500..5000), including a 300-ms
  publication reserve; every Laya pass gets remaining time, not a new 5 seconds.
  Late results stay withheld. The original 3027.3-ms full observation benchmark
  is not a seated or capture-to-browser result; new end-to-end acceptance is unrun.

### Actual Validation Chronology

Command starts/ends below come from retained local `.run.json` records. Browser
times are actual tool-result timestamps, not implementation/request times.

| Check | UTC | Actual result |
| --- | --- | --- |
| Initial Python suite | `02:09:28.130Z` to `02:09:34.238Z` | 50 passed; later integration added cases. |
| Initial integrated suite | `02:24:54.490Z` to `02:25:00.534Z` | Exit 1: Windows reset an unread rejected POST connection; fixed bounded body draining. Failure retained, not hidden. |
| First Rust workspace suite | `02:38:04.361Z` to `02:38:54.885Z` | Exit 101: observer fixture carried known zero wager into a new hand while claiming Raise. Production contradiction guard correctly rejected it; fixture evidence corrected to unknown. |
| Fixed Rust workspace suite | `02:48:02.234Z` to `02:48:13.102Z` | Exit 0: **397 passed, 1 ignored**, including all **32 observer tests**. No safety guard was relaxed. |
| UI-only server and intentional stop | Started `02:24:40.509Z`; stop `03:00:53.915Z` to `03:00:55.827Z`; launcher ended `03:00:56.216Z` | Stop command exit 0; launcher exit 1 from intentional owned-child termination. No unowned process/client was stopped. |
| Release compilation | `03:00:53.902Z` to `03:02:12.598Z` | Exit 0; compiled updated native executable. No packaging/workflow/release action. |
| One model/dashboard start | `03:02:51.497Z`; left running | One Laya instance, no live config/feed, existing checkpoint verified/loaded. Generated warm-up **3273.1 ms**, not latency acceptance. |
| Baseline preservation audit | `03:03:08.708Z` to `03:03:11.019Z` | Exit 0; train/calib/eval/late, labels, vendored questions and all original/filtered scores unchanged/reproduced. |
| Model endpoint | `03:06:07.322Z` to `03:06:07.398Z` | Exit 0; correct alias/checkpoint/revision, temperature calibrated, `quality_gate:failed`, `seated_advice_supported:false`. |
| Initial doctor | `03:06:40.402Z` to `03:06:46.713Z` | Alias/generated colors passed; hash check incorrectly rejected HF snapshot blob links. No capture. Diagnostics retained. |
| Artifact boundary audit | `03:16:55.701Z` to `03:16:55.950Z` | Confirmed model bytes also resolve into shared `hf/hub/blobs`, not only repository blobs. Size matches pins. Validator now permits only configured hub plus exact pinned hashes and relative paths; FT confinement preserved. |
| Final Python suite | `03:19:04.978Z` to `03:19:10.636Z` | Exit 0: **53 tests passed**, including cache-link/escape regression. |
| Final doctor | `03:19:04.873Z` to `03:19:13.349Z` | **10 checks passed, no failures**; `coinpoker_discovery` intentionally BLOCKED, overall exit 1. No captured/saved client pixels or physical acceptance. |
| Synthetic browser lease tests | `03:24:02.451Z` | **7 passed**: expiry despite polls, closed-version replay blocked, new version recovery, older packets rejected, disconnect clearing, unapproved advice rejected. No game/inference activity. |
| Final desktop/small-window browser tests | `03:27:30.071Z` | **15 passed**: multi-label demo, separate actual status, demo clearing, references, pending recorder gate, 390px no-overflow, no JS errors or mutation/external requests. |

### Status and Stop

The current listener was observed as PID `24372` on loopback 18090, managed by
background process `bgp_123c36795001sDuMmb0Jhemxll`; command stdout and uniquely
timestamped private server stderr remain local. Source state is idle, capture
count zero, recording disabled, ledger inactive. The browser can be inspected
without selecting/capturing a CoinPoker window.

**UI_READY is not COLLECTOR_READY or ADVICE_READY.** The native first-phase feed
does not write images, and arbitrary heartbeat recording claims cannot promote
readiness. The previously used private capture harness is retained; its actual
Practice Games profile/recorder readiness and the separate seated-data session
must still be approved and validated before seating for data. Positive controls,
enabled/disabled states, hero cards, amounts and regions remain untrained.

The prior Gate F FAIL/human UNVERIFIED, fitted board threshold 1.0, source/vendor
calibrated false and historical it1 results are unchanged. No positive import,
training/retraining, it2/it3, real capture, plays, uploads, commits or pushes.
No new `.ps1` or release/workflow edits. Six-max, thin lobby-size evidence,
cursor compositing, local-only weights, untested currency glyphs and omitted
release server packaging remain gaps; template matching remains a later explicit
alternative, not a silently implemented replacement. Root `lobby-screengrab.png`
is untouched for user deletion; the reference PNGs/PDF remain untouched.

Artifact index: `.local/laya/train/phase1-20261010/phase1-summary.json`, command
`.run.json`/`.stdout.txt`/`.stderr.txt` records (including pre-fix failures), the
two private browser test scripts, and dashboard-only images under
`.local/captures/20261010T0238Z-dashboard-tests/`. All user changes remain
uncommitted; the user commits. Do not turn software test passes or model loading
into physical/seated acceptance.

## Addendum 12: Role-aware Monitor + Reference, Checkpoint A (2026-10-10)

Request received `2026-10-10T05:37:13Z`. The superseding adjustment was written
at the top of the active practice plan before process inspection/implementation.
It replaces the P1 four-view dashboard and operator-launched profile as the
normal workflow. This addendum records A only; B-F remain explicit checkpoints.
The earlier Gate F FAIL remains historical and unchanged.

### Implemented, Without Physical Acceptance

- Exactly **Monitor** and **Reference**. No Replay/Checkpoint tabs, connect/process
  controls, or visible runtime/lease/ledger diagnostics. Empty/disconnected
  Monitor is a single compact message; retained history is hidden, not discarded.
- Separate Suggested action box: Watching the table, Waiting for your turn,
  highlighted Suggestions off on a source-bound current turn, or one short
  Reading uncertain line. No advice is activated or poker action automated.
- Explicit role/field verification preserves unknown seating, amounts, controls
  and wagers. Empty hero cards cannot imply unseated. Valid waiting-stack evidence
  can survive waiting/folded states. Six-max seat labels are one-based and never
  inferred from a player-vector index. Role changes do not reset stream/history.
- Observing call cost uses a separately verified acting-seat reading, not hero
  placeholders. Missing actor clears call cost; mismatched/unlabelled observer
  odds are withheld. Multi-label controls distinguish Bet and Raise/re-raises.
- Source-provided betting counts/gaps and trusted complete preflop raise ordinals
  can be presented without guessing 3-bet/4-bet order or exposing player names.
  The actual current observer still has only unvalidated-source gaps.
- Rank, pot odds, draw and equity fields remain **null until capability approval**;
  the browser does not calculate strategy from experimental perception. Current
  native acting-seat/wager evidence remains unavailable rather than fabricated.
  Seated recognition remains untrained; real role transitions are not accepted.
- Lease review fixed an old/new-version deadline comparison: genuinely newer
  observations own their remaining source budget, without poll-based renewal.
  Both epoch and generation are monotonic, so a new epoch cannot launder an older
  generation. Missing/future/over-budget captures, malformed cards, stale
  heartbeat, disconnect, tab visibility, clock changes and retired sessions clear.

### Researched Reference

Eight searchable/collapsible sections cover rankings/ties, pot odds, fixed-outs
exact/approximate draws, six-max positions, contextual opening examples, facing
raises/3-bets/4-bets, glossary and limitations. Ten retrieved pages from PokerNews,
Upswing Poker, Pokerology and GTO Wizard are cited in
`scripts/dashboard/reference.json`. PokerStars Learn redirected to unrelated
FanDuel material and was not supporting evidence. The exact JSON is bundled in
`app.js`; a parity test prevents drift. Reference does not make runtime requests.

Fraction/combinations calculations independently verify every arithmetic row:
`C/(P+C)`, `n/47`, `n/46`, and `1-comb(47-n,2)/comb(47,2)`. For example, nine clean
outs by river give `34.967623%`; fifteen give `54.116559%`, not rule-of-4 `60%`.
Completion probability is not showdown equity. Opening examples are independently
authored strategy opinion for unopened six-occupied-seat cash pots around 100bb,
with sizing/rake assumptions, not copied root charts or claimed solver solutions.

### Actual Command and Browser Records (UTC)

All times below are on 2026-10-10. Full command/exit/stdout/stderr receipts are
private under `.local/laya/train/role-aware-20261010/`. Normal unittest output is
on stderr; nonempty stderr alone is not a failure.

| Check | UTC start to end | Actual result |
| --- | --- | --- |
| OS listener/process inspection | `05:38:33.6548212Z` to `05:38:37.5435818Z` | Exit 0; existing PID 24372 on loopback 18090, not replaced/duplicated. |
| Baseline preservation, before | `05:43:22.742831Z` to `05:43:26.744344Z` | Exit 0; protected data/questions and original/filtered scores reproduced. |
| Existing metadata/state | `05:43:22.742831Z` to `05:43:23.033045Z` | Exit 0; correct it1 model, failed quality, idle/zero capture, no advice. |
| HTTP policy/reference routing | `05:48:09.933448Z` to `05:48:12.799619Z` | Exit 0; 17 tests passed, bounded/sanitized Reference failures and new replay 404 included. |
| Reference source/bundle parity | `06:00:31.731935Z` to `06:00:31.962962Z` | Exit 0; 9 schema/citation/arithmetic/bundle tests passed. |
| Rust full suite | `06:02:59.561495Z` to `06:03:57.880564Z` | Exit 0; **402 passed, one ignored**. |
| Python first full suite | `06:02:59.559269Z` to `06:03:06.931912Z` | Exit 0; 78 passed before the new-generation lease regression test. |
| Initial browser run | `06:04:54.147Z` to `06:05:04.719Z` | Exit 0; 39 checks passed. |
| Final browser run | `06:18:48.238Z` to `06:19:01.502Z` | Exit 0; **47 passed**, desktop 1366px and 400px, no page JS errors, mutation, prediction or external requests. |
| Final Python suite | `06:18:48.944750Z` to `06:18:56.041378Z` | Exit 0; **79 passed**, including new-source budget/nonrenewal regression. |
| Final node syntax | `06:18:48.942578Z` to `06:18:49.069317Z` | Exit 0. |
| Final doctor | `06:18:48.956711Z` to `06:19:09.379098Z` | Ten passes, discovery **BLOCKED**, overall exit 1. Generated-colour API smoke on the retained engine only; no captured/saved client pixels or physical acceptance. |
| Final protected-data audit | `06:23:00.466097Z` to `06:23:02.585934Z` | Exit 0; labels/train/calib/eval/late/questions unchanged; scores/66-frame agent-review filtering reproduced, still human UNVERIFIED. |
| Rust formatting | `06:23:00.466097Z` to `06:23:01.485088Z` | Exit 0; check only, no formatting edits. |
| Worktree whitespace | `06:23:00.500718Z` to `06:23:00.621092Z` | Exit 0. |
| Final listener | `06:25:24.876572Z` to `06:25:27.775987Z` | Exit 0; still PID 24372 on 127.0.0.1:18090. |
| Final source state | `06:25:24.894328Z` to `06:25:25.135776Z` | Exit 0; idle, zero frames/recordings, no advice, failed quality. |

Browser receipts distinguish synthetic DTOs from real client recognition; images
are dashboard-only under `.local/captures/20261010-role-aware-ui-tests/`. Two
earlier harness failures (unsupported dynamic Node import and missing VM URL
global) are retained and are not application JS failures or passing attempts.
Their exact times and the first read-only git-status times were not supplied;
receipts mark them null rather than fabricating timestamps. Later checks are
fully timestamped. Subagent CPU/unit/math checks also have individual receipts.

### Boundaries, Stop and Subsequent Git Authorization

No native feed/recorder, new model download, training, new dataset, live observing
or seated session, human verification, or warm capture-to-Monitor p50/p95 result
was obtained in A. The only model work was doctor's generated-colour smoke on the
one existing instance. Gate F/threshold 1.0/source calibrated:false are unchanged;
no confident cards is still a fail. Source-empty Monitor is useful UI readiness,
not COLLECTOR_READY or ADVICE_READY, and no real-money acceptance is claimed.

Updated static UI/Reference already work on the retained process. Python DTO and
route changes were tested in isolated CPU test servers and will take effect only
with B's controlled refresh using the existing launcher. Target executable/title
calibration, private bounded image recording and actual source/history validation
are still B, followed by the separately approved human sessions and GPU training.

Six-max-only coverage, thin lobby evaluation, server omitted from release
packaging, cursor compositing, local-only/nonredistributed weights and untested
currency glyphs remain limitations. Template matching remains a user decision,
not an implemented fallback. Root `lobby-screengrab.png` is retained for the user
to delete, now ignored along with the generated `.conda/` environment; neither is
part of the source upload. Root educational reference material remains reference,
not positive seated UI data. No new `.ps1` source or release/workflow edits in A.

At `2026-10-10T06:27:30Z` the user explicitly requested a thoughtful commit and
push of all updates before B. That supersedes the prior no-commit/no-push rule for
the reviewed source/docs/scripts/tests/reference batch; private `.local` material,
weights, environments, secrets and the lobby capture remain excluded. Git results
will be recorded privately after the operation; no commit/push is claimed here
before it actually occurs. Checkpoint B still requires explicit approval.

Pre-publication review found no actual tokens/credentials or identified player/
account data in the eligible source/text. The educational PNGs/PDF contain no
client/account images. Plans retain anonymous technical capture examples and
ephemeral PID/HWND diagnostic evidence, not images or named player histories;
the user requested all source/documentation updates. Private raw captures,
weights, ledgers, environment binaries and the lobby image remain excluded.
Upstream `LICENSE` and `pyproject.toml` at the exact pinned fork revision both
declare Apache-2.0; the contrary current MIT wording in MODEL_LICENSES/README/
SECURITY was corrected, leaving pins and weight terms unchanged. Older MIT
statements in these chronological addenda are historical, superseded by this
primary-source check. The local command logger's console encoding was fixed
after a BOM in old Git history caused a preliminary log-print failure; the full
history was then rechecked successfully with a separate retained receipt.

### Addendum 12 Continuation: Approved B and NLH Correction

B was explicitly approved via the question tool after push3d7a1d5. Goal resumed
at `2026-10-10T14:26:32Z`; initial tracked worktree was clean. At `15:03:16Z`
the user explicitly removed practice/lobby/cash title-discrimination requirements
and selected CoinPoker windows beginning NLH plus digits. The built-in rule now
uses `^NLH\s*[0-9]+`, positive actual bounds/visibility and exactly one match.
Missing private profile is allowed; no confirmation is fabricated. PID/HWND key
ignores role, dimensions and title suffix. Actual normalized capture geometry
scales to window size. Lobby image stays private/reference, never seated data.

Implemented native recorder: new UTC-practice directory only, no overwrite or
delete, synced PNG before append-only synced SHA-256 manifest acknowledgement,
opaque provenance/actual source UTC and capture-start monotonic time, null unknown
generation. Defaults7200frames/1GiB/500ms; hard20000/2GiB/250..60000ms. Complete
means eligible sampled prefix, not all frames. Cap/I/O failure keeps evidence,
latches incomplete and does not restart recording. Browser gets counters only.
Current-health snapshots feed observer gaps without guessing seats/actions or
promoting unvalidated recognition; role changes keep table/session/history.

Read-only confidence audit found a dormant native-floor gap below fitted it1
thresholds. Acceptance report `calibration.json` remains byte-identical and is
now separately pinned: size2297, SHA256
`fb58984f894a6aeabeaac9de7c06e33e796a75752fc13423d342ad7332c626e7`.
It is not the temperature-artifact hash. Server-generated per-pass floors and
native f64 comparisons enforce max(vendor,fitted,override), p0.995/board1.0,
both noul polarities/no_card; .99999999 cannot round into acceptance. No fit,
dataset, weight, calibrated:false, R17, quality or advice promotion was changed.

Actual UTC records, all 2026-10-10, in `.local/laya/train/checkpoint-b-20261010/`:

| Check | UTC start..end | Result |
| --- | --- | --- |
| Corrected OS inspection | `14:30:44.979914Z`..`14:30:48.279923Z` | Existing solePID24372, no duplicate model. Initial quoted-shell failure retained. |
| Listing under NLH rule | `15:09:15.867776Z`..`15:09:17.048402Z` | Metadata only; summary at15:10:13 found0 eligibleNLHwindows. |
| Current-source history | `15:17:00.462432Z`..`15:17:13.589788Z` | 19 tests pass; earlier duplicate capture-reference test failure retained/fixed. |
| Native build | `15:21:08.585227Z`..`15:21:15.035507Z` | Exit0, no capture/model startup. |
| Existing artifacts verify | `15:22:57.022590Z`..`15:22:59.660258Z` | Exit0, no download/model load. |
| Full Rust suite | `15:24:33.951977Z`..`15:25:33.029272Z` | 425 passed, one ignored, exit0. |
| Full Python suite | `15:41:35.521017Z`..`15:41:41.484751Z` | 159 passed, exit0. |
| Rust format/whitespace | `15:41:35Z`..`15:41:36Z` | Checks exit0. |
| Owned old service stop | `15:44:47.172034Z`..`15:44:50.247996Z` | Identity checked, PID24372 stopped, port-free verified, exit0. |
| Existing launcher start | `15:45:14.076490Z` | Persistent service, not finished; no end timestamp invented. |
| Refreshed ready state | `15:47:59.344827Z`..`15:47:59.560382Z` | it1 ready/floors loaded, qualityFailed, idle/blocked, zero recordings. Earlier503 during async load retained. |
| Replacement OS/model meta | `15:49:06Z`..`15:49:10Z` | OnlyPID67552 on18090; no secondmodel. |
| Desktop UI final | `15:59:11.054Z`..`15:59:11.061Z` | Eight actual-helper checks pass at1366x900. |
| Exact400px UI final | `16:00:08.252Z`..`16:00:08.258Z` | Eight actual-helper checks pass at400x844. |

Focused synthetic recorder/CLI tests15, revised NLH selector tests36, native
floor tests40 and supervisor/server tests88 also pass with separate receipts.
Clippy is not claimed clean: large LiveEvent variant remains; equivalent nested-
if and recorder fixture-array cleanups remove other warnings. Browser no JS
errors; inspected traffic read-only local state, no Reference or external fetch.
Initial lazy-Reference assertion failed before opening its tab; Chrome resize
minimum yielded500px, so final400px uses device-metrics emulation. Failed/setup
attempts retained, not counted as passes. Page now distinguishes blocked target
from transport disconnection using one compact NLH waiting message.

**Blocked physical verification:** no eligible visible NLH-number game window is
running. The refreshed automatic service waits safely; actual frame/recording
counts remain0 and readiness UI_READY, not COLLECTOR_READY/ADVICE_READY. Real
manifest/hash verification, observing/seated recognition and warm capture-to-
Monitor p50/p95 are unmeasured. No C/D/F human session, newdataset/Etraining,
real-money acceptance, newPS1 source, release/workflow edit, upload or Bcommit.
Sixmax/thinlobby/cursor/localweights/packaging/currencyglyph limits remain;
template matching remains a user option. User deletesrootlobby image, notagent.
Goal execution forbids questions: report blocked and stop before any C approval.

### Addendum 12 Continuation: Confirmed Actual Window and Real B Recording

User reported an observing table `2026-10-10T16:52:31Z`. Metadata plus desktop
inspection showed that logo/NLH/number is drawn inside a game window whose OS
title is `CoinPoker`. The user explicitly confirmed using that actual window
and beginning B checks via question tool. Private profile now selects exact
`^CoinPoker$` plus executable. Default NLH remains, no unconfirmed lobby fallback,
no fixed resolution, no PID/HWND persisted. Calibration means window identity,
not practice/cash proof or perception-quality approval. Scope is user-declared.

Actual UTC receipts under `.local/laya/train/checkpoint-b-20261010/`:

| Check | UTC start..end, 2026-10-10 | Actual result |
| --- | --- | --- |
| Confirmed selector tests | `16:58:21.448655Z`..`16:58:23.598577Z` |38 passes; exact/default isolation, confirmation, ambiguity and resizing. |
| Current measured selector | `16:58:21.466229Z`..`16:58:22.069962Z` |Unique900x686 game-window match. |
| Controlled old-service stop | `16:58:43.721650Z`..`16:58:48.473539Z` |Only owned model stopped, port free. |
| Launcher tracking retry |OS inspection `16:59:16.008483Z`..`16:59:19.581946Z`|First persistent tracking failed; no model/listener remained before retry. Session-tracked helper now runs, not a duplicate. No fabricated end/exit for killed tracker. |
| Full Python suite | `16:59:57.152759Z`..`17:00:05.265334Z` |161 passes, exit0. |
| First live-state receipt | `16:59:57.389602Z`..`16:59:57.709320Z` |Active900x686,3 acknowledged PNGs, model ready, no accepted observation/advice. |
| Initial hash audit | `17:02:00.141523Z`..`17:02:00.730719Z` |199/199 verified,140818142bytes. |
| Actual400px UI | `17:02:51.764Z`..`17:02:51.772Z` |8 checks pass; concise uncertainty, recording counters, no fake readings/overflow. No console errors. |
| Owned processes | `17:02:52.853793Z`..`17:02:55.805483Z` |One it1 model, one passive native feed. |
| User replacement report | `17:03:46Z` |Automatic new-source attachment, no model reload/manual reconnect. |
| Replacement fresh state | `17:04:29.332044Z`..`17:04:29.671541Z` |Active879x670,80 recordings; same replacement stream/history. |
| Original final audit | `17:04:52.431212Z`..`17:04:53.357519Z` |322/322 hashes correct,223457967bytes,900x686. |
| Replacement prefix audit | `17:04:52.409193Z`..`17:04:52.877572Z` |118/118 hashes correct,76558576bytes;21 at800x613 and97 at879x670 in one session. |
| Transition audit | `17:04:52.543728Z`..`17:04:52.718133Z` |9/9 correct,2984581bytes,1280x778; unlabelled transition evidence. |

First original capture16:59:55.804Z; last17:03:17.015Z. Source rotation uses new
private sessions, preserving all old images/ledgers. Resize retained source/
session and actual dimensions changed safely. Replacement's first frame was a
loading window, followed by the actual table; integrity checks are not labels.
No raw names, accounts or captured betting values are reproduced in public docs.

The no-window blocker is resolved; perception acceptance is not. Audited ledgers
contain zero admitted observations, with screen-not-accepted and changed/obsolete
source rejections. Monitor correctly shows one Reading uncertain line, not false
Observing/cards/pot/odds or betting counts. History is partial/unvalidated gaps.
Health-only p50/p95(first141samples)=109.68/150.86ms; replacement48samples=
108.66/152.27ms. These exclude inference/browser and cannot pass full reading
capture-to-Monitor latency. No fitted floor, GateF failure, calibrated:false,
humanUNVERIFIED or advice/metric gate was changed. All images remain ignored local.

Real B recording/rotation checks are complete. No timed C was approved/counted;
user setup/rotation is not permission to seat, play, run C/D/F, label/train E,
upload captures or commit/push B. Explain recognition failure at the next explicit
checkpoint. Root lobby image remains for the user to delete, not the agent.

### Addendum 12 continuation: perception repair stage 1 (2026-10-10 UTC)

The user now requests implementation, subject to stopping after diagnosis/design
and before production changes. That first gate is reached, not bypassed. Existing
checkpoint B code and earlier artifacts remain; no production extraction, profile,
model, dataset, launcher, release/workflow source was changed in stage 1. Private
harnesses/receipts: `.local/laya/train/perception-diagnosis-20261010T1751Z/`.
Full design, sources, targets and later gates are at the top of the active plan.

Replay ran `2026-10-10T17:56:12.120597Z` to `17:56:28.224808Z`, exit 0, empty
stderr: 36 sequential existing-helper requests across three genuine table sizes
and one negative lobby frame. PID 87008 remained sole 18090 it1 listener; no model
load/restart, new live session, training, parallel GPU instance, upload, commit
or push. Initial nested-PowerShell quoting preflight failed (exit 1), retained;
corrected listener/process checks exited 0. CPU inventory and it1 audit exited 0.

Concrete blockers: unseated controls 0.9808 <0.995 at 900x686; phase
0.8725 <0.995 at 800x613; not-seated classification 0.9925 <0.995 at 879x670.
The latter also confidently calls five board cards turn at 0.9976. All 30 table
board answers remain below 1.0: zero accepted identities, failure. Pot and 13/14
visibly occupied stack examples meet existing glyph floors/syntax; one stack
glyph fails. These are diagnostic candidates, not human precision/coverage or
Monitor acceptance. Four empty stack crops remain unknown, not zero/open-seat.

Native skips trained p5 stacks, discards players, lacks wager/badge/button/acting
passes; board failure prevents even trying pot. Full-state consensus precedes
dashboard field flags, and live history receives unapproved gap-only snapshots.
Observing-empty preflop collides with the actionable inter-hand guard. No original
per-question traces exist: replay is not claimed as original live inference.
Audit-time helper capture was unavailable. Selected table batteries took
4696.0/4624.9/4735.2 ms including encoding, not capture-to-Monitor p95; capture,
queue, assembly, publish/render timing remains null/unmeasured.

Proposed typed `PartialObservation` is separate from unchanged actionable
`GameState`/R17: per-capability calibration, physical six-slot mapping, frozen
hand roster/positions, occupant epochs, distinct stack/wager/live credit/street
contribution/pot, source/field expiry and observed-versus-inferred gaps. Cache
never disguises source age. New untrained passes are shadow-only. Proposed
72-frame human checklist is private/all pending, not a new labelled dataset.

Gate F remains historical FAIL, human verification UNVERIFIED, suggestions OFF,
six-max visual scope only. Stage 2 requires approval; live observing, seated
collection, human verification and GPU training have separate gates. CoinPoker's
published tools policy prohibits gameplay-connected tracking/RTA; no practice/
observing exemption is established. Resolve that separate live-use risk before
a new live acceptance session.

Final private checks ended `2026-10-10T18:06:32.399907Z` (diagnostic/checklist,
exit 0) and `18:06:33.410952Z` (pinned packages/files, exit 0), both empty stderr.
Seventy-two checklist hashes and agent amount comparisons checked, still no
human approval, live observation or advice. `git diff --check` passed; existing
production tests were not rerun or counted as new extraction validation.

### Addendum 12 continuation: approved stage2 outcome (2026-10-10)

Independent typed partial fields, six stacks, disabled-by-default wager/seat-scene
paths, exact latest-region witnesses, original leases and strict-sibling veto are
implemented. Anonymous hand-position/occupant/betting helpers and private bounded
diagnostics are tested; unsupported or contextless data staysunknown, no action
guesses/quality promotion. Exactly Monitor/Reference and R17/suggestionsOFF remain.

Receipts `.local/laya/train/perception-stage2-20261010T1810Z/`: workspace506pass/
1liveignored20:04:51.413426Z–20:05:21.849401Z exit0; Python/Node207pass
19:54:44.199857Z–19:54:51.521075Z exit0; strictclippy20:24:50.949364Z–
20:24:53.044757Z exit0. Earlier failures/corrections retained. Saved-answer
regression retains pot+3/5/5stacks withstrictnull; no new model/live quality claim.
NEWprivateobserving-v2-staging index has72hash-checked existingframes, all labels/
splits pending, training/calibration/activation disabled. ExistingB/it1 preserved;
helper not restarted, binaries isolated, noGPU/newcapture/gameinput/uploads/commits.
Stop afterstage2. Real quality, warmtotalp95, actualhand/convention and human/data/
provider-policy gates remain; GateF FAIL, humanUNVERIFIED, no full live acceptance.

### Addendum 12 continuation: offline draft data readiness (2026-10-10)

Existing B/stage2 was preserved as `68832c5` (41 files), pushed by
20:58:19.709308Z without a co-author trailer before this authorized offline task.
No private captures/datasets/weights/receipts were pushed. Full current outcome
and exact review entry points are at the top of the active practice/dashboard/
history plan. Private pack:
`.local/laya/datasets/observing-20261010-v2-staging/human-review-20261010/`.

All72 indexed entries/all1878 archive images hash/size/dimension checked;67 unique
indexed PNGs,62 table rows/58 unique table PNGs. There are432 physical-seat draft
rows and280 coverage cells with exact frame/crop hashes. Everything is DRAFT,
human PENDING, not ground truth. Original staging manifest stays unlabeled and
ineligible; it1 artifacts and historical outcomes are preserved. No new UI/runtime
changes. Earlier seat1-wager absence is corrected:12 indexed positives at879x670;
330 wider-archive positive-display frames/53 exact crops/18 sampled runs, NOT
independent actions. Corrected bounds remain review-only. Other-size/seat/class
gaps, ambiguous participation/phase and unknown pot conventions remain explicit.

Six stable visible board-cycle candidates and one gapped animation candidate are
not complete betting/return/side-pot accounting. Source gaps reach20.330s. Hand
IDs/splits remain pending; adjacent sessions/duplicates stay together in one
exposed development episode. Actual seated hero/cards/stack/controls positives0;
educational roots and lobby excluded. Finite manual quotas include>=20 distinct
positive seated controls EACH for held-out and late, with separate train/calib
and per-seat/size/sequence requirements, capped at80 segments/2400 review frames.
Missing quotas stay blocked; none is automatic quality or collection approval.

Official tools policy rechecked (maxAge0/HTTP200, updated25June2026): no established
practice/observing/anonymity exemption for gameplay-connected tracking/assistance.
Offline existing/provider-approved data only; provider clarification plus separate
user permission gate any later live route. No new capture, input, restart,
inference, training, fitting or activation. Private UTC/command/exit/stdout/stderr
receipts: `.local/laya/train/data-readiness-20261010T2054Z/`; failures and initial
unclocked read-only preflight limits disclosed. Artifact integrity checks are not
recognition tests. STOP: GateF historicalFAIL, humanUNVERIFIED, suggestionsOFF, R17strict.

Final artifact-only verification21:24:51.172336Z..21:25:08.912858Z exit0, empty
stderr:6635 bound fields/1739 field crops/1878 source rehashes/71 protected files
byte-identical. Temporal check57 source bindings/13 intervals/328 crops also exit0.
Remote68832c5 confirmed; four new handoff-document edits are left uncommitted for
human review, private pack ignored. No new production-suite or recognition score.

## Addendum 13: Desktop Companion and Manual Seated Diagnostic (2026-10-11)

The new explicit implementation authorization supersedes the previous dashboard
prohibition. B/stage2 and all four incoming uncommitted handoffs were preserved.
This checkpoint stops at **READY FOR MANUAL SEATED DIAGNOSTIC/CAPTURE**, not trusted
live recognition. Suggestions OFF, R17 strict, Gate F historical FAIL; all existing
draft labels stay DRAFT / human PENDING.

Root cause of the tall browser: leftover CDP400x844 override inside an802x534 outer
window. Clearing it restored786x439. Actual Windows DPI100%/browser scale1; measured
resized800x520 outer784x425 CSS. Fluid width is retained with no forced min-width.
Short landscape Monitor, six independent physical seats, literal amounts and
per-field reasons now fit; history/diagnostics collapse. Reference uses the current
content/search in a topic/content split, no new app/framework or live advice.

Fieldwise fixes retain independent board slots, hero stack under uncertain turn,
literal amount text and source-bound closed failure reasons throughout typed native
assembly/feed/projection. Original UTC/expiry and strict state validation remain.
Saved actual answers still yield pot+3/5/5stacks, no admitted cards, strictnull and
lobby refusal. No new model call. Positive physical-seat1 wagers exist, but p6/p7
remain disabled without required qualification. Actual seated hero/control evidence
is not established; board cycles do not establish betting/accounting sequences.

Manual capture uses the existing PlatformCapture/PrivateRecorder via a one-shot
`laya_capture.py` flow: fresh exact PID/HWND challenge, literal seated-ready assertion,
600s or1200frames whicheverfirst, terminal replacement/failure, explicit stop,
private hash/source-time/gap receipts and DRAFT markers. Target20 means distinct
operator-marked opportunities; unmet target stops anyway and is reported. Normal
dashboard launch has no model load/auto-attach. Separate inference opt-in is neither
active nor approved here; no browser refresh can start collection.

Final workspace514pass/1real-HWNDignored, Python/Node240pass, full-workspace strict
Clippy and formatting pass. Independent review defects (non-object receipt crash
and false inference-OFF during loading) were fixed and rechecked, no open actionable
finding. Browser23checks each at780x400,640x360,1000x600 and actual800x520outer passed;
console clean, no mutation/inference requests. Earlier failed attempts retained.
Exact UTC/commands/exits/stderr are under `.local/laya/train/companion-20261011/`;
browser/screenshot receipts under `.local/captures/20261011-companion-ui/`.
The active practice plan records the final UTC table. Occupied-port launch check
returned expected exit1 without stopping/starting a helper. The old runtime remains
untouched pending controlled operator launch. No actual HWND/capture/session/model
inference, training, download, client input or push occurred.

The first-session runbook and capability matrix are `docs/SEATED_DIAGNOSTIC.md`.
No requirement to complete the future full training corpus blocks this implemented
UI/capture workflow; recognition acceptance and real stop/latency measurements remain
separate, unrun gates.
