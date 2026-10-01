# Contributing

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
  `download-model.ps1`, `scripts/start-vlm.ps1`, `scripts/doctor.py`,
  [model provenance](MODEL_LICENSES.md) and
  [compatibility evidence](docs/VLM_COMPATIBILITY.md).
- Keep private images, local evaluation labels, logs and calibrated client titles
  in ignored `.local/`. Do not commit model weights or `.env` files.
- Preserve one-worker scheduling, fresh observation generations and epochs,
  exactly-once clearing, and leased JSON output. Add focused regression coverage
  for behavior changes and keep the protocol docs in sync.
- Require a calibrated executable name and table-only title for live advice.
  Preserve the lobby veto and explicit multi-window ambiguity.
- Do not connect input automation, process-memory inspection or client network
  interception. Keep the optional UI unwired unless separately scoped.

The candidate workflow can package and optionally sign an archive. A build or CI
pass does not change the physical acceptance status or version `0.1.0`.
