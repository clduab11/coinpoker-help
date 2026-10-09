# Windows acceptance report, format 1

**Status: NO-GO until every applicable gate below has recorded evidence.** A
synthetic evaluation, successful Rust build or generated color probe cannot close
real-image, client-lifecycle or pixel-boundary gates. Use `PASS`, `FAIL`, `BLOCKED`
or `UNRUN` with UTC time, sanitized local evidence path and reproduction for a
failure. Keep raw images and private window listings under ignored `.local/`.

## Environment and provenance

- Automated host observations: 2026-09-23 and 2026-10-08/09 UTC; physical gate
  reviewer UNRECORDED
- Candidate commit: **81f59986531204b338780333839757bb6b930e3f** (f97ca44 plus
  c5a145a: gate-20 clippy fix, thinking disabled, 8000 ms lease, loopback endpoint
  18080; and 81f5998: reference-sheet table rules, opening ranges, outs). Later
  commits that touch only this report do not change the candidate code
- Windows version/build and architecture: Windows 11 build 26200, x64; display
  topology UNRECORDED
- CPU UNRECORDED; GPU NVIDIA RTX 4060 Ti, driver 591.86, 8 GiB VRAM; host RAM
  47.8 GiB and free disk approximately 508 GiB at validation time
- Client under test: 1.27.0.6876, accepted 2026-10-01 from the installed
  executable. Historical client 1.26.0.6518 remains the 2026-09-23 record.
  Install source UNRECORDED
- Observed executable `CoinPoker.exe`, lobby title `CoinPoker` on both
  versions. 2026-10-08: the table window carries the same exact title
  `CoinPoker`; discovery selects it by size (`COINPOKER_LOBBY_SIZE` 1280×778,
  table 800×613). Re-list after any lobby resize
- Historical 1.26 lobby capture: 1280×778 pixels, five frames, DPI UNRECORDED.
  2026-10-01 lobby metadata only: 1280×1032. No new pixels were saved
- Rust toolchain/target: 1.95.0 / x86_64-pc-windows-msvc, locally verified
- GGUF, projector and llama-server hashes verified locally; see
  [VLM_COMPATIBILITY.md](VLM_COMPATIBILITY.md)
- Server endpoint `127.0.0.1:18080` (standard since 2026-10-09; earlier records
  used 8080), alias `coinpoker-gemma-4-e2b`; generated color-probe cold/warm
  latency 48.02/2.09 seconds. Real 800×613 table frame: 11.0–20.9 s with model
  thinking (5/5 runs), 5.8–6.3 s warm with thinking disabled (2 runs); cold
  table-sized latency without thinking UNRECORDED. llama-server working set
  1748 MiB, peak 3731 MiB; GPU about +455 MiB (partial offload)
- Held-out corpus revision/hash, authorization and independent label reviewer: UNRECORDED
- Local source-free candidate packaging dry-run completed; verify the archive
  digest against the adjacent `SHA256SUMS`. Clean-account operation and
  Authenticode status UNRECORDED
- Final recommendation: **NO-GO**

## Gates

| # | Evidence to collect | Status | Local evidence / limitation |
| --- | --- | --- | --- |
| 1 | Fresh clone or candidate archive on a clean Windows account using only `INSTALL_WINDOWS.md`; record installed prerequisites, Defender/firewall prompts and undocumented steps. | UNRUN | |
| 2 | Pinned GGUF, separate projector and server ZIP download/hash verification; corrupt/missing artifact refuses startup. | UNRUN | 2026-10-08T22:47Z partial: `download-model.ps1 -Verify` exit 0 on already-present artifacts; renaming the projector made verify exit 1 ("Missing model artifact"), file restored. Fresh download and wrong-bytes corruption untested. `.local/acceptance/20261008T224705Z-phase1/gate2-*.txt` |
| 3 | Pinned `llama-server` starts on loopback; `/v1/models` matches alias; both generated color probes pass with stop reason. Record cold/warm table-sized request latency and memory. | UNRUN | 2026-10-08T22:47Z partial: b10964 on 127.0.0.1:18080 with the pinned alias; doctor `vlm_models`, `multimodal_api`, `model_files_sha256` and `runtime_asset` PASS warm. The first, cold `multimodal_api` probe failed on its timeout (52.3 s cold prompt evaluation). Table-sized latency and memory as listed above; cold table-sized latency without thinking UNRECORDED. `.local/acceptance/20261008T224705Z-phase1/`, `.local/acceptance/20261008T232304Z-calibration/` |
| 4 | Unavailable/denied Windows capture reports an actionable reason and never leaves advice visible; no OS protection is disabled. | UNRUN | |
| 5 | Real client metadata and selected-window native pixels match executable, PID, HWND, title and dimensions. No adjacent desktop or other-window pixels enter the image. | UNRUN | |
| 6 | Helper starts before the client, waits with bounded polling and no repeated error flood. | UNRUN | |
| 7 | Start the client normally; helper discovers the calibrated executable without restart. Inspect updater behavior and locate `update.log` only through actual installation evidence. | UNRUN | |
| 8 | All tested lobby views and table previews remain lobbies or non-actionable screens, with zero recommendations. | UNRUN | 2026-10-02T00:00:35Z. One visible lobby titled CoinPoker at 1280×1032. Release helper, no PID/HWND/table pin, loopback VLM, no pixels saved. Two `lobby_detected` statuses, one lobby-title veto, 15 discarded observations, zero decisions or clears. `.local/acceptance/20261001T235902Z/lobby-observation.json`. 2026-10-02T00:47:14Z listing: lobby 1280×1032 and a second on-screen window 800×613, both titled exactly CoinPoker, hero not seated. A 15s live run selected neither window (`only lobby windows are present; no arbitrary observation window selected`), with zero decisions or clears. `.local/acceptance/20261002T004714Z/lobby-observation.json`. The user identified the 800×613 window as the game window and was not seated. Its Windows title is still exactly CoinPoker; the NLH label and table id are painted at the top left, so they are not a window-title selector. 2026-10-02T02:10:21Z release run passed the observed lobby size, selected that other-size window, and published no `table` event. Model replies were unreadable, invalid, or a non-table classification. `.local/acceptance/20261002T021021Z/live.jsonl`. No community-card reading is claimed. Other lobby views remain untested. |
| 9 | Open a real table; helper rebuilds selection, applies table-only title hint and two fresh matching observations without restart. | UNRUN | 2026-10-09T05:58:58Z partial, helper started after the table opened (the no-restart path is untested). Discovery selected the 1015×770 table, HWND 0x27910ec, on the first pass by size, since the table shares the lobby title. No fresh matching observation was obtained: the model read 0 of 3 table frames as a valid table (2 non-table, 1 schema-invalid). `.local/acceptance/20261009T055858Z-table-live/summary.md` |
| 10 | Close active table; advice clears exactly once within bounded discovery/capture time and never exceeds lease. | UNRUN | |
| 11 | Reopen or replace a table; fresh HWND/consensus prevents reuse of the previous hand or frame. | UNRUN | |
| 12 | Quit/relaunch the client; helper recovers across a new PID without restart when no PID/HWND pin is set. | UNRUN | |
| 13 | Two equally ranked table windows cause ambiguity and one clear; no enumeration-order choice; recovery after one closes. | UNRUN | |
| 14 | Minimized, obscured, animated, unreadable or inconsistent table emits no recommendation; recover after readability returns. | UNRUN | 2026-10-09T05:58:58Z partial: an animating live table emitted zero decisions and zero clears in 90 s. Recovery was not exercised. Finding: the table never held still for one inference, so no reading can be published during active play until animated regions are handled (decision pending). `.local/acceptance/20261009T055858Z-table-live/summary.md` |
| 15 | Slow real inference while cards, actions or window identity change discards obsolete work and never overwrites newer state. | UNRUN | 2026-10-09T05:58:58Z partial: all 3 live completions were discarded as `obsolete-observation` after the frame changed mid-inference, with no `observation-expired` discards under the 8000 ms lease and no state published. Card, action and identity changes were not isolated. `.local/acceptance/20261009T055858Z-table-live/live.jsonl` |
| 16 | Small card/action/amount changes clear prior advice before inference completes; capture/process loss and consumer EOF/expiry clear display. | UNRUN | |
| 17 | At 100%, 125% and 150% DPI, record window logical bounds and native pixels; test resize, move, multiple displays, aspect/crop and adjacent-window pixel exclusion. | UNRUN | |
| 18 | Held-out authorized real corpus meets every threshold in `VISUAL_EVALUATION_V2.md`; independently review all actionable states and coverage. | UNRUN | |
| 19 | Download checksummed candidate ZIP into clean account; verify support-file allowlist, execution, actual Authenticode status if requested, and complete local model setup. | UNRUN | |
| 20 | Required Rust, Python, PowerShell syntax, synthetic evaluation and Windows CI checks pass at the exact candidate revision; inspect CI run links. | PASS | 2026-10-09T04:36:30Z for candidate 81f5998. Local `scripts/validate.py`: all 12 checks exit 0, 293 Rust tests. CI run 37883810315 succeeded: https://github.com/clduab11/coinpoker-help/actions/runs/37883810315 (windows-latest 293 tests, ubuntu-latest 294). The earlier f97ca44 run 37030966828 failed only on clippy at `bin/config.rs:210`, fixed in c5a145a. `.local/acceptance/20261008T224705Z-phase1/gate20-summary.md` |

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
