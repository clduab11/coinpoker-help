# Laya Vision Prototype — Phase A Design (Question Set + Calibration Corpus)

Status: Phase A COMPLETE (structure). Human annotation pending. Approved in-session
2026-10-09 UTC. This is a prototype track alongside the Windows acceptance plan;
it does not modify any pipeline code yet.

## 1. Motivation

The pinned Gemma 4 E2B path measures **5.8-6.3 s warm** on a real 800x613 table
frame (two samples, 2026-10-09) against an 8000 ms frame lease — a thin margin
that cold starts and load can break, and the pre-remediation thinking path was
11-21 s. Laya Vision replaces autoregressive JSON generation with **typed,
calibrated decisions in one forward pass with no text generation**, promising
orders-of-magnitude faster perception. It also gives per-answer probabilities,
which map naturally onto this project's never-fabricate envelope semantics.

## 2. Model facts (verified against the HF model card 2026-10-09)

- Model: `thaitea/laya-vision` — 201M params (SmolVLM-256M-Instruct cut to 20 of
  30 language layers). Code: github.com/r33drichards/laya-vision (Apache 2.0).
- **License: CC-BY-NC-SA-4.0 for the weights** (training data includes ScienceQA
  and CrisisMMD). An earlier in-session research note said Apache 2.0 — that was
  wrong; the base SmolVLM and the code are Apache 2.0, the trained weights are
  not. Compatible with local personal use; redistribution of the weights or
  derivatives would carry NC+SA terms. Flagged for the user's decision.
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
- Phase B must pin the exact revision hash at download time (the card advises
  pinning; the repo has moved checkpoints before).

## 3. Architecture

```
capture -> [Laya region passes] -> typed answers + probabilities
        -> assembly (question-set.json rules) -> strict screen envelope JSON
        -> UNCHANGED parser/validator (crates/ingest/src/parser.rs)
        -> unchanged downstream state machine / decision engine
```

Key principle: the Laya path **never bypasses validation**. It produces the same
envelope the Gemma path produces; the unchanged validator remains the gate. The
Gemma backend stays the pinned default; Laya lands as an alternative perception
backend behind the same `VlmBackend` contract (Phase B).

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

## 4. First baseline findings (recorded 2026-10-09)

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

## 5. Calibration corpus and annotation protocol

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

## 7. Phase gates

- **Phase A — COMPLETE (structure)**: question set 0.2.0 (203 questions, validated; reference sheet pinned by hash),
  corpus + annotations (baseline candidates recorded), worksheet, baseline
  evidence, this document. **Remaining for A**: human annotation.
- **Phase B — wiring**: download `thaitea/laya-vision` pinned to a recorded
  revision; implement region capture + a Laya perception backend that assembles
  the envelope from typed answers; Gemma remains the default; feature-flagged.
  Blocked on human annotation (region boxes + ground truth).
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

## 8. Risks and open assumptions

- Out-of-domain accuracy is the main risk: a 201M model trained on no poker
  clients. Calibration on our corpus is mandatory; targets may not be met.
- License (CC-BY-NC-SA-4.0 weights) needs a user decision if this ever ships.
- Region boxes depend on the 800x613 layout; window-size drift invalidates them
  (same calibration-drift caveat as window discovery).
- The batch-of-questions-per-pass API is confirmed by the model card, but
  per-pass latency on this GPU is unmeasured until Phase C.
- One corpus table image is thin; more labeled captures (ideally one per
  game_phase, with and without hero cards, action and idle) are needed before
  Phase C statistics mean much.

## 9. Artifacts

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
