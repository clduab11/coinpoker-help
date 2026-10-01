# Windows validation evidence

This document separates automated checks, host-specific calibration and physical
acceptance for the Windows-only candidate. Version remains `0.1.0`. The results
below are from the dirty working tree on 2026-09-23 UTC, not a CI run or release.

## Current automated run

`python scripts/validate.py` exited 0 on the final tree. Its machine-readable
report and individual logs are under ignored `.local/validation/`.

| Check | Result | Evidence |
| --- | --- | --- |
| Rust format, locked check/test/Clippy | PASS | `cargo fmt --all -- --check`; locked workspace check, test and Clippy; 237 Rust tests passed, one live HWND smoke test ignored by default. See `.local/validation/report.json` and `test.log`. |
| Python diagnostic tests | PASS | 14 tests in `.local/validation/python-tests.log`. |
| PowerShell syntax parse | PASS | Root download script and three `scripts/*.ps1` parsed in `.local/validation/`. |
| Workflow YAML parse and documentation links | PASS | `.local/validation/workflow-yaml.log`; active relative links checked against the final tree. Windows CI itself has not run. |
| Synthetic format-2 evaluation | PASS | 26 synthetic cases, zero critical actionable false positives and zero request errors in `.local/validation/synthetic-evaluation.log`. This is contract coverage, not vision accuracy. |
| Pinned model and server hashes | PASS | `pwsh -File download-model.ps1` verified the GGUF and projector; `pwsh -File scripts/setup-windows.ps1` verified the server asset/build and built `target/release/coinpoker.exe`. |
| Generated multimodal doctor probes | PASS with blocked table discovery | Running pinned server at `127.0.0.1:8080` returned the exact alias and correct red/blue generated-image JSON. `.local/validation/doctor-online.json` records API passes; the overall doctor exits 1 because no table title/window is calibrated. |
| Source-free candidate packaging dry-run | PASS | The exact stage/archive workflow blocks packaged the final rebuilt executable into `.local/candidate-clean-f5xnlrpq/dist/coinpoker-help-windows-x64-candidate.zip`. The ZIP has 18 allowlisted files plus `CANDIDATE.txt`, 22 valid bundled links, no model/private assets, and SHA-256 `7d2498f03fabb96f1e39ac5b05558ab5b8224933f89547390c01cdce69249e16` matching `SHA256SUMS`. Bundled synthetic evaluation passed all 26 cases. No signing or publication ran. |
| Held-out real-image metrics | UNRUN | Requires authorized local corpus |
| Physical twenty-gate Windows report | UNRUN | [Acceptance report](WINDOWS_ACCEPTANCE_V1.md) |

The Windows 11 build 26200 host has an NVIDIA RTX 4060 Ti (8 GiB) and a
CoinPoker 1.26.0.6518 installation. A running main window was observed with
executable `CoinPoker.exe` and title `CoinPoker`; PID, HWND and path are retained
only in ignored `.local/windows-client-calibration.json`. A gated smoke test
captured five consecutive 1280×778 frames in memory with packed RGBA8 pixels,
including a static-window refresh; no screenshot was logged or saved. This
observation does not establish table-title conventions,
table readability, adjacent-pixel exclusion, DPI behavior or client restart
behavior. No executable or title is hardcoded as a product default.

The first generated VLM image request took 48.02 seconds after server startup;
the next took 2.09 seconds. The live request timeout remains 30 seconds and
discards a late result. Real table-sized latency and p95 remain unmeasured.

`pwsh -File scripts/windows-acceptance.ps1` wrote
`.local/acceptance/20260923T051330Z/acceptance-v1.json`. Source validation,
release build and synthetic evaluation passed. Its offline doctor failed only
because `table_metadata` is blocked while the lobby is the sole observed client
window. The script correctly exits 1 and leaves all twenty physical gates UNRUN.
No clean-account candidate run, real-image corpus, Windows CI run or signing
evidence exists, so the release decision is **NO-GO**.

## Boundaries retained from the previous implementation

- Stdin replay and poker equity/EV rules remain independent of visual capture.
- A table-only title, readable frame, strict screen envelope, two matching fresh
  observations and temporal continuity gate any visual recommendation.
- One inference worker and one replaceable latest frame prevent an old completion
  from reviving stale advice. Changed frames, capture loss and lease expiry clear
  active output; consumers still enforce expiry and EOF.
- The VLM client sends PNG data URLs through the bounded OpenAI-compatible HTTP
  contract without logging images, model replies or server error bodies.
- Synthetic gradients and generated color probes cannot establish real table
  accuracy. The complete held-out corpus thresholds remain release gates.
- The candidate archive contains source-free support files but no model weights,
  private fixtures or signing credentials. Signing and physical execution need
  their own evidence.

Keep `UNRUN` where physical or corpus evidence is absent. The ignored local
reports carry exact commands, exit codes and sanitized details; do not use a
subjective readiness percentage as a substitute for the twenty gates.
