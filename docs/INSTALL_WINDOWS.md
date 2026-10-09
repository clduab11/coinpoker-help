# Windows installation and calibration

**Candidate procedure:** clean-account and live-table acceptance are recorded in
[WINDOWS_ACCEPTANCE_V1.md](WINDOWS_ACCEPTANCE_V1.md). This guide does not claim
that the model has read a real table successfully. Version remains `0.1.0`.

## 1. Prerequisites

Use Windows 10 version 1903 or later, or Windows 11. The minimum is set by the
Windows Graphics Capture `CreateForWindow` API. CoinPoker's
[Windows installation guide](https://coinpoker.com/help/install-on-windows/)
describes downloading its Windows installer, opening it, and signing in. The real
executable name, installation path, lobby/table titles and display behavior must
be observed locally. Do not copy an example selector into live configuration.

Install PowerShell 7 (`pwsh`) and Python 3.11. A source checkout also requires
Rust 1.95.0, the MSVC C++ build tools and Windows SDK. Review each installer.
The setup script requires Windows x64 and a Vulkan GPU; it downloads a pinned
server ZIP into `.local/`, checks its hash and executable version, then builds
the source unless `-SkipBuild` is used. Record the OS build, GPU/Vulkan driver
and available RAM/storage for acceptance; performance is not established by
package metadata.

Clone or open the repository, then run from its root:

```powershell
pwsh -File scripts/setup-windows.ps1
```

For a source-free candidate bundle, use the included `coinpoker.exe` and support
scripts from its root. The bundle intentionally omits Rust source, model weights
and downloaded runtime binaries. Use `pwsh -File scripts/setup-windows.ps1 -SkipBuild`
to check bundle prerequisites; the source checkout setup command above builds
from source. The model download and server commands below apply to both.

## 2. Download and verify the pinned vision runtime

Review [model and server provenance](VLM_COMPATIBILITY.md) and
[model terms](../MODEL_LICENSES.md). The required GGUF and projector are separate
multi-gigabyte files; the Windows Vulkan llama.cpp build is a third pinned asset.
Run from the repository or candidate root:

```powershell
pwsh -File download-model.ps1
pwsh -File download-model.ps1 -Verify
```

The expected repository revisions, asset names, sizes and SHA-256 hashes are in
`scripts/vlm-pins.json`. Model verification rehashes existing files; Windows setup
verifies the server ZIP and executable. Both refuse missing or corrupt assets.
Keep model and server files under the local ignored paths;
candidate archives do not redistribute them. Do not substitute a moving revision
or an unrelated projector.

## 3. Start the local server and diagnose it

In terminal A:

```powershell
pwsh -File scripts/start-vlm.ps1
```

The script verifies the assets, runs `llama-server.exe` in the foreground, binds
only `127.0.0.1:18080`, and serves alias `coinpoker-gemma-4-e2b`. Leave the
terminal open; Ctrl-C stops it. Other local processes may reach this
unauthenticated port. Do not publish it through a proxy or tunnel.

In terminal B, from the same root:

```powershell
curl.exe --fail --silent --show-error http://127.0.0.1:18080/v1/models
$coinpoker = if (Test-Path -LiteralPath .\coinpoker.exe) { '.\coinpoker.exe' } else { '.\target\release\coinpoker.exe' }
python scripts/doctor.py --binary $coinpoker
```

The binary selection uses the candidate executable when present, otherwise the
source checkout build. Doctor sends two
generated red/blue PNG requests through the same multimodal API and requires
different correct color JSON plus a stop finish reason. It neither captures nor
uploads a real table. A connection or color-probe pass does not establish table
accuracy, memory fitness or production latency. Doctor may also report missing
client calibration; do that next.

## 4. Calibrate the real Windows client

Launch the client normally. The helper's listing reads process/window metadata,
not pixels. Keep its output local because titles may contain private details.
Select the source checkout build or bundled candidate executable:

```powershell
$coinpoker = if (Test-Path -LiteralPath .\coinpoker.exe) { '.\coinpoker.exe' } else { '.\target\release\coinpoker.exe' }
& $coinpoker --list-windows
```

Record the exact executable basename and distinguish observed lobby and table
titles by opening and closing a table manually. Do not guess a title. Configure:

```powershell
$env:COINPOKER_EXE_NAME = '<exact observed exe_name>'
$env:COINPOKER_WINDOW_TITLE = '<observed table-only title fragment>'
$env:COINPOKER_LOBBY_TITLE = '<observed lobby title fragment>'
& $coinpoker --doctor
& $coinpoker
```

The table title hint is required for advice; a lobby hint vetoes a matching
table hint. When the client reuses the lobby window title and paints the table
label inside the window, pass the observed lobby size as
`--lobby-size WIDTHxHEIGHT` (`COINPOKER_LOBBY_SIZE`). That exact size stays the
lobby. One other size with the same title is the table. Equal-ranked windows
are ambiguous. Optional `--pid` and
`--window-hwnd` are hard pins: remove them for automatic recovery after a client
restart or table replacement. HWND input may be decimal or `0x` hex; JSON output
uses lowercase `0x` hex. Process metadata cannot authenticate an executable.

Before a table title is known, a bounded lobby check can record live JSON under
ignored `.local/acceptance/`. It passes only when the stream contains
`lobby_detected`, zero `decision` or `clear` events, and a settled result: the
lobby-title veto or a discarded observation. Exit 2 means the lobby was seen but
the visual result did not settle before the time limit. The check removes any
PID, HWND, and table-title environment values for that run, saves no pixels, and
leaves physical gate 8 `UNRUN`:

```powershell
pwsh -File scripts/lobby-observation.ps1 -ExeName '<exact observed exe_name>' -LobbyTitle '<observed lobby title>'
```

Add `-VlmEndpoint` when the local server is not the product default. The endpoint
must stay on loopback. One passing lobby view does not cover other lobby screens,
table previews, or real-image accuracy.

Live output is JSON lines. Consume it according to [EVENTS_V2.md](EVENTS_V2.md),
including `clear`, absolute expiry and EOF. A failed or stale capture must not
leave a prior recommendation displayed. Windows capture access failures are
reported through doctor and capture errors; no manual permission command is
required. Keep OS protections enabled while diagnosing them.

## 5. Evaluate and record acceptance

```powershell
$coinpoker = if (Test-Path -LiteralPath .\coinpoker.exe) { '.\coinpoker.exe' } else { '.\target\release\coinpoker.exe' }
pwsh -File scripts/windows-acceptance.ps1
& $coinpoker --evaluate fixtures/synthetic/manifest.json
```

The synthetic manifest validates contracts only. For an authorized held-out
image corpus, use an ignored `.local/fixtures/manifest.json` and meet all
thresholds in [VISUAL_EVALUATION_V2.md](VISUAL_EVALUATION_V2.md). Complete the
twenty physical gates with evidence, including 100%, 125%, and 150% DPI scaling,
window-only pixel bounds, client restart, visual accuracy and clean-account
candidate execution. In a source-free archive, the acceptance script marks
source-validation checks blocked because Cargo source and `scripts/validate.py`
are omitted. It produces local reports but cannot observe manual facts for you.

## Candidate archive

The manual `release-windows.yml` workflow stages an explicit source-free allowlist
and SHA256SUMS. On a downloaded archive, calculate the ZIP SHA-256 with
`Get-FileHash` and compare it with SHA256SUMS before extraction. Optional
Authenticode signing requires repository secrets and signs only the executable;
an unsigned candidate remains a development artifact. The workflow never
publishes a release. Record actual signing status and clean-account execution in
the acceptance report.
