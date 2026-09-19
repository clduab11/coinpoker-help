# Contributing

Thanks for contributing. This guide explains the tools and standards used in
this repository. If anything is unclear, ask in an issue before starting.

## Setting up

The repository pins Rust 1.95.0 with `rustfmt`, `clippy`, and
`llvm-tools-preview` in `rust-toolchain.toml`. Install Rust through
[rustup](https://rustup.rs); the first time you enter the repository the pinned
toolchain is selected automatically.

Three optional tools make local development faster and match what CI runs:

- **[just](https://github.com/casey/just)** — a command runner. Running `just`
  on its own lists every recipe. Install with `brew install just` (macOS) or
  `cargo install just`.
- **cargo-llvm-cov** — measures test coverage. Install with
  `cargo install cargo-llvm-cov`.
- **cargo-audit** — checks dependencies for known security vulnerabilities.
  Install with `cargo install cargo-audit`.

You can also skip `just` entirely and run the individual `cargo` commands listed
below by hand.

## Validating a change

Run the same checks CI runs before submitting a pull request. The quickest way
is a single command via `just`, which stops at the first failure:

```bash
just validate
```

The individual checks are:

```bash
cargo fmt --all -- --check                                     # formatting
cargo check --workspace --all-targets --all-features --locked  # does it compile?
cargo test --workspace --all-targets --all-features --locked   # unit + integration tests
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings  # lints; warnings fail
cargo test --doc --workspace --all-features --locked           # code examples in docs
bash -n download-model.sh                                      # shell syntax
```

### Coverage (enforced)

CI fails a pull request when line coverage on default features falls below
**80%**. Check it locally:

```bash
cargo llvm-cov --workspace --all-targets --locked
```

Coverage is measured on default features only, because the optional `desktop`
UI panel is not wired up and has no tests. That feature is still compiled and
linted through the `--all-features` steps above.

### Dependency audit (enforced)

CI checks dependencies against the RustSec advisory database. Run it locally:

```bash
cargo audit --locked
```

If an advisory appears, update the affected crate. If no fixed version exists
yet, open an issue rather than silencing the check.

### Shell scripts (enforced)

`download-model.sh` is checked with `bash -n` (syntax) everywhere and with
`shellcheck` when it is installed. If you change that script, run both locally:

```bash
bash -n download-model.sh
shellcheck download-model.sh   # install with `brew install shellcheck`
```

## Tests we write

Tests do not require model weights, and CI never exercises live screen capture,
window discovery, or VLM calls. Verify those behaviors manually on a supported
Apple Silicon Mac when you change capture code.

### Property tests (`proptest`)

A property test states a rule that must hold for a function, then checks that
rule against many randomly generated inputs. This finds edge cases hand-written
examples miss.

- Put them in a `#[cfg(test)] mod proptests` module next to the code under test.
- Use `proptest` strategies for pure, deterministic functions.
- Do not property-test Monte Carlo code (for example `equity`), because random
  sampling makes results nondeterministic. Keep seeded unit tests for those.

### Snapshot tests (`insta`)

A snapshot test saves the exact output a function produces and compares future
runs against that saved file, so accidental changes to output are obvious.

- Put them in a `#[cfg(test)] mod snapshot_tests` module.
- Use `insta::assert_json_snapshot!`.
- Commit the generated `.snap` files alongside the source.
- Review changes with `cargo insta test --review` to accept or reject them.

### Integration test fixtures

End-to-end tests for the `coinpoker` binary live in `bin/tests/` and read
shared JSON `GameState` inputs from `bin/tests/fixtures/`. Load them with
`include_str!` instead of copying JSON into test code. If a test needs a new
input shape, add it as a fixture file rather than inlining a string.

## Change guidelines

- Keep `Cargo.lock` committed and use `--locked` in reproducible checks.
- Do not commit model weights, `.env` files, or anything under `models/`.
- Keep model repository IDs and revisions synchronized across
  `download-model.sh`, `README.md`, and `MODEL_LICENSES.md`.
- Add tests for behavior changes and update user-facing documentation when CLI
  behavior changes.
- Keep coverage at or above 80%; if a change reduces it, add tests for the new
  or changed code.
- Avoid including screenshots, credentials, or real table data in issues,
  fixtures, or logs.
