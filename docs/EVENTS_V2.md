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
Current profile `user_scope` is `six-max-table`, not a practice/cash restriction.
Legacy `practice-six-max` values load as the same exact selector, without profile
rewrites or selector widening. `.local/practice-table.json` and `-PracticeConfig`
remain compatibility names; metadata/title never proves actual game mode/layout. Stable
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
Untrained passes remain unrun and Gate F is unchanged. The original checkpoint
kept metrics/advice off; the current experimental projection contract below does
not change those historical results or establish new model capabilities.

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
| `decision` | Existing decision fields plus `observation`, `captured_at_unix_ms`, `valid_for_ms`, `emitted_at_unix_ms`, `expires_at_unix_ms`. Only emitted after source-current full-state admission. A matching current decision can project as explicitly experimental analysis; it does not certify perception quality. |
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
experimental observation, history/ledger status, nullable experimental `advice`, and readiness.
It omits native HWND/PID/name data, raw responses, images and backend bodies.
The service accepts an explicit, session-bound capture-stop request; HTTP start,
mark, model/process management and poker-input routes are not implemented. The
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

`metrics` has `hand_rank`, `pot_odds`, `draw`, and `equity_pct`. Only a current full
native observation that passes native-shape and semantic checks can supply them;
partial fields, raw model answers or a claimed `quality_approved:true` cannot.
Numbers must be finite and in range, with the required card/role/amount evidence.
Hand ranks use the closed native vocabulary; hero metrics require a seated hero
with two cards. Pot odds carry an explicit acting seat when observing and must
match the verified call/pot amounts. Draw completion applies to flop/turn and is
not win equity. Missing or unsupported metrics stay null, not zero.

Public full observations and advice carry `session_id`, opaque 16-hex `source_id`,
`generation`, `epoch`, original `captured_at_unix_ms`, `expires_at_unix_ms`, and
`remaining_ms`. They bind to the current root session, `capture.source_id`,
`capture.generation`/epoch and service `server.instance_id`. Advice must match
the full observation's source, generation, epoch and capture time; its expiry and
remaining lease cannot exceed the observation's. Polls, duplicates or relabelled
generations cannot renew the original lease.

`advice` is null or a bounded projection of the matching native decision:
`action`, `amount`, `ev`, `equity_pct`, nullable `pot_odds_pct`, `break_even_pct`
and `confidence`, plus the source/lease fields above. Actions are `fold`, `check`,
`call`, `raise`, or `all_in` and must be explicitly offered/enabled on a current
`your_turn` full state. Fold/check amount is zero; call is `min(to_call, hero_chips)`;
raise uses verified min/max bounds. The current DTO can validate `all_in` only
as a short all-in call, not an all-in raise-to amount; native Bet is unsupported.
No recommendation is inferred from weak `table` events or partial observations.

Projected observations/advice stay `experimental:true`, `quality_approved:false`.
`server.advice_ready` is true only while admitted experimental advice is current,
not a certification flag. The model's `quality_gate:"failed"` remains factual;
it is not a blanket veto on genuine validated native analysis. R17/parser checks,
the current model's untrained hero/control limits, source freshness, legal-action
validation and clearing on stale/partial/replaced input all remain in force.

- `UI_READY` means the page/status service works, not that a model/recorder/adviser passed.
- `COLLECTOR_READY` requires actual registered capture/recording evidence; a
  capture-health heartbeat alone does not establish a recorder receipt.
- `server.model_state:ready` means verified weights loaded; temperature calibration
  loading is separate from the failed quality gate and experimental advice availability.
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

### Explicit Capture Stop

`POST /api/capture/stop` accepts a JSON object with exactly `session_id` and
`service_instance_id`, both 32-character lowercase hex identifiers. The browser
uses the current `capture_session.session_id` and `server.instance_id`; duplicate
or extra keys are invalid. Requests require `application/json`, a body of at most
512 bytes, and the service's local Host/same-origin checks. The request is admitted
only for a fresh currently capturing receipt and matching service/session binding.

`200 {"ok":true}` acknowledges a stop request, not completed child teardown.
`409 {"error":"capture-session-unavailable"}` reports an ended/stale/mismatched
session or service; malformed JSON/identifiers return `400`. The route requests
the named session's existing stop path and invalidates current output. It neither
loads a model nor waits for a GPU slot. Monitor exposes it through **Stop capture**;
GET polling remains side-effect-free. HTTP start/mark and poker-input endpoints
are not implemented; their absence is a capability description, not an authorization ban.

### Historical Checkpoint A/B Startup

The following paragraph records the old startup design, not current commands.
Current defaults, explicit inference opt-in and manual/automatic source workflows
are in [SEATED_DIAGNOSTIC.md](SEATED_DIAGNOSTIC.md).

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

### Companion diagnostic extension (2026-10-11)

The current launcher defaults to dashboard-only, with no automatic capture/model
load; earlier `-LiveConfig`/automatic-attachment descriptions are historical.
`--enable-inference`/`-EnableInference` is a distinct explicit service opt-in and
does not start capture. `server.inference_enabled` reflects declared opt-in even
while the model is loading/failed, not merely whether an engine object exists.

Native partial views add optional `pot_size_text`, per-seat `displayed_stack_text`
and `visible_wager_text`; projection requires these numeric glyphs to equal the
separate integer-hundredths value. Existing numeric fields are unchanged. Missing
literal text does not imply a currency symbol. Full observation uses optional
`amount_texts` and separately verified `hero_seat`; seat4 is never a default hero.

Public snapshot/observation `field_statuses` maps closed field paths to
`{status: accepted|unavailable, reason: null|<code>}`. The only unavailable codes
are `missing-capability`, `unsupported-layout`, `below-floor`, `stale`, `occluded`,
`insufficient-context`. Private diagnostics remain private; scores, crops, prompts,
source identity and raw text never leak through these reasons. Diagnostics cannot
admit values, extend source expiry, or turn draft labels into approval. A changed
board slot clears only that slot plus dependent phase/count, not unchanged cards.

`capture_session` is an allowlisted, read-only projection of the separate manual
session receipt: opaque session ID, capture-only or inference-enabled mode/status, elapsed/remaining
time,600000ms/1200-frame maxima, acknowledged saved frames/bytes, capture failures,
gap count/max gap/estimated missed samples, distinct draft opportunity count,
target20/deficit, stop reason, update time and separate inference consent. Missing/malformed
receipts remain unknown/failed; stale active status becomes interrupted. Estimates
are missed samples, never inferred poker actions. No HWND/title/path/PNG/marker
prose is served. Capture stop is the explicit POST described above; HTTP start/mark
and poker-input endpoints are not implemented.

Manual capture emits separate private `manual_capture` progress JSONL and uses
the existing recorder manifest, with capture-call-start UTC, PNG SHA256 and
previous-saved-gap receipts. Markers reference an acknowledged hash/frame index
without rewriting observations or evidence; labels DRAFT, human PENDING and
accepted_correction false. Manual startup requires only the fresh exact
`CAPTURE <PID> <HWND> <nonce>` challenge, identity recheck and 30-second deadline,
not seating. New manual receipts use `operator_assertion:null`; the known legacy
`I am seated and ready` value is accepted only for persisted-receipt compatibility,
and arbitrary strings are rejected. Neither form establishes hero identity.
Terminal budget/source/error stops
do not rearm. See [SEATED_DIAGNOSTIC.md](SEATED_DIAGNOSTIC.md).

### Manual Inference Transport (2026-10-12)

The separate native entry point is `--manual-inference --approval-file <private>`.
Its supervisor requires separate installed-it1 consent and ready service, then fresh
exact-source confirmation with no seating assertion. `--capture-only` keeps its independent dispatch,
without model probes or prediction calls. Automatic attachment is not restored.

One approved capture owner records the identical frame before passing it to existing
LiveRuntime/Laya machinery. Tickets carry optional original capture-call-start UTC
alongside monotonic time; lease endpoints never use inference/HTTP/poll time.
Same-source resize revalidates geometry, not budget or consent. The first duration
or frame limit stops the entire session, not only recording.

Native stdout mixes private version-1 progress and existing schema-2 typed capture,
partial/full observation, diagnostics and history. Records add private
`service_instance_id` and `mode: inference-enabled`. Manual single/batch prediction
requests add `X-Coinpoker-Service` and `X-Coinpoker-Session`. The exact active private
session must remain approved before/after work; mismatch, STOP, expiry or terminal
state returns `409 manual-session-ended`. Separately enabled saved-frame diagnostic
callers keep their existing API. No new capability or floor is activated.

The bounded passive `ManualSessionFeed` reads the owned child's private JSONL and
invokes existing `DashboardState.ingest`/projection. It never selects/spawns capture.
The browser reads sanitized `GET /api/state`, distinguishing
session consent, model loading/ready/error, busy/idle, rejected or independently
accepted fields, and terminal states. Source replacement and terminal conditions
tombstone results and stop the retired owned session; recovered status cannot rearm
it. Refresh starts neither mode; only an explicit Stop action issues the POST above.
Manual mode now supplies the existing decision Pipeline and forwards its genuinely
admitted full observations/decisions instead of dropping them categorically.
R17/parser/source/deadline validation remains; partials and unleased `table` records
cannot stand in for complete GameState or leased analysis. Old
logs are not rebased into current readings. See the runbook for bounded receipts.

### Explicit Automatic Observation Policy

After the operator's later authorization, `--enable-inference --automatic-inference`
arms one bounded startup attempt using a required, existing private source profile.
Approval uses `source_policy: automatic-bounded` and a separate automatic assertion,
never a fabricated seated assertion. The native dispatch/recorder/Laya/feed stay the
same. Missing profiles, ambiguity, replacement and terminal conditions fail closed.
`automatic_startup` describes metadata search/loading independently of any session.
Progress and typed events include `source_policy` and `activity_state`. Under the
2026-10-12 standing GO, independently admitted partial Pot/stack/card readings can
publish while `activity_state: verifying`; history/full observations still require
qualified visible table activity. Source health and partial display do not depend
on a betting-content change or seated assertion. The former 30s unconfirmed-probe
stop is removed; all frames/time count against the original 600s/1200-frame limits.
Activity qualification does not claim continuing poker actions. Automatic jobs run
p0 plus one trained field from startup in bounded three-job lanes; qualified partial
readouts continue requesting distinct fresh sources rather than pausing a full lease.
Exact field-source witnesses, two-source consensus, fitted floors, five-second source
expiry and invalidation remain unchanged. Partial readouts cannot enable advice;
experimental analysis still requires the full-state contract above.

### Sustained Observation Receipt Variant

`--continuous-observation` additionally requires both inference/automatic opt-ins
and refuses experimental diagnostics. It authorizes only `automatic-sustained`
with a private version-2 source approval and a distinct same-source assertion;
version-1 manual and automatic-bounded approvals retain their original limits.
Native progress is version 2 only for sustained mode and adds a required nullable
`recording_end_reason` (`duration-limit`, `frame-limit`, or `disk-limit`). Native
`elapsed_ms` continues measuring observation; expected recorder closure freezes
its durable counters but does not stop fresh, validated live inference.

The browser root schema stays version 1. Its sustained `capture_session` requires
`receipt_version: 2`, explicit `source_policy: automatic-sustained`, inference-only
mode, experiment false, and null `max_duration_ms`, `remaining_ms`, and `max_frames`.
It retains observation status, elapsed time, heartbeat, opaque session ID, and top
saved counters. Its exact `evidence` object has `status: active|ended`, nullable
cap-only `stop_reason`, frozen-on-end `elapsed_ms`, finite `max_duration_ms`,
`max_frames`, `max_bytes`, and matching `recorded_frames`/`recorded_bytes`.
Limits remain at most 600000ms/1200 frames and exactly 1073741824 bytes. Disk closure
can precede the byte maximum when the next PNG would not fit. Terminal observation
may retain an earlier active evidence receipt, but neither is then current.

Sustained `elapsed_ms` is the original owner-monotonic sample, not that sample
plus wall-clock receipt age. On Windows those clocks can have different tick
granularities; interpolating UTC age can manufacture a backward elapsed counter
at the next valid heartbeat and falsely retire the owner. Receipt freshness and
the non-renewable monotonic heartbeat deadline remain independent and unchanged.

Only the current approved owner's bounded stdout pipe can submit sustained typed
events through ManualSessionFeed's existing source/instance/activity/DTO guards;
its capped diagnostic JSONL is never a live feed or replay source. Recorder-budget
closure does not authorize new evidence, change source, renew a five-second field
lease, or relax the three-second receipt / 2500ms capture heartbeat. Terminal and
stale receipts remain tombstoned; GET remains passive. Numeric scheduling combines
Pot and one physical-seat stack where supported, repeats Board captures for actual
consensus, and prioritizes numeric refresh using measured job cost. It never merges
unrelated generations or promises simultaneously current stacks at every seat.

The explicit automatic mode now reads the selected window's current unobscured
desktop rectangle using a synchronous GDI screen copy. It does not ask the client
to paint, send input, change focus/geometry, use disk PNGs, or restamp a WGC surface.
Window identity, visibility, Z-order obstruction and rectangle equality are checked
before/after the copy; an obscured/moved/lost source stops rather than switches.
Private native stderr records the capture backend. Each saved frame and model job
retains its original capture-call UTC/monotonic stamp and five-second lease. Manual
and ordinary platform capture retain WGC and its compositor-timestamp checks.

Automatic readout scheduling compares the existing trained readout regions
independently; inference still receives original, unmasked pixels. Activity's two
baseline/two changed witnesses must refer to the same exact-current region within
the original freshness interval and source epoch. Missing witnesses never renew a
baseline. Source/scope/geometry changes still invalidate the source; cosmetic pixel
changes outside a field do not make that field's unchanged pixels obsolete.

The private schema-2 `partial_observation_invalidated` event contains `reason`,
the exact originally published `observation` ticket, its `generation`, `epoch`,
`identity`, optional original `captured_at_unix_ms`, and current emission time.
It contains no values or renewed lease. Without `fields`, it clears only the
matching published partial. An optional nonempty `fields` list names exact removed
verified fields from the closed field allowlist; only those values and their
dependent display aggregates are cleared. Unchanged fields retain the original
ticket, capture timestamps, expiry, and remaining lease. Empty, duplicate, or unknown
field lists are invalid. Recognized fields already cleared or withheld by consumer
projection are ignored; they must not prevent invalidating other admitted fields
in the same list. An invalidation cannot add values or make the old source admissible
again. Complete source/core loss still clears the bundle. Publication-only expiry
uses the original publication ticket with `observation-expired` and no `fields`;
it does not tombstone a newer worker ticket or renew any candidate's original budget.
Capture-health version remains monotonic, an older publication cannot
tombstone a newer in-flight result, and the invalidated original source cannot be
replayed under another generation. Foreign, malformed, mismatched or delayed scoped
events cannot clear a newer packet. Existing global `observation_invalidated`
retains its whole-generation/source veto. The public `/api/state` shape is unchanged.

The real corrected trial produced three private `perception_diagnostics` and three
`discarded` events: two decision-deadline-exceeded and one obsolete-observation.
DashboardState retained original source provenance but did not admit expired values;
the browser displayed stopped/cleared readings and the actual recorder receipt.
These rejection events verify transport, not live reading accuracy or activation.

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

### Offline draft labels are not events (2026-10-10)

The private `observing-20261010-v2-staging/human-review-20261010` sidecar binds
draft labels to original-frame SHA256, original-pixel crop bounds and crop hashes.
Its six physical-seat IDs are spatial slots, not player-vector order, opponent
identities or confirmed hand rosters. All labels remain DRAFT, human review
PENDING; the original staging manifest remains unlabeled/ineligible.

These artifacts are not accepted `PartialObservation`, strict `GameState`,
history events, fitted floors or registry authorization. Visible wager, upper
Pot text and lower center-chip text remain separate; street contribution, pot
convention and ordered actions stay unknown. A badge is not a new action; payout
glow is not acting; sampled board changes are not confirmed hand boundaries.
Whole-hand/split IDs remain pending, with adjacent session/duplicate groups kept
together. Artifact checks do not validate recognition or promote Gate F. R17 and
suggestions OFF remain unchanged. No event schema or runtime path changed here.

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
