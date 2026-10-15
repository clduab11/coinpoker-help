# Bounded Diagnostics and Sustained Observation

This is a bounded evidence-collection session, **not a recognition-accuracy
acceptance test**. R17 remains strict, Gate F historical FAIL,
and labels DRAFT / human review PENDING. The current companion has no poker input
controls.

Current local integration (2026-10-13) removes the manual seating assertion and
adds **Stop capture** plus an experimental full-state analysis path. Only a genuine
current full native observation and matching legal decision can use that path;
partials cannot. `quality_approved:false`, failed model grade and human-review
status remain unchanged. Historical tests below are not new integration or live
acceptance results; the pinned model's untrained hero/control limitations remain.

## Current Work Authorization

At **2026-10-12T19:08:04Z**, the operator issued standing GO for repeated
implementation, installed-it1 use, owned-helper replacements, and controlled live
verification cycles until supported current table data appears in Monitor while
observing. See [the next-conversation prompt](../HANDOFF.md) for the exact request,
scope, current blocker, execution loop, and definition of done.

Historical "separately authorized attempt" / "no further run authorized" wording
below is not a requirement to ask again for each agent-directed run of that task.
Existing source sessions still retire permanently; retries use fresh sessions and
evidence. The two-baseline/two-changed qualifier remains for activity/history only;
the former 30-second startup timeout is removed under this GO. Independently admitted
partial readouts do not require activity qualification. Data integrity and
honest verification remain separate requirements.

## Explicit Automatic Startup (Observer or Seated)

On 2026-10-12 the operator additionally authorized bounded automatic startup,
whether observing or seated. This changes the source-confirmation policy only for
this explicit mode; source selection does not establish hero identity or approve
general recognition accuracy. Manual confirmation also no longer requires seating.

After revalidating/stopping only the owned helper and verifying port 18090 is free:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -PracticeConfig .local/practice-table.json
```

Both flags are required. The existing private source profile is reused unchanged.
Current `user_scope` is `six-max-table`; legacy `practice-six-max` metadata loads
with the same exact selector, without rewriting the file or widening matches.
The existing `.local/practice-table.json` path and `-PracticeConfig` flag remain.
Its metadata match is a candidate, not proof of a table or of practice/cash status.
The removed `--auto-attach` / `-LiveConfig` supervisor is still not used.

1. Model loading starts under the separate model approval. No source is captured
   while waiting for readiness. Browser refresh starts/restarts nothing.
2. Metadata-only discovery waits at most 600 seconds for exactly one profile match.
   Absent candidates show Searching for table. Ambiguous matches or discovery errors
   block the one attempt; no automatic source replacement or retry session.
3. One bounded source session records and infers that exact candidate, running p0 plus
   one trained numeric/card field from startup. Independently admitted partial fields
   can display while activity is verifying. The yellow Windows capture border is not
   proof of recognition. Source health and field freshness remain independent checks.
4. Activity/history qualification requires existing qualified table/layout/readability evidence
   plus two stable eligible source samples followed by two stable samples of changed
   board/Pot/stack-region pixels. Model-answer jitter, outside-region changes,
   geometry-only changes and stale/ambiguous samples do not qualify. This establishes
   visible table-content change, not a betting action, position or hero identity.
   This is an activity/history qualifier, not a readout gate or proof of continuing betting activity. All
   subsequent displayed fields still require their own current evidence and expiry.
5. All frames/time count against the same 600-second or 1,200-saved-frame maximum.
   Activity qualification/resizing never restarts either budget. No 30-second
   activity timeout remains. Partial fields retain fitted floors, exact source-region
   currentness, independent consensus and original five-second expiry. Full/history
   publication cannot use a partial readout as activity or a seated assertion.
6. Monitor's **Stop capture**, Ctrl+C in the service terminal, or `laya_capture.py stop --session <SESSION_ID>`,
   stops the owned session. Source replacement, errors and the first limit stop
   permanently; later activity/browser refresh does not rearm it.

The renderer can show independently admitted supported Pot, stack and board fields.
Hand-relative positions, wagers and betting actions remain unknown when unsupported
or contextless. p6/p7 remain disabled. Observing does not require sitting down, but
automatic startup cannot turn unestablished model capabilities into reliable ones.
Automatic-mode test/runtime receipts: `.local/laya/train/automatic-inference-20261012/`.

### Sustained Same-Source Observation

The bounded command above is unchanged. For separately approved sustained
observation, first verify the canonical listener belongs to this checkout, stop
only that owned helper, rebuild `target/debug/coinpoker.exe`, and verify the saved
private profile still selects exactly the intended visible table. Reconfirm the
source if it no longer matches; never widen a selector or use another port.

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation -PracticeConfig .local/practice-table.json
```

The additional flag authorizes `automatic-sustained`, not a longer bounded run.
Its private version-2 approval uses `AUTHORIZE SUSTAINED SAME-SOURCE OBSERVATION`
and binds one fresh PID/HWND/title/executable to the current service instance.
Metadata waiting is still finite. Once selected, the observation has no diagnostic
duration/frame deadline; evidence PNGs still cap at 600s/1200 saved frames/1 GiB.
Counters freeze on evidence closure and no replacement evidence directory is created.
Live unsaved acquisitions retain their original UTC/monotonic stamps and must pass
the same frame, source, consensus, model-floor and five-second freshness checks.

Native live results use bounded pipes, not tailing a perpetually growing JSONL.
Private diagnostic logs and history are capped separately. Old bounded/manual
receipts, save-before-infer requirements, and terminal budget stops stay unchanged.
Source loss/replacement/ambiguity, occlusion/minimization, owner/model/I/O failure,
Ctrl+C or a named-session STOP remains terminal and clears readings before teardown.
Browser polling, restored receipts and later visibility do not rearm a stopped run.
Experimental p6/p7 diagnostics are refused in sustained mode. Its partial readouts
cannot supply a full actionable state or enable experimental decisions.

Monitor shows observation/capture ages and evidence status separately. Unknown
role or activity-verifying status does not suppress independently admitted supported
numbers. Rotating seat lanes can legitimately leave other stacks unknown or label
their last readings stale; neither whole-table freshness nor recognition accuracy
is implied. Board requires consecutive distinct-source consensus at its existing
floor. Table-countdown recognition and automatic pause/resume are not included.

Verify the same source continues acquiring beyond ten minutes after evidence closure,
with bounded disk usage and no stale field shown current. The 45-minute fake-clock
supervisor and mocked native/UI tests exercise lifetime/transport, not live GPU or
real-table accuracy. An approved real-window trial is still required before claiming
end-to-end live acceptance. Refreshing Monitor cannot substitute for this launch.

Implementation verification on 2026-10-13: 432 offline Python/UI tests passed,
including the 45-minute fake-clock owner/transport checks and 82 mock UI tests.
The selected Rust workspace run passed 545 tests; focused sustained native tests
passed separately, covering 1210 acquisitions, cap closure and positive Board
consensus. The workspace command excluded legacy artifact-producing recorder and
manual-inference groups; ignored live-HWND and saved-private-capture tests stayed
ignored. `cargo build -p coinpoker`, JavaScript syntax, launcher parsing, and
whitespace checks passed. A passive browser check verified the terminal reason
and no horizontal overflow at 400px. No model/real-window inference or new capture
was performed. The existing canonical listener was confirmed to belong to this
checkout and still uses the older bounded launch; it was not stopped/restarted.

Live activation on 2026-10-13 replaced that owned listener after confirming the
new visible table against the unchanged private source profile. The first run
exposed Windows wall/monotonic tick interpolation falsely tripping the sustained
elapsed watermark; a failing reproducer preceded the fix, and 433 offline tests
passed afterward. Sustained public elapsed now retains the owner sample while
all heartbeat/field expiry and anti-replay checks remain enforced.

The explicitly restarted live observer stayed active beyond 12 minutes with zero
capture failures: 973 acquisitions versus 812 saved frames, frozen evidence bytes
218910384, and evidence `duration-limit` at 600000ms while observation continued.
The sampled frame matched the confirmed table. This verifies source capture and
lifetime separation, not numeric recognition: current Pot, stacks, and board were
unavailable with `unsupported-layout` / `screen-not-accepted`. No confidence floor
was lowered, role assumed, or rejected value promoted. Suggestions remained OFF.

The same live session subsequently passed 31 minutes and 2543 acquisitions with
the same 812 saved frames, unchanged evidence bytes, fresh capture and zero
capture failures. The fresh-start browser also needed a first-feed-claim fix:
the SDK boot feed must not be pinned as the native owner's identity before live
health exists. That correction passed 85 mock UI/static checks; later feed/service
replacement, heartbeat expiry, evidence freezing and field TTLs stay fail closed.
The final refreshed Monitor showed `Observing same table` and `Evidence recording
ended; observation continues`. No admitted numeric or board reading was claimed.

### Recognition Audit (2026-10-13)

The retained sustained session ultimately contains 1916 complete p0 diagnostics,
not only the most recent 200 in its bounded perception summary. None qualified
the screen/layout: 1836 first failed screen confidence and 80 confidently selected
a non-table class. Table-layout evidence independently failed in every result;
readability passed in all 1916. No regional amount or board pass ran through live
admission. The session later terminated on an obscured-source capture failure;
its evidence and terminal receipts were preserved.

The checkpoint, calibration files, canonical prompts/option order, RGB conversion,
and shared crop/glyph preprocessing were checked against the installed it1 contract.
The observed rendering has a near-black surface, unlike the green-felt originals.
Saved-frame diagnostic probes at both trained sizes and with the inferred titlebar
removed still reject it. The green original passes p0 and the real lobby negative
remains rejected. Desktop screenshots agree with the saved geometry/background,
but this does not establish what a physical display's hardware overlay shows.
Reselecting the client theme did not visibly restore the trained appearance.

On two recorded originals, offline amount probes matched the visible upper Pot
and physical-seat stacks. This is a limited agent pixel comparison, not human
approval, distinct-live-capture consensus, or a Monitor reading. Board probes across
real 3/4/5/0 transitions include wrong ranks/suits and guessed cards in empty slots.
None meets the unchanged board floor of 1.0, including genuine empty boards.
Neither lowering floors nor substituting source confirmation for p0 is supported.

Private replay outputs and an 18-original, versioned review pack live under
`.local/laya/recognition-20261013-v1/`. The pack preserves source hashes and original
timestamps, includes overlays/enlarged crops, and leaves every label explicitly
`PENDING_HUMAN_LABEL_REVIEW`. Sampling heuristics are not labels. It reuses existing
evidence; a single session is insufficient for independent calibration and held-out
approval. Existing it1 artifacts and historical results remain unchanged. Human
label verification is required before training/calibration; GPU training and broader
collection remain separate approvals. No candidate checkpoint was produced.

Two downstream defects are also corrected without changing admission floors:
sustained scheduling gives Board its two consecutive distinct-capture attempts
instead of indefinitely preempting the second attempt to protect Pot, and a changed
field can invalidate only that field while unchanged publication fields retain
their original lease. Expiring an older publication must not erase a separately
fresh consensus candidate. Pot may expire during Board work; six rotating stacks
are not promised simultaneously fresh. These changes cannot cure p0/model errors.

The rebuilt owned helper was restarted only after reconfirming the same source.
The browser attached successfully through model loading. A saved post-restart
check reached 284 captures over 175 seconds with zero capture failures, while
`screen-not-accepted`, `partial_observation: null`, and unsupported-layout reasons
persisted for Pot, all stacks, and board/count. The live outcome is explicitly
**blocked**, not accepted. Private `live-check.json` and `live-ui.json` are in the
audit directory. Regression verification passed 447 Python/UI tests, 344 selected
Rust tests, the offline build, pinned-artifact verification, and syntax/format
checks; one separately opt-in HWND smoke test was not run. Synthetic tests do not
establish recognition accuracy on this table.

### Static Visible Source Capture

The standing-GO startup readout implementation reached real numeric passes, but the
first two fresh trials stopped at 7 and 2 saved frames with `capture-failed`. The
second preserved the backend error: `timed out waiting for a fresh window frame`.
Original WGC freshness checks rejected pooled compositor images rather than
restamping them. A read-only metadata/Z-order check confirmed one unobscured source.

Automatic mode now explicitly uses a new synchronous desktop-pixel copy of that
selected visible rectangle. This is live OS pixel capture, not PNG replay, cached
WGC data or a request for the poker client to repaint. The client is never focused,
resized or sent input. Before/after identity, visibility, rectangle and obstruction
checks fail closed. Native stderr records the method; saved PNG hashes and original
capture-call UTC/monotonic clocks remain the model and field provenance. No floor,
source lease, model weight, untrained pass or run budget is relaxed. This mode needs
the table fully visible; automatic source replacement remains forbidden. Manual
capture retains WGC. Live functional success still requires actual field backchecks.

### First Runtime Finding and Correction

The first authorized automatic attempt ran 2026-10-12T05:33:19.385526Z through
05:33:30.330769Z. It saved 9 hash-verified frames but submitted **zero** captured-frame
model jobs. It was fail-closed, not a successful live-recognition test. Its original
receipts remain unchanged, including the incomplete/forced-stop flag and a stop
reason incorrectly reported as operator-stop; the API trace identifies the actual
receipt-validation failure. There were zero draft opportunities and a deficit of 20.

Offline fixes use Windows shared-delete read handles plus ReplaceFileW to publish
receipts atomically under concurrent readers, pair automatic/source status from one
authoritative receipt, and report receipt retirement as feed failure rather than
operator action. The corrected contention test completed 1,470 reads with no errors.

The actual capture intervals were 780-1,398 ms; the three-capture stability filter
submitted none of the 9 saved frames. Automatic mode now uses 2 stable captures with
the unchanged 300 ms minimum and pixel thresholds, and requests bounded fresh samples
while verifying activity without preempting an in-flight worker. Activation restores
ordinary refresh scheduling. Manual mode, fitted floors, source/field admission,
five-second expiry and R17 are unchanged. Saved-frame replay confirms submission
can begin at frame 2; it does not predict answers or guarantee current-field admission.
The stopped session is never resumed or rearmed. Corrected real recognition remains
unverified until a separately authorized new bounded attempt.

### Authorized Second Attempt

The separately approved corrected run lasted 2026-10-12T06:46:34.237719Z through
06:47:04.907041Z. It saved **25 hash-verified frames** and executed existing it1
passes: 3 full-table, 3 board, 3 Pot and 12 seat-stack answer records. These are
21 pass-answer records, not 21 accepted observations.

Three typed diagnostic records reached DashboardState's private ledger with exact
original source times; 27 crop geometries were checked against their source PNGs.
Two completions arrived at source ages **5,426 ms** and **5,990 ms**, exceeding the
unchanged five-second deadline. A third was obsolete at 1,892 ms because the source
had changed. Stack batches alone measured 4,496.6 ms and 6,071.3 ms. Board answers
remained below the unchanged 1.0 floor. Pot/stack model candidates were not current
admitted fields. The Monitor correctly cleared readings and showed the failed
activity probe, saved count, gaps, limits and deficit.

Outcome: **real capture, model execution and typed rejection transport verified;
zero live fields admitted and usable live recognition NOT verified.** The probe
stopped with `table-activity-unconfirmed`; it did not automatically rearm. There
were 13 sampling gaps, 16 estimated missed samples, and 0/20 draft opportunities.
No stale values were promoted and no floor/expiry was relaxed. The remaining
performance/admission blocker is getting supported pass results within the original
source lease while the table changes, not loading a model or opening the dashboard.
Private audit: `.local/laya/train/automatic-inference-20261012/retry-1/audit.json`.

### Source Stability Corrections (Offline)

The later 27-frame trial executed four table-classification passes in 399-475 ms,
but admitted no fields. Saved-pixel analysis found only one identical whole-frame
pair. On both source-current failures, eleven trained readout regions were exactly
unchanged; timer/halo pixels and one stack-crop fringe blocked qualification.
Archival PNGs are not model context: the worker uses the newly captured in-memory
frame, and the installed model resets its prediction cache on each call. Original
captures/receipts are retained, not deleted or relabeled as fresh samples.

Automatic readout mode now tracks the existing twelve readout crops independently
for scheduling and still sends the full original frame to the model. Activity needs
two stable witnesses followed by two stable changed witnesses in the same region;
each must match its original source pixels exactly. A missing regional witness
cannot count or renew the five-second baseline. Source epoch/identity/geometry
boundaries reset qualification; other seats need not become motionless together.
Role and phase keep their conservative whole-frame proof. Published field pixels
are rechecked on every fresh capture; changed fields cannot silently regain values.

Qualification runs only p0; active observation rotates one trained field alongside
p0 with three source jobs per lane. A completed job may use that tick's distinct
fresh frame for the next pending job, without worker preemption. Automatic capture
waits only the remainder of its configured 500 ms period after capture/publication
work, anchored to the last acknowledged capture-call timestamp, rather than adding
500 ms to that work or anchoring to pre-capture initialization. Neither source clocks, five-second
leases, confidence floors nor the 600s/1200-frame and 30s probe bounds are extended.

Windows capture drains/closes older pool frames and checks compositor QPC timestamps
against the current capture invocation. Stale, future, duplicate or unverifiable
frames are not restamped as fresh. One in-call recreation shares the existing
1500 ms application wait budget. Live Windows behavior still requires an authorized
test; synchronous OS calls cannot be preempted by that wait budget.

Offline Rust replay increased pixel-eligible frames from 7 to 24 of 27 while preserving
every original PNG hash and source clock; its busy spy generated no predictions.
Conditional replay at the old cadence did not establish activity activation, and
is not a substitute for actual model-to-Monitor evidence. Private evidence is under
`.local/laya/train/automatic-inference-20261012/stability-investigation-20261012/`.

### Subsequent Authorized Live Checks

The source-stability build first saved one frame and retired with `recorder-failure`
before any inference. Its residual wait had been anchored before slow initial
selection, allowing a second source call inside the recorder's 500 ms interval.
The fix anchors to acknowledged capture-call time. A slow-selection regression
records all 16 synthetic frames at their original 500 ms spacing. The failed trial
is preserved under `retry-4-stability-20261012`; its session was not resumed.

The separately authorized recorder-aligned trial ran 2026-10-12T18:18:15.834670Z
through 18:18:46.331396Z. All 33 PNG hashes were verified. It executed 20 actual p0
passes (359.7-767.1 ms prediction time); 19 source-current diagnostics reached the
private feed at source ages 796-2888 ms. No obsolete/deadline discard occurred.
These were score-only core results, not accepted live fields. The required timed
same-region baseline/change sequence did not qualify, so numeric passes did not
start and Monitor still had zero admitted readings/advice. Code/test progress is
not usable live recognition. The 0/20 draft opportunity deficit remains 20.

Native exit 0, `forced_stop=true` and `receipt_complete=false` are preserved as
recorded. No source timestamp, floor, expiry or label was changed to obtain a pass.
Evidence: `.local/laya/train/automatic-inference-20261012/retry-5-clock-aligned-20261012/`
(`audit.json`, `gate-analysis.json`, native receipts and browser evidence). The
postrun gate timing estimate uses diagnostic emission UTC; it is not an exact
near-boundary timing measurement or an extra inference run.

## Launch without collection

Run these commands from the repository root on the already provisioned host:

```powershell
cargo build --offline --locked -p coinpoker
$py = '.\.local\laya-runtime\env\python.exe'
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

Open `http://127.0.0.1:18090/`. Ordinary `start-vlm.ps1` and `laya-server.py serve`
now also default to dashboard-only. They never attach, record or load a model.
An occupied port is refused, not killed or moved. Refreshing a page does not reload
the helper's Python code. Revalidate the listener's executable, full command,
creation time and owned launcher before an operator-controlled replacement. Never
kill a remembered PID or run two helpers. Do not use the legacy automatic-attachment instructions.

Use a normal desktop browser at 100% zoom, with device emulation off. Approximately
800x520 **outer** pixels is the target window, not the CSS viewport. In the measured
100%-DPI Chrome window, 800x520 outer yielded 784x425 CSS. Chrome consumed 16 pixels
in width and 95 in height. The separate regression viewports were 780x400,
640x360 and 1000x600 CSS. Reference and expanded diagnostics use one page scrollbar.

Inference is a separate runtime choice, requiring explicit operator approval.
`-EnableInference` / `--enable-inference` enables loading/warming the installed,
pinned it1 model; it does not select a source or start capture. No training,
download, new model, p6/p7 activation or threshold fitting is needed. Capture-only
never imports the model, probes model readiness or calls prediction endpoints.

## Inference-enabled preparation

Only after separate approval to load/use it1, stop the revalidated owned helper
through its terminal/tracked launcher, verify port 18090 is free, and start one
replacement in a terminal:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference
```

Do not combine this with `-DashboardOnly`, `-LiveConfig` or `-AutoAttach`. Keep the
same canonical address. Monitor separates service loading/ready/error from session
inference activity. While the model initializes, no capture is selected or started.
Ctrl+C in this service terminal stops the service. A stopped initialization cannot
publish a late ready state or start collection. GPU operations already in progress
may finish during shutdown; their results cannot enter a stopped session.

## Confirm and start

In a second terminal, list window metadata only:

```powershell
$py = '.\.local\laya-runtime\env\python.exe'
& $py scripts/laya_capture.py list
```

Select the intended table; seating is not required for source confirmation. Use the actual PID and
HWND printed by `list`, not values copied from an old receipt:

```powershell
& $py scripts/laya_capture.py start --mode capture-only --pid <PID> --hwnd <HWND> --max-seconds 600 --max-frames 1200
```

This command first displays the exact private executable/title/PID/HWND/dimensions.
It requires only the fresh `CAPTURE <PID> <HWND> <nonce>` challenge shown in that
terminal. Confirmation expires after 30 seconds and metadata is rechecked before
the child starts. No seating assertion is requested. A changed source
needs a new confirmation. It never follows a replacement window automatically.
Same-identity resize is handled separately; it is not approval of a new source.

For the integrated diagnostic, after the service has separate model authorization,
use this instead (never both capture commands):

```powershell
& $py scripts/laya_capture.py start --mode inference-enabled --pid <PID> --hwnd <HWND> --max-seconds 600 --max-frames 1200
```

The operator must first type **`USE INSTALLED IT1 FOR THIS SESSION`**. The CLI then
checks the canonical service's inference opt-in, ready state, fitted floors and
private-feed protocol. It waits at most 120 seconds for loading, with **no capture
or session budget started**; Ctrl+C cancels. Only after readiness does it display
the fresh exact-window challenge. The same 30-second confirmation deadline and
identity recheck apply; no seating assertion is required.
The service instance is rechecked before spawning; replacement requires a new
approval. Missing/failed/old dashboard service is refusal, not an automatic restart.
New manual receipts set `operator_assertion:null`. The known old seated string is
accepted only for persisted-receipt compatibility; arbitrary strings are rejected.
Source confirmation and inference consent do not establish hero seat/cards.

The terminal prints an opaque session ID, elapsed time, saved-frame count and limits.
Monitor shows the same recorder status separately from observation/model status.
Capture-only can save evidence while every recognition field is unavailable; that
is not a failure to start capture and is not live recognition.

Inference-enabled can also legitimately have no admissible results: Monitor shows
that state and per-field rejection reasons rather than filling missing values.
Partial Pot/stack/board fields remain visible independently of hero/control failures.

## Actual transport

1. The CLI creates one private, fresh, one-shot approval and owns one native child.
   Capture-only uses `--capture-only`; inference mode uses `--manual-inference`.
2. The native approved-source wrapper validates identity before/after acquisition,
   records the same original frame through `PrivateRecorder`, then returns it to
   the existing `LiveRuntime` / Laya crop/pass worker. There is no second capture loop.
3. The existing decision Pipeline receives only a fully admitted native GameState;
   partial fields are not promoted, and R17/parser/source/deadline checks remain.
   Original capture-call-start UTC/monotonic time and the recorder's exact PNG/hash
   receipt accompany the source. Existing per-field eligibility, source-region
   admission and typed partial/full observations retain the original <=5000ms expiry.
   Each native single/batch prediction request also carries the approved service
   instance and manual session identity. The service checks these before work and
   after completion; stopped/expired/replaced requests return 409, not late answers.
4. Native stdout contains recorder progress plus existing schema-2 typed events.
   The CLI retains it privately at `.local/laya/manual-capture/<id>/stdout.jsonl`.
   The service's passive `ManualSessionFeed` reads that bounded file independently
   of browser polls and passes events to existing `DashboardState.ingest`.
5. Projection and `GET /api/state` supply Monitor. Genuine current full observations
   and exact matching legal decisions can display experimental metrics/analysis,
   always `quality_approved:false`; partial, stale, mismatched or illegal inputs
   cannot. The model's failed quality grade is not upgraded by this transport.
   The browser receives no HWND/title, pixels, hashes, raw answers or private paths.

The native worker retains bounded active/latest work; the feed rejects oversized
records, more than 1 MiB of unread backlog or a log over 20 MiB instead of replaying
old work as current. Session/service identity, source identity, source timestamp,
absolute expiry and monotonic deadlines cannot be renewed by file/poll activity.
Stop, source replacement, budget expiry, model/recorder/feed error and shutdown
invalidate pending output; a stopped session cannot rearm. The current service
supports the explicit session-bound stop request below, but has no HTTP start/mark
or poker-input controls. Refreshing the browser starts neither mode.

## Stop and annotate

Use Monitor's **Stop capture** for the current capturing session. It sends only
`POST /api/capture/stop` with exact JSON keys `session_id` and `service_instance_id`,
bound to the current receipt/service and same-origin request checks. A `200`
`{"ok":true}` acknowledges the stop request, not completed teardown; `409` means
the session is stale, unavailable or mismatched. The route needs no model or GPU.
GET status polling never issues a stop or starts/rearms capture. No HTTP start,
annotation/mark or poker-input route is implemented. The full contract is in
[EVENTS_V2.md](EVENTS_V2.md).

Press **Ctrl+C in the capture terminal**, or use the printed session ID from another
terminal:

```powershell
& $py scripts/laya_capture.py stop --session <SESSION_ID>
& $py scripts/laya_capture.py status --session <SESSION_ID>
```

The native deadline and independent supervisor stop at 600 seconds or 1,200 saved
frames, whichever comes first. Smaller limits are allowed; larger first-session
limits are refused. Disk/receipt/source failures stop early. There is no automatic
retry/rearm. A stale lock requires inspection, not automatic deletion.

To flag an incorrect/missing reading, select an acknowledged frame from the private
manifest or the session's latest-frame receipt. Frame indexes are **not** identical
to the saved-frame count because capture attempts can be skipped. For example:

```powershell
$session = '<SESSION_ID>'
$receipt = Get-Content -LiteralPath ".local/laya/manual-capture/$session/status.json" -Raw | ConvertFrom-Json
& $py scripts/laya_capture.py mark --session $session --kind missing --opportunity-id reading-01 --frame-index $receipt.latest_frame.frame_index --note 'Hero stack missing; review this source frame'
```

Use `--kind incorrect` for an incorrect reading. Use `--kind opportunity` and a
stable opportunity ID such as `hand01-turn01` for a naturally occurring positive
action-control opportunity. Repeated frames from the same opportunity must reuse
that ID, not receive fresh IDs. Marker creation checks the PNG hash against the
manifest, is append-only, and never changes pixels, source times or observations.
Duplicate IDs/hashes cannot inflate the draft opportunity counter. Distinctness
still depends on the operator and later review, not automatic hand recognition.

Private PNG/hash/source-time and loss/gap receipts remain under `.local/captures/`.
Approval, status, stdout/stderr, final summary and markers remain under
`.local/laya/manual-capture/<SESSION_ID>/`. The summary reports capture failures,
sampling gaps, estimated missed samples, stop reason, exit code, and the deficit
against 20 distinct draft opportunity markers. Estimated missing samples are not
counts of missed poker actions. Raw evidence and free-text notes are not served
to the browser or committed.

## Manual-source checklist

1. Confirm the intended table and selected mode, with separate it1 consent for
   inference mode. Keep the default first-session budget.
2. Select the actual source and repeat its exact PID/HWND/nonce challenge within
   30 seconds; source identity is rechecked. Seating is not required.
3. Check that saved-frame count advances and that elapsed time/limits are visible.
4. Let actual hero cards/stack and waiting/acting states occur naturally. Mark at
   least 20 distinct positive control opportunities if available, not 20 frames.
5. Flag missing/incorrect observations as draft review markers without correcting
   evidence. Stop immediately if the selected source is wrong.
6. Stop at the first budget limit even when the target is unmet. Retain the final
   summary and report the opportunity deficit, gaps and any incomplete receipt.

## Capability matrix

| Capability | Implemented / exercised | Genuine validation or remaining blocker |
|---|---|---|
| Upper Pot text | Saved-source assembly/projection/browser contracts and fresh it1 pass execution | Saved candidates retained; fresh candidates expired before admission. Literal text preserved; accounting convention unknown. |
| Six physical stacks | Independent slots/zero-value contracts, saved-source replay and fresh it1 stack batches | Saved 3/5/5 candidates; measured fresh batches 4.50-6.07s did not establish current admitted readings. |
| Board cards/count/phase | Per-slot witnesses/admission; one changed slot no longer clears unrelated slots; browser contracts and fresh passes | Saved and fresh board answers remain below unchanged 1.0 floor. Zero accepted cards is not approval. |
| Visible wagers | Separate qualified-registry path and synthetic rendering | Disabled/untrained p6. Physical-seat1 draft positives exist; they do not activate recognition. |
| Occupancy/status/badges/dealer/blinds/actor | Separate qualified fields and synthetic contracts | Disabled/untrained p7. Payout glow is not an acting-seat proof. |
| Explicit hero cards/stack, waiting/acting, control labels | Typed/projection/browser contracts; uncertain turn does not erase independently evidenced hero stack | No established actual seated hero/control positives. Physical seat 4 is never assumed to be hero. |
| Lower center chips, contributions, boundaries, actions, positions and pot convention | Separate unknowns, never filled by Pot/wager arithmetic | Missing validated temporal/accounting context; six draft complete board progressions are not complete betting histories. |
| Capture-only workflow | Synthetic native source, mocked subprocess, private recorder/hash/gap and HTTP no-activation tests | First actual seated collection remains UNRUN; source/window behavior during that session is operator-supervised. |
| Manual capture + inference + Monitor | Synthetic production native recorder/runtime/assembly/typed events through private feed and actual renderer | Direct manual-source live trial remains unrun; the shared pipeline was exercised by authorized observer trials below. |
| Automatic observer + inference + Monitor | Explicitly authorized real source -> recorder -> it1 -> typed rejection -> DashboardState/browser, without seating requirement | Activity activation failed; no current fields accepted. Latency/source-change blockers remain. |
| Unavailable reasons / stale clearing | Six closed reason codes; source-bound diagnostics; expiry/replacement/browser tests | Contract evidence, not model confidence or human acceptance. |

## Verification boundaries

Synthetic unit/DOM tests exercise consent, original clocks, limits, races, errors,
independent field rejection and the real renderer. Native synthetic transport proof
exercises the production manual source -> exact recorder -> LiveRuntime -> Laya
assembly -> typed JSONL -> ManualSessionFeed -> DashboardState -> actual app.js.
Isolated/mocked browser measurements prove UI behavior, not recognition accuracy.

Saved-source replay reuses existing answers: it verifies hashes, crop geometry,
assembly and projection without re-running the model. Upper Pot and 3/5/5 stacks
remain candidates awaiting temporal consensus, not current admitted readings.
Historical timestamps are refused by the current-time dashboard, never rewritten.
Saved board remains below its unchanged 1.0 floor. No seated hero/control positives
were established by replay or by an operator's seated-ready assertion.

The initial manual implementation was verified offline. Later, separately
authorized automatic trials are documented above; actual model execution and
source-current diagnostics still admitted no current fields. This is not successful live recognition or
seated accuracy. No new labels, training, client inputs or threshold relaxation.
Actual receipts retain UTC, command/exit/stderr, original source hashes, rejection
timing, loss/forced-stop flags and opportunity deficit. The forced-stop/incomplete
receipt flag is retained even though the second native child exited 0.
Receipts are separated under `.local/laya/train/manual-inference-20261012/` and
`.local/laya/train/automatic-inference-20261012/`. Further runs need explicit consent;
a stopped session, its limits and its expired results are never revived.

Prior private verification receipts: `.local/laya/train/companion-20261011/`.
Before/after screenshots and browser checks:
`.local/captures/20261011-companion-ui/`. Keep both directories private.
