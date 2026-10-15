# Contributing

## Active development scope

The current work is actual CoinPoker Practice Games development with practice
chips in this repo, not real-money acceptance. Practice and cash share one
representation and validation mechanism; do not create a practice-only model,
repo or bypass. The canonical read-only browser is `http://127.0.0.1:18090/`,
with `/v1/models` (alias `coinpoker-laya-vision`) and `/v1/laya/predict` on the
same loopback service. Retired product ports, Gemma fallback and remote VLM
opt-in are not supported.

Reuse `models/laya-vision/finetuned/20261009T190322Z-it1` and
`scripts/laya-pins.json`; download/training/calibration/scoring already completed.
No redownload or retraining is needed for the dashboard/history phase. The
baseline Gate F remains **FAIL**, human verification **UNVERIFIED** and
source/vendor `calibrated:false`. Its full-battery p95 `3027.3 ms` failed the
old `<2000 ms` target; the prospective `<5000 ms` full end-to-end requirement
does not turn that receipt into a pass. No confident board units at threshold
1.0 remains a failure, not a reason to clamp the threshold.

Browser, launcher and feed/ledger changes need their own actual tests. Model
health or replay success is not `COLLECTOR_READY`: measured target/timestamps,
frame progress and actual recorder/output counters must be tested. Neither
collector readiness nor temperature calibration supplies seated advice approval;
positive real UI data and approved human-held-out calibration/evaluation are
still required. The root charts/PDF are reference facts, not positive UI pixels.
Current native feed health has `recording_enabled:false`, `recorded_frames:0`;
do not treat capture-frame counters as image recording. Typed `-LiveConfig`
target settings do not add a `--record-dir` option; recorder readiness stays
at the later manual-data checkpoint.

## Toolchain and checks

The workspace pins Rust 1.95.0 in `rust-toolchain.toml`. Windows live capture also
needs the MSVC build tools and Windows SDK. Linux remains useful for structured
stdin replay and platform-neutral library checks.

These checks require a source checkout with Cargo, `scripts/validate.py` and the
test suite. Run from PowerShell before submitting a source change:

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
python -m unittest discover -s scripts/tests -v
cargo run --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
python scripts/validate.py
```

`scripts/validate.py` records individual outcomes under ignored `.local/`.
Synthetic fixtures verify contracts, not real visual recognition. Capture changes
also require the physical checks in [Windows acceptance](docs/WINDOWS_ACCEPTANCE_V1.md).
Keep gates `UNRUN` until a real observation and evidence exist.

## Change rules

- Keep `Cargo.lock` committed and use `--locked` for reproducible checks.
- Keep model and server artifact identifiers, revisions and hashes consistent in
  `scripts/laya-pins.json`, `download-model.ps1`, `scripts/start-vlm.ps1`, `scripts/doctor.py`,
  [model provenance](MODEL_LICENSES.md) and
  [compatibility evidence](docs/VLM_COMPATIBILITY.md).
- Keep private images, local evaluation labels, logs and calibrated client titles
  in ignored `.local/`; new capture pixels belong under `.local/captures/`.
  Do not commit/redistribute model weights or commit `.env` files. Source/Laya
  code MIT and upstream backbone Apache-2.0 do not override CC-BY-NC-SA-4.0
  base/derivative weight constraints.
- Keep bounded private per-session history under `.local/` with opaque
  table/seat-occupant IDs, unknowns and explicit gaps; never public player names
  or cross-session identity guesses. Raw model answers and legacy table events
  are not trusted history/current-action inputs. Missing amounts are not zero.
- Preserve one-worker scheduling, fresh observation generations and epochs,
  exactly-once clearing, and leased JSON output. Add focused regression coverage
  for behavior changes and keep the protocol docs in sync. Browser polling must
  not renew old leases; invalidation must work even without active advice.
- Require a calibrated executable name and table-only title for live advice.
  Preserve the lobby veto and explicit multi-window ambiguity.
- Implement capabilities within the user's requested bug-bounty proof-of-concept
  scope. There is no repository-wide read-only restriction. Distinguish missing
  functionality from authorization restrictions; the native desktop panel remains unwired.
- `scripts/start-vlm.ps1 -DashboardOnly` is planned to load no model/use no GPU;
  default startup loads the pinned model asynchronously. Optional
  `-LiveConfig .local/profile.json` explicitly supervises one native passive
  feed, never automatic capture in this first phase. Confirm actual flag/profile
  behavior in coordinator tests before calling the instructions tested.
- Keep the historical Gate F scores/receipts and dated Gemma/port evidence.
  `scripts/vlm-pins.json` is an orphaned historical manifest, not an active pin
  source. Laya server/dashboard support and the user's local fine-tuned weights
  are omitted from historical packaging; this phase does not edit releases or
  workflows to hide that gap.

The candidate workflow can package and optionally sign an archive. A build or CI
pass does not change the physical acceptance status or version `0.1.0`.
