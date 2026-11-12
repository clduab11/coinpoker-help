# coinpoker-help

Local bug-bounty proof of concept for poker observation and decision support.
Native capture targets Windows 10 version 1903 or later. Structured JSON replay
and poker libraries also run on Linux.
The current helper has no mouse/keyboard input path, client-memory reader, or
client-network interception.

**Status:** engineering candidate, version `0.1.0`; Laya iteration-1 Gate F
**FAIL**, human verification **UNVERIFIED**, no validated live seated advice. A build,
synthetic evaluation or loaded model is not real-table acceptance. Physical
Windows, model, real-image and clean-account evidence is recorded in
[the Windows report](docs/WINDOWS_ACCEPTANCE_V1.md); unrun gates stay `UNRUN`.
Practice and cash use this same repo, representation and validation mechanism,
without a practice-only bypass. No real-money acceptance has been established.

## Start here

- [Next live session: self-sufficient play (handoff brief)](HANDOFF.md)
- [First manual seated diagnostic: launch, confirm, stop and checklist](docs/SEATED_DIAGNOSTIC.md)
- [Windows setup and local dashboard](docs/INSTALL_WINDOWS.md)
- [VLM compatibility and provenance](docs/VLM_COMPATIBILITY.md)
- [Live JSON-lines contract](docs/EVENTS_V2.md)
- [Visual evaluation contract](docs/VISUAL_EVALUATION_V2.md)
- [Model terms](MODEL_LICENSES.md), [security](SECURITY.md), [contributing](CONTRIBUTING.md)
- [Archive — superseded docs and handoffs](docs/archive/README.md)

## Current model and browser

The sole perception backend is Laya Vision. Reuse the already downloaded and
trained checkpoint `models/laya-vision/finetuned/20261009T190322Z-it1`, based on
`thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc` and recorded in
`scripts/laya-pins.json`. No redownload, retraining or new dump is needed for
this dashboard phase. A fresh install lacks this user's local fine-tuned weights.

The canonical browser address is **`http://127.0.0.1:18090/`**. Model metadata
is at `/v1/models` under alias `coinpoker-laya-vision`; typed Laya requests use
`/v1/laya/predict` on the same listener. Gemma, ports `18080`/`8080`,
chat-completions and remote VLM opt-in are retired product instructions, not
alternate endpoints or fallbacks.

The browser has exactly two views, **Monitor** and **Reference** in a compact
landscape companion. Monitor shows source/role/freshness, independent readings,
six physical seats and a separate recorder status; history and diagnostics are
collapsible. A genuine current full native observation and matching decision can
display **EXPERIMENTAL** analysis with `quality_approved:false`; partial readouts
cannot supply it. The pinned model's R17 and untrained hero/control limitations
remain, and no live seated capability or quality certification is claimed.
Reference uses a searchable topic list and selected content, with the existing
bundled education and citations unchanged.
It makes no runtime content requests and does not copy the root charts.

Open `http://127.0.0.1:18090/` beside the selected table. **Start monitor** and
**Stop monitor** issue the local `POST /api/capture/start` and
`POST /api/capture/stop` routes. Both bind the request to the current service and
control token; Stop also binds the active capture session when one exists and can
cancel pending source discovery before a session ID is assigned. Start requires a
configured manual-start service and ready model. These JSON routes retain the
local Host/same-origin and session/service checks; polling remains passive, and a
start/stop acknowledgement is not completed capture/teardown. There are no HTTP
mark, seating or betting controls. For development startup, choose one mode below,
not two concurrent servers; inspect the existing 18090 listener before starting
anything. Reuse an already running service.

```powershell
# Dashboard-only startup without loading a model or using the GPU.
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

```powershell
# Normal startup is also dashboard-only. No automatic model load or attachment.
pwsh -File scripts/start-vlm.ps1
```

The role display follows explicit current-source evidence: **Observing**,
**Seated** ("Waiting for your turn"), **Your turn**, or **Reading uncertain**.
Observing call cost/pot odds belong to the labelled acting seat, never a fictitious
"your call". Sitting down changes the role, not the stream or accumulated history.
Unknown readings stay unknown; a missing feed is one compact message, not a grid
of unavailable fields. Expiry, heartbeat loss, hidden/resumed tabs and disconnects
clear current readings without renewing their leases. Runtime/lease/ledger details
and synthetic fixtures stay behind the scenes, not in extra app views.

Normal startup no longer follows a saved selector. `-LiveConfig`, a supplied
`-PracticeConfig` without explicit automatic inference, and server `--auto-attach` are refused. A fresh manual
session requires the fresh exact PID/HWND/nonce challenge via
`scripts/laya_capture.py`, with identity rechecked within 30 seconds. No seating
assertion is required; replacement requires new source confirmation. Default first-session
limits are **600 seconds or 1,200 saved frames**, whichever comes first. Model
loading requires separately approved `-EnableInference`; it never starts capture.
See the [manual runbook](docs/SEATED_DIAGNOSTIC.md) for commands and draft markers.

For explicitly approved observation of one confirmed table window until it closes,
use the canonical sustained manual-start mode after verifying/stopping only the
owned existing service:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation -ManualStart
```

For bounded manual-start recovery, omit `-ContinuousObservation`:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ManualStart
```

Both modes reuse the confirmed private source profile and start capture only after
an explicit Monitor Start request; they never follow a replacement or change the
poker client. In sustained mode, evidence recording still stops at 600 seconds,
1,200 saved frames, or 1 GiB, but newly acquired live frames continue through
bounded in-memory transport. Bounded mode instead stops collection at its first
time, frame or evidence limit. Monitor labels that distinction and puts stop
reasons in its main view. Field confidence floors and five-second reading leases
are unchanged; unknown role/activity does not hide independent admitted numeric
fields. Page refresh starts nothing. Source/visibility/owner/model failure or an
explicit stop ends observation without automatic resume. Sustained mode does not
run experimental p6/p7 diagnostics, strategy, or timer recognition. Synthetic
sustained tests are not real-window recognition acceptance.

CPU numeric, visual and context lanes are **provisional**, distinct from native
admitted **current** values and UI-only **last-read** values. Per field, a newer
or same-capture provisional CPU value may win; CPU empty Pot cannot veto native
Pot; and board precedence is native admitted board, then provisional board, then
last-read. Last-read values are not current and never enter API GameState,
history or advice. Private original/event diagnostics, including
`diagnostic-attempts-only`, are not admitted observations.

Some client windows draw the CoinPoker logo and `NLH` number inside their frame
but expose only `CoinPoker` as the OS title, and the client reuses that same title
for its lobby window. A confirmed private selector can use that exact OS title.
When several visible windows match, the selector keeps only those whose
dimensions can present the calibrated table surface without letterbox bars, so
the lobby is discarded and the table is selected; if no single table surface
remains, attachment still fails closed. This is **not** a general lobby
classifier: it is metadata-only geometry, requires explicit user confirmation for
the title rule, and pins the selected PID/HWND without a size pin. Source
identity, current dimensions and perception-quality gates stay independent;
transition/loading/lobby captures are not positive table labels.

Current profile metadata uses `user_scope:"six-max-table"`, not a practice/cash
mode restriction. Legacy `practice-six-max` profiles load with the identical
exact selector, without rewriting the source file or broadening its matches.
`.local/practice-table.json` and `-PracticeConfig` remain compatibility names;
neither names nor window titles prove the actual game mode or layout.

The native recorder saves only private PNGs and a durable SHA-256 manifest under
`.local/captures/<UTC>-practice/`. The historical generic recorder defaults were
7,200 frames, 1 GiB and 500 ms; the new bounded manual entry point overrides the
frame limit to 1,200 and adds the independent 600-second stop.
Caps or I/O failures preserve the prefix and stop new recording without deleting
evidence. The manual session never rearms or follows a replacement. State DTOs
contain no PNG bytes or data URLs. Bounded `GET /api/evidence/<sha256>` serves
only registered hash-allowlisted local original/crop PNGs for source backchecks;
it is not arbitrary file access. Local on-screen player labels remain allowed.
Raw private paths, raw model answers, backend bodies, HWND, PID and window class
are not public browser fields. Public bindings use opaque identities while full
capture provenance remains local. Real counters are separate from capture-health
counters.
The confirmed real-window B check recorded 900x686 frames, followed the
replacement table and captured its 800x613-to-879x670 resize. SHA-256 audits passed
for 322 original, 9 transition and 118 replacement-prefix frames; old evidence
remains in separate private sessions. This establishes capture and recording,
**not usable recognition**: no observations passed the fitted gate, so Monitor
shows `Reading uncertain`. No timed C/seated session or full reading-to-Monitor
latency acceptance has occurred. Seated controls/hero amounts and calculated metrics
require the later genuine-data/quality checkpoints; a null metric is not zero.
Private session history uses opaque IDs, not player names or cross-session guesses.

Current Phase 0a/A3 validation (2026-10-25): **633 Rust tests passed/5 ignored**,
**968 Python tests ran/26 skipped**, and **60/60 synthetic intercepted real-browser
cases passed**. Canonical `scripts/validate.py` checks, synthetic evaluation and
pinned-artifact verification also passed. The browser receipt is
`.local/browser-smoke/20261025T040732Z-81bbf5e5/report.json`. Clean Linux Python
remains the separately recorded A2 result of 963 ran/29 skipped; Linux Rust and
hosted CI remain unverified. These software/synthetic results do not establish
live recognition, physical numeric accuracy or capture-to-Monitor latency.

The old it1 fitted acceptance floors are enforced independently from temperature
calibration; board `1.0` is never lowered or rounded into acceptance.

The baseline receipt stays failed: board threshold `1.0` gave **0/330 confident
board units** on the 66 agent-reviewed frames, despite raw accuracy
`307/330 = 93.03%`. Warm full-battery p95 was **3027.3 ms**, failing the original
`<2000 ms` Gate F target. The prospective `<5000 ms` warm capture-to-display p95
and hard 5000 ms full end-to-end deadline do not retroactively pass that run;
the old benchmark was not seated or capture-to-browser timing. Temperature
calibration is not capability approval; source/vendor `calibrated:false` remains.
Positive real UI data and approved human-held-out calibration/evaluation are
required before seated advice.

**Perception repair stage2 (2026-10-10):** approved implementation is verified
offline, not live-accepted. Partial read-only fields are separate from strict
GameState/R17. Independent pot/sixstacks, source-region witnesses/originalexpiry,
gated per-seat wagers and occupancy/status/badge/button/blind/acting paths are
wired. New capabilities require their own pinned crop/floor/evidence/human-held-out
proof; defaults remainuntrained/unknown. No suggestions/metrics or qualitypromotion.
Monitor/Reference remain the onlyviews; stack and wager are distinct, and
unsupported contributions remain unknown in secondary diagnostics.

Offline regressions supported this historical implementation stage but did not
establish live accuracy or latency. Private receipts and the unlabeled 72-frame
v2 index remain local. No helper/model reload, GPU training, new observing/capture
or game input occurred in that stage. Gate F FAIL, human UNVERIFIED and
suggestions OFF remained unchanged; later readiness counts are recorded above.

Historical stage1 diagnosis: native observing assembly previously skipped trained stack
passes, discards players and lacks wagers/badges/dealer/acting-seat extraction.
This is a recognition/integration failure, not successful tracking. Saved-frame
replay isolated failed unseated/phase questions and zero board admission at the
unchanged 1.0 floor; independent pot/stack glyphs often meet their own old floors.
A confident wrong phase also shows why semantic checks remain necessary. These
historical diagnostic candidates are not Monitor reads or human acceptance.

Proposed repair separates calibrated source-leased **partial read-only
observations** from fully validated actionable `GameState`, with explicit six
physical slots, distinct stacks/wagers/street contributions, hand positions and
betting gaps. R17 remains; partial data cannot enable experimental decisions. No warm total capture-to-Monitor
latency/live recognition gate has passed. [Vision section 7](docs/LAYA_VISION_PHASE_A.md)
records outcomes and later gates; private receipts and a pending 72-frame human
checklist remain local.

`screenshot-1.png`, `screenshot-2.png` and `poker-info-sheet.pdf` are odds,
six-handed raise-first-in and rules references, respectively. They remain
historical deterministic calculation material, not the source of the new
researched Reference or positive hero-button/seated-card UI examples.
Reference displays are not live recommendations.

## Architecture

```text
Windows process and window metadata (exe name, PID, HWND)
  -> unique source-specific confirmed game-window selection, explicit ambiguity
  -> automatic mode: checked synchronous GDI desktop copy, RGBA frame
     (manual/ordinary capture retains Windows Graphics Capture)
  -> cumulative and local pixel change checks, persistently animated tiles
     suppressed (seat avatars, badges, glows), stability gate
  -> one inference worker and one replaceable latest frame
  -> generation, epoch, window identity and capture-age checks
  -> strict screen classification and complete poker-state validation
  -> two matching fresh observations and hand transition guards
  -> Monte Carlo equity and legal decision pipeline
  -> JSON-lines status, leased decision, clear, or discarded event
```

The native capture loop continues during a blocking local Laya
request. A changed or lost window, ambiguous selection, stale frame, or expired
lease clears active advice. Configured source identity and strict recognition,
quality and action validation are required before a visual recommendation. Repeated
model agreement is not independent proof of correct recognition; the held-out
real-image gate remains necessary.

The workspace crates are `ingest` (capture and vision), `core-engine` (poker math),
`ghost-layer` (unwired timing primitives), `opponent-model`, `ui` (unwired native
desktop panel), and `bin` (CLI, replay, diagnostics and evaluation). The current
browser is a local observation dashboard with no input execution layer. Observed
controls, history, calculated metrics and eventual recommendations stay separate;
legacy table events and raw model answers are not trusted current hero actions.

## CLI

From a source checkout, run these in PowerShell after following the install guide:

```powershell
cargo run --release --locked --bin coinpoker -- --help
cargo run --release --locked --bin coinpoker -- --stdin
cargo run --release --locked --bin coinpoker -- --list-windows
cargo run --release --locked --bin coinpoker -- --doctor
cargo run --release --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
```

The historical source-free candidate archive supports bundled CLI/replay checks:

```powershell
& .\coinpoker.exe --help
& .\coinpoker.exe --stdin
& .\coinpoker.exe --list-windows
& .\coinpoker.exe --doctor
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
```

The real client executable and title conventions must come from `--list-windows` on
the actual installed client. The listing reads public metadata and may contain
personal window titles. It captures no pixels. The following low-level selector
example is internal calibration/diagnostic tooling, not a Monitor connect step:

```powershell
$env:COINPOKER_EXE_NAME = '<observed executable name>'
$env:COINPOKER_WINDOW_TITLE = '<observed table-only title fragment>'
$env:COINPOKER_LOBBY_TITLE = '<observed lobby title fragment>'
cargo run --release --locked --bin coinpoker
```

This is not the dashboard-only first-phase startup. With the current helper,
seating and play are manual; capture alone does not establish analysis eligibility.
The old candidate binary invocation is:

```powershell
& .\coinpoker.exe
```

CLI values override nonempty environment values, which override defaults. Invalid
values fail instead of being clamped. `--help` lists all timing and pixel bounds.

| CLI | Environment | Purpose |
| --- | --- | --- |
| `--exe-name` | `COINPOKER_EXE_NAME` | Exact calibrated executable basename, required for live discovery |
| `--pid` | `COINPOKER_PID` | Optional process pin; remove it for restart recovery |
| `--window-hwnd` | `COINPOKER_WINDOW_HWND` | Optional hexadecimal HWND pin; remove it for replacement-window recovery |
| `--table-title` | `COINPOKER_WINDOW_TITLE` | Calibrated table-only substring, required for advice |
| `--lobby-title` | `COINPOKER_LOBBY_TITLE` | Lobby veto that takes precedence over a table hint |
| `--lobby-size` | `COINPOKER_LOBBY_SIZE` | Observed lobby `WIDTHxHEIGHT`. The same title at another size is the table |
| `--vlm-endpoint` | `COINPOKER_VLM_ENDPOINT` | Sole local target: `http://127.0.0.1:18090/v1/laya/predict` |
| `--vlm-model` | `COINPOKER_VLM_MODEL` | Sole pinned alias: `coinpoker-laya-vision`; verify through `/v1/models` |
| `--timeout-secs` | `COINPOKER_VLM_TIMEOUT_SECS` | Per-request timeout, default 5 seconds; not a fresh budget for every phase |
| `--decision-budget-ms` | `COINPOKER_DECISION_BUDGET_MS` | Total source-capture deadline, default 5000 ms, bounds 500..5000; reserves 300 ms for publication/poll/render |
| `--retry-ms` | `COINPOKER_RETRY_MS` | Default 2000 ms; bounded recovery delay |

Equal-ranked windows produce an ambiguity state. A PID or HWND pin is a deliberate
restriction and will wait if its target disappears. Title strings and public process
metadata are user calibration, not cryptographic proof that a window is a table.

## Privacy and model provenance

Automatic capture requests the selected window's current unobscured desktop
rectangle through checked synchronous GDI copies; manual and ordinary capture use
Windows Graphics Capture. The pixel boundary still needs physical evidence. Laya
receives local PNG region requests. Browser state/history DTOs contain no PNGs,
raw model replies or backend bodies; only registered hash-allowlisted original/crop
PNGs are available through `GET /api/evidence/<sha256>`. Local on-screen player
labels are allowed, while raw private paths, raw answers, backend bodies, HWND,
PID and window class stay out of public DTOs. Public bindings are opaque and full
provenance remains local. The service binds loopback only; there is no supported
remote opt-in. Keep new capture pixels under `.local/captures/` and diagnostics
private. Local logs, swap and crash dumps need separate review; private answer
logs are diagnostics, never advice inputs.

`download-model.ps1 -Verify` verifies existing Laya files against
`scripts/laya-pins.json`. Repository source is MIT; the pinned Laya fork and
upstream SmolVLM backbone are Apache-2.0, but Laya weights and the local derivative are
CC-BY-NC-SA-4.0 and are not redistributed. See [model terms](MODEL_LICENSES.md)
and [compatibility evidence](docs/VLM_COMPATIBILITY.md). The orphaned
`scripts/vlm-pins.json` is historical only.

## Structured replay

`--stdin` consumes one complete `GameState` per line and retains its existing bare
decision and clear records. It does not need capture or model setup. Invalid input
clears an active recommendation once; later valid input may recover.

```json
{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],"board":[{"rank":"A","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],"pot_size":1000,"to_call":500,"hero_chips":5000,"min_raise_to":1500,"max_raise_to":5000,"players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Villain","chips":4500,"last_action":"bet","bet_amount":500}],"action_required":true,"available_actions":["fold","call","raise"]}
```

## Study overlay (`--ui`)

`--ui` runs the same live loop with a transparent, click-through decision panel
beside the table. It compiles by default (the `desktop` feature); build without
default features for a lean headless binary. `--features ws` additionally mirrors
every panel event as JSON text frames over a loopback WebSocket.

```powershell
# Show the study overlay beside the table
cargo run --release --bin coinpoker -- --ui
# Dim panel on the left, and mirror events to a local WS consumer
cargo run --release --features ws --bin coinpoker -- --ui --overlay-opacity 0.65 --overlay-position left
```

`--overlay-position` is `right|left|above|below`; both overlay options are only
valid with `--ui`. The overlay is fail-closed: if the live loop stops (source
lost, configuration error, stream EOF) the process exits instead of leaving a
stale window, and closing the overlay window ends the run. The overlay is
presentation only — it never clicks.

## Known limits

- Pixel checks reject malformed, blank and tiny frames; they do not positively
  identify a real table. Wrong title calibration and correlated model errors remain
  possible.
- The 8-second maximum frame age is independent of the tighter 5-second total
  deadline. Published leases use the shorter remaining limit, not a new lifetime
  from delivery. Consumers must honor invalidation, absolute expiry and EOF even
  when capture blocks.
- Persistently animated tiles (seat avatars, badges, glows) are excluded from
  change detection while they animate, so a state change inside such a tile is
  only picked up by the periodic forced refresh (5 s by default), not instantly.
  On a live six-max table real state changes arrive every few hundred
  milliseconds; an inference of several seconds rarely finds a quiet window.
- Strict continuity may suppress valid hands after missed frames or street changes.
  Multiway all-in and side-pot decisions remain suppressed; poker math is unchanged.
- Real image accuracy, end-to-end latency, DPI behavior, window occlusion, restart
  recovery and clean-account packaging require recorded physical evidence.
- Six-max capture support is not complete six-player strategy support. Preserve
  heads-up-only raising and multiway all-in/side-pot guards. Unknown cards,
  amounts, offered actions and history stay unavailable, not fabricated zeros.
- Laya server/dashboard support and the local fine-tuned checkpoint are absent
  from the historical release packaging. The source-free bundle is not a current
  Laya/dashboard installation; this phase makes no release/workflow changes.
- Lobby evaluation is thin: one eval-only image does not validate general lobby
  recognition or the configured lobby-size guard. Capture cursor compositing
  remains a limitation, and currency-glyph handling is untested.
- Weights remain local-only and nonredistributed. Template matching is an option
  for the user's decision, not an implemented or validated substitute for Laya.
- Root `lobby-screengrab.png` was removed in the 2026-11-10 decruft. The private
  eval-only copy and the reference PNGs/PDF are retained.

## Validation

These commands require a source checkout with Cargo and the test suite:

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-targets --all-features --locked
& .local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests
& .local/laya-runtime/env/python.exe -B scripts/validate.py --output-dir ".local/validation/$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))"
cargo run --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
pwsh -File download-model.ps1 -Verify   # before/after any model work
```

The historical source-free candidate has the binary and acceptance helper. Its
report marks source validation blocked and physical gates unrun; it does not
bundle the current Laya server or this user's fine-tuned weights. Its replay
and report commands do not validate the new dashboard:

```powershell
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
pwsh -File scripts/windows-acceptance.ps1
```

CI configuration covers Windows and platform-neutral Linux checks, but hosted CI
acceptance remains unverified. The recorded clean Linux Python suite does not
establish Linux Rust or hosted CI success. The manual `release-windows.yml`
workflow prepares a checksummed candidate archive; it does not publish a release
or establish physical acceptance.
