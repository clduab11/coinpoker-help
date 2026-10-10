# JSON-lines contracts, live schema version 2

Live capture emits one JSON object per line and flushes each object. Human stderr
is diagnostic, not part of the protocol. Live records contain `schema_version:2`
and `event`. Schema version 2 changes the live identity from a platform-specific
application identifier to `{exe_name,process_id,hwnd}`. Consumers of version 1
must explicitly migrate. A new process or stream starts a new generation namespace.

The stream never prints screenshots, PNG data URLs, raw model responses, player
names or backend response bodies. Consumers may ignore unknown additive fields or
events but must never infer a recommendation from `status`.

## Checkpoint B Additions

The B recorder adds metadata-only `recording_enabled`, `recorded_frames`,
`recorded_bytes`, `recording_status` and `recording_complete`. Status is
`disabled`, `active`, `count_limit`, `disk_limit` or `io_failure`. Counters
acknowledge PNG plus append-only manifest rows durably synced under a new
`.local/captures/<UTC>-practice/` session. Defaults are 7,200 frames, 1 GiB and
500 ms; hard bounds are 20,000 frames, 2 GiB and 250..60,000 ms. Caps/failures
preserve the prefix and do not reset, delete evidence or create another run.
Monitoring may continue after recording stops. Complete means an uninterrupted
eligible sampled prefix, not every frame or validated game history.

Manifest rows contain source UTC, capture-call-start monotonic time, dimensions,
frame index, PNG size/SHA-256 and opaque provenance. Generation stays null when
unknown. Images, paths, titles and private candidates never enter the browser.
Enabled B telemetry supersedes the fixed first-phase no-recorder fields below.

The user's `2026-10-10T15:03:16Z` correction selects the unique visible CoinPoker
window matching `^NLH\s*[0-9]+`, without practice/lobby/cash title distinctions.
Practice-six-max is user-declared scope, not mode proof from a title. Stable
executable/PID/HWND identity survives resizing, title suffix and role changes.
Capture reads current dimensions; normalized six-max regions scale and
letter/pillar-box to them. Missing/ambiguous windows block. Lobby imagery stays
reference only, never seated-positive data.

Source-current health reaches the observer even if model admission fails.
Opaque capture references advance for genuine new captures, including identical
images whose generation stays unchanged. Age is checked after output writes.
Role changes do not reset history; unknown seats/actions yield unvalidated gaps,
never fabricated betting statistics.

The immutable it1 `calibration.json` acceptance report is separately size/SHA
pinned from temperature calibration. Responses carry `acceptance_floor`;
native comparisons are f64 and use `max(vendor, fitted, optional override)`.
Missing/invalid floors fail closed. P0 0.995 and board 1.0 are not clamped to the
CLI override bound; 0.99999999 cannot round into a confident board card.
Untrained passes remain unrun, metrics/advice remain off and Gate F is unchanged.

Actual-window calibration after the user's `16:52:31Z` table report found the
logo/NLH/number caption drawn internally while Win32 exposes exact `CoinPoker`.
After explicit question-tool confirmation, a private profile can select exact
`^CoinPoker$` on the same executable. This does not broaden the default NLH rule
or approve perception, and multiple matching visible windows still block.
Changed PID/HWND during table rotation begins a separate stream/recorder while
retaining prior files/ledgers; resizing the same identity retains its stream and
history. Real B captures verified both cases. Loading/transition captures remain
unlabelled, never implicit positive table or seated examples. Hash/manifest
integrity and fresh capture health do not establish accepted poker readings.

## Live records

| Event | Required fields and meaning |
| --- | --- |
| `configuration` | Active `runtime` thresholds, `identity_configured`, `model`, `vlm_timeout_secs`, `visual_calibration:"not_validated"`; this does not assert readiness. |
| `status` | `state`, `reason`, `identity`. Runtime status identity is an object or null. Early configuration and listing failure records may omit it; treat omission as null. Emitted only when this tuple changes. |
| `decision` | Existing decision fields plus `observation`, `captured_at_unix_ms`, `valid_for_ms`, `emitted_at_unix_ms`, `expires_at_unix_ms`. Only emitted after source-current admission; the first-phase browser still withholds all advice because seated quality is unapproved. |
| `observation` | Separately admitted full-state observation with `observation` ticket, source capture/emission/expiry times, remaining lease, cards/phase, nullable chip amounts/actions, `action_required` and `quality_approved`. This is the browser's freshness-bound diagnostic source, not a raw model response or a quality approval. Unseated hero amounts and offered controls are null, not zero/absent. |
| `observation_invalidated` | `reason`, `generation`, `epoch`, `identity`, `emitted_at_unix_ms`. Invalidates current diagnostics even when no recommendation exists. |
| `capture_health` | Every 1000 ms: cumulative `frame_count`, nullable `frame_width`/`frame_height`, capture/emission time, generation/epoch/identity and `fresh_capture`. A delayed source frame cannot claim fresh health. `recording_enabled:false` and `recorded_frames:0` explicitly distinguish capture from image recording. |
| `history` | Sanitized bounded observer `summary` and emission time after a successfully emitted, still-current observation. The baseline contributes `unvalidated_source` gaps only, never guessed player actions or profiles. |
| `table` | `game_phase`, `hero_cards`, `board`, `action_required`. Weaker card-only consensus reading without a ticket or external lease. Not equivalent to complete state/advice admission and not authoritative current controls. Emitted only when that tuple changes; no player names or table id. |
| `clear` | `reason`, `generation`; invalidates one active decision and is not repeated when no decision is active. |
| `discarded` | `generation` and a safe reason such as `obsolete-observation`, `observation-expired`, `decision-budget-expired`, or `publication-expired`. Obsolete/expired completions are discarded whole; they cannot classify, seed consensus, or reactivate older diagnostics/advice. |

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

1. Clear current diagnostics on `observation_invalidated` independently of advice, and clear advice on `clear`. Clear both on EOF/process loss, expired lease, or new stream.
2. `valid_for_ms` is the remaining lease at emission. Compare
   `expires_at_unix_ms` with the current clock; delayed lines do not receive a new
   full lease. Use the shorter available wall-clock or monotonic lease.
3. Never show an older generation/epoch over a newer one; duplicate packets/polls cannot renew a lease. Tombstone cleared/expired versions until a newer source admission.
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

`--decision-budget-ms` defaults to 5000 (bounds 500..5000), independently of the
5-second per-request timeout and 8-second maximum frame age. The total deadline
starts with source capture and reserves 300 ms for publication/poll/render;
each Laya pass receives only the remaining worker budget. A timeout does not
cancel GPU work or free its slot: late completions/publications are withheld.
The previous iteration's latency/quality failure is not retroactively passed.

## Monitor and Reference, browser snapshot version 1

The browser and model API share `http://127.0.0.1:18090/`. `GET /api/state`
normalizes the native JSONL pipe into a small snapshot:
opaque stream `session_id`, monotonic `event_seq`, model/capture states, nullable
experimental observation, history/ledger status, `advice:null`, and readiness.
It omits native HWND/PID/name data, raw responses, images and backend bodies.
The service never accepts browser capture/process/poker-control requests. The
user-facing app has exactly **Monitor** and **Reference** views; runtime details,
freshness internals, private ledger status and synthetic fixtures are not extra
app views. A disconnected/empty Monitor has one compact message.

The additive role-aware observation contract uses `role` (`observing`,
`seated_waiting`, `your_turn`, `uncertain`), nullable `hero_seated` and
`action_required`, and nullable one-based `acting_seat` (1..6). Missing hero cards
are not evidence that the user is unseated. Contradictory or absent role evidence
stays uncertain. Role changes do not begin a new stream or clear prior history.
The new DTO is software-tested, not validation of it1 seated recognition.

The native feed's `verified_fields` allowlist distinguishes explicit shape/
semantic-validated readings from legacy placeholders. Allowed names are
`hero_seated`, `action_required`, `controls`, `pot_size`, `to_call`, `hero_chips`,
`min_raise_to`, `max_raise_to`, `acting_seat`, `acting_to_call`, and `wagers`.
Omitted/malformed verification yields unknowns; it is not perception-quality or
advice approval and is not forwarded as a browser grant. Existing question-set
0.4.0 R15/R17 unseated admission can supply observing provenance only on a full
source-leased Laya observation. A generic state with no Hero or a weak `table`
record cannot establish that the user is unseated. Valid seated Hero stack
evidence can survive waiting/folded states; it does not enable turn controls.

`amounts.acting_to_call` is nullable, separately from hero `to_call`. Observing
mode never exposes hero placeholders as a "your call". `wagers` is a bounded list
of `{seat,amount}` entries, with physical seat labels 1..6 and unknown amounts
null. Controls keep independent presence/enabled labels, are multi-label, and
distinguish Bet from Raise (including re-raises). Neither presence nor an empty
legacy action list establishes legality. No parser/raw-model bypass is added.

`metrics` has `hand_rank`, `pot_odds`, `draw`, and `equity_pct`. Until separate
capability approval, all are null even if a feed asserts `quality_approved:true`.
Future pot-odds metrics carry the acting seat; future draw-completion probability
is not win equity. Browser rendering does not derive poker strategy from
experimental perception. `advice` remains null and `advice_ready:false`.

- `UI_READY` means the page/status service works, not that a model/recorder/adviser passed.
- `COLLECTOR_READY` requires actual registered capture/recording evidence. This
  phase has no image recorder in the native feed and cannot claim it from a heartbeat.
- `server.model_state:ready` means verified weights loaded; temperature calibration
  loading is separate from the failed quality gate and `advice_ready:false`.
- Live controls remain independently unknown, with presence/enabled labels. No
  empty legacy array or recommended action supplies missing offered controls.
- The private session ledger is prefix-preserving, capped at 10,000 events / 25 MiB;
  cap or I/O failure is visible as incomplete, never silently repaired/deleted.
- Internal observer slots 0..5 are normalized to physical browser labels 1..6;
  opaque u64 identities are not passed through JavaScript numbers.
- Synthetic fixtures are internal/test-only; `GET /api/replay` is no longer a
  supported route. CLI `--stdin` below is unchanged, not another app view.
- Reference facts are researched from several cited education sources and bundled
  in the browser asset. Reference search/collapse makes no runtime requests.
  `GET /api/reference` also exposes the bounded local JSON source for development;
  missing/invalid data returns a sanitized 503, never file or exception details.
  Reference material is not live advice or positive seated UI images.
- History includes nullable observed fold/check/call/bet/raise counts and bounded
  source-provided preflop raise ordinals. The browser never invents 3-bet/4-bet
  order from a gapped sequence or resets history just because seating changes.

HTTP handling is bounded/concurrent, but model requests have one nonblocking
GPU admission slot. Status/UI remain responsive during slow inference. The
browser polls at 250 ms with one outstanding request and source-bound local
expiry; disconnect, heartbeat loss, older sequence/session, and tab hide/resume
clear before revalidation. Same-session polls never refresh a source lease.

Launch `scripts/start-vlm.ps1 -DashboardOnly` for Monitor/Reference without GPU loading;
the default asynchronously verifies/loads the pinned model. An explicit
`-LiveConfig .local/profile.json` supervises only the configured native passive
feed, with fixed local model endpoint and a private ledger. Supported profile
keys: `binary` (built checkout coinpoker executable), `exe_name`, `pid`,
`window_hwnd`, `window_title` (native `--table-title`), `lobby_title`,
`lobby_size` (`WIDTHxHEIGHT`). No arbitrary argv, model endpoint, or record-dir
field is accepted. Actual capture requires a later operator go-ahead; no such
profile is invoked by first-phase validation. The role-aware work supersedes
operator-launched profiles as the normal Monitor workflow: automatic attachment
after one-time `--list-windows` calibration is checkpoint B, not implemented or
started in checkpoint A. Checkpoint A reuses the existing model service without
restarting it; changed Python imports/routes take effect at the controlled B
restart. The updated bundled Reference/static page already works without one.

## Per-field observing contract (stage2 implemented)

Implemented2026-10-10: independently leased `partial_observation` bundles use
nullable phase/board slots/count/pot and six explicit physical seats1..6, separate
from strictactionable GameState. Closed field/capability allowlists gate each value;
p6wager/p7scene registries defaultdisabled, requiring pinned per-seat ownfloor/crop/
model/evidence/human-held-out proof. Source-region SHA256 comparisons and original
expiry withhold changed/late/stale data; negativeproof also vetoes strictsiblings.
Same-ticket fullobservations cannot refill rejectedpartialfields. No advice/R17
promotion or unknown-to-zero conversion. Hand/roster/order/convention gaps block
derivedevents/positions/math, not independently accepted amounts.

`perception_diagnostics` is bounded, closed-vocabulary PRIVATE journaling only,
including obsolete zero-lease outcomes, exactcrops/floors/answers and eligibility
versusadmission. Unmeasuredtimings null; no pixels/prompts/names/fingerprints in
browserstate. Browser gets only sanitized amount/scene status markers. Exactly
Monitor/Reference. Offline506Rust/207Python-Node regressions andclippy passed;
realwarmtotal latency/perception/humanacceptance remainpending. The earlier
designhistory below is retained but its not-implemented claims are superseded.

Stage 1 (2026-10-10) confirms existing `observation`/`verified_fields` sanitize
fully admitted states downstream, not independent native field admission. Laya
skips trained stack passes, lacks wagers/badges/dealer/acting and discards players.
Historical diagnostic candidates must never be injected into current observations.
See section 7 of `LAYA_VISION_PHASE_A.md` and the active practice/history plan.

Proposed `partial_observation` is **distinct from actionable GameState and existing
observation**. No producer or consumer supports it yet. Proposed invariants:

- Bind opaque session/table/geometry identity, optional validated hand/street,
  original capture time, monotonic sequence, absolute expiry and per-field evidence
  IDs. Browser exposes no raw score/prompt/crop/pixel/path/name/backend payload.
- Each field is optional, never default zero: phase, board count/cards, pot, six
  physical slots with occupancy/participation/fold/all-in, displayed stack, visible
  wager, established street contribution/live credit, dealer/blinds, hand-relative
  position/group, badge/action and acting indication. Hero fields require seated
  evidence and their own approved capability; hidden opponent cards are not inferred.
- Read-only capability/floor/dependency approval is separate from actionable
  quality. Uncertain role/card identity cannot erase independent accepted pot/stack;
  unknown hand/street blocks dependent commitments/events/positions. Confidence
  does not cure contradiction. Partial observations never enable suggestions.
- Polling never renews leases; changes invalidate dependent fields. Replacement,
  source loss, unknown hand transition or geometry reassociation veto context.
  Reject expired/out-of-order/cross-hand combinations and uncertain occupant transfer.
- Freeze dealt-in roster across folds, exclude mid-hand arrivals, keep blind labels
  distinct from early/middle/late and retain actual preflop/postflop order separately.
- History preserves observed/inferred provenance, forced money, badge occurrences,
  ordering uncertainty, gaps, returns/side pots and confirmed street resets. Stack
  changes alone are not actions; visible chips are not proven total contribution
  or a complete 3-bet/4-bet prefix. Unknown remains unknown, not zero.
- Acting-seat call cost/odds need legal bring-in/live credit/remaining chips and
  eligible pot convention; never 'your call' while observing. Do not double-count
  wagers already included in displayed pot.

Private diagnostics retain source/session/hand/hash/age, pass/question, exact crop
bounds/dimensions, closed-vocabulary answer, score/effective floor, score decision
versus admission decision and specific reason; capture/preprocess/encode/queue/
inference/assembly/publish/render timings are separate. Unmeasured stages are null.
Historical score eligibility is not live admission or human capability approval.
Strict advice events/validator/R17 remain unchanged. Stage 2 implementation and
later live observing acceptance each require their own explicit approval.

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
