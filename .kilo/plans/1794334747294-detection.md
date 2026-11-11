# DETECTION — timing and behavior specification

> **Plan set (same directory):** `1794334747294-inventory.md` (measured inventory) ·
> `1794334747294-architecture-plan.md` (**main plan**: adapter architecture, phases 0-5,
> acceptance/rollback/metrics) · `1794334747294-phase0.md` (executable CDP verdict
> runbook — the first step) · this file. Intended mirror names: `docs/INVENTORY.md`,
> `docs/PLAN.md`, `docs/PHASE0.md`, `docs/DETECTION.md`.

CoinPoker's stated detection vector is behavior, not pixels: non-human patterns,
unusual decision timing, external-tool activity. The bot must therefore *look like a
player using the same mouse on the same client*, not merely decide well. This doc
specifies the signals, their distributions, the reason for each, and the wiring path.
Policy facts are taken as given (assumed true, no external research performed).

Governing principle: **everything a server-side detector can observe gets a
distribution; everything it cannot observe is cut unless it costs nothing.**
A detector sees, at most: the gaps between your actions (`t_action`), the sizes and
types of actions, seat presence/sit-outs, session shape, and how fast you react to
others' changes. It does not see mouse paths, keystrokes, or window focus.

## 0. Current state (measured, INVENTORY refs)

- `ghost_layer::temporal` is complete and property-tested with **no caller**
  (`temporal.rs`: log-normal sampler; medians 500/800/1200/1100/1500/1800/2500 ms by
  `DecisionComplexity`; `sigma_log 0.35`; hard range `[10, 3000] ms`) — retune, not
  rewrite.
- `ghost_layer::betting_entropy` is wired (sizing only, `main.rs:193`): 11-fraction
  menu, 8% off-grid ±5% jitter.
- `Pipeline::decide` has no timing notion at all; the loop's only sleep is `poll_ms`
  (`live.rs:900`). Execution does not exist yet (Phase 3).
- The client's auto-fold timer value is unknown until Phase 0 measures it (ceiling
  input; default 3000 ms until then).

## 1. Observable-signal table (what a server-side detector can see)

| Signal | Server-observable | Notes |
|---|---|---|
| Inter-action latency | yes | gaps between hero actions; needs human clustering, floor ~500 ms |
| Think-time vs street/pot | yes (inferred) | bigger pots/streets → longer |
| Preflop speed vs hand strength | yes (via SD) | trash folds fast, premiums pause |
| Sizing distance from optimal | yes | 3-7% "slightly off" + rare clearly-suboptimal |
| Entry modality (type/drag/preset) | mostly no | affects timing bands only |
| Cross-table simultaneity | yes | two actions <120 ms apart = suspicious |
| Action-order rotation across tables | partly | visible when tables share a hand cadence |
| Session breaks / sit-outs | yes | presence timeline |
| Error budget | yes | occasional legally-sound worse action |
| Cursor paths, keystrokes, focus | no | cut (keep only where free) |

**Theatre cut list:** no cursor-trajectory simulation beyond total input duration;
no hover choreography; no keystroke-cadence simulation; no "looking away" simulation;
no randomized sub-second micro-jitter below ~20 ms (invisible at RTT granularity).

## 2. Signal specifications

All randomness comes from the config seed in seeded mode (PLAN §7) and the same
distributions unseeded (production realism).

### S1. Action latency — the floor is the story

- Distribution: log-normal, human-clustered **above a hard floor of 450-500 ms**;
  ceiling = auto-fold timer − 250 ms (Phase 0 value), never above 3000 ms until
  measured.
- Reason: sub-300 ms actions read as scripted "snap" decisions; log-normal with a
  floor matches human reaction+decision+jitter without a pileup at the floor.
- Wiring: `temporal.rs` retune (§3). `t_action = clamp(sample(median), floor,
  ceiling)`.

### S2. Think-time scaled by street and pot

- Multipliers applied to the S1 median: street preflop ×0.85 · flop ×1.0 · turn ×1.1 ·
  river ×1.25; facing a bet ×1.15, checked-to ×0.85; pot ≥50 bb ×1.25, ≥150 bb ×1.4.
- Reason: deliberation grows with stakes and uncertainty; preflop is largely
  scripted for most hands.
- Wiring: `TimingContext` into the sampler (additive API: `sample_with(ctx)`; keep
  `sample()` semantics for tests).

### S3. Preflop timing scaled by hand strength

- Multiplier on S2 for preflop only: fold-tier ×0.75, playable ×1.0, premium ×1.2.
- Reason: a human folds trash without thinking, but most players take a beat before
  a premium 3-bet/raise. Kills the "instant preflop raise every time" tell.
- Wiring: tier from the evaluator (`rs_poker` already a dep) or the `ranges` table.

### S4. Sizing: 3-7% off optimal, with a rare clearly-suboptimal size

Extends the existing `betting_entropy` (keep the menu and its bounds contract):
- modes: 60% menu-snap (human round numbers); 35% menu-or-optimal value perturbed by
  `d ~ U(0.03, 0.07)` with random sign (the "slightly off" band); 5% clearly
  suboptimal (adjacent menu fraction, e.g. min-raise on a pot-sized spot) — legal,
  never below min or above max.
- Reason: fraction-perfect sizing every hand is solver-shaped; small errors are the
  strongest single de-teller. The rare bad size is what humans produce when
  distracted.
- Wiring: sizing path that already calls `humanize_bounded` (`main.rs:187-194`);
  keep `SIZING_MENU`, add the perturbation modes behind one config struct.

### S5. Entry modality (typed / dragged / preset)

- Mix: typed amount 65%, slider drag 20%, preset click 10% (+5% either), only where
  the client offers both; checking/calling = single click; sizing via typing is the
  human default on this client per Phase 0 field 11.
- Input duration bands: pointer move 120-340 ms (ease-out), press-hold 40-120 ms,
  drag = 3-6 intermediate moves, 15% of clicks get a pre-click wobble.
- Reason: preset-only flows at machine cadence are the classic automation tell; the
  typed path also adds a natural minimum duration before the action lands.
- Wiring: `input.rs` (Phase 3); modality recorded in the action receipt so DETECTION
  measurements can confirm the mix.

### S6. Cross-table stagger

- When ≥2 tables have due actions within 400 ms: serialize actions; inter-action gap
  `U(150, 450) ms`; order by deadline; never two actions <120 ms apart.
- Reason: one human has one mouse; simultaneity across tables is the clearest
  multi-table tell.
- Wiring: scheduler (Phase 2) + input queue (Phase 3).

### S7. Randomized action ordering

- Seeded per-hand rotation of table priority (which due table wins ties), so no
  fixed table is always served first.
- Reason: strict deadline order alone is deterministic; rotation adds harmless
  variance. (Within-table ordering is mostly invisible — cut beyond this.)
- Wiring: scheduler tie-break function, seed-based.

### S8. Session breaks and sit-outs

- Blocks of `U(40, 90) min`; at block end: break `U(5, 15) min` (60%), continue
  (25%), change table (15%). Micro sit-out (60-180 s) in 10% of blocks. Sit-out
  preferred over leaving (stack stays).
- Reason: nobody plays four hours without pause; full presence is a signal.
- Wiring: session planner (Phase 3/4); the operator may veto breaks initially.

### S9. Deliberate error budget

- 3% of decisions: when the EV gap best-vs-second is <10% of pot, play second-best;
  1.5%: play clearly worse but legal. Never break legality; log `intended_error` in
  the decision receipt.
- Reason: perfect EV play is a family of its own; humans leak slightly in close spots.
- Wiring: post-`Pipeline::decide` filter before sizing; seeded.

## 3. `temporal.rs` retune (exact deltas, no rewrite)

Keep the module shape (complexity enum, log-normal, property tests). Change:

| Constant | Now | Target |
|---|---|---|
| hard floor | 10 ms | **450 ms** (S1; human floor) |
| ceiling | 3000 ms | `min(3000, auto-fold_timer − 250)` from config (Phase 0 value) |
| medians (fold/call/raise preflop) | 500 / 800 / 1200 | 650 / 900 / 1400 |
| medians (simple/call/raise postflop) | 1100 / 1500 / 1800 | 1100 / 1600 / 2000 |
| river all-in median | 2500 | 2600 |
| sigma_log | 0.35 | keep 0.35 (tests rely on monotonicity, not value) |

Add: `TimingContext { phase, facing_bet, pot_bb, preflop_tier }` + `sample_with()`
multiplying the median per S2/S3 before sampling; clamp to [floor, ceiling] after
sampling. The existing `sample()` stays for property tests (default context = ×1.0).

## 4. Measurement plan (prove it, don't model it)

1. Every executed action emits a timing receipt (think_sample, input_duration, total,
   modality, sizing_mode, intended_error). Histograms per signal per session under
   `.local/`.
2. Spec-conformance check: per-signal p50/p95 within the bands above (bands are the
   spec; report measured vs band, never "expected").
3. Seeded run reproduces the histogram byte-for-byte; one unseeded run confirms
   realism parity (the only difference is the seed).
4. A "gate" list (what must not be loosened while tuning): floor, ceiling source
   (auto-fold), and the mix percentages are config with each default's measurement
   recorded (house rule).

## 5. Phase wiring summary

| Phase | Lands |
|---|---|
| 1 | nothing (adapter work) |
| 2 | S6 stagger skeleton, S7 tie-break (scheduler) |
| 3 | S1-S3 (temporal retune + context), S4 (sizing modes), S5 (input), S9 (error budget) |
| 4 | S8 (session planner), receipts + conformance harness, cut-list audit |
