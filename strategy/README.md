# strategy/ — the fuel

Machine-readable poker doctrine for the decision engine. Human-readable companion:
`PLAYBOOK.md` in this directory.

| File | Contents | Consumed by (now/next) |
|---|---|---|
| `preflop_ranges.json` | 6-max positional opens EXACTLY mirroring the user's card (`screenshot-2.png` / `ranges.rs`), plus playbook 3bet/defense tiers | drift-guarded vs `core-engine::ranges`; next: engine preflop gates |
| `odds_tables.json` | exact outs/equity, pot-odds break-even, implied/SPR guidance; `card_printed` mirrors `screenshot-1.png` | reference + tests vs `core-engine::pot_odds`; the outs table lives here now (outs.rs was deleted in the decruft pass) |
| `exploits.json` | archetype counter-deltas (`fold_equity_multiplier`, `raise_size_multiplier`, pool defaults) | `opponent-model::exploit` inputs; archetypes match `classifier::Archetype` (Tag, Lag, LoosePassive, TightPassive, Unknown) |
| `PLAYBOOK.md` | doctrine: Ivey baseline + Negreanu exploitation, hard rules, engine mapping, provenance | humans and the engine wiring in PLAN §9 Phase 2/3 |

Dialect: range tokens parse with `core-engine::ranges` (`22+`, `A2s+`, `KTo+`,
`T9s`). Keep one change per session and measure it (PLAYBOOK learning loop).
