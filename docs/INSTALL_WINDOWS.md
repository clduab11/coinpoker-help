# Windows installation and calibration

**Development procedure:** the active scope is actual CoinPoker Practice Games
with practice chips, not cash/real-money acceptance. Laya iteration-1 Gate F
remains **FAIL**, human verification **UNVERIFIED**, and seated advice unavailable.
Version remains `0.1.0`. Historical physical and clean-account evidence is in
[WINDOWS_ACCEPTANCE_V1.md](WINDOWS_ACCEPTANCE_V1.md).

The dashboard/launcher instructions describe the approved follow-on interface
and remain subject to the coordinator's actual implementation tests. They are
not a receipt for accepted live capture or guidance.

## 1. Prerequisites

Use Windows 10 version 1903 or later, or Windows 11. The minimum is set by the
Windows Graphics Capture `CreateForWindow` API. CoinPoker's
[Windows installation guide](https://coinpoker.com/help/install-on-windows/)
describes downloading its Windows installer, opening it, and signing in. The real
executable name, installation path, lobby/table titles and display behavior must
be observed locally. Do not copy an example selector into live configuration.

Use PowerShell 7 (`pwsh`) and the existing pinned local Python/Laya runtime.
The recorded inference environment uses Python 3.12.15, Laya 0.1.7,
PyTorch `2.11.0+cu128` and torchvision `0.26.0+cu128`; see
[VLM_COMPATIBILITY.md](VLM_COMPATIBILITY.md). Normal model loading uses that
CUDA runtime, not the retired llama.cpp/Vulkan ZIP. `-DashboardOnly` is intended
to use no GPU and must not load the model. A source checkout also requires Rust
1.95.0, the MSVC C++ build tools and Windows SDK. Record actual OS, driver,
memory and runtime details; package metadata is not performance acceptance.

For a new source build, the existing setup entry point from the repository root is:

```powershell
pwsh -File scripts/setup-windows.ps1
```

The already prepared host does not need to repeat setup or completed model
work just to test the dashboard. Fresh-runtime/checkpoint provisioning and
actual launcher behavior still need the coordinator's recorded tests.

Prefer the source checkout for this phase. The historical source-free candidate
omits Rust source, Laya server/dashboard support, local weights and runtime
artifacts. Its bundled replay commands remain historical evidence; do not assume
current Laya setup works from that archive. No release/workflow change is included
in this phase.

## 2. Reuse and verify the existing Laya checkpoint

Review [runtime provenance](VLM_COMPATIBILITY.md) and
[model terms](../MODEL_LICENSES.md). The sole checkpoint is
`models/laya-vision/finetuned/20261009T190322Z-it1`, based on
`thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc`.
Download, training, calibration, scoring and pin verification already completed.
No redownload, retraining or repeat dump is needed for the existing installation.
For an offline recheck from the repository root:

```powershell
pwsh -File download-model.ps1 -Verify
```

Expected revisions, artifacts and SHA-256 hashes are in `scripts/laya-pins.json`.
Missing or corrupt model artifacts must fail verification/prediction readiness,
not trigger a Gemma fallback. `scripts/vlm-pins.json` is an orphaned historical
manifest, not an active install source. Keep weights and private data local;
The pinned Laya fork and upstream backbone are Apache-2.0; base/derived Laya weights are
CC-BY-NC-SA-4.0. They are not redistributed.

**Fresh installation:** a base-model download cannot supply this user's private
fine-tuned derivative. Provisioning that checkpoint locally and validating the
matching runtime is a separate missing setup step; do not silently substitute
the base or run training. Dashboard-only use is distinct from model readiness,
and clean-account acceptance is still unrun.

## 3. Open the read-only local dashboard

For the first-phase dashboard without model loading or GPU use:

```powershell
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

Alternatively, normal startup is intended to bind the dashboard independently
of asynchronous verification/loading of the existing pinned model:

```powershell
pwsh -File scripts/start-vlm.ps1
```

Choose one mode, not two concurrent servers. Open **`http://127.0.0.1:18090/`**.
The same loopback listener exposes `/v1/models` and `/v1/laya/predict`; the
read-only state view is `/api/state`. Predict must stay unavailable until pin
verification/loading succeeds, while the page reports loading or failure.
Neither mode starts live capture automatically. Keep the owning terminal open;
shutdown should stop only owned processes. If 18090 is occupied, report the
conflict rather than kill an unowned process or fall back to `18080`/`8080`.
There is no supported remote-VLM mode. Other local processes may reach this
unauthenticated listener; do not expose it through a proxy or tunnel.

In terminal B, from the same root:

```powershell
curl.exe --fail --silent --show-error http://127.0.0.1:18090/v1/models
$coinpoker = '.\target\release\coinpoker.exe'
python scripts/doctor.py --binary $coinpoker
```

Use the current source-checkout binary and matching Python environment for
diagnostics; an old bundled executable is not evidence about the new interface.
Confirm alias `coinpoker-laya-vision` in `/v1/models`, and distinguish model
readiness/temperature calibration from quality approval. Doctor/status checks
do not start a seated-data session or establish table accuracy. The historical
Gemma red/blue probes and stop-reason contract are not the current Laya API.
The coordinator must record actual launcher, metadata, unavailable/busy predict
and dashboard behavior before these follow-on instructions are marked tested.

## 4. Prepare a measured passive capture profile

Launch the client normally. The helper's listing reads process/window metadata,
not pixels. Keep its output local because titles may contain private details.
Use the current source-checkout build, not the historical bundled executable:

```powershell
$coinpoker = '.\target\release\coinpoker.exe'
& $coinpoker --list-windows
```

Record the exact executable basename and distinguish observed lobby and table
titles by opening and closing a Practice Games table manually. Do not guess a
title or region geometry. The native CLI's selectors include:

```powershell
$env:COINPOKER_EXE_NAME = '<exact observed exe_name>'
$env:COINPOKER_WINDOW_TITLE = '<observed table-only title fragment>'
$env:COINPOKER_LOBBY_TITLE = '<observed lobby title fragment>'
& $coinpoker --doctor
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

The follow-on optional `-LiveConfig .local/profile.json` launcher argument
explicitly supervises exactly one native passive CLI feed via its UTF-8 JSONL
stdout. It is not automatically used in the first phase. Use only the actual
profile fields/CLI bounds confirmed by the coordinator's launcher tests; this
guide does not invent a profile schema. Confirm measured six-max geometry and
source timestamps/frame progress, plus actual recording counters/private output
when recording is enabled, before a later seated-data session. A capture heartbeat
alone is not proof that images are being recorded or that `COLLECTOR_READY` holds.
The native feed currently supplies health only: `recording_enabled:false`,
`recorded_frames:0`. `-LiveConfig` accepts typed target settings, not a new
`--record-dir` option. Recorder/profile readiness and a manual go-ahead remain
the next checkpoint; retained `.local/laya/dataset/capture_loop.py` is later-session
tooling, never automatically launched by the UI or this first phase.
Capture and any new pixels stay local, with pixels under `.local/captures/`.
The user alone selects a seat and plays; the page has no capture/training or
poker-client input controls.

Native output is JSON lines; see [EVENTS_V2.md](EVENTS_V2.md). Honor clearing,
absolute expiry, stream reset/EOF and capture health. Legacy table events/raw
model answers cannot establish trusted current hero controls. The planned
private bounded per-session history under `.local/` uses opaque IDs, unknowns
and gap markers, not public names or guessed cross-session identity. Browser
polling must never renew an old lease. These are follow-on validation requirements,
not recorded successful live behavior.

## 5. Evaluate and record acceptance

```powershell
$coinpoker = '.\target\release\coinpoker.exe'
pwsh -File scripts/windows-acceptance.ps1
& $coinpoker --evaluate fixtures/synthetic/manifest.json
```

The synthetic manifest validates contracts only. The baseline Gate F receipt
remains FAIL: board threshold 1.0 gives zero confident units, and full unseated
warm p95 3027.3 ms failed the old <2000 ms target. The prospective <5000 ms warm
capture-to-display p95 and hard 5000 ms full end-to-end deadline are new tests,
not a retroactive pass or a longer freshness lease. Seated advice remains blocked
until positive real UI data and approved human-held-out calibration/evaluation.
Temperature calibration and an agent label review do not supply that approval.

For a later held-out image corpus, use ignored `.local/` fixtures and meet all
thresholds in [VISUAL_EVALUATION_V2.md](VISUAL_EVALUATION_V2.md). Complete the
twenty physical gates with evidence, including 100%, 125%, and 150% DPI scaling,
window-only pixel bounds, client restart, visual accuracy and clean-account
candidate execution where applicable. Practice and cash share one representation
and mechanism, with no practice bypass; this development phase gives no real-money
acceptance. The root PNG charts and PDF are mathematical references, not positive
seated UI examples. In a historical source-free archive, the acceptance script marks
source-validation checks blocked because Cargo source and `scripts/validate.py`
are omitted. It produces local reports but cannot observe manual facts for you.

## Historical candidate archive and current omissions

The manual `release-windows.yml` workflow stages an explicit source-free allowlist
and SHA256SUMS. On a downloaded archive, calculate the ZIP SHA-256 with
`Get-FileHash` and compare it with SHA256SUMS before extraction. Optional
Authenticode signing requires repository secrets and signs only the executable;
an unsigned candidate remains a development artifact. The workflow never
publishes a release. Record actual signing status and clean-account execution in
the acceptance report.

That packaging record does not include the current Laya server/dashboard path
or the local fine-tuned derivative. `scripts/vlm-pins.json` may remain in the
old allowlist as a historical orphan; it must not be treated as the active
manifest. Release/workflow updates are outside this phase.
