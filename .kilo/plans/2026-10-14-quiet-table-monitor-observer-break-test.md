# Quiet Table Monitor And Observer Break Test

## Purpose And Session Boundary

This is a portable implementation brief for the next session. Complete Part 1 and its regression checks before starting Part 2. A cosmetic mockup, a ready model, or synthetic role tests alone do not complete this task.

Workspace: `C:\Users\cld-main\Desktop\github-projects\coinpoker-help`.

Monitor: `http://127.0.0.1:18090/`.

Read `AGENTS.md` first. The implementation session is authorized for relevant code/configuration changes, model use, tests, rebuilding, capture/inference, and restarting verified owned helpers. Preserve unrelated worktree changes. Do not commit, push, reset, or discard changes. Do not obtain platform-policy documentation or introduce policy-derived restrictions. Source identity, freshness, recognition qualification, and evidence limits are technical checks, not new permission requirements.

The user handles client hovering, seating, buy-in, and gameplay. Do not execute poker actions or automatically move the mouse over client profiles. Selecting a seat in the Monitor must only open Monitor details, never control CoinPoker.

The user is observing. No live seated-player test has been established. Do not assume hero, own cards, position, or offered legal actions. Implement role-transition logic in Part 1; live seated verification remains UNTESTED unless the user separately chooses to sit.

User-confirmed UI decision: put imported VPIP, PFR, 3-BET, and C-BET in selected-player details. Keep all six seat cards concise.

No separate mockup was available in this planning session. Use the prompt's dark six-seat table direction, not invented recognized data or a claimed pixel-exact mockup match. No genuine profile-tooltip example was inspected; acquiring one is an implementation intake step, not a reason to invent its geometry.

## Planning Findings

Code, saved evidence, and the existing Monitor page were inspected without editing implementation files or changing running Monitor state. Only this plan file was created. Tests and builds were not run during planning.

At the planning API sample `1791948344334` Unix ms, `/api/state` returned HTTP 200 and `server.model_state=ready`, but `capture_session.status=failed`, `stop_reason=capture-failed`, `capture.state=unavailable`, and `capture.source_id=null`. There were no current partial or visual observations. The page displayed failed automatic observation, expired readings, and a last capture over 41 minutes old. OS listener ownership was not verified because the shell listener query was denied. Do not equate a responsive page or loaded model with healthy capture.

The existing runtime reported incomplete compact readout evidence: 702 records and 4,193,715 bytes, close to the existing 4 MiB limit. The prior 600-second collector saved 31,557,318 bytes of API JSON, close to its 32 MiB limit. Enlarging the state payload without changing collection strategy risks losing the end of the next test.

Verified code gaps:

- Sustained numeric scheduling repeats adjacent readout pairs for seats 1/2, 3/4, and 5/6. CPU board readiness removes the two GPU board jobs, leaving six numeric jobs. Numeric p0 intentionally omits hero/role questions.
- Partial native/API role projection currently supports observing-or-uncertain, not a live independent seated/hero path. Role enums and provisional crop declarations are not recognition evidence.
- Qualified occupancy fields exist, but occupant epochs have no live producer; identity and imported client-profile statistics are absent.
- The frontend replaces seat children during rendering and hides the all-unknown panel. This conflicts with a stable six-physical-slot diagram.
- Visible-desktop capture rejects overlapping top-level windows, including same-client popups. WGC captures the selected HWND rather than automatically capturing separate popup content.
- Archival recording is bounded, followed by a two-slot rolling mailbox. Visual logs currently cover archival frames only; mailbox filenames cannot serve as durable event originals.
- Native partial consensus currently has one candidate/publication slot. Inserting sparse role/scene jobs without lane isolation can overwrite a numeric consensus seed.

Prior evidence, not proof of the planned implementation:

```text
.local/laya/train/observer-verified-measure-20261014T015435Z/
.local/laya/train/live-monitor-witnesses-20261014.json
```

The witness file explicitly says agent visual comparison, `human_reviewed=false`, and seated testing UNTESTED. Two referenced originals were viewed during planning: an observer river frame with folded occupied seats, and an observer frame with distinct stack, wager, and explicit fold/raise badges. Neither contained a profile tooltip. Historical native attempt-gap maxima of 10.191-11.917 seconds are supplied by the brief; they were not remeasured during planning. The ten-second native target must not be reported as passed.

Prior continuity requirement retrieved from MemPalace, verbatim:

> Taking a seat should **not restart monitoring or discard the history already collected**.

`source_file`: `ses_edd57acccffeE2YctfN6xccARr.md`.

## Implementation Map

Line ranges describe the inspected worktree and may move. Read the current functions before editing; this is a dirty worktree with substantial unrelated changes.

| Concern | Existing seam | Planned change |
|---|---|---|
| Layout/rendering | `scripts/dashboard/index.html:59-80`; `app.js` normalization at 749-805 and rendering at 1208-1307; `styles.css:63-103,157-176` | Persistent six-seat table, selected-player details, quiet per-field updates and explicit freshness |
| Dashboard projection | `scripts/laya_dashboard.py` field allowlists at 41-77, `partial_view` at 272-395, `DashboardState` and `snapshot` | Typed independent context/role/stat projections; owner-bound retention; evidence/event projection |
| Public source IDs | `laya_dashboard.py::_target` at 870-881; `begin_stream`; `ManualSessionFeed::_ingest_row` at 1897-1898 | Explicit crosswalk between feed, receipt, native capture, source, and table-context IDs |
| CPU recognition | `scripts/laya_visual.py::VisualWorker`; `laya_actions.py`; `laya_board.py` | Separate roster/identity/role/tooltip recognition using validated original pixels; region occlusion |
| Numeric/model scheduling | `bin/manual_inference.rs` sustained schedule at 869-887; `crates/ingest/src/laya/client.rs:418-435`; `scripts/laya-server.py` | Preserve paired numeric path; add only independently budgeted requests needed by new lanes |
| Admission/transport | `crates/ingest/src/partial.rs`; `runtime.rs`; `laya/partial.rs`, `assembly.rs`, `scene.rs`, `questions.rs`, `geometry.rs` | Per-lane qualification/leases where necessary; occupancy and verified role/hero transport without full-state dependency |
| Window/popup capture | `crates/ingest/src/windows.rs:310-369`; `scripts/laya_capture.py`; `manual_inference.rs` | Narrow selected-client popup validation, real visible popup capture, explicit covered-region masks |
| Native history | `bin/live.rs`; `crates/opponent-model/` | Preserve local observed history and table/occupant boundaries; never substitute local counts for imported rates |
| Recording/evidence | `crates/ingest/src/recorder.rs`; `laya_visual.py`; dashboard private journals; server evidence routes | Immutable selected originals/crops, event links, bounded storage and completeness counters |
| Measurement | `.local/laya/train/measure_observer.py` | Exact-source lane timing, ownership, render receipts, screenshot audits, compact bounded collection |

Keep the existing HTML/CSS/JavaScript and Rust/Python stack. Do not migrate frameworks, retrain the whole vision model, or add unrelated advisory/gameplay features. Prefer extending current types and tests; add a small OCR/tooltip adapter only where genuinely needed.

# Part 1: Recognition, Evidence, And Table-First UI

Dependency order: intake -> typed contracts -> immutable evidence handoff/archive plus popup/source proof -> occupancy/identity and independent role recognition -> atomic tooltip import -> frontend projection/layout -> regressions and exact-source smoke verification. Implement Section 6's capture-time preservation before running new asynchronous recognizers, even though its event semantics are described after the recognition sections.

## 1. Revalidate Runtime And Collect Genuine Inputs

1. Read `git status` and relevant diffs; identify existing changes that must survive. Resolve only direct conflicts with the user.
2. Inspect port 18090, full helper executable paths/command lines, process-instance/start witnesses where available, service identity, active receipts, and selected-window metadata. Never reuse this plan's sample runtime identifiers as launch constants or kill processes by name alone. PID/HWND alone are not durable identity across restarts. Do not create an alternate-port duplicate.
3. Read `.local/practice-table.json`. Its inspected selector is `CoinPoker.exe` with OS title regex `^CoinPoker$`; its filename does not restrict the table to practice money. The title drawn inside the client is not necessarily its OS title.
4. For implementation intake, recover/restart only verified owned helpers if needed, then separately verify advancing capture receipts/heartbeats, completed inference, source-current admission, API projection, and actual UI rendering. A failed recovery is a technical blocker, not a passed observer run.
5. Ask the user to open occupied-player profiles manually. Preserve genuine examples, including open/closed panels and an A-to-B hover change where feasible. Determine whether each panel is in-table or a separate owned popup, which regions it covers, and which owner/labels/scope are actually visible. Do not choose fixed tooltip geometry from an imagined layout.
6. Collect observer, occupied/empty, truncated/ambiguous identity, and occlusion examples where available. Label missing examples honestly; use finite synthetic fixtures for logic, not as successful live coverage.

Normal sustained launch, only after canonical-port and ownership checks:

```powershell
$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
pwsh -NoProfile -File "scripts/start-vlm.ps1" -EnableInference -AutomaticInference -ContinuousObservation -PracticeConfig ".local/practice-table.json" -AnswersLog ".local/laya/train/quiet-monitor-$runId.answers.jsonl"
```

## 2. Define Independent, Source-Bound Contracts

Reuse existing original capture tickets and provenance rather than introducing guessed associations. Add closed typed projections for table context/roster, role/hero evidence, imported profile-stat snapshots, and observed events. The frontend is not the identity authority.

Every recognition lane needs its own status, original capture reference, expiry, qualification result, and recognizer/method/artifact version. Carry service instance, recording session, dashboard feed session, native source identity, public source ID, source/table epochs, capture sequence/generation, original UTC and monotonic clocks, dimensions, original PNG SHA-256, and relevant crop bounds/hash. Preserve a recorded crosswalk where producer IDs differ. Preserve the current numeric observation's maximum five-second lease and capture heartbeat's 2.5-second bound; new lanes have explicit independent validity rules, not permission to extend old numeric timestamps.

The public source ID is currently a truncated SHA-256 of `[feed_session_id, PID, integer_HWND, exe]`. It is not a player ID or necessarily the native recorder/history table ID. Never join those namespaces by apparent equality or nearby timestamps.

Keep independent numeric, board, badge/wager, roster, role, and tooltip results separate. A materialized table view can show separately timed fields, but must expose their source receipts and indicate asynchronous/last-seen values. Do not serialize old fields under a newer capture ticket or describe a mixed-age view as one simultaneous snapshot. Preserve legacy raw partial packets for diagnostics/replay; do not promote a context packet into a complete gameplay state or advice-ready input.

Use per-lane consensus and leases if additional model jobs enter native partial admission. Preserve adjacent numeric pairs; a scene/role result must neither replace a numeric seed nor refresh unrelated field timestamps. Prefer a lightweight independent CPU roster/text lane on the existing original-frame path, with narrow canonical role/model requests only when required. Benchmark the text-recognition adapter on actual intake crops before selecting it; unsupported glyphs/owners stay unknown.

Separate byte-level compute caching from observation identity. Two genuinely newer captures may contain identical PNG bytes; reusing computed recognition is permissible only with a validated new receipt. Replaying the same receipt is not a second observation and polling never renews freshness. Do not inherit whole-image hash dedup as a blanket reason to suppress new occupancy/identity confirmation.

## 3. Make Client Popups A Regional Occlusion Case

Extend visible-desktop source validation narrowly, not by disabling obscuration checks. Validate selected process/executable, popup ownership/parent relationship, source/table association, geometry, and actual visible content. Same executable alone is insufficient, especially with multiple tables. Revalidate the relationship as windows/panels change. Reject unrelated, ambiguous, or intervening overlapping windows.

For an in-table overlay, detect its real panel bounds in the original table PNG. For a separate verified popup, capture its actual visible pixels and retain the selected-table receipt plus popup capture/relative bounds; do not pretend a selected-HWND WGC image contains a separate window. Record non-atomic table/popup captures separately and reject ambiguous owner joins.

Carry explicit region-occlusion metadata into recognition and admission. An unchanged covered crop hash is not proof that the underlying field remains visible. Covered seats, board slots, pot, identities, and controls become current unknown/occluded as appropriate; their same-context last-seen data may remain dimmed. Do not read through the popup, invent vacancy, clear a board as gameplay, reset occupant epochs, or restart source history because a panel appeared.

Reuse `bind_source_frame`, `retain_source_current_fields`, and regional digest witnesses, but require visibility at both the original capture and current admission witness. Design scoped readability explicitly: do not reinterpret a global `ev_readable=covered/unreadable` answer as a readable full frame. Only separately proven uncovered regions may remain eligible, under their original leases.

Avoid diagnostic overlays on top of the client during verification.

## 4. Produce Occupancy, Identity Continuity, And Role

Keep six one-based physical seats: 1 top, 2 upper right, 3 lower right, 4 bottom, 5 lower left, 6 upper left. Never renumber after folding, leaving, or rejoining.

Occupancy is `occupied | empty | unknown`, separate from participation/status and identity. Use positive seat/presence or explicit vacant-seat evidence. Folded, sitting-out, and all-in occupants remain occupied. No cards, unreadable/zero stacks, missing wagers, and unknown names do not establish vacancy.

Maintain one authoritative backend roster keyed by verified table context and physical seat, with an occupant epoch and qualified identity. Extend the existing observer/context store rather than creating frontend-only identity guesses. Publish unknown identity without calling the seat empty. Truncated, colliding, inconsistent, or unreadable names do not establish a unique owner.

Advance occupant continuity exactly once on confirmed replacement or confirmed departure/reoccupation. Direct identity replacement without an empty frame must also be detected. Transient unknowns and occlusion neither prove replacement nor increment epochs. On confirmed vacancy/replacement, clear that seat's current stack/wager/action attachments and selected stats; fence retained stacks by occupant epoch as well as source scope. On identity uncertainty, detach current stat association while preserving the previously confirmed player's historical cache.

Recognize actual table-context changes inside a reused OS window using qualified client/table evidence. Partition histories and retire old associations on confirmed table change. Do not treat each frame generation, popup, resized crop, or role change as a new table. Geometry changes invalidate old crop work without fabricating a new occupant.

Implement role evidence independently of successful pot/board recognition:

| Role | Required meaning |
|---|---|
| `observing` | Positive current client evidence that the user is not seated; no fabricated hero |
| `seated_waiting` | Confirmed self-player/physical-seat association plus reliable current evidence of waiting/not own turn |
| `your_turn` | Confirmed self-player association plus current client-offered own-action controls |
| `uncertain` | Missing, contradictory, stale, or occluded evidence prevents a reliable current role |

Use self-player indicators and, where necessary, the user's actual display name as an identifying input. Ask only if that fact is genuinely missing. Match visible own cards and offered controls to the confirmed self-player; keep the same seat association across ordinary missing-card periods. Bottom geometry, stack value, mockup outline, and another player's face-up showdown cards cannot establish hero. Validate seats 1-6; reject model seat 7-9 outputs rather than clamping them.

Preserve the Monitor session and collected history across observing/seated/own-turn changes at the same actual table. Do not call `begin_stream` or restart helpers for a role transition. Own cards, positions, dealer/acting markers, and controls remain unknown unless independently supported.

## 5. Import Atomic Client-Displayed Profile Stats

Create a typed imported-stat store separate from local opponent history. Each snapshot must carry:

```text
source = client_profile_tooltip
verified source/table scope and source-ID crosswalk
physical seat, confirmed player identity, occupant epoch
tooltip observation/owner revision
original labels and literal values
nullable parsed VPIP, PFR, 3-BET, C-BET percentages
sample size and filter/scope when visible, otherwise unknown
original capture IDs/clocks/dimensions/PNG hashes/crop bounds and hashes
recognition status, confidence/reasons, and evidence references
```

Recognize and bind owner and values atomically from the same panel evidence. Panel proximity or a guessed hover seat is not enough. Validate owner/table/occupant/tooltip revision again when delayed recognition completes. Reject delayed A results after the target changes to B, including same-seat replacement, source changes, partial mixed panels, duplicated identities, or disappearing owner evidence.

Preserve decimal percentages and accepted `0%`; distinguish missing, literal dash, unreadable, invalid/out-of-range, and partial fields. Validate labels alongside values; reject duplicate/misaligned labels and ambiguous numeric locale rather than parsing profile percentages with the chip-amount parser. A securely owner-bound panel may store known fields with unknown missing metrics, but must never fill them from old or locally calculated values. Replace all four metric slots atomically, including explicit unknown slots for missing fields. A panel with uncertain ownership cannot attach stats. Preserve the client's C-BET label/scope without inventing its definition. Do not interpret an avatar number as sample size without actual evidence.

When the panel closes, keep values only as last observed client-displayed stats for that confirmed player, with original observation time. Repeated API/UI polls must not refresh that time. Genuine newer open-panel observations carry their own receipts. On departure/replacement/identity uncertainty, detach the current-seat association; never transfer cache entries to the next occupant or across a table-context boundary.

In selected-player details, display literal percentages, known sample/filter scope or explicitly unknown scope, last observation age, and a link to provenance. Label the source as client-displayed, not locally calculated or verified population truth. Local VPIP/PFR ratios, three-bet counts, and incomplete betting history remain a different product and cannot populate this store.

## 6. Log Truthful Events And Preserve Their Pixels

Separate raw recognition/diagnostics, source-bound observed events/provisional sightings, and rendered table state.

Log qualified occupancy/replacement, role/hero association, board changes, independently supported hand boundaries, explicit badge occurrences, separate pot/wager changes, tooltip appearance/owner/stat changes, occlusion, gaps, rejections, and source lifecycle events. Include original capture receipts, lane status, table/occupant association, and stable event IDs. Deduplicate repeated sightings of the same occurrence, not all occurrences of the same action word.

Do not infer actions from stacks or disappearing chips. Do not turn capture/completion order into betting order. Street/hand association must be supported at the original event capture; delayed board recognition cannot retroactively manufacture certainty. Keep unknown street, provisional occurrence, simultaneous/ambiguous ordering, and incomplete histories explicit. Board absence or popup coverage alone is not a hand boundary. A historical confirmed badge event may survive badge disappearance without remaining a current live badge.

Pin original bytes before a rolling mailbox slot can be overwritten, including while downstream recognition is pending. An immutable-byte handoff or bounded recognition lease must prevent the worker from processing different pixels under an old receipt. For selected events retain exact native originals, relevant seat/tooltip crops, and useful preceding/following context where available. Reuse immutable archived originals when possible; otherwise preserve mailbox bytes at ingestion and promote selected frames to immutable event evidence. Never copy a mailbox path later and assume it still contains the establishing capture.

The latest-only visual worker cannot guarantee seeing every brief popup or player transition. Use a bounded capture-time candidate-pin path for panel/identity-region changes where required, and expose queue drops or missed candidates. Do not describe the two-slot mailbox or accepted sightings as complete event coverage. Commit immutable image/manifest references before labeling an event's replay evidence complete; archive failures remain explicit.

Use content-hash dedup for stored bytes while preserving all distinct capture receipts and event associations. Crop evidence records derivation from the original, bounds, dimensions, and crop hash. Evidence lookup must be same-origin, receipt/ID based, private, and path-constrained; no arbitrary filesystem paths or client-supplied URLs. Escape untrusted player/tooltip labels through text nodes.

Keep existing archival limits. Default additional event-evidence budget: 256 MiB of new image bytes, 512 distinct selected source-frame receipts, and a 16 MiB event/manifest budget per evidence run; reuse of already archived bytes must be accounted for separately. Use a small bounded in-memory context ring, not an unbounded second recorder. If a limit prevents a screenshot/log record, mark its evidence incomplete with a reason and counts. Stop only additional evidence accumulation at its budget; do not stop otherwise valid observation. Never present a missing or changed PNG as complete replay evidence.

## 7. Render A Quiet, Persistent Table

Use the established dark visual language with a restrained SVG table outline. Create six physical seat cards and five board slots once; patch only changed text, classes, and provenance/freshness attributes. Keep six unknown slots visible even when there is no current reading, alongside a compact source/capture status. Replace existing tests that equate clearing readings with removing seat DOM nodes.

Seat cards show recognized identity or unknown, remaining stack, visible wager, current explicit badge, supported markers, and one defined freshness/uncertainty indicator. Center the upper Pot and board slots. Do not hardcode amounts, currency, actions, occupancy, or hero at seat 4. Preserve literal supported numeric text; unknown is a dash, never zero. A real zero remains zero. Never derive a wager from a stack or select the lower pot-chip total as the upper Pot.

Keep connection, capture state, observation role, and occupancy compact. Use counts such as `Observing | 6/6 seats occupied` or `Observing | 5/6 seats occupied` only when all six current occupancy states support that count; otherwise say occupancy uncertain. Current, provisional, unknown/occluded, and dimmed last-seen states have distinct labels, not unexplained color meanings. Per-field details explain differing source times.

Preserve the explicit Stop capture control and test it outside the measured window. Opening/refreshing the Monitor or selecting details must never silently start, stop, or restart capture.

Preserve coarse age labels; no ticking millisecond counters. Show expired same-context values only as dimmed last seen with the original time. Source loss/context retirement clears current associations rather than reusing old-source amounts as live data. Hide verbose reasons, confidence, original clocks/hashes, timing traces, and records behind Diagnostics or explicit details.

Selecting a seat opens its player details; keyboard focus/Escape and close work without client interaction. Preserve selection/focus across ordinary polling; clear or relabel details when the occupant changes. No automatic activity-log scrolling, badge flicker, layout jumps, or repeated live-region announcements for unchanged readings.

Use responsive CSS: spatial six-seat diagram beside the client at desktop/compact-window widths; at narrow widths place top seat, upper pair, center, lower pair, and bottom seat in stable labeled grid areas. Maintain physical mappings and readable values without horizontal page scrolling. Browser-check approximately 940x740, 600x800, and 360x800; test actual layout/focus, not just the existing DOM harness.

## 8. Part 1 Verification Gate

Extend existing Python/dashboard/Node-harness and Rust suites before the measured window. Include these finite cases:

| Area | Required cases |
|---|---|
| Occupancy | Six occupied; five plus confirmed empty; uncertain; fold/sit-out/all-in; missing cards, stack and wager; empty clears stale attachments |
| Identity/context | Direct same-seat replacement, departure/rejoin, truncated/duplicate identities, uncertainty detachment, reused HWND with new table, resize, old-source completion |
| Role | Hero at all six physical seats; observing, seated-waiting, own-turn, uncertain; missing own cards; opponent showdown; absent pot/board; history preserved across roles |
| Tooltip | Genuine owner-bound example; decimals/0%/dash/missing fields; partial panel; A-to-B delayed result; replacement; closure retains original time; local-stat separation |
| Occlusion | In-table and owned-popup fixtures; unrelated/same-process-wrong-table overlap rejected; no false vacancy, board clearing, epoch bump or history restart |
| Freshness | Independent lane expiry; stale results; repeated same receipt; identical pixels on distinct actual captures; no timestamp renewal from polling or field aggregation |
| UI | Six persistent node identities; null versus zero; last-seen labeling; no invented hero/currency; stable selected details/focus; responsive layout and quiet announcements |
| Evidence | Event-original/crop hash round trip; pending-frame pinning and mailbox overwrite; capture identity preserved under byte dedup; path validation; caps/completeness |
| Timing | Attempt starts versus completions versus accepted fields; strict 10,000 ms boundary; leading/trailing censored gaps; sparse lane jobs cannot break numeric consensus |

Relevant existing tests include `scripts/tests/test_laya_dashboard.py`, `test_laya_dashboard_stage2.py`, `test_companion_ui.py`, `test_laya_visual.py`, `test_laya_visual_ui.py`, `test_laya_actions.py`, `test_laya_capture.py`, `test_laya_server.py`, `test_manual_inference.py`, `test_laya_readout_log.py`, and ingest `live_runtime`, `partial_observation`, `seat_scene`, and `saved_capture_schedule` tests. Upgrade the shared DOM harness only as needed for persistent nodes/details. Add browser-level checks for CSS and real keyboard focus.

If native pass variants are introduced, update the `ObservationPass` definition/dispatch and closed server request validators as well as the scheduler; do not append new questions to the existing numeric batteries. Test fair GPU-lock scheduling and unchanged numeric floors/crops/row ordering.

Replay actual immutable source PNGs through recognition, API projection, event evidence, and rendering. Keep tuning examples distinct from held-out qualification examples; same-hand bitmap reuse is not independent validation. The native board threshold of 1.0 represents failed qualification and must not be lowered just to populate the diagram. Preserve independent CPU-board provisional/qualification labeling.

Run, outside Part 2:

```powershell
& ".local/laya-runtime/env/python.exe" -B -m unittest discover -s scripts/tests
cargo test --workspace --offline --locked
cargo clippy --workspace --all-targets --offline --locked -- -D warnings
cargo fmt --all -- --check
```

Rebuild the actual helper target(s) used by the owned launcher, verify binary provenance, and perform a short integration smoke check. Do not stop at a green static test suite if actual tooltips, source handling, or rendering do not work. Start Part 2 only after the implemented lanes, genuine tooltip intake, exact-source replay, regressions, and smoke check are complete. If genuine tooltip recognition cannot be validated, report that blocker rather than silently omit it. Live seated testing is explicitly not a prerequisite.

# Part 2: Ten-Minute Observer-Only Break Test

## 1. Extend The Collector Before The Window

Extend `.local/laya/train/measure_observer.py` without changing its observer-only behavior. Maintain distinct capture-session, dashboard-session, service, and table/source identifiers; stop the segment on an incompatible boundary. Instrument every new lane's requested/attempted/completed/accepted/rejected work with exact original receipts. Answers-log signature/time-bracket correlation is not capture identity; add explicit capture IDs for new records rather than using that heuristic as proof.

Collect compact validated API projections and cursor/change-based event records instead of repeating full growing history each second. Keep response/file/row/time limits explicit, preserve source timestamps and collected-boundary metadata, detect dropped cursors/partial tails/caps, and report completeness. Do not fetch later state and use it to fill the earlier measured window. Do not blindly raise caps to hide data loss.

Measure actual rendered state separately from API admission. Add/read bounded per-field DOM render receipts containing the original field capture reference and publication clock, plus occasional UI screenshots/readbacks tied to those receipts. Clock origins must be explicit; browser/native monotonic clocks are not interchangeable. API first visibility remains poll-bounded; do not call it exact UI publication time. Instrumentation must not renew field observation time or spam the primary UI.

Preflight the collector's finite deadline/provenance/budget tests before starting the live run. Keep lightweight recording only during the window, with offline analysis afterwards.

## 2. Run One Continuous Observer Segment

1. Recheck selected source and helper ownership, then verify model readiness, advancing original frame receipts/heartbeats, inference completions, admitted fields, API output, and actual displayed values independently.
2. Record a unique run manifest: code/helper/recognizer identities, source/ID crosswalk, starting clocks, recording/event budgets, collector limits, and observer-only context. Do not claim the old evidence session is the new run.
3. Observe for approximately 600 seconds continuously across multiple hands where possible. The user stays unseated and manually hovers occupied profiles, ideally including distinct players and an A-to-B change.
4. Collect exact-source examples and lightweight render receipts. Compare raw recognition, native/CPU output, API state, and actual UI with the original PNGs after collection. Record only streets/actions that actually appeared.
5. Do not run heavyweight regressions, training, or competing model benchmarks during the measured window. The ordinary production recognizers may run; do not introduce test contention and then attribute it to normal latency.
6. At the measurement limit stop only the bounded collector. Archival or screenshot budget exhaustion is a separate evidence condition, not an instruction to stop valid capture.

If capture/source failure or a genuine session interruption occurs, preserve that failed segment and its originals, diagnose it, and verify a fresh controlled segment. Never concatenate disconnected segments into a claimed uninterrupted ten-minute success. Gaps within an active segment remain reported gaps, not deleted samples.

Collector invocation after the extension is verified; resolve these variables from the active validated receipt and unique run manifest, not old evidence or the dashboard feed UUID:

```powershell
& ".local/laya-runtime/env/python.exe" -B ".local/laya/train/measure_observer.py" collect --out $runOutput --session $verifiedCaptureSessionId --answers $currentAnswersLog --manifest $currentManifest --seconds 600 --poll-ms 1000
```

## 3. Required Report

Provide per physical seat and recognition family:

- Requested/attempt-start, original-source attempted, and completed intervals; strict gaps greater than 10,000 ms and missed deadlines. Exactly 10,000 ms is not a strict overrun. Keep censored start/end gaps separate.
- Accepted-reading intervals separately from attempt intervals; source-to-publication delay, stale/unknown/occluded duration, and renderer timing with clock/measurement limits.
- Occupancy/identity results, confirmation/replacement counts, and rejected or uncertain associations.
- Tooltip appearances, confirmed owners, correctly bound imports, delayed/ambiguous rejections, missing metrics/scope, and original observation timestamps.
- Capture/source interruptions, dropped work, evidence caps/completeness, and exact original/crop hash audit outcomes.

Audit no fabricated hero while observing; no folded player classified empty; no stats/old stacks transferred to replacements; no stale timestamp renewal; no actions inferred from stack/chip movements; no fabricated complete betting order; correct upper-pot/stack/wager separation; and board clearing/street/hand association only where supported. Confirm the UI stays quiet and usable during updates, panel occlusion, expiry, and recognition gaps.

Classify inspected examples as correct, incorrect, unknown, or rejected with exact source references. Unseen streets/actions, replacements, and hover cases are NOT OBSERVED, not passed. Keep recognition accuracy, source integrity, timing, UI usability, and evidence completeness as separate results. A completed collector is not automatically a successful recognition or ten-second-deadline test. Explicitly report every deadline miss; acceptance cannot be claimed when it fails.

## 4. Finish And Handoff

State what is running now, including current source/capture validity and visible Monitor output. Report exact observer coverage and interruptions, per-seat timing, source-bound examples, tooltip ownership/import evidence, event screenshot coverage, tests/builds completed, and remaining technical blockers. Include paths to the private run manifest, timing/coverage report, event receipts, and witness originals.

End with `Seated-player testing: UNTESTED` unless a separate genuine seated test occurred. Preserve observer completion even though live seated behavior remains untested. Leave the Monitor active and visible when its selected source is valid; if it is not valid, report the actual failed/unknown state rather than manufacture healthy running status.
