# PLAYBOOK — Ivey baseline, Negreanu exploitation

Doctrine for the bot's play: plan for the repo's engine (core-engine decisions +
opponent-model reads + ghost-layer timing). Two gears, one rule for switching.

**Gear A (Ivey — baseline).** Unexploitable lines, math-first (equity, pot odds,
SPR). Gear A is the default for every spot and the whole game vs unknowns.

**Gear B (Negreanu — exploitation).** Reads, tempo, targeted deviations. Gear B
activates only with *evidence* (observer stats / ledger history), never on a hunch.
When evidence fades, return to Gear A.

The winning edge in this pool is not hero calls. It is: preflop discipline by
position, charging draws correctly, stealing from nits/tags in position, and never
paying off calling stations.

## Hard rules (never violated)

1. **Open by chart** — `strategy/preflop_ranges.json` by position; trash stays
   folded. This alone beats most of the pool.
2. **Raise-or-fold** except: SB complete vs very passive BB, and one overlimp with
   small pairs/suited connectors only after ≥2 limpers.
3. **Every bet has a reason**: value (worse hands call), equity denial (charge
   draws), or fold equity (make better hands fold). No "information bets".
4. **Draw discipline**: pot odds + implied odds only; sets need ~15-20x implied vs
   the open; no chasing vs nits.
5. **SPR law**: SPR ≤ 3 → top pair+ commits; SPR ≥ 6 → one pair controls the pot
   (check/call streets, raise only vs maniacs).
6. **River logic**: stations → thin value (half-pot+ with third pair+); nits → size
   up or bluff once; maniacs → trap with strong hands, bluff less.
7. **Bluff selection**: prefer blockers (A5s-A2s, KQs) and backdoors; cap bluff
   frequency at ~1 bluff per 2 value combos vs this pool.
8. **Position**: in position → wider flop stabs at checked-through pots;
   out of position → check more, donk almost never.
9. **Never over-commit with one pair vs a raise** unless villain is maniac/LAG
   (their raise range includes worse).
10. **Lifecycle**: play blocks, take the sit-out breaks (see DETECTION.md session
    spec); the client auto-acts at the clock (~15 s) — never need the emergency
    path because a decision is late.

## Exploit matrix (Gear B — drives `strategy/exploits.json`)

| Read | Evidence (observer signals) | Counter |
|---|---|---|
| Nit | VPIP < 18, PFR tight, folds to 3bets | steal wide IP; fold to their raises; barrel turn when they check-call flop |
| TAG | VPIP 18-26, low limp, standard lines | Gear A mostly; 3bet bluff in position; punish capped check-calls with river pressure |
| LAG | PFR > VPIP+20%, high aggression | widen value 3bets; trap more; call down lighter with A-high vs their barrels |
| Maniac | VPIP > 45, big sizing chaos | value-heavy, thin value all streets, slow down with air |
| Station (fish) | VPIP > 40, calls everything, little raising | never bluff; bet 3 streets for value with top pair+; size up |
| Unknown | < 30 hands | pure Gear A |

Negreanu checklist before Gear B: (a) what does his size mean for *this* player
(population tells only), (b) turn tempo asymmetry (fast overshove = capped? slow
min-raise = monster?), (c) what did he show down last orbit, (d) who is steaming.

## Engine mapping

| Doctrine | Repo knob |
|---|---|
| Legal lines, EV floor | `core-engine::decision` (raise gate lift, side-pot EV — PLAN §4) |
| Exploit multipliers | `opponent-model::exploit` (`raise_size_multiplier`, `fold_equity_multiplier`) fed from `observer`/`observing` stats |
| Sizing humanness + 3-7% off optimal | `ghost-layer::betting_entropy` (DETECTION.md §S4) |
| Preflop ranges by position | `core-engine::ranges` (card-mirrored opens; `preflop_ranges.json` uses this dialect) |
| Timing | `ghost-layer::temporal` (retune per DETECTION.md §3) |
| Reads persist | observer ledger → archetype → `exploits.json` thresholds |

## Learning loop (the fuel)

1. Every session emits receipts; review hands where EV gap was small.
2. Update one line at a time: `strategy/exploits.json` (thresholds) or
   `strategy/preflop_ranges.json` (pool tweaks). One change = one measured session.
3. Keep `strategy/READS.md`-style notes per opponent name → seeds Gear B for
   returning players (later: `(table, seat)` keying, PLAN §5).
4. Discipline: in Gear B, deviate on **one street per hand at most**; two deviated
   streets is a plan, three is tilt.

## Sources and provenance (who authored what)

- `poker-info-sheet.pdf` (PokerNews cheat sheet, hash-pinned in the question set)
  drives **rule/perception math**: seat names, clockwise numbering, streets vs board
  count, action semantics → `core-engine::table_rules`, mapped to six-max; it does
  NOT contain the ranges or odds.
- `screenshot-2.png` ("Before the flop, six-handed") → the open tiers in
  `core-engine::ranges::RANGE_TIERS`; `preflop_ranges.json` opens are an EXACT mirror
  (drift-guarded by `bin/tests/strategy_fuel.rs`).
- `screenshot-1.png` ("Odds worth knowing") → the draw-odds card mirrored in
  `odds_tables.json` (`card_printed` fields) beside exact formula columns.
- Playbook-authored: 3bet/call/defense tiers, exploit matrix, SPR/board doctrine,
  session and error budgets. Keep one change per session and measure it.
- Other reference material: `crates/core-engine/src/{equity,pot_odds,table_rules,
  ranges}.rs`, `docs/DETECTION.md`, `docs/PLAN.md`.
