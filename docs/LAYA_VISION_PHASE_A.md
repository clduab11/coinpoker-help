# Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)

Current status: Laya-only iteration-1 checkpoint installed/trained; **Gate F
FAIL**, human verification **UNVERIFIED**, no seated advice. The current model
is `models/laya-vision/finetuned/20261009T190322Z-it1`, served locally under
alias `coinpoker-laya-vision` at `http://127.0.0.1:18090/`, with `/v1/models`
and `/v1/laya/predict`. It is not evaluation-only; Gemma is not the default or
a fallback. See section 7 for the preserved failed-gate receipt and follow-on.

Sections 1-5 record the initial Phase A design approved 2026-10-09, not current
install instructions or pending tasks to repeat. The Phase A structure was
complete with human annotation pending at that point. Subsequent wiring,
download, iteration-1 training, dumps, calibration, scoring and verification
already happened. Reuse them; no redownload or retraining is needed for the
read-only dashboard phase. A fresh install lacks the user's local derivative.

## 1. Historical motivation

The pinned Gemma 4 E2B path measures **5.8-6.3 s warm** on a real 800x613 table
frame (two samples, 2026-10-09) against an 8000 ms frame lease — a thin margin
that cold starts and load can break, and the pre-remediation thinking path was
11-21 s. Laya Vision replaces autoregressive JSON generation with **typed,
calibrated decisions in one forward pass with no text generation**, promising
orders-of-magnitude faster perception. It also gives per-answer probabilities,
which map naturally onto this project's never-fabricate envelope semantics.

## 2. Initial model facts (2026-10-09, licensing corrected)

- Model: `thaitea/laya-vision` — 201M params (SmolVLM-256M-Instruct cut to 20 of
  30 language layers). Pinned fork code: github.com/r33drichards/laya-vision (Apache-2.0).
- **License: CC-BY-NC-SA-4.0 for the weights** (training data includes ScienceQA
  and CrisisMMD). An earlier in-session research note said Apache 2.0 — that was
  wrong for the weights; the upstream SmolVLM backbone and pinned fork code are Apache 2.0, and
  trained weights are CC-BY-NC-SA-4.0. The existing local fine-tuned derivative
  inherits NC+SA constraints. This workflow keeps weights local and does not
  redistribute them; repository source MIT does not override weight terms.
- API: `laya.load_vlm(id).predict({image, note}, {qid: {type, instructions,
  criteria}})` — one call answers a **batch of typed questions** about one image.
  Types: `choice` (categorical pick), `noul` (yes/no probability), `score`
  (ordinal rubric level). No free-form generation; no raw numerals.
- Hard constraints: **one image per predict call, resized to a single 512 px
  tile**; trained on everyday photos/diagrams/charts/simple game frames — not
  poker clients. `agent.calibrate` on our own labeled data is the documented
  path for a new domain.
- Published: 69.1% accuracy over 34 validation sets, ECE 0.041, 0.83x latency of
  the previous 237M checkpoint on an L4. Experimental research status.
- The initial Phase B design required an exact revision pin. The completed base
  and fine-tuned artifact records are now in `scripts/laya-pins.json`; this is
  not an outstanding download task.

## 3. Historical Phase A architecture

```
capture -> [Laya region passes] -> typed answers + probabilities
        -> assembly (question-set.json rules) -> strict screen envelope JSON
        -> UNCHANGED parser/validator (crates/ingest/src/parser.rs)
        -> unchanged downstream state machine / decision engine
```

Key principle retained today: the Laya path **never bypasses validation**.
The initial design targeted the same envelope/validator as Gemma and proposed
keeping Gemma as the default with Laya as an alternative behind `VlmBackend`.
That backend selection is superseded: Laya is now the sole active backend.

**Region-crop passes** mitigate the 512 px tile limit (a full 800x613 table
shrinks cards below readable size):

| Pass | Image | Tier | Questions |
|---|---|---|---|
| p0_full | full window | 0 | screen_kind, 6 evidence, game_phase (cross-check), hero_position (cross-check), action_on_hero, 5 offered actions, hero_seat_index, dealer_button_seat (17) |
| p1_hero_cards | crop | 1 | hero_card_1, hero_card_2 (54-option card vocab) |
| p2_board | crop | 1 | board_1..5 (54-option card vocab) |
| p3_amounts_center | crop | 1 | pot_size, to_call, hero_chips as 7 digit-slot questions each |
| p4_raise_bounds | crop | 1 | min_raise_to, max_raise_to digit slots |
| p5_seat_{1..9} | per-seat crop | 2 | present (noul), chips + bet digit slots, last_action |

203 questions total (17 / 42 / 144 by tier). Tier 0+1 = 5 passes; full battery =
14 passes. Even if per-pass latency on the RTX 4060 Ti is 10x the L4 figure, the
full battery stays far inside the 8000 ms lease; Phase C measures the real number.

The pass counts and latency forecast above are historical design estimates,
not a measurement or guarantee. The actual iteration-1 full unseated battery
and its failed original timing gate are recorded in section 7.

**Numeric fields** cannot be `score` questions (score is an ordinal rubric, not
numerals), so every amount is 7 fixed character-slot `choice` questions over
`[none, 0-9, '.', ',']`. Assembly parses the displayed decimal and encodes it as
an integer in hundredths of the displayed unit.

**Uncertainty**: there is no no-answer type; every answer carries a calibrated
probability. Assembly maps below-threshold answers to the envelope's null/false
semantics via each question's `on_low_confidence` rule (unknown / false /
unreadable / not_visible / state_null / field_null). Initial threshold 0.8
everywhere; Phase C refits per pass with `agent.calibrate` on the human-labeled
corpus, split into calibration/eval halves.

## 4. Historical first baseline findings (recorded 2026-10-09)

Running the corpus through the pinned Gemma server (`.local/laya/baseline/`):

- **table.png**: 6138 / 5811 ms. The envelope is **schema-invalid** — preflop
  declared with 4 board cards, `hero_cards: false` (boolean, not array), float
  amounts (pot `1.05`, bet `12.45`), no Hero player, `action_required: true`
  without readable hero cards. The live pipeline would discard this reading.
  This is the first recorded Gemma table envelope and it is strong evidence for
  the typed-question approach: per-field probabilities + strict assembly
  localize failures instead of emitting one plausible-looking but broken JSON.
- **lobby.png**: 1318 / 1395 ms, schema-valid (`lobby`, state null), consistent
  with the live pipeline's 2026-10-08 `lobby_detected` result.
- The decimal amounts in two independent fields indicate the client displays
  currency with two decimals; the digit-slot design handles this, pending human
  confirmation (worksheet section 1).

## 5. Historical Phase A corpus and annotation protocol

Corpus: `.local/captures/20261008T232842Z-new-calibration/` (authorized
calibration captures; provenance.json carries hashes and window identity).
Annotation files: `.local/laya/corpus/{table,lobby}.annotation.json`;
worksheet: `.local/laya/human-worksheet.md`.

Protocol:
1. Human (you) fills the worksheet from the pixels: region boxes, amount format,
   tier 0/1 answers, seat battery, and verifies/corrects the baseline candidates.
   Uncertain answers are recorded as unreadable — uncertainty is ground truth.
2. Human answers are copied into the annotation files (`annotator: human`,
   `status: complete`). Baseline records stay as `candidate` for cross-checking.
3. More captures can be added the same way (new capture dir + annotation file +
   baseline run via `.local/laya/baseline_label.py`). The validator
   (`.local/laya/validate_phase_a.py`) checks hashes and question-id coverage.
4. Phase C splits labeled images into calibration/eval halves.

## 6. The reference sheet drives the Laya logic (poker-info-sheet.pdf)

`poker-info-sheet.pdf` (PokerNews "Poker Cheat Sheet", 15 pages, repository
root, kept untracked; SHA-256
`5ce3a3f811b0a9cd0291e906162c1a5014b43700c4e4f9437574b14a06bd7de6`) is the
source of truth for the Laya logic since question set 0.2.0. The question set
records the hash under `reference_sheet` and `validate_phase_a.py` fails if
the file changes. The design rule: **the model reports only visible facts;
the sheet's rules derive everything else in Rust** (`core-engine::table_rules`).
Direct model answers for derivable values are kept as cross-checks only.

This PDF and the two reference PNGs below are rules/odds/range references,
not actual seated CoinPoker UI captures or positive hero-card/button examples.
They support deterministic calculations/replay, never perception-quality
approval. A reference panel must remain distinct from live observed facts and
eventual recommendations. Best-five ranking requires enough verified cards;
unknown cards or amounts produce unavailable metrics, not fabricated zeros.

| Sheet | Rule | Laya logic |
|---|---|---|
| p.6 | Nine-handed names UTG, UTG+1, MP1, MP2, HJ, CO, BTN, SB, BB; SB left of the button, BB left of SB, UTG left of BB; CO right of the button, HJ right of CO | New `dealer_button_seat` question. `hero_position` = `table_rules::seat_position(hero_seat_index, dealer_button_seat, occupied seats)` (R11). The `hero_position` answer uses the sheet's nine names and is a cross-check; disagreement or any unreadable input gives `unknown` |
| p.3 | "Left" is clockwise: blinds left of the dealer, deal clockwise from the small blind | Seat numbering 1..9 clockwise matches the seat battery |
| p.3-4 | Four rounds; the flop shows three community cards, the turn the fourth, the river the fifth | Street = `table_rules::Street::from_board_count` on the assembled board (R4). `game_phase` is a cross-check that also picks river vs showdown at five cards (R12). This rejects the first Gemma baseline's failure (preflop with four board cards) |
| p.3-4, p.9 | Preflop fold/call/raise; postflop first player checks or bets, later players fold/call/raise; all-in | A Bet button is reported by `act_raise` and assembled as `raise` (R13). Consistency stays with the unchanged validator (to call 0 ⇒ check, no call/fold) |
| p.7 | More players left to act ⇒ tighter | `TablePosition::opening_seat`: UTG+1/MP1/MP2 use the UTG base range |
| p.2, p.5 | Hand rankings; showdown after the river | `core-engine::equity` evaluates hands (R14); never asked of the model |
| p.7-8, p.11-15 | Positional, cash, tournament, heads-up, bounty and bankroll tips | Advice content for the decision layer; not perception |

Positions below nine players: the sheet only names a full table. The anchored
definitions still hold in this precedence: button, blinds, UTG, cutoff,
hijack. Remaining seats after UTG take UTG+1, MP1 and MP2 in diagram order, so
six seated players derive exactly UTG/HJ/CO/BTN/SB/BB. Heads-up blind posting
is not defined by the sheet, so two players yield `unknown`, not a guess. The
p.6 text and diagram disagree on group sizes (the text implies ten seats);
the diagram labels are canonical.

### 6.1 Range and odds provenance (screenshots, not the PDF)

The PDF contains neither the opening ranges nor the odds table. They come from
two separate reference cards at the repository root, also untracked:

- `screenshot-2.png` ("Before the flop, six-handed",
  SHA-256 `8fcf048089453d5e4a48946b550682d6412aa5e88b32816e90d6f44d7fc2ac2b`)
  → `core-engine::ranges`.
- `screenshot-1.png` ("Odds worth knowing",
  SHA-256 `ac9bce3df78e2ed10c464ba14a988531a5fbf33704194f6ce2fde30d9c7cc7b4`)
  → `core-engine::outs`.

**Range transcription corrected (2026-10-09T04:30Z).** The first Gemma
transcription (`.local/laya/extract_ranges.py`) dropped the card's dash
ranges and misread several tokens. It covered 8.7% of combinations where the
card prints 14%. The "three suspects" were symptoms: `K5s` belongs only to
`K9s-K5s` (tier 2), tier 3's `QJo` is `QTo`, and tier 1 is `AJo+`, not
`ATo+`. The tiers were re-read at 3x magnification:

1. From any seat (14%): `22+ ATs+ A5s-A2s KTs+ QTs+ JTs T9s 98s AJo+ KQo`
2. Add from the hijack and cutoff (26%): `A9s-A6s K9s-K5s Q9s Q8s J9s J8s
   T8s 97s 87s 76s 65s 54s ATo A9o A8o KJo KTo QJo`
3. Add on the small blind and button (43%): `K4s-K2s Q7s-Q4s J7s J6s T7s T6s
   96s 95s 86s 85s 75s 64s A7o-A2o K9o K8o QTo Q9o JTo J9o T9o 98o`

The printed percentages verify the read. Exact coverage is 190 / 338 / 574 of
1326 combinations (14.33% / 25.49% / 43.29%); the card rounds 25.49% up to
26%. Encoded sizes: UTG 33 classes, HJ/CO 58, SB/BTN 89; BB never opens. The
parser gained the card's `XYs-XZs` dash notation. Tests pin the combination
counts, each printed percentage within one point, and tier disjointness. The
duplicate-token "suspects" are resolved and `RANGE_SUSPECTS` is removed.

The odds table (screenshot-1) was re-checked against the card and is
unchanged in `core-engine::outs`: the rule of two and four, exact turn/river
combinatorics, and the five memorized draws (flush draw 9 outs 19%/35%,
open-ended straight draw 8 outs 17%/32%, two overcards 6 outs 13%/24%,
gutshot 4 outs 9%/17%, pocket pair to set 2 outs 4%/8%). The card rounds
loosely: the 8-out two-card entry is the rule-of-four 32%, against an exact
31.45%; this is flagged in code.

Opening-range membership applies only to a verified unopened pot and position;
this is not a 3-bet defense range. Draw-completion probability is not win equity.
Pot odds are `to_call / (pot + to_call)` and undefined without a verified call
amount. Reference correctness does not establish the model's UI recognition.

## 7. Phase gates

### Practice dashboard infrastructure: verified 2026-10-10

The separate follow-on implementation is complete through software/dashboard/feed/
history infrastructure, not seated data or live advice acceptance. Browser and
model API share **http://127.0.0.1:18090/**; the page is read-only. No actual
client capture or plays were performed by this validation.

- 397 Rust tests passed (1 ignored), including 32 pure observer tests; 53 Python
  tests passed; 15 desktop/small-window presentation checks and 7 synthetic
  lease/order/disconnect/advice-rejection checks passed. Release build exited 0.
- Native full-state observations now have current-source admission, tickets and
  expiry; controls invalidate independently of advice. Weaker legacy table events
  and raw model answers are not current-action/advice authority.
- The bounded private observer/ledger handles occurrences, gaps, hand/occupant
  changes and full-raise prefixes. The current unapproved model contributes only
  unvalidated-source gaps, never invented player actions, profiles or default-zero
  bets. Actual semantic watching recognition is not validated yet.
- Default total decision budget is 5000 ms (bounds 500..5000), with 300 ms reserved
  for publication/poll/render. Remaining time is carried through Laya requests.
  Existing freshness limits are not enlarged; end-to-end seated timing is unrun.
- One existing pinned model was loaded without downloading/retraining; generated
  warm-up 3273.1 ms is not a p95 or an end-to-end acceptance benchmark. Temperature
  calibration loaded, quality FAILED, advice unsupported, capture idle.
- Doctor at `03:19:13.349Z`: all 10 installation/runtime/hash/API/metadata checks
  passed; discovery intentionally BLOCKED without executable/table calibration,
  so overall exit 1. No screenshots captured/saved. A regression now covers both
  repository-local and shared HF cache blob links without permitting path escape.
- `UI_READY` is established. Image recording is not integrated into the native
  feed, so `COLLECTOR_READY`/`ADVICE_READY` are NOT established. The retained private
  capture harness, real seated profile/positive examples, explicit go-ahead, and
  later quality acceptance remain at the manual-data checkpoint.
- Baseline dataset/vendored-question hashes and all four original/filtered score
  files reproduced unchanged. No threshold clamp, calibrated activation, it2/it3,
  uploads, commits, client input, new PowerShell files or release/workflow edits.

Evidence: `.local/laya/train/phase1-20261010/phase1-summary.json`, recorded command
logs, dashboard-only screenshots under `.local/captures/20261010T0238Z-dashboard-tests/`,
and readiness-plan Addendum 11. The October 9 failed-gate receipt below is unchanged.

### Current: iteration-1 Gate F FAIL (2026-10-09)

The approved Laya-only wiring supersedes the historical B-lite disposition below.
The original sequential continuation finished at **2026-10-09T22:00:15.956Z**:
eval/late dumps, temperature fitting, calib/eval/late scores, fine-tuned pins, and
pin verification all exited 0. Checkpoint:
`models/laya-vision/finetuned/20261009T190322Z-it1`. No training or dump was repeated.

- Fitted pass thresholds: p0 `0.995`, board `1.0`, pot `0.8`, six seat-stack passes
  `0.8`. Temperatures: choice `3.796329`, noul `4.100601`.
- **Board gate FAIL**: zero confident board units on calib/eval/late
  (`0/863`, `0/568`, `0/2034`); precision is undefined and coverage is 0%, not a
  pass against >=99% precision / >=85% coverage. Threshold `1.0` was not lowered.
- **Latency gate FAIL**: one `bench_server.py 30` run, 30 frames with the first
  two excluded as warm-up, completed `22:03:05.348Z`. Warm p50/p95 (ms): p0
  `213.2/271.0`; tier01 `904.7/1497.9`; full unseated battery
  `1467.0/3027.3`. Each warm p95 must be <2000 ms.
- **Human verification UNVERIFIED**: asked once for the 66-row checklist; the
  user requested an agentic review instead. All 66 original PNGs were inspected
  individually; all claimed fields matched, with no corrections or unsure
  claimed fields. Phase abstentions for rows 1, 5, 6 were retained. The filtered
  supplemental score completed `22:29:03.459Z`: 66 of 115 frames, 3,589 selected
  rows, 2,593 excluded. Board remains `0/330` confident; pot precision/coverage
  `100/96.72%`; p5 stacks `100/98.92%` (non-blocking). Agent review does not
  certify human label truth or authorize a gate exception.
  `thresholds.calibrated` remains false in source and vendored questions;
  the fitted thresholds were not
  activated. Server `meta.calibrated:true` meant loaded temperature calibration
  only, never Gate F acceptance.
- The sole loopback server was started for the benchmark and intentionally
  stopped at `22:08:30.914Z`. Its launcher exit 1 is the recorded intentional
  termination, not a prediction or benchmark failure. Gemma was not restarted.
- **STOP**: no iteration 2-3, downstream validation, release build, doctor
  invocation, live run, uploads, or commits. The prior 20 scoring and 29
  server/doctor unit-test passes are retained, not rerun as live acceptance.
- Seated practice and cash tables share this repo, representation, and mechanism:
  no advice. Seated frames remain `readable:false`, `state:null`. Seated passes have no
  training data and are provisional/unrun. Enabling seated advice requires a
  separately approved session here with user-controlled seating, harness
  captures, region measurements, labels/training, and its own Gate F.
- Remaining gaps: six-max only; one very thin lobby eval example (1278x785,
  not validation of the configured 1280x778 lobby-size guard); server absent
  from release packaging; cursor compositing; local-only fine-tuned weights;
  untested currency-glyph handling. Template matching remains an alternative
  for the user's decision, not an implemented or validated fallback.
- Root `lobby-screengrab.png` is untouched and must be deleted by the user;
  the byte-identical eval-only copy remains under `.local/captures/`.

Evidence: `.local/laya/train/continuation-20261009/`, checkpoint
`calibration.json` / `score-{calib,eval,late}.json`, supplemental
`score-eval-agent-reviewed.json`, `.local/laya/dataset/human-check/agent-review.json`,
and readiness-plan Addendum 10. Final read-only audit at `22:29:53.468Z`
reproduced all four scores, checked the exact agent-reviewed frame filter, and
confirmed protected data hashes and source/vendor `calibrated:false` unchanged.

### Active follow-on: dashboard/history first, baseline still FAIL

The historical stop above records the iteration-1 closeout; it does not claim
that the approved 2026-10-10 dashboard/history follow-on has been tested.
The work targets actual Practice Games with practice chips in this same repo,
representation and mechanism as cash, without a bypass or real-money acceptance.
First-phase browser/feed/ledger infrastructure remains no-advice; model health,
schema validity and fresh timestamps do not certify perception quality.

On the 66 agent-reviewed frames, raw board accuracy was `307/330 = 93.03%`,
but fitted threshold `1.0` produced `0/330` confident units. Matching annotation
claims is not a claim that all model predictions were correct. The original
full-battery p95 `3027.3 ms` fails the old `<2000 ms` requirement. The prospective
warm capture-to-display p95 `<5000 ms` and hard 5000 ms full end-to-end deadline
require new usable-result timing, including capture, all inference passes,
history/math, admission, transport and rendering. This is not a retroactive pass,
a per-request timeout claim, or a reason to enlarge independent freshness leases.

Canonical browser: `http://127.0.0.1:18090/`; read-only state at `/api/state`,
metadata at `/v1/models`, prediction at `/v1/laya/predict`.
`scripts/start-vlm.ps1 -DashboardOnly` uses no GPU/model load;
default startup asynchronously verifies/loads/warms the pinned model. Optional
`-LiveConfig .local/profile.json` explicitly supervises one native passive CLI
feed. The 2026-10-10 role-aware adjustment supersedes an operator-launched profile
as the normal workflow: one-time executable/title calibration followed by
automatic practice-table attachment is checkpoint B, not active in checkpoint A.
UI/model health alone is not `COLLECTOR_READY`: actual source timestamps/frame
progress, optional recording counters and private output must be tested.
Current native feed is capture-health only: `recording_enabled:false`,
`recorded_frames:0`. Typed `-LiveConfig` target settings do not add a
`--record-dir` option. Recorder/profile readiness remains pending; retained
`.local/laya/dataset/capture_loop.py` belongs to a later manual-data checkpoint,
not an automatic first-phase capture job.

The browser cannot start/stop capture, seat/play or trigger training. Bounded
per-session history lives privately under `.local/` with opaque IDs,
unknowns and gaps, not public names or cross-session identity guesses. Legacy
table events/raw model answers cannot provide trusted current controls or
eligible opponent statistics. Polling does not extend source-bound expiry.

No seated advice until positive real UI examples and approved human-held-out
calibration/evaluation support the critical fields and enabled controls. Existing
it1 inputs remain immutable; new data/training is a separately versioned later
checkpoint, not a repeat of completed work. Six-max capture is not complete
six-player strategy: heads-up raising and multiway all-in/side-pot guards remain.
Current release packaging omits the Laya server/dashboard path and local
fine-tuned weights; `scripts/vlm-pins.json` is an orphaned historical manifest.
This phase changes no release/workflow.

### Role-aware Monitor + Reference, checkpoint A (2026-10-10)

The binding adjustment is at the top of
`.kilo/plans/1791590483000-practice-sandbox-dashboard-and-history.md`. Exactly two
app views replace the four-view dashboard: **Monitor** and **Reference**. Replay,
Checkpoint, runtime/lease diagnostics and ledger details are not user-facing.
The empty/disconnected state is one compact message. Current readings have a
separate Suggested action box; suggestions remain OFF while the gate is failed.

Source-current role DTOs distinguish Observing, Seated/waiting, Your turn and
Uncertain using explicit validated seating/turn evidence, not missing hero cards.
Waiting says "Waiting for your turn"; current turns highlight the box without
enabling advice. Role changes retain the same stream/history. Observing call cost
is a separate nullable reading for a labelled acting seat, never a fabricated
hero call. Wagers and independently present/enabled controls stay separate from
strategy. All calculated metrics remain null until capability approval; the
browser does not calculate them from experimental perception.

Reference is a concise locally bundled study guide with eight searchable,
collapsible sections and ten cited pages from four education publishers.
Pot/draw arithmetic is independently checked using exact fractions/combinations;
fixed clean-out probabilities are not showdown equity. Six-max opening examples
are explicitly authored strategy opinion for unopened cash pots around 100bb,
not copied root charts or attributed solver frequencies. Runtime Reference
requests are unnecessary; optional further-reading links are not auto-fetched.

At `2026-10-10T05:38:33.6548212Z`..`05:38:37.5435818Z`, OS inspection confirmed
the sole canonical listener was the existing it1 process PID `24372` on 18090.
Read-only metadata/state queries at `05:43:22.742831Z`..`05:43:23.033045Z` confirmed
the pinned model ready, quality gate failed, no advice and capture idle with zero
frames/recordings. The process was not replaced; no training or native feed was
started for A. The later doctor used only generated-colour API smoke inputs on
that retained engine, not poker/client images or a second model. Updated static
assets/Reference are served by that process; new Python role normalization/routes
require the controlled B restart.

Checkpoint A verification passed: **402 Rust tests (one ignored), 79 Python tests,
47 browser checks** at desktop and 400px, node syntax, formatting and whitespace
checks. Doctor had ten passes and discovery BLOCKED (exit 1), not live acceptance.
Integration receipts are in Addendum 12 and
`.local/laya/train/role-aware-20261010/`; these are software/UI evidence only.
Live attachment/recorder, actual observing/seated sessions, human verification,
new versioned data/training and warm end-to-end latency remain later checkpoints.
Thin lobby coverage, six-max scope, omitted release server packaging, cursor
compositing, local-only weights and untested currency glyphs remain limitations.
Template matching remains an option for the user's decision, not an implemented
fallback. The user, not the agent, deletes root `lobby-screengrab.png`.

### Historical A-D proposals and B-lite results

These dated proposals/results are superseded where they call Gemma current or
Laya evaluation-only. They are retained as history, not tasks to restart.

- **Phase A — COMPLETE (structure)**: question set 0.2.0 (203 questions, validated; reference sheet pinned by hash),
  corpus + annotations (baseline candidates recorded), worksheet, baseline
  evidence, this document. **Remaining for A**: human annotation.
- **Phase B — wiring**: download `thaitea/laya-vision` pinned to a recorded
  revision; implement region capture + a Laya perception backend that assembles
  the envelope from typed answers; Gemma remains the default; feature-flagged.
  Blocked on human annotation (region boxes + ground truth).
  - **Phase B-lite status (2026-10-09T16:10-16:35Z): GATE FAILED, wiring not
    started.**
    - On 2026-10-09 the user decided that Laya would replace Gemma as the sole
      backend, observation-only until calibrated, provided the Phase B-lite gate
      passed first.
    - **Installed and pinned** (`scripts/laya-pins.json`, `MODEL_LICENSES.md`):
      - checkpoint `thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc`
      - laya code `9e1e2419`
      - torch 2.11.0+cu128, transformers 5.19.0
      - Python 3.12.15 env at `.local/laya-runtime/env`
      - Offline load is verified.
    - **Question set 0.3.0** (source and expander fixes) is vendored to
      `crates/ingest/assets/laya/question-set.json`. Normalized regions are in
      `crates/ingest/assets/laya/regions.json`.
    - **Geometry, measured numerically on both captures** (no pixels saved):
      - Frames are whole windows with an unscaled 28 px title bar.
      - The content area is aspect-locked at 1.3677 and scales uniformly.
    - **Results** (`.local/laya/phase-b/SUMMARY-20261009T1650Z.md`):
      - The API works.
      - `screen_kind` does **not** separate lobby from table: lobby →
        `poker_table@0.41`. One refinement round did not fix it.
      - The 54-option card questions are truncated by the 256-token option
        budget. No card or amount was read correctly with confidence.
      - Every crop answer is below the 0.8 threshold.
      - Latency: tier-0 250-320 ms warm; six-max battery 2.1-2.8 s (target
        < 2.0 s).
    - **Gemma stays the backend.** Its removal was conditional on this gate.
      Laya stays an evaluation-only install.
- **Phase C — benchmark**: Laya vs pinned Gemma on the labeled corpus: accuracy
  per question group, calibrated thresholds via `agent.calibrate`, end-to-end
  latency per pass and per full battery on the RTX 4060 Ti, VRAM/WS footprint.
  Proposed acceptance targets (to revisit with data): screen_kind >= 95%,
  card identity >= 90% calibrated, amounts >= 95%, full-battery latency
  < 2000 ms. Realism caveat: 201M model, out-of-domain; targets may need a
  small fine-tune (separate decision) or the prototype stops at classification.
- **Phase D — GO/NO-GO**: Laya replaces/augments Gemma only if C clears targets
  without weakening the never-fabricate guarantees. Otherwise findings stand as
  evidence for the acceptance report.

## 8. Current risks and open assumptions

- Out-of-domain accuracy remains a risk: the 201M base was not trained on poker
  clients, and the local it1 domain fine-tune did not establish seated capability.
  Required per-capability calibration/held-out targets may still not be met.
- Base/derivative weights remain CC-BY-NC-SA-4.0 and local-only in this workflow;
  code MIT/upstream backbone Apache-2.0 do not remove their constraints.
- Region boxes depend on the 800x613 layout; window-size drift invalidates them
  (same calibration-drift caveat as window discovery).
- The batch-of-questions-per-pass API is confirmed by the model card.
  Per-pass latency on this GPU was measured in Phase B-lite: 120-320 ms per pass
  warm.
- Phase B-lite exposed out-of-domain accuracy risk; iteration-1 domain training
  already completed and did not pass Gate F. Dashboard/history work does not
  require retraining. A later candidate needs genuine positive seated/control
  examples, a new versioned dataset, approved human-held-out calibration and a
  bounded compute checkpoint; no automatic iteration 2-3 or base redownload.
- The original Phase A two-image corpus is historical. The later 66-frame
  agent review is not human certification, and the all-negative action labels
  cannot establish positive hero-button recognition. New critical capabilities
  need class-specific positive/negative/disabled examples and held-out coverage.

## 9. Artifacts

Current artifacts are the local it1 checkpoint and its calibration/scores,
`scripts/laya-pins.json`, source/vendor question sets (still `calibrated:false`),
and the private continuation/review evidence named in section 7. Keep those
existing inputs/outputs intact. The following list records initial Phase A
artifacts and reference provenance; 0.2/0.3-era files are not new tasks or the
current Gate F outcome.

- `docs/LAYA_VISION_PHASE_A.md` — this document.
- `.local/laya/question-set.json` — machine-readable question set (source of truth).
- `.local/laya/question-set.expanded.json` — 203 expanded questions (Phase B input).
- `.local/laya/validate_phase_a.py` — structural validator (PASS).
- `.local/laya/baseline_label.py` + `.local/laya/baseline/{table,lobby}.json` —
  pinned-Gemma baseline candidate labels + latency samples.
- `.local/laya/corpus/{table,lobby}.annotation.json` — annotation records.
- `.local/laya/human-worksheet.md` — the human annotation worksheet.
- `poker-info-sheet.pdf` — the user-provided reference sheet that drives the
  Laya logic (repo root, untracked, pinned by SHA-256; section 6).
- `screenshot-1.png`, `screenshot-2.png` — the odds and opening-range reference
  cards behind `core-engine::outs` and `core-engine::ranges` (untracked; 6.1).
- `crates/core-engine/src/table_rules.rs` — the sheet's position and street
  rules used by Laya assembly.
