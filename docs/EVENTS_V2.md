# JSON-lines contracts, live schema version 2

Live capture emits one JSON object per line and flushes each object. Human stderr
is diagnostic, not part of the protocol. Live records contain `schema_version:2`
and `event`. Schema version 2 changes the live identity from a platform-specific
application identifier to `{exe_name,process_id,hwnd}`. Consumers of version 1
must explicitly migrate. A new process or stream starts a new generation namespace.

The stream never prints screenshots, PNG data URLs, raw model responses, player
names or backend response bodies. Consumers may ignore unknown additive fields or
events but must never infer a recommendation from `status`.

## Live records

| Event | Required fields and meaning |
| --- | --- |
| `configuration` | Active `runtime` thresholds, `identity_configured`, `model`, `vlm_timeout_secs`, `visual_calibration:"not_validated"`; this does not assert readiness. |
| `status` | `state`, `reason`, `identity`. Runtime status identity is an object or null. Early configuration and listing failure records may omit it; treat omission as null. Emitted only when this tuple changes. |
| `decision` | Existing decision fields plus `observation`, `valid_for_ms`, `emitted_at_unix_ms`, `expires_at_unix_ms`. Only emitted after all gates. |
| `table` | `game_phase`, `hero_cards`, `board`, `action_required`. Visible cards after the same acceptance gates as a decision. Not advice. Emitted only when that tuple changes. `hero_cards` is empty when none are visible. No player names and no table id. |
| `clear` | `reason`, `generation`; invalidates one active decision and is not repeated when no decision is active. |
| `discarded` | `generation` and `reason:"obsolete-observation"`, `"observation-expired"`, or `"publication-expired"`. Never reactivate older advice. A `table` event for the same unchanged window can still follow an `"obsolete-observation"` discard; an `"observation-expired"` result is discarded whole and never classifies the screen. |

Decision fields are `action`, `amount`, `ev`, `pot_odds`, `equity`, `break_even`,
`opponent`, and `confidence`. Amount retains the poker engine's chip/raise-to
convention. Unknown opponent confidence is null. Equity is calculated poker
equity, not confidence in screen recognition.

An observation has this shape:

```json
{"identity":{"exe_name":"SyntheticClient.exe","process_id":42,"hwnd":"0x7"},"generation":2,"epoch":3,"captured_at_ms":500}
```

The identity above is fictional. `exe_name` is the exact calibrated executable
basename; `process_id` is an unsigned 32-bit Windows PID; `hwnd` is a pointer-width
window handle serialized as lowercase `0x`-prefixed hex. Do not parse it as a
32-bit integer. A changed title or size also resets runtime state even when these
three identity fields persist. `captured_at_ms` is monotonic time since process
start. Generation increments with submitted observations; epoch invalidates work
after a meaningful frame or scope change.

**Consumer requirements:**

1. Clear immediately on `clear`, EOF/process loss, expired lease, or new stream.
2. `valid_for_ms` is the remaining lease at emission. Compare
   `expires_at_unix_ms` with the current clock; delayed lines do not receive a new
   full lease. Use the shorter available wall-clock or monotonic lease.
3. Never show an older generation over a newer one; ignore duplicate decisions.
4. If transport delay or clock uncertainty makes freshness unknowable, clear.
5. Never execute a recommendation as a client input command.

## States and reasons

`configuration_required` asks for an exact executable name. `waiting_for_coin_poker`
means no matching process, `waiting_for_table` means no eligible window, and
`lobby_detected` is a veto. `candidate_table` and `analyzing` are not decisions.
`capturing_table` means the current frame passed metadata, readability, consensus
and continuity gates; a poker calculation can still yield no decision.
`ambiguous_multiple_tables` never chooses enumeration order.
`other_coin_poker_window` and `unknown` are not actionable.
`recovering` retries after a bounded delay without retaining advice.
`unsupported_platform` indicates a non-Windows host (`windows-only`) or a Windows
host below the capture OS floor (`windows-1903-required`). `permission_required`
with `capture-access-required` indicates capture access failed.

Windows capture may enter `recovering` with `stale-window-filter`. Other
important reasons include `frame-changed`,
`window-changed`, `forced-refresh`, `recommendation-expired`,
`capture-unavailable`, `vlm-unavailable`, `unsupported-model-api`,
`invalid-vlm-schema`, `invalid-vlm-choices`, `invalid-vlm-empty`,
`invalid-vlm-encoding`, `invalid-vlm-size`, `invalid-observation`,
`table-title-calibration-required`, `decision-suppressed`,
`action-not-required`, and `screen-not-accepted`. Static reason text can describe
consensus and hand transitions; no model-authored text is logged.

Rejected observations use closed typed categories: `board-count`, `hero-cards`,
`action-required`, `finish-reason`, and `truncated`. Safe fallbacks are `no-json`,
`malformed`, `schema`, and `invalid-observation`. These codes never contain cards,
player names, identifiers, prompts, parser prose, response bodies, or credentials;
classification matches error variants, never formatted diagnostic strings.
`truncated` includes exhausted generation budgets and incomplete screen JSON.
Malformed fences, including trailing prose after a closed fence, remain `malformed`.

The default capture poll is 100 ms and discovery interval is 1 s. These are
targets, not real-time guarantees. A blocked capture or output write cannot
extend the external advice lease. Obsolete queued and completed work is discarded
under the same identity, generation, epoch and age checks. An over-age completion
is discarded without classification; it never labels the screen or feeds consensus.

## Replay, listing, doctor and evaluation

`--stdin` keeps its original complete `GameState` per line and bare decision or
`{"event":"clear","reason":"..."}` output. It has no live capture lease or
schema version 2 envelope. Invalid input clears once and resets replay tracking
so a later valid identical state can recover. Rejected-line stderr contains only
the static category, not deserializer or validator prose.

`--list-windows` emits schema version 2 `application` and `window` records with
public executable, PID, HWND, title, on-screen and size metadata. HWND uses the
same hex encoding. The listing does not capture pixels but can expose personal
titles; keep it local. `--doctor` emits one independent JSON diagnostic report
with `format:2`, and `--evaluate` emits one aggregate JSON report with `format:2`.
Evaluation adds `rejection_categories`, a map from safe static codes to counts of
parser/backend failures (one category per failed case, no case identifiers).
Existing aggregate fields remain unchanged. Neither mode is physical acceptance.
Both refuse remote VLM endpoints.
