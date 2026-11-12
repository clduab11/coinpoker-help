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

# PowerShell syntax check for the operator scripts (Windows host).
syntax:
	pwsh -NoProfile -Command "$paths = @(Get-ChildItem scripts -Filter '*.ps1' -File | ForEach-Object FullName); foreach ($path in $paths) { $tokens = $null; $errors = $null; [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count -gt 0) { throw \"PowerShell syntax errors in $path\" } }"

# Coverage (excludes the opt-in private-capture replays)
coverage:
	cargo llvm-cov --workspace --all-targets --locked

# Aggregate validation
validate: fmt check test clippy syntax