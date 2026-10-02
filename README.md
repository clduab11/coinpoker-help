# coinpoker-help

Experimental, human-controlled poker decision support. Live capture targets Windows 10
version 1903 or later. Structured JSON replay and poker libraries also run on Linux.
The helper never sends mouse or keyboard input, reads client memory, or intercepts
client network traffic.

**Status:** engineering candidate, version `0.1.0`. A successful build or synthetic
evaluation is not evidence that real table recognition works. Physical Windows,
model, real-image, and clean-account acceptance are recorded in
[the Windows report](docs/WINDOWS_ACCEPTANCE_V1.md); unrun gates stay `UNRUN`.

## Start here

- [Install and calibrate on Windows](docs/INSTALL_WINDOWS.md)
- [VLM compatibility and provenance](docs/VLM_COMPATIBILITY.md)
- [Live JSON-lines contract](docs/EVENTS_V2.md)
- [Visual evaluation contract](docs/VISUAL_EVALUATION_V2.md)
- [Model terms](MODEL_LICENSES.md), [security](SECURITY.md), [contributing](CONTRIBUTING.md)

## Architecture

```text
Windows process and window metadata (exe name, PID, HWND)
  -> calibrated table/lobby title selection, explicit ambiguity
  -> Windows Graphics Capture for the selected window, RGBA frame
  -> cumulative and local pixel change checks, stability gate
  -> one inference worker and one replaceable latest frame
  -> generation, epoch, window identity and capture-age checks
  -> strict screen classification and complete poker-state validation
  -> two matching fresh observations and hand transition guards
  -> Monte Carlo equity and legal decision pipeline
  -> JSON-lines status, leased decision, clear, or discarded event
```

Capture continues during a blocking local VLM request. A changed or lost window,
ambiguous selection, stale frame, or expired lease clears active advice. A configured
table-only title is required before a visual recommendation can be emitted. Repeated
model agreement is not independent proof of correct recognition; the held-out
real-image gate remains necessary.

The workspace crates are `ingest` (capture and vision), `core-engine` (poker math),
`ghost-layer` (unwired timing primitives), `opponent-model`, `ui` (unwired desktop
panel), and `bin` (CLI, replay, diagnostics and evaluation). No client input
execution layer is connected.

## CLI

From a source checkout, run these in PowerShell after following the install guide:

```powershell
cargo run --release --locked --bin coinpoker -- --help
cargo run --release --locked --bin coinpoker -- --stdin
cargo run --release --locked --bin coinpoker -- --list-windows
cargo run --release --locked --bin coinpoker -- --doctor
cargo run --release --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
```

From the source-free candidate archive, use its bundled executable:

```powershell
& .\coinpoker.exe --help
& .\coinpoker.exe --stdin
& .\coinpoker.exe --list-windows
& .\coinpoker.exe --doctor
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
```

The real client executable and title conventions must come from `--list-windows` on
the actual installed client. The listing reads public metadata and may contain
personal window titles. It captures no pixels. To start live mode after calibration:

```powershell
$env:COINPOKER_EXE_NAME = '<observed executable name>'
$env:COINPOKER_WINDOW_TITLE = '<observed table-only title fragment>'
$env:COINPOKER_LOBBY_TITLE = '<observed lobby title fragment>'
cargo run --release --locked --bin coinpoker
```

In a candidate archive, replace the last command with:

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
| `--vlm-endpoint` | `COINPOKER_VLM_ENDPOINT` | Local default: `http://127.0.0.1:8080/v1/chat/completions` |
| `--vlm-model` | `COINPOKER_VLM_MODEL` | Default model alias: `coinpoker-gemma-4-e2b` |
| `--allow-remote-vlm` | `COINPOKER_ALLOW_REMOTE_VLM=1` or `true` | Off by default; capture mode only and HTTPS required |
| `--retry-ms` | `COINPOKER_RETRY_MS` | Default 2000 ms; bounded recovery delay |

Equal-ranked windows produce an ambiguity state. A PID or HWND pin is a deliberate
restriction and will wait if its target disappears. Title strings and public process
metadata are user calibration, not cryptographic proof that a window is a table.

## Privacy and model provenance

Live mode requests the selected window through Windows Graphics Capture. The
pixel boundary must be proven on a real desktop in acceptance. Captured pixels
are encoded as a PNG data URL and sent to the configured VLM. The default server
binds loopback. Remote capture
requires explicit opt-in and HTTPS and sends the full window image to that host.
The client refuses redirects and URLs with embedded credentials or query strings;
doctor and evaluation refuse remote endpoints entirely. It does not log screenshots,
data URLs, raw model replies, or server error bodies. Local server logs, swap, and
crash dumps need separate review.

`download-model.ps1` verifies the pinned GGUF and vision projector; Windows setup
verifies the server ZIP and executable before use. Their pins and the
[compatibility record](docs/VLM_COMPATIBILITY.md) record artifact IDs and hashes.
MIT covers repository source, not model
weights. Candidate archives contain no weights or private images.

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
- The 5-second default advice lease can expire before a slow inference finishes.
  Consumers must honor clear, absolute expiry and EOF even when capture blocks.
- Strict continuity may suppress valid hands after missed frames or street changes.
  Multiway all-in and side-pot decisions remain suppressed; poker math is unchanged.
- Real image accuracy, end-to-end latency, DPI behavior, window occlusion, restart
  recovery and clean-account packaging require recorded physical evidence.

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

The source-free candidate has the binary and acceptance helper. Its acceptance
report marks source validation blocked and leaves physical gates unrun. Install
the pinned server and model using the Windows guide first; otherwise its offline
doctor check fails on the absent assets:

```powershell
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
pwsh -File scripts/windows-acceptance.ps1
```

CI covers Windows and platform-neutral Linux checks. The manual
`release-windows.yml` workflow prepares a checksummed candidate archive; it does
not publish a release or establish physical acceptance.
