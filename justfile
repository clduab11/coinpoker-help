# Task runner for coinpoker-help.
# Wraps the canonical commands from README.md and CONTRIBUTING.md.
# Run `just` to list available recipes.

# Default shell is bash for portability
set shell := ["bash", "-cu"]

# Core validation recipes (mirror README/CONTRIBUTING)
fmt:
	cargo fmt --all -- --check

check:
	cargo check --workspace --all-targets --all-features --locked

test:
	cargo test --workspace --all-targets --all-features --locked

clippy:
	cargo clippy --workspace --all-targets --all-features --locked -- -D warnings

shellcheck:
	bash -n download-model.sh

# Coverage (default features only; desktop feature has no tests)
coverage:
	cargo llvm-cov --workspace --all-targets --locked

# Aggregate validation
validate: fmt check test clippy shellcheck