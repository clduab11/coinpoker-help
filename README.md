# coinpoker-help

Experimental, human-controlled poker observation and decision-support development.
The active follow-on targets actual CoinPoker **Practice Games with practice
chips**, not real-money deployment or acceptance. Native capture targets Windows
10 version 1903 or later. Structured JSON replay and poker libraries also run on Linux.
The helper never sends mouse or keyboard input, reads client memory, or intercepts
client network traffic.

**Status:** engineering candidate, version `0.1.0`; Laya iteration-1 Gate F
**FAIL**, human verification **UNVERIFIED**, no seated advice. A build,
synthetic evaluation or loaded model is not real-table acceptance. Physical
Windows, model, real-image and clean-account evidence is recorded in
[the Windows report](docs/WINDOWS_ACCEPTANCE_V1.md); unrun gates stay `UNRUN`.
Practice and cash use this same repo, representation and validation mechanism,
without a practice-only bypass. This plan provides no real-money acceptance.

## Start here

- [Windows setup and read-only dashboard](docs/INSTALL_WINDOWS.md)
- [VLM compatibility and provenance](docs/VLM_COMPATIBILITY.md)
- [Live JSON-lines contract](docs/EVENTS_V2.md)
- [Visual evaluation contract](docs/VISUAL_EVALUATION_V2.md)
- [Model terms](MODEL_LICENSES.md), [security](SECURITY.md), [contributing](CONTRIBUTING.md)

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

The browser has exactly two views, **Monitor** and **Reference**. Monitor puts a
separate **Suggested action** box first, with table readings, odds and recent
betting activity below it. Suggestions are currently **OFF**. Reference is a
searchable, collapsible, locally bundled study guide with cited education sources;
it makes no runtime network requests and does not copy the root charts.

Open `http://127.0.0.1:18090/` beside the practice table. There are no connect,
seating, betting or process controls in the page. For development startup, choose
one mode below, not two concurrent servers; inspect the existing 18090 listener
before starting anything. Reuse an already running service.

```powershell
# Read-only dashboard without loading a model or using the GPU.
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

```powershell
# Normal startup: dashboard plus asynchronous verified loading of the pinned model.
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

**Checkpoint A is UI/contract work, not live recognition acceptance.** The retained
server is intentionally capture-idle. The next explicitly approved checkpoint
integrates the bounded private recorder and automatic practice-table attachment,
after one-time executable/title calibration using local `--list-windows` output.
The planned automatic attachment supersedes an operator-launched CLI profile as
the normal Monitor workflow; it is not yet active in checkpoint A. Existing
`-LiveConfig` remains internal feed tooling, not a browser connect step.

Currently the native feed reports capture health, **not image recording**:
`recording_enabled:false`, `recorded_frames:0`. Page/model readiness is not
`COLLECTOR_READY`. No real observing/seated session or end-to-end latency acceptance
has occurred in checkpoint A. Seated controls/hero amounts and calculated metrics
require the later genuine-data/quality checkpoints; a null metric is not zero.
Private session history uses opaque IDs, not player names or cross-session guesses.

Checkpoint A validation: 402 Rust tests passed (one ignored), 79 Python tests
passed, and 47 desktop/400px browser checks passed with no JavaScript errors or
mutation/external requests. Doctor has ten passes and discovery blocked (exit 1).
These tests use synthetic role observations, not real seated recognition or
capture-to-Monitor latency acceptance. Receipts remain private under `.local/`.

The baseline receipt stays failed: board threshold `1.0` gave **0/330 confident
board units** on the 66 agent-reviewed frames, despite raw accuracy
`307/330 = 93.03%`. Warm full-battery p95 was **3027.3 ms**, failing the original
`<2000 ms` Gate F target. The prospective `<5000 ms` warm capture-to-display p95
and hard 5000 ms full end-to-end deadline do not retroactively pass that run;
the old benchmark was not seated or capture-to-browser timing. Temperature
calibration is not capability approval; source/vendor `calibrated:false` remains.
Positive real UI data and approved human-held-out calibration/evaluation are
required before seated advice.

`screenshot-1.png`, `screenshot-2.png` and `poker-info-sheet.pdf` are odds,
six-handed raise-first-in and rules references, respectively. They remain
historical deterministic calculation material, not the source of the new
researched Reference or positive hero-button/seated-card UI examples.
Reference displays are not live recommendations.

## Architecture

```text
Windows process and window metadata (exe name, PID, HWND)
  -> calibrated table/lobby title selection, explicit ambiguity
  -> Windows Graphics Capture for the selected window, RGBA frame
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
lease clears active advice. A configured
table-only title is required before a visual recommendation can be emitted. Repeated
model agreement is not independent proof of correct recognition; the held-out
real-image gate remains necessary.

The workspace crates are `ingest` (capture and vision), `core-engine` (poker math),
`ghost-layer` (unwired timing primitives), `opponent-model`, `ui` (unwired native
desktop panel), and `bin` (CLI, replay, diagnostics and evaluation). The follow-on
browser is a read-only local dashboard, not an input execution layer. Observed
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

This is not the dashboard-only first-phase startup. All seating and play remain
manual, and capture does not enable advice. The old candidate binary invocation is:

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

Explicit native capture requests the selected window through Windows Graphics
Capture. The pixel boundary still needs physical evidence. Laya receives local
PNG region requests; browser snapshots/history must not expose captures, raw
model replies, backend bodies or player names. The service binds loopback only;
there is no supported remote opt-in. Keep new capture pixels under
`.local/captures/` and diagnostics private. Local logs, swap and crash dumps need
separate review; private answer logs are diagnostics, never advice inputs.

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
- Root `lobby-screengrab.png` remains for the user to delete. The private eval-only
  copy and the reference PNGs/PDF are retained; the helper does not delete them.

## Validation

These commands require a source checkout with Cargo and the test suite:

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
python -m unittest discover -s scripts/tests -v
cargo run --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
python scripts/validate.py
```

The historical source-free candidate has the binary and acceptance helper. Its
report marks source validation blocked and physical gates unrun; it does not
bundle the current Laya server or this user's fine-tuned weights. Its replay
and report commands do not validate the new dashboard:

```powershell
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
pwsh -File scripts/windows-acceptance.ps1
```

CI covers Windows and platform-neutral Linux checks. The manual
`release-windows.yml` workflow prepares a checksummed candidate archive; it does
not publish a release or establish physical acceptance.
