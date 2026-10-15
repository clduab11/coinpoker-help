# Two-Track Live-Test Readiness

## Goal And Agreed Decisions

Bring this Windows repository to reproducible live testing through two independently accepted tracks:

- **Track A:** sustained native-model Pot/stack readings visibly current in Monitor, with source evidence and independent agent verification.
- **Track B:** independently agent-labelled board calibration, seated inputs, and the first experimental advice from real pixels. Track B does not block Track A.
- Local checkpoint commits are authorized during implementation. Commit the coupled existing refactor atomically, then use small verified commits. No push, PR, branch promotion, history rewrite, or destructive cleanup is authorized by this plan.
- Preserve local player labels and hash-addressed source PNG links. Minimize unnecessary browser window metadata and document the actual boundary. Do not research platform policies.
- A fresh agent replaces the human reviewer for both tracks. Call results **independently agent-verified**, never human-reviewed. Unknown/ambiguous labels remain unresolved.
- Track A requires native numeric capture-to-DOM p95 **strictly below 3,000 ms**, in addition to the functional criteria below. Existing original-capture/per-lane lease ceilings remain unchanged.
- Planning changed only this plan. Implementation was subsequently authorized, including the local checkpoint commits described here.

## Evidence And Current Boundaries

The supplied 2026-10-15 appraisal is the planning baseline, not a new test result. Local inspection confirms:

- Nine modified files plus four untracked source dependencies and the earlier refactor plan remain in the worktree. `scripts/laya-server.py` imports `scripts/laya_server_validation.py`; three Rust modules import extracted test files. Preserve these changes.
- `scripts/laya_dashboard.py:1072-1093` checks acquisition freshness against consumer time and invalidates on non-fresh health. Partial rejection paths at 1022-1043 and 1139-1162 can return before ledger append.
- `scripts/laya_capture.py:572-612`, `scripts/laya_dashboard.py:2047-2074`, and `scripts/laya_visual.py:529-612` couple receipt consumption to synchronous visual work. Asynchronous OCR alone does not isolate PNG validation/comparison work.
- Existing launch flags support manual-start bounded and sustained modes. `-ManualStart` is not the exact-PID/HWND manual capture CLI. Automatic capture currently uses GDI; WGC acceptance is separate.
- CI lacks lightweight Python dependencies and a default test imports private implementation code. Some native test helpers write synthetic data beneath private evidence roots.
- Existing receipts have source/session/service identity, but not complete code/binary/config identity. Diagnostic completeness and terminal receipt completeness are different.
- `crates/ingest/src/laya/assembly.rs:314-327` emits an observation-only state with empty hero/actions and null raise bounds. Advice needs a real input-production path, not merely a visible panel.
- The second-worktree salvage claim comes from the appraisal; its current registration and unique files were not independently inspected. Inspect before any worktree maintenance. Never prune as part of this plan.

No tests, captures, model loads, listener probes, or service changes were performed during planning. Reported 623 Rust / 814 Python passes remain appraisal-reported, not freshly reproduced. The generated graph is historical navigation only; current source is authoritative.

## Execution Order And Context Boundaries

| Packet | Work | Dependency | Finish Before Reset |
| --- | --- | --- | --- |
| S0 | Preserve and atomically checkpoint existing refactor | None | File inventory, coherent source commit, validation limitations |
| S1 | Hermetic tests and clean-checkout validation | S0 | Test-isolation commit and fresh baseline receipts |
| A1 | Freshness recovery and complete rejection accounting | S1 | Focused regression commit and deterministic replay report |
| A2 | Supervisor isolation and latency work | A1 | Blocking/race tests and measured stage timings |
| A3 | Operator UI, browser boundary, reproducibility receipts | S1; integrate after A2 | Separate UI/provenance commits, real-browser evidence |
| B1 | Label inventory and independent board review preparation | S1 | Frozen dataset/split manifest; no production model changes |
| A4 | Integrated freeze and live preflight | A1-A3 | Tested committed build, exact run instructions |
| A5 | Live execution, then fresh independent verification | A4 | Immutable evidence bundle and pass/fail/inconclusive verdict |
| B2 | Experimental board fit and seated input production | B1; avoid A5 GPU/service overlap | Candidate artifacts and input-contract tests |
| B3 | Decision correctness, integration, live experimental advice | B2 | Separate real-pixel advice acceptance report |

Use a fresh primary context for each packet; A5 execution and its independent review must use different contexts. UI work and receipt work may run concurrently with A1/A2 only with disjoint file ownership. B1 may proceed in parallel; B2 model/GPU work must not contend with A5. One coordinator owns shared files, integration commits, and port 18090.

Do not start a new packet when context is already substantially consumed. Prefer resetting around half the context used, after an atomic tested boundary; do not depend on compaction to preserve lease or concurrency invariants. If a packet grows, split at a regression-tested seam, not midway through a state-machine change.

At every cutoff, update this plan's execution record or its implementation handoff section with: commit SHA; dirty/untracked inventory; exact changed files; tests/commands and exit codes; evidence paths; unresolved failures; invariant decisions; running process/session ownership; and the single next task. A new agent reads that packet and relevant code/tests, not all logs or all historical plans. Preserve full logs privately and reference them by path.

## S0: Preserve The Existing Baseline

1. Reinspect status, diff, recent commit style, tracked/untracked dependencies, and source paths. Never stage everything indiscriminately, stash others' work, or revert it.
2. Inspect the second worktree without pruning; preserve any unique files through a non-destructive verified copy and record the location. Do not copy private evidence into tracked files.
3. Review the existing refactor as behavior-preserving: geometry parity, lazy heavyweight imports, server test monkeypatch compatibility, and Rust test extraction. Do not expand it into another architecture refactor.
4. Run non-mutating checks and focused tests whose output roots are safe. Do not run known contaminating native helpers yet. Commit all coupled source dependencies and their existing plan together; describe any baseline validation still pending accurately.
5. Add `.claude/` to ignores as a separate small hygiene change if still appropriate. Exclude unrelated private launcher state and this new plan from the refactor's source inventory unless intentionally staged.

**Exit:** an internally coherent baseline commit exists; unrelated changes are preserved; no claim of new full-suite success precedes S1.

## S1: Make Validation Hermetic

1. Move the affected native test fixture roots to uniquely owned OS temporary directories with cleanup, including failure paths and parallel test safety. Prove tests no longer add files to existing `.local` evidence trees.
2. Declare/install only the lightweight default test dependencies needed by clean CI, aligned with Python 3.12 and available pinned runtime versions. Do not install the GPU stack in ordinary CI or hide missing required dependencies behind blanket skips.
3. Inspect `test_observer_measurement.py`: move reusable measurement implementation into tracked source if it belongs to default tests; otherwise make only genuinely private replay tests explicitly opt-in with clear skip reasons. No unconditional `.local` import during collection.
4. Align local validation with the interpreter invoking it, CI commands, dependency setup, and skip reporting. Preserve synthetic-versus-physical acceptance distinctions.
5. Reproduce checks from a tracked-files-only clean checkout/export with no inherited `.local`, model cache, or untracked modules. Exercise both supported CI platforms through available local/CI-equivalent environments; mark unavailable coverage pending rather than claiming hosted CI is green.
6. Inventory suspected synthetic historical sessions separately. Quarantine only positively identified test artifacts using a manifest and reversible moves; preserve uncertain/real evidence. Historical cleanup is not a prerequisite once new tests are isolated.

**Validation baseline:** `cargo fmt --all -- --check`; `cargo check --workspace --all-targets --all-features --locked`; `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`; `cargo test --workspace --all-targets --all-features --locked`; `.local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests`; pinned-interpreter `scripts/validate.py`. Record fresh counts and skips, not hardcoded appraisal totals. Run heavyweight full checks once per integration boundary, not redundantly in every worker.

## A1: Repair Freshness Without Weakening Leases

Primary files: `scripts/laya_dashboard.py`, dashboard/stage2 regression tests.

1. Add failing regressions first. Compute acquisition freshness from `emitted - captured < 1000`; retain timestamp ordering, producer `fresh_capture`, source/dimension/frame checks, and consumer delivery-age bound `now - emitted < HEARTBEAT_MS`.
2. Allow recovery after transient `capture-not-fresh` in the same generation/epoch. Distinguish this health unavailability from capture invalidation/replay tombstones; do not indiscriminately reset `invalidated_version` or revive an invalidated ticket. Existing displays still clear while capture is unavailable.
3. Add a bounded reason-coded ledger outcome for every partial rejection or suppression, including session mismatch, malformed envelope, activity gate, scoped replay, failed lease, version/source regression, duplicate bundle, and exhausted remaining time. Keep foreign-session rows from mutating current state; record them at the appropriate owner boundary. Do not persist arbitrary unvalidated payloads.
4. Make packet identity and counting explicit using session/service/source, generation/epoch, capture clocks, and source digest where valid. Preserve sequence floors, field-specific invalidation, and same-capture deadline non-renewal.
5. Distinguish obsolete packets from current-source failures. Newer health -> delayed older partial -> valid newer partial must not silently destroy newer state, while genuine current-source failure still clears it. Adjust existing fail-closed tests intentionally, never simply delete them.

**Tests:** emit-prompt/deliver-late cases; exact 999/1000 and 2499/2500 ms boundaries; same-generation unhealthy/healthy recovery; explicit invalidation replay; malformed/future clocks; wall rollback versus monotonic expiry; repeated/duplicate partials; source/service/epoch changes; every return path has an observable outcome. Demonstrate new tests fail before the fix. Replay d643 if its private inputs exist, without treating replay as live proof.

## A2: Remove Transport Starvation And Meet The Latency Target

Primary files: `scripts/laya_capture.py`, `scripts/laya_dashboard.py`, `scripts/laya_visual.py`, associated tests; native batching/scheduling only if timings justify it.

1. Measure separate acquisition-to-emit, emit-to-ingest, ingest-to-API, and API-to-DOM timings. Add minimal bounded instrumentation sufficient for run accounting and optimization; no new observability platform.
2. Move PNG reads, hashing, decode, and region comparisons out of supervisor callbacks and long feed-lock sections. Use bounded latest-work/coalescing only for visual jobs. Native/control/invalidation events must retain ordering and may not be silently dropped.
3. Capture immutable source bytes and validated identity before asynchronous work can race with rotating files. Completion must recheck session/service/source/epoch/sequence and remaining original lease. Retired-session completions cannot publish.
4. Avoid repeated `public_snapshot` work per feed row; move expensive CPU projection out of lock-held HTTP snapshots. Preserve conservative withholding while validation is pending. Add serialized snapshot caching only if measured contention remains; expiry must never become cached renewal.
5. Persist actionable capture failure reasons in private status and expose a minimized operator explanation. Add bounded overlap rechecking/cooldown only with tests that keep affected reads unavailable throughout uncertainty; never reuse pre-overlap pixels as current. Do not auto-rearm a failed session indefinitely.
6. If the three-second target still fails, optimize the measured dominant native passes/batch scheduling. Any change to scheduled board work must be explicit and recorded in the run manifest; do not change model floors, hide slow samples, extend leases, or disable a lane silently to pass.

**Tests:** blocked visual submit/projection cannot starve health, stop, or owner receipts; bounded queue/memory behavior; alternating-file overwrite race; worker failure; stop/source replacement during completion; capture overlap; snapshot concurrency and expiry. Measure all stage distributions, not just inference time.

## A3: Make Operation And Evidence Truthful

Split this packet into separate commits and owners where feasible.

### Operator UI

- Implement the seven appraisal quick wins in `scripts/dashboard/{index.html,app.js,styles.css}`: visible empty message; state-dependent source tone; mobile dot padding; explicit correct clear reasons; visible current/provisional/last-read vocabulary and distinct shapes; dated previous-session copy; visible next-step/lifecycle instructions.
- Distinguish native admitted values from CPU provisional values. Specify existing lane precedence and prevent a CPU empty result from erasing a valid native pot; an expired value remains unknown, not zero.
- Retain keyboard focus during Start/Stop requests with a guarded `aria-disabled` pattern. Distinguish timeout/unreachable/rejected responses in diagnostics. Connection-status debounce must not delay lease expiry or hide invalidation.
- Do not announce invisible recommendations. Keep experimental advice visibly unavailable until B3 actually produces valid input and output; B3 must implement the visible state when reached.
- Add real-browser smoke tests at 800x600, 375x812, and 1280x800, including computed visibility, overlap, keyboard focus, forced colors, disconnect-first idle recovery, previous session, and provisional/last-read qualifiers. Do not rely solely on Node DOM shims or rewrite the entire frontend.

### Browser Boundary And Documentation

- Keep local on-screen player labels and source-backed PNG access. Open evidence in a separate tab with appropriate isolation so Monitor polling continues.
- Remove HWND/PID/window-class browser fields only after tracing binding consumers; retain necessary opaque source identity and full private capture provenance. Test DTO allowed keys, capture binding, allowed image lookup, missing image, and traversal rejection.
- Replace apparent real names in tracked test fixtures with synthetic names. Do not rewrite existing history.
- Update README, SECURITY, EVENTS_V2, and HANDOFF to reflect actual Start/Stop routes, evidence route, CPU lanes, GDI automatic path, lane precedence, evidence tiers, canonical commands, and fresh validation results. Keep HANDOFF at its current path until consumers are deliberately migrated; moving it is not required for live readiness.

### Reproducibility Receipts

- Record Git revision, dirty state, executable SHA-256/path, relevant tracked source/config manifests, launcher arguments, service-instance identity, runtime/package identities, selector digest, model/checkpoint/calibration/question/region digests in private approval/run evidence. Bind the Python service and browser assets too, not just the Rust exe.
- Missing provenance is explicit unknown, not an invented clean identity. Acceptance requires a frozen known build; diagnostic runs may remain dirty if reported as such.
- Fix stderr filename disagreement and test exact-cap/over-cap/tail behavior. Preserve transport after sustained diagnostic archival caps, but explicitly report `diagnostics_complete`, `receipt_complete`, bytes dropped, and affected intervals. Do not blindly replace the cap comparison with a stop condition that changes sustained semantics.
- Keep essential bounded acceptance accounting usable if verbose diagnostics reach their cap. If evidence needed to reconstruct acceptance is missing, the run is inconclusive.

## A4: Freeze And Preflight

1. Integrate on the reviewed checkpoint line, resolve only intended overlaps, rerun full checks, build the exact executable, and commit final source changes. Freeze code/config/model identities for the test.
2. Verify the listener owner and startup mode at execution time; the appraisal's dashboard-only process may no longer exist. Do not kill an unknown listener or use an alternate port to evade the one-instance contract. Deliberately stop/replace only the identified owned instance when implementation execution is authorized.
3. Verify pinned runtime/model files locally, source selector, expected table geometry/theme, disk/evidence budgets, and unobscured source. A source mismatch is a diagnostic result, not a reason to guess another window.
4. Preflight bounded capture and short inference smokes only if current receipts do not already prove the frozen configuration. These are diagnostics, not substitutes for the sustained run.
5. Use the existing sustained manual-start launcher:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation -ManualStart
```

Default selector is `.local/practice-table.json`; explicitly pass `-PracticeConfig` only when the reviewed source differs. The bounded UI recovery command omits `-ContinuousObservation`; label the two modes accurately. `-ExperimentalBetAction` is not part of Track A.

6. Start capture through the existing Monitor control only after service/source readiness. Prepare an external monotonic stop deadline for the measurement window, terminal-state checks, and an immutable output folder. Sustained observation does not self-stop at its archival evidence limit.

## A5: Execute And Independently Verify Track A

Start in a fresh execution context; use another fresh agent for the verdict. The reviewer reads the frozen manifests, original frames, raw producer/feed/API events, and browser receipts without adopting the implementer's conclusions.

### Run Protocol

1. Warm the model before the measured interval; record warm-up and first-read latency separately. Freeze the interval before looking at performance results.
2. Observe the same identified source for at least 600 seconds after readiness. Request stop at the end and verify terminal receipt/owned-child exit; a bounded stop grace is not a new observation window. No restart loop or arbitrary extension to obtain a favorable sample.
3. Preserve source frames/manifests, producer events, reason-coded ledger outcomes, API samples, actual browser state/DOM timestamps, screenshots, stage timing samples, and terminal status. Respect the existing archival limits and explicitly identify post-archive intervals.
4. Perform stop/source-loss/overlap boundary exercises in separately labelled smoke sessions so they do not contaminate the primary stable-window performance denominator.
5. On failure or no natural change, stop, retain evidence, and report failure/inconclusive with one diagnosed next task. Fix in a new code packet, commit, and repeat on the new build; never relabel the old run.

### Acceptance Criteria

- At least three distinct source-backed accepted display updates span at least 60 seconds within the sustained run, including a naturally occurring numeric change. Backcheck Pot and at least two supported stacks; fields need not share one frame.
- Every value claimed as verified numerically matches its original frame after stated unit/format normalization. No arbitrary tolerance, corrected labels, or plausible-value substitution. Record the complete verification sample and all mismatches; any known incorrect current native value fails the run.
- Every producer partial in the measured interval has a ledger disposition. Compute admission rate over distinct validly identified producer partial tickets, documenting duplicates and malformed rows separately. At least 90% are admitted; legitimate expiry rejections count against admission, not unexplained disappearance. Report raw totals as well as distinct-ticket totals.
- Native numeric capture-to-first-current-DOM p95 is strictly below 3,000 ms. Use every unique displayed native numeric capture/field in the predefined interval; report sample size, quantile method, per-field breakdown, first-read latency, and undelivered/rejected events separately. Do not use CPU provisional values or repeated polls to improve this distribution.
- Report availability, gaps, and delivery/admission/DOM-conversion rates separately. Sparse output is not continuous accuracy. The minimum update demonstration is not a statistical model-quality certification.
- Browser receipts show actual `current` values. No value survives its original wall/monotonic lease, invalidated source, or stop; same-ticket polling never renews it. Preserve CPU lane leases and provisional labels.
- Code/model/config identities and evidence required for the verdict are complete and frozen. Finish with confirmed terminal process state and update HANDOFF plus this plan's execution record.
- Verdict is `pass`, `fail`, or `inconclusive`, with separate functional, transport, latency, and sampled-numeric results. Label the overall evidence independently agent-verified, not human-reviewed. If hosted CI has not run, state that separately; local physical acceptance does not establish hosted CI success.

## Track B: Board And Experimental Seated Advice

### B1: Dataset And Independent Labels

1. Inventory the existing 72-frame checklist against original hashes, dimensions, theme, capture source, and related hand/session groups. Do not assume it is complete, independent, or representative of seated play.
2. Have one fresh agent propose labels from pixels and another review independently without model predictions or proposed answers initially. Preserve both raw label sets, disagreements, adjudications, and unknowns; unresolved samples do not become ground truth.
3. Split by source session/hand/near-duplicate group, not random adjacent frames. Freeze fit/calibration/held-out manifests before refitting. The fitting agent cannot tune against held-out labels/results repeatedly.
4. Produce an explicitly agent-labelled dataset artifact. Human-review status stays unverified. Do not promote global `quality_approved` or similar historical flags merely because this review replaces the requested human workflow.

### B2: Board Calibration And Seated Inputs

1. Diagnose the board score/objective and unreachable fitted floor from saved data; determine whether calibration alone is adequate or training data/objective must change. Do not lower a threshold until cards appear.
2. Fit an isolated candidate, preserving it1 and current pins. Record precision/recall/coverage, per-card errors, held-out sample counts, and uncertainty. Minimum experimental promotion requires zero observed false admissions on the frozen held-out set plus nonzero admission coverage; small samples do not prove general precision. If insufficient, retain the candidate as non-promotable and report the data requirement.
3. Benchmark candidate end-to-end latency under the shared capture-to-DOM methodology. Keep historical Gate F/full-battery results distinct. Promote candidate pins only in a dedicated reviewed commit with an explicit rollback identity.
4. Capture a bounded seated dataset, measure actual hero/action regions, and add replayed crop/geometry tests. Do not assume observation-only region geometry covers seated controls.
5. Implement typed production of hero cards, board/street, hero stack, current contribution, to-call, legal actions, opponents needed for equity, and exact raise bounds. Every required field needs validated source identity, units, original capture lease, and coherent hand/street context. Missing values remain unknown.
6. Do not reinterpret the observation-only zeros in `assembly.rs` as verified actionable data. Missing raise bounds cannot be hidden by erasing a visible raise action; either implement full bounds or withhold the full-state recommendation under its existing input contract. Test genuinely no-raise states separately.

### B3: Math, Wiring, And Real-Pixel Advice

1. Fix short-stack EV using eligible-pot contributions, distinguishing contestable main/side pots and uncalled excess. Do not merely subtract one unmatched amount or reuse a helper without confirming its pot semantics. Add heads-up, multiway, side-pot, short-call, and all-in reopening/legal-raise tests.
2. Add deterministic seed injection across equity/sizing randomness and record the seed/config in experimental receipts. Keep estimates/assumptions such as fold equity distinct from observed facts.
3. Wire one supervised real-capture path through complete validated state -> parser -> equity/decision engine -> typed event -> DashboardState -> visible experimental advice. The existing automatic/manual-inference launcher does not by itself prove this path exists; extend the owned integration seam and test its lifecycle rather than starting an unrelated untracked binary path.
4. Show the panel only for a coherent current recommendation, with provenance and `quality_approved: false`; expire it on input/hand/source changes. Do not announce hidden content. Opponent historical statistics remain unavailable until quality-backed action history actually exists; do not invent counters to unblock a decision.
5. Accept B3 only after at least one real seated observation and experimental recommendation are independently backchecked against original source hashes, the engine's reproducible inputs, legal action bounds, and seeded output. Exercise missing input, expiry, source loss, and stop. A saved-frame replay is a prerequisite, not a substitute for this live acceptance.

## Deferred Work And Explicit Limits

- No prerequisite wholesale `app.js` module/Lease rewrite, renderer redesign, keep-alive conversion, dependency-major convergence, or dead-code purge. Revisit measured hotspots after Track A.
- WGC migration, DPI-awareness changes, cursor exclusion, and worker restart policy become targeted work only if live evidence identifies a capture blocker; record GDI/theme/DPI limits honestly.
- Stop tracking generated graph artifacts, third-party asset relocation/notices, broad line-ending normalization, repository repacking, release allowlist repair, and reference-range reconciliation are separate maintenance packets. Use the self-contained appraisal; no policy/licensing research or history rewrite.
- Do not create a release from the known stale packaging workflow. Release repair is required before distribution, not before a local source-run test.
- Hosted CI proof requires publishing a revision; pushing is not authorized here. Default-branch promotion, remote branch cleanup, PRs, and history removal require separate explicit authorization.
- No automated table actions or unrelated product expansion is included. This is scope definition, not a repository-wide read-only restriction.

## Failure And Rollback Rules

- Keep failed raw runs and label every source: synthetic, saved replay, live, agent-labelled, independently verified. Never overwrite earlier evidence to make a gate pass.
- Revert only an identified new change through a reviewed forward/revert commit when appropriate; never reset away user work. Preserve the last passing model/config/code identity.
- An occupied unknown listener, unknown source, missing build identity, truncated essential evidence, expired input, or ambiguous label yields an actionable diagnostic or inconclusive result, not guessed success.
- Do not change tests to bless an unsafe replay, renewed lease, zero-filled unknown, leaked source identity, or incomplete terminal receipt.

## Execution Record

### S0 Completed (2026-10-15)

- Atomic source checkpoint: `f8816aa` (`Checkpoint hybrid geometry and validation refactor`), all 14 coupled source/earlier-plan files staged explicitly. New readiness plan and private `.claude` state were excluded.
- Independent static Rust review found no introduced regression. Python review found alias-rebinding differences across the extracted module; tested ROOT/REPO and handler seams remain intact. No concrete alias-rebinding consumer was found, so no speculative compatibility layer was added. Default geometry is cached for the lifetime of the process; restart on manifest changes.
- Commands passed (exit 0): `git diff --check`; `cargo fmt --all -- --check`; `cargo check --workspace --all-targets --all-features --locked`; `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`; `cargo test -p ingest --locked laya::geometry::tests::` (5 passed); pinned Python `-B -m unittest discover -s scripts/tests -p test_laya_server.py` (101 passed); corresponding board module (27 run, 4 explicit skips).
- Full Rust/Python suites intentionally not rerun before fixture isolation. Console command results are in this session transcript; no S0 full-validation receipt is claimed.
- WSL-registered second worktree is present on disk but its gitfile is invalid on Windows. No repair/prune attempted. Preserved `scripts/lint-instructions.py` and `.pre-commit-config.yaml` beneath `.local/worktree-salvage/20261015/`; SHA-256 pairs match originals: `2a3768ca682a0b1386caa89852cdf790ddb8075352dcc403dcbc53fc60c534cb`, `e8e3b0d67f3b857f81cc8707ec1d6df8775e8df4261d874ee48ad41471cc8a9f`.
- No servers, model loads, captures, or client actions performed. Existing process disposition remains uninspected. No commits pushed.

### S1 Completed (2026-10-15)

- Native fixture-isolation and Python clean-collection work were implemented by disjoint workers; main reviewed/integrated their changes and performed the integration validation. A separate read-only agent inspected stable S1 invariants and found no actionable introduced regression, with an explicit inability to inspect Git diff attribution under its permissions.
- Additional isolation seam found: `crates/ingest/src/recorder.rs::tests::temp_root` currently uses temporary directories beneath private evidence. It is included in S1 along with the two native test modules.
- Historical synthetic evidence is not deleted or moved. Private observer-measurement original remains preserved; reusable default-test implementation will be promoted into tracked source.
- Native isolation committed separately as `639956e` (`Isolate native test fixtures from private evidence`), after `90d40ff` ignored private desktop launcher state. Five native/dependency files only; seven new cleanup/root/ownership regressions.
- Full integration validation passed using a clean Python 3.12.15 environment containing only requirements-test dependencies: 630 Rust tests passed; Python 820 run, 26 explicit skips; fmt/check/clippy, six PowerShell parses, synthetic evaluation and workflow YAML validation passed. Full receipts: `.local/validation-readiness/s1-20261015T2125/integration/`.
- Evidence-isolation inventory in `.local/validation-readiness/s1-20261015T2125/evidence-isolation.json` records 115,730 entries in the two historical native evidence trees before and after the full suite, with zero additions/removals/metadata changes. This is a metadata comparison, not a full content-hash claim.
- Clean tracked-only export: `C:/Users/cld-main/AppData/Local/Temp/kilo/s1-checkout-20261015T2133/`; exported from the intentionally staged S1 index before commit. No `.local`, runtime/model assets, or untracked source. Dependencies install successfully on Windows Python 3.12.15 and WSL Ubuntu Python 3.12.3; Linux Node 24.21.0 is available, Linux cargo is not.
- First clean-export suites exposed pre-existing tempfile parent assumptions: 183 Windows setup errors / 182 Linux errors; logs retained at `clean-windows/python-tests.log` and `clean-linux/python-tests.log` under the S1 receipt directory. Do not count these as passes. A focused worker is replacing checkout `.local` tempfile parents with OS temp roots; it owns eight affected test modules and is not changing production path security.
- The 16 fixture-parent corrections preserve injected fake roots and production containment rules. Focused worker validation: 421 tests run, 3 skips; an audit hook found all 212 temporary-directory allocations outside both checkout and selected-source export. Export `.local` remained absent.
- Final tracked-only snapshot: `C:/Users/cld-main/AppData/Local/Temp/kilo/s1-checkout-final-20261015/`. Main independently ran the full Python suite there on Windows (820 run, 26 explicit skips, exit 0) and Linux (820 run, 29 explicit skips, exit 0); assertions verified `.local` absent before and after. Linux's three extra skips cover Windows OCR, shared-delete receipt semantics, and unavailable PowerShell 7. Logs: `clean-windows-final/python-tests.log` and `clean-linux-final/python-tests.log` under the S1 receipt directory. Both isolated environments pass `pip check`.
- A tracked-only Rust export compiled successfully with `cargo check --workspace --all-targets --all-features --locked`, reusing only the local target cache. Full native test execution was in the main checkout, not a clean Linux runner.
- Python/CI/measurement migration committed as `5ef6a75` (`Make Python validation reproducible on clean checkouts`), 14 explicitly reviewed files. CI now declares Python 3.12, Node 24, and NumPy/Pillow/PyYAML test dependencies. No model/GPU stack installed in either clean environment. The reusable measurement source differs from its preserved private original only in docstring and repository-root calculation.
- Validation receipts were written into distinct new directories. `validate.py --output-dir` does not enforce no-clobber or filesystem immutability; preserve evidence by continuing to select unique directories and never rerunning over old outputs.
- No changes were made to acquisition leases, model floors, runtime services, source selectors, or the poker client in S0/S1. Historical evidence was not quarantined or deleted. Generated graph artifacts were not refreshed; they remain explicitly historical navigation, not current evidence.
- Linux Rust and hosted CI remain unverified. All live, performance, board, and seated-advice acceptance gates remain pending.

### A1 Completed (2026-10-15)

- Source commit `647de17` (`Fix consumer freshness and account for rejected partials`), three scoped files. Producer acquisition freshness now uses emission minus capture; delivery remains strictly below 2,500 ms. Transient capture-not-fresh health and partials during unavailability do not permanently tombstone a generation. Same-capture wall and monotonic budgets remain capped by the original admission.
- Sanitized reason-coded private dispositions cover partial rejection/suppression at state and owner boundaries. Ledger exhaustion remains explicit incomplete accounting, not an implied complete outcome stream.
- Fourteen regression methods added. Before-code evidence includes seven failure subcases and one error, plus owner-accounting and interleaved-unhealthy regressions. Focused final result: 237 run, 3 explicit skips. Detailed red/green commands and replay notes: `.local/validation-readiness/a1-20261015T2149/summary.json`.
- Independent static review found a new delayed-health poisoning edge; fixed and re-reviewed. Provably older same-source health is now inert and reason-logged rather than clearing a newer partial. Genuine current-source clock contradictions, explicit source/epoch/geometry invalidations, and independent heartbeat expiry deliberately retain hard invalidation. No blanket auto-rearm or tombstone reset was added.
- Saved d643 metadata-only replay: 2,842 rows, 16 producer partials, artificial fixed 1,500 ms delivery. Baseline recorded 0/16 partial outcomes; A1 recorded 16/16, with 9 admissions and 7 lease failures. This is not a reconstruction of historical arrival, source-PNG verification, DOM measurement, or live proof.

### A3 Subsets Completed (2026-10-15)

- UI/browser commit `56cb16c` (`Clarify Monitor validity and preserve control focus`), eight scoped files. Visible empty state, truthful status tones and qualifiers, distinct shapes, previous-session timestamps/ages, visible complete launcher commands, guarded focus-preserving controls, and CPU-empty/native-pot precedence are implemented. Evidence links open separately. Hidden recommendations no longer announce availability; visible coherent advice remains B3 work.
- Added optional `scripts/browser_smoke.py` and `scripts/requirements-browser.txt` (Playwright 1.64.0). All browser requests are intercepted against synthetic fixtures, including control POSTs; no TCP service on 18090 is contacted. Cases cover three viewports, normal/forced colors, visible empty/previous-session states, native/provisional expiry and amounts, overlap/overflow, 800x600 table fit, and pending Start/Stop focus/repeat guards.
- Final browser result: 42/42 passed, zero page errors or unexpected requests. Evidence: `.local/browser-smoke/20261015T221647Z-0b6df46e/report.json`, with asset hashes, per-case snapshot hashes, browser version and screenshots. Earlier harness-selector/wording/unit-normalization failures and compact-layout failures remain preserved; use only the final report for the pass claim. Native integer hundredths are explicitly normalized to displayed chip units; CPU literals remain separate.
- Provenance commits `941c900` (`Bind private run provenance and account for diagnostic loss`) and `27dc701` (`Resolve virtual-environment interpreter identity`). Rust v1/v2 approval fields are unchanged. Private `provenance.json` binds approval bytes; `run.json` binds both hashes. Source/config/browser/binary/runtime/service/selector identity is recorded at startup/admission, not per row. Verified model hashes come only from the existing verifier; expected pins are separately labelled.
- Original stdout/stderr transport survives archival clipping; stderr tail uses the same `stderr.txt`. Exact/over-cap loss, uncertain writes, unconfirmed shutdown, and persistent close/flush failure are explicit. Terminal receipt completeness is separate from diagnostic accounting. Independent review findings were corrected with red-before-green regressions; final focused capture/provenance suite: 57 passed, no skips. Main also corrected the initializer-stop mock and asserted that verification actually ran, removing a possible incidental-TypeError false pass.
- Cross-platform clean export initially found Linux venv interpreter symlinks reported unknown. `27dc701` resolves only the process-owned interpreter before hashing; generic evidence/model redirect rejection remains unchanged. The failing log and subsequent passing receipts are separate.
- Provenance limitations remain explicit: disk source hashes do not attest compiler-to-executable linkage (`native_build_link` is unknown); CPU asset manifests cover declared banks/configs, not every original template image; standalone capture uses the last private service diagnostic publication. A4 still needs the frozen build command/artifact linkage and actual service/model checks.

### Integration Checkpoint (2026-10-15)

- Source HEAD `27dc701`, all source commits local/unpushed. Full pinned Python suite passed after the final close-failure correction: 868 run, 26 explicit skips. Log: `.local/validation-readiness/a1-a3-20261015T2210/final/python-tests.log`.
- Final tracked-only export: `C:/Users/cld-main/AppData/Local/Temp/kilo/a1-a3-checkout-final-20261015/`. Clean Windows dependencies: 868 run, 26 skips, exit 0. Clean Linux dependencies: 868 run, 29 skips, exit 0. `.local` was asserted absent before and after both suites. Logs: `clean-windows-final/python-tests.log` and `clean-linux-final/python-tests.log` under the same receipt root. Earlier failed Linux interpreter-identity run remains at `clean-linux/python-tests.log`.
- Rust source/dependencies did not change in A1/A3; the last full native result remains S1's 630 passed. Linux Rust and hosted CI remain unverified. No full Rust rerun was needed for these Python/browser-only packets.
- No production listener, model, source capture, or poker client has been started, stopped, or inspected. Only synthetic test servers on ephemeral ports and isolated intercepted headless browser contexts ran; these have exited. No live availability, model accuracy, or capture-to-DOM latency acceptance is claimed.

### Next Context: A2 And Remaining A3

- Read this execution record, `git status --short --branch`, HEAD, and the A2 section. Expected source checkpoint is `27dc701` followed by the execution-record commit. S0, S1, A1, UI quick wins, and provenance are complete; do not redo their implementation or overwrite earlier evidence.
- Use a fresh worker for bounded supervisor/visual isolation in `scripts/laya_dashboard.py`, `scripts/laya_visual.py`, relevant tests, and `scripts/laya_capture.py` only where actual owner coupling requires it. Preserve new A1 reason accounting, emission-based health, original lease budgets, tombstones, ordered control/native events, new provenance arguments, and diagnostic counters.
- Measure source-to-emit, emit-to-ingest, ingest-to-API and API-to-current-DOM separately. Keep latest-work coalescing limited to visual jobs. Validate immutable bytes/source identity before publication, reject stale or rotated-file work, and prove stop/health remain responsive while visual work is blocked. No silent board-lane removal or lease/threshold changes to manufacture a performance pass.
- Remaining A3: minimize unnecessary browser popup HWND/PID/class through a coordinated opaque binding projection; current JS still validates raw popup fields and this seam must not be broken piecemeal. Update actual browser boundary/route docs, canonical launch/runbook details and evidence tiers. Control-request timeout/unreachable/rejection detail is implemented; generic poll-failure taxonomy is not yet changed. Historical human-review wording must not be mistaken for a new human-approval gate; user selected independent agent review.
- No worker owns files or a runtime service now. Optional browser interpreter: `C:/Users/cld-main/AppData/Local/Temp/kilo/readiness-browser-env-20261015/Scripts/python.exe`; run `-B scripts/browser_smoke.py --channel msedge` for the 42 synthetic cases. Do not call that live proof. Real runtime ownership/source readiness stays an A4 check.
- After A2 and remaining A3 are verified/committed, proceed to A4/A5 frozen live testing and B1 agent-only label preparation. The three-second native capture-to-DOM gate, 600-second sustained run, independent source-frame backchecks, board calibration and seated advice all remain pending.
