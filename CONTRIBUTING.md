# Contributing

## Toolchain

The repository pins Rust 1.95.0 with `rustfmt` and `clippy` in
`rust-toolchain.toml`. Install Rust through rustup; entering the repository will
select the pinned toolchain automatically.

## Validation

Before submitting a change, run:

```bash
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
bash -n download-model.sh
```

Tests do not require model weights. Capture support is compiled on macOS, but
CI does not exercise runtime ScreenCaptureKit permissions, window discovery, or
live capture. Verify those behaviors manually on a supported Apple Silicon Mac
when changing capture code.

## Change guidelines

- Keep `Cargo.lock` committed and use `--locked` in reproducible checks.
- Do not commit model weights or local `.env` files.
- Keep model repository IDs and revisions synchronized across
  `download-model.sh`, `README.md`, and `MODEL_LICENSES.md`.
- Add tests for behavior changes and update user-facing documentation when CLI
  behavior changes.
- Avoid including screenshots, credentials, or real table data in issues,
  fixtures, or logs.
