# Windows acceptance report, format 1

**Status: NO-GO until every applicable gate below has recorded evidence.** A
synthetic evaluation, successful Rust build or generated color probe cannot close
real-image, client-lifecycle or pixel-boundary gates. Use `PASS`, `FAIL`, `BLOCKED`
or `UNRUN` with UTC time, sanitized local evidence path and reproduction for a
failure. Keep raw images and private window listings under ignored `.local/`.

## Environment and provenance

- Automated host observations: 2026-09-23 UTC; physical gate reviewer UNRECORDED
- Candidate commit and dirty-diff hash: UNRECORDED (working tree remains dirty)
- Windows version/build and architecture: Windows 11 build 26200, x64; display
  topology UNRECORDED
- CPU UNRECORDED; GPU NVIDIA RTX 4060 Ti, driver 591.86, 8 GiB VRAM; host RAM
  47.8 GiB and free disk approximately 508 GiB at validation time
- Client version 1.26.0.6518 observed from the installed executable; install
  source UNRECORDED
- Observed executable `CoinPoker.exe`, main/lobby title `CoinPoker`; table title
  UNRECORDED
- Observed main-window rectangle and five captured frames: 1280×778 pixels;
  logical bounds and DPI scale UNRECORDED
- Rust toolchain/target: 1.95.0 / x86_64-pc-windows-msvc, locally verified
- GGUF, projector and llama-server hashes verified locally; see
  [VLM_COMPATIBILITY.md](VLM_COMPATIBILITY.md)
- Server endpoint `127.0.0.1:8080`, alias `coinpoker-gemma-4-e2b`; generated
  color-probe cold/warm latency 48.02/2.09 seconds; table-sized latency and peak
  RAM/VRAM UNRECORDED
- Held-out corpus revision/hash, authorization and independent label reviewer: UNRECORDED
- Local source-free candidate packaging dry-run completed; verify the archive
  digest against the adjacent `SHA256SUMS`. Clean-account operation and
  Authenticode status UNRECORDED
- Final recommendation: **NO-GO**

## Gates

| # | Evidence to collect | Status | Local evidence / limitation |
| --- | --- | --- | --- |
| 1 | Fresh clone or candidate archive on a clean Windows account using only `INSTALL_WINDOWS.md`; record installed prerequisites, Defender/firewall prompts and undocumented steps. | UNRUN | |
| 2 | Pinned GGUF, separate projector and server ZIP download/hash verification; corrupt/missing artifact refuses startup. | UNRUN | |
| 3 | Pinned `llama-server` starts on loopback; `/v1/models` matches alias; both generated color probes pass with stop reason. Record cold/warm table-sized request latency and memory. | UNRUN | |
| 4 | Unavailable/denied Windows capture reports an actionable reason and never leaves advice visible; no OS protection is disabled. | UNRUN | |
| 5 | Real client metadata and selected-window native pixels match executable, PID, HWND, title and dimensions. No adjacent desktop or other-window pixels enter the image. | UNRUN | |
| 6 | Helper starts before the client, waits with bounded polling and no repeated error flood. | UNRUN | |
| 7 | Start the client normally; helper discovers the calibrated executable without restart. Inspect updater behavior and locate `update.log` only through actual installation evidence. | UNRUN | |
| 8 | All tested lobby views and table previews remain lobbies or non-actionable screens, with zero recommendations. | UNRUN | |
| 9 | Open a real table; helper rebuilds selection, applies table-only title hint and two fresh matching observations without restart. | UNRUN | |
| 10 | Close active table; advice clears exactly once within bounded discovery/capture time and never exceeds lease. | UNRUN | |
| 11 | Reopen or replace a table; fresh HWND/consensus prevents reuse of the previous hand or frame. | UNRUN | |
| 12 | Quit/relaunch the client; helper recovers across a new PID without restart when no PID/HWND pin is set. | UNRUN | |
| 13 | Two equally ranked table windows cause ambiguity and one clear; no enumeration-order choice; recovery after one closes. | UNRUN | |
| 14 | Minimized, obscured, animated, unreadable or inconsistent table emits no recommendation; recover after readability returns. | UNRUN | |
| 15 | Slow real inference while cards, actions or window identity change discards obsolete work and never overwrites newer state. | UNRUN | |
| 16 | Small card/action/amount changes clear prior advice before inference completes; capture/process loss and consumer EOF/expiry clear display. | UNRUN | |
| 17 | At 100%, 125% and 150% DPI, record window logical bounds and native pixels; test resize, move, multiple displays, aspect/crop and adjacent-window pixel exclusion. | UNRUN | |
| 18 | Held-out authorized real corpus meets every threshold in `VISUAL_EVALUATION_V2.md`; independently review all actionable states and coverage. | UNRUN | |
| 19 | Download checksummed candidate ZIP into clean account; verify support-file allowlist, execution, actual Authenticode status if requested, and complete local model setup. | UNRUN | |
| 20 | Required Rust, Python, PowerShell syntax, synthetic evaluation and Windows CI checks pass at the exact candidate revision; inspect CI run links. | UNRUN | |

## Smoke order

1. Record a genuinely clean account and prerequisites. Follow the install guide
   literally; record and fix undocumented interventions before repeating.
2. Verify all model/server assets and test corruption refusal. Keep the VLM on
   loopback. Generated color probes establish only image-dependent API behavior.
3. Calibrate executable and titles from the real client. Run listing before and
   after opening a table. Avoid sharing personal window titles.
4. Check capture error paths and actual selected-window pixels with a visible
   unrelated adjacent window. Window-only capture must be demonstrated.
5. Exercise lobby/table lifecycle, ambiguity, restart, slow inference, lease and
   consumer clear behavior. Use 100%, 125% and 150% DPI.
6. Run `pwsh -File scripts/windows-acceptance.ps1`, inspect its local report, then
   run the held-out real-image corpus. Script exit zero alone does not certify
   physical gates.
7. Verify and execute the candidate archive on a separate clean account. Record
   actual signing status and Windows prompts. Candidate packaging does not publish
   a release.

Only physical evidence can close gates 1–19. CI cannot establish window pixel
bounds, client behavior, real image quality or clean-account operation. The
manual `release-windows.yml` workflow stages an explicit allowlist and SHA256SUMS;
optional Authenticode requires signing secrets. It neither bumps `0.1.0` nor
publishes a release.
