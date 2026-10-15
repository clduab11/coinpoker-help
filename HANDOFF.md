# Next Conversation: Deliver Verified Live Table Data

Operator GO recorded: **2026-10-12T19:08:04Z**.
Repository: `C:\Users\cld-main\Desktop\github-projects\coinpoker-help`.
Actual Monitor: `http://127.0.0.1:18090/`.

## Local Integration Update (2026-10-13)

Manual source confirmation now requires only the fresh PID/HWND/nonce challenge,
identity recheck and 30-second deadline. New receipts have `operator_assertion:null`;
the old seated string is accepted only for receipt compatibility, not as hero proof.
Profile metadata now uses `six-max-table`; legacy `practice-six-max` profiles keep
their identical exact selectors. Existing profile paths/flags remain compatible;
no title or scope label proves game mode/layout or widens source selection.
Explicit inference/resource opt-in remains separate. Monitor's **Stop capture**
uses the current receipt and service instance through `POST /api/capture/stop`;
GET polling is passive and no HTTP start/mark or poker-input route is implemented.

The native manual path now uses the existing decision Pipeline. Only a genuine
current full native observation plus a matching legal decision can project
**EXPERIMENTAL** analysis with `quality_approved:false`. Source/lease/parser/R17
checks remain; partial fields and unleased `table` events cannot become advice.
Gate F, human-review status and the pinned model's actual capabilities are unchanged.
The historical test counts and live receipts below do not test this new behavior.
This integration does not establish live seated recognition or certification.
See [the current contract](docs/EVENTS_V2.md) and [runbook](docs/SEATED_DIAGNOSTIC.md).

## Latest Operator Instructions And Verified State

The operator paused work at 2026-10-12T23:29:37Z while explaining that the earlier
desktop-access failure occurred during work in another Windows user profile.
The operator resumed at **2026-10-12T23:33:09Z** and explicitly authorized enabling
bet/action recognition as part of final live verification. The standing
GO remains in force. Recognition authorization does not establish validated
recommendations or justify fabricated values, lowered fitted floors or false training
and accuracy claims. Bet/action capability enablement must follow actual model
support, source-bound evidence and verification rather than an approval-only gate.

At 2026-10-12T23:35:56Z, read-only revalidation found normal input desktop access,
one uncloaked/unobscured profile candidate, and exact screen-point/root ownership.
The prior source is retired, not resumable; each next run needs a fresh owned session.

The first real numeric functional demonstration succeeded on 2026-10-12:
`readout-startup-20261012t1943z/attempt-4-live/` under the private evidence root.
885 original PNG hashes and clocks were verified, with 293 native diagnostics and
71 accepted partial publications. Actual Monitor screenshots numerically matched
Pot `0.08` and physical-stack readings `3.7`, `2`, and `2.02` against their original
source frames. Four separately backed displays spanned 191,251 ms, including natural
stack changes (`3.56` to `3.7`, `1.98` to `2`). No numeric tolerance or label correction
was applied. See `numeric-backchecks.json` and `audit-retired.json` privately.

This was not general recognition-accuracy approval: Gate F remains historical FAIL,
labels DRAFT, human review PENDING. The complete run ended at its duration budget
with native exit 1, forced stop true and receipt_complete false; preserve those
receipts. Only 37 of 293 native diagnostics reached the bounded private projection;
the missing projection clocks are recorded, not presented as complete evidence.

The operator then requested retaining stale values while fresh readings overwrite
them. UI-only Pot/stack retention is implemented with unmistakable Last read / Stale
or Changed labels and original source age. It never renews the five-second live
lease or enters API GameState/history/advice. Same service/session/epoch/geometry,
an active receipt/budget and the unchanged 2500-ms owner heartbeat are required.
Stop/source loss/replacement/unknown epoch clears the cache; refresh is passive.
The public `capture.epoch` hint makes hidden epoch boundaries observable.

The six-stack automatic batch was live-tested and retired after its roughly
four-second prediction cost plus other work exceeded the five-second lease. The
current rebuilt schedule uses p0 + Pot + one trained stack in three-job physical
seat lanes, then periodic p0 + board. Source copies are new current desktop pixels,
not cached WGC frames or archived PNGs. Input-desktop availability/identity, exact
window identity, visibility, root hit-test, occlusion and before/after geometry
checks fail closed. No desktop switch or poker-client focus/resize was performed.

Current supporting verification: **553 Rust tests passed / 3 opt-in checks skipped**,
**350 Python/UI tests passed**, build/clippy/format checks passed. Numeric continuity
and stale-label behavior still require the resumed actual live verification; no
live success is inferred merely from those tests. New evidence is under
`.local/laya/train/automatic-inference-20261012/readout-startup-20261012t1943z/`.
Inspect fresh ownership/API receipts rather than saved PID constants.

## Start Here

Continue implementation, debugging, and real live verification until the operator
can see current supported table values in the actual Monitor while observing a
table. Do not stop at a plan, model readiness, passing synthetic tests, or another
explanation that the activity gate rejected everything. Diagnose the blocker,
implement the fix, rebuild, test, launch, inspect the real result, and iterate.

The operator's current instruction is:

> Put a prompt in place for the next conversation to meet the final goal, backchecked by live testing while I'm currently sitting at the table. Make all runs authorized; I'm the one who had limitations in the first place, and I'm explicitly giving a GO command that authorization is now up and down the board on tying the functionality together so that I can see live data in the Monitor while I'm observing a table.

## Standing Authorization

This packages the operator's explicit authorization for this task, not an approval
invented by an agent or peer. It supersedes earlier conversation/document statements
such as "no further live run authorized", "one additional attempt only", and
"a separately authorized new attempt is required". A later operator stop or scope
change takes precedence. It does not override system/tool permission requirements.

- All necessary implementation, rebuild, offline verification, installed-it1 loading/use, live capture/inference, and real Monitor verification runs for this goal are authorized.
- Repeated controlled live-test cycles and freshly owned helper replacements are authorized. Do not ask for another generic GO after each failure or merely because a new source session is needed.
- Revise over-restrictive startup/activity gating or scheduling when it prevents a correctly identified, readable table from producing supported values. The inherited two-baseline/two-changed gate and 30-second unconfirmed probe are implementation/policy starting points, not immutable requirements that excuse an unusable Monitor.
- In particular, investigate separating activity/history qualification from running and displaying independently admitted Pot/stack/card observations. An observed table need not generate a betting-content change before its already-visible, current values can be read. Record and test any resulting policy change; do not pretend it was already implemented.
- Start with the existing finite 600-second/1,200-saved-frame diagnostic budgets and private profile. These are per-run budgets, not a limit of one authorized run. Keep resource bounds explicit; avoid runaway background retry loops.
- Retire ended sessions permanently. Each retry gets a new session, fresh limits, fresh ownership validation, and a unique evidence directory. Never revive an old session or make browser refresh silently rearm capture.
- Ask only for a genuine missing fact, external blocker, or out-of-scope action, not another blanket authorization for this work. Ambiguous/absent source selection is a real blocker; do not manufacture a matching source.

The operator says they are at the table and observing it. This does **not** prove a
seated-player or hero identity. Observer operation is sufficient; source confirmation
does not require seating and is not evidence of hero identity.

## Integrity Boundaries

- Keep R17 strict. Only genuine source-bound full-state analysis may display as experimental, without upgrading model quality. Do not turn a partial readout into a full GameState, recommendation, action history, hand-relative position, or claimed hero identity.
- Preserve original source UTC/monotonic provenance and freshness. Do not restamp old images or extend the five-second source lease merely to make a failed result appear live.
- Use the installed it1 and existing fitted floors as the baseline. Do not lower confidence floors, fabricate values, relabel guesses, or substitute synthetic/replayed readings for live success. Unsupported fields remain unknown; zero is a real value, not a fallback for missing data.
- The 23:33:09Z operator instruction authorizes enabling bet/action recognition. p6/p7 must still be independently justified and source-verified; an unsupported model head cannot be called trained because permission was granted. Gate F remains historical FAIL; labels remain DRAFT and human review PENDING. Functional readout evidence is not general recognition-accuracy approval.
- Keep source identifiers, PNGs, raw answers, diagnostics, and screenshots private under `.local`. Preserve original receipts, including failures and incomplete flags. Do not overwrite an earlier attempt's evidence.
- Do not indiscriminately delete captures, model weights, calibration files, or training data. Delete only demonstrated disposable contamination. No archived PNG reuse was found in the current live inference path.
- Preserve the dirty worktree and unrelated work. Do not commit, push, revert other changes, or alter credentials/permissions as part of this task.

## Historical Incoming Baseline

The goal is **not yet met**. The latest live run ended with
`table-activity-unconfirmed` and zero admitted readings/advice.

At a read-only API check on **2026-10-12T19:12:00.846Z**, the canonical helper was
model-ready and idle, with a failed/retired 33-frame source session and null full
and partial observations. Revalidate this state; do not assume saved process IDs,
an old tracked handle, or on-disk edits describe the currently loaded service.

Latest actual trial, 18:18:15.834670Z-18:18:46.331396Z on 2026-10-12:

- 33 original PNG hashes verified; 20 actual p0 predictions, 359.7-767.1 ms each.
- 19 typed diagnostics reached the private feed, all source-current, source ages 796-2888 ms; no obsolete/deadline discard.
- Table/layout/readability scores passed their unchanged floors. Those score-only results are not live field admission.
- The required same-region baseline/change sequence did not complete before the gate's timing limits. Numeric passes never started. The current p0-only-until-activation design is the immediate integration blocker to investigate, not lack of operator permission.
- Native exit 0, `forced_stop=true`, `receipt_complete=false` are preserved. Observer exit 0 means evidence collection completed, not recognition passed.
- 0/20 DRAFT control opportunities, deficit 20. This diagnostic collection target is not permission to invent actions or a prerequisite for displaying an independently verified value.

## Changes Already Implemented

1. Automatic readout stability tracks the twelve existing board/Pot/stack crops independently. The model still receives original unmasked pixels; field-source equality remains exact.
2. Activity witnesses are per-region. Missing regional witnesses cannot count or renew a baseline; identity, epoch, geometry, and expiry boundaries remain enforced. Role/phase retain conservative whole-frame proofs.
3. WGC drains/closes old pool frames and checks compositor QPC timestamps against the capture invocation, with bounded waiting/recreation. No old disk image is used as a live fallback.
4. A completed job can dispatch the already-captured distinct fresh frame while qualification/consensus is pending. There is one native capture owner and one bounded model worker; no busy-worker preemption.
5. Automatic capture cadence uses the acknowledged capture-call timestamp, not loop entry or an extra full sleep after work. A slow-initial-selection regression verifies recorder interval alignment.
6. Active inference rotates p0 plus one trained field in three-job lanes. Full/manual inference keeps its separate path. The current startup gate prevents those numeric lanes from running in the failed live trials.
7. Private schema-2 `partial_observation_invalidated` targets the exact old publication. It cannot tombstone a newer in-flight result or revive an invalidated source under another generation. Producer, supervisor allowlist, feed, and DashboardState are integrated.

A cadence regression introduced during this work caused one earlier follow-up to
stop after one saved frame with `recorder-failure`. It was fixed before the latest
33-frame trial. Do not reinstate the old loop-entry anchor or erase that failure.

## Evidence And Entry Points

Read the relevant sections instead of indiscriminately loading every old frame.

- Latest actual run: `.local/laya/train/automatic-inference-20261012/retry-5-clock-aligned-20261012/` (`audit.json`, `gate-analysis.json`, `actual-runtime-result.json`, `fresh-answers.jsonl`, `actual-api.jsonl`, `monitor-final.png`, `no-rearm-after-refresh.json`). Resolve its private source session from these receipts; do not hardcode an old session into a new run.
- Offline work: `.local/laya/train/automatic-inference-20261012/stability-investigation-20261012/` (`pixel-analysis/` and `verification/`). A gate timing estimate derived from diagnostic emission UTC is not an exact near-boundary measurement.
- Historical one-frame failure: `.local/laya/train/automatic-inference-20261012/retry-4-stability-20261012/`.
- Operational history and capability matrix: `docs/SEATED_DIAGNOSTIC.md`. Event contracts: `docs/EVENTS_V2.md`. Older per-run approval wording is superseded by this standing GO, not erased from historical evidence.
- Capture/probe/field schedule: `bin/manual_inference.rs`. Typed producer: `bin/live.rs`.
- Worker, epochs, freshness and publication: `crates/ingest/src/runtime.rs`. Exact source witnesses/partial admission: `crates/ingest/src/partial.rs`.
- WGC freshness: `crates/ingest/src/windows.rs`. Crops and execution: `crates/ingest/src/laya/geometry.rs`, `crates/ingest/src/laya.rs`.
- Model and session binding: `scripts/laya-server.py`. Source/supervision: `scripts/laya_attach.py`, `scripts/laya_capture.py`. Feed/state: `scripts/laya_dashboard.py`. Actual renderer: `scripts/dashboard/app.js`.
- Preserve the incoming untracked `.kilo/plans/2026-10-12-dashboard-only-runtime-refresh.md` unless its integration becomes explicitly necessary; do not accidentally implement dashboard-only operation instead of this live-readout goal.

## Controlled Live Loop

1. Inspect current code/worktree, actual helper state, and `.local/practice-table.json`. The profile must exist, validate, and identify exactly one current visible candidate. No missing-profile fallback to an NLH selector; no legacy auto-attach.
2. Reproduce the specific remaining blocker against saved evidence without changing its timestamps or presenting replay as current. Instrument the gate and field path enough to distinguish confidence, scheduling, source change, expiry, feed rejection, and renderer suppression.
3. Implement and test the smallest complete fix, including producer/consumer/UI contracts when affected. Revise the startup qualification policy if necessary under this GO; do not keep rerunning an unchanged failing p0-only probe.
4. Build the actual executable. Freshly verify the canonical listener's command, executable, parent, and creation time. Stop only the owned helper/native session, verify no listener remains, and use the same canonical port. No PID-only kill or silent alternate port.
5. Start a new tracked helper and a fresh source session with a unique private evidence directory. Collect API states during the run. The standing GO covers this and subsequent controlled retries; no renewed approval prompt is needed.
6. Inspect the real Monitor while the table is being observed. Compare admitted displayed values with corresponding source frames and original timestamps, not with a prior screenshot or a canned test payload.
7. On failure, retain the receipt, diagnose, fix, rebuild/revalidate, and repeat. On source loss/ambiguity, stop that attempt rather than silently switching it. Stop the task for an actual external blocker or operator stop, not an obsolete authorization restriction.

Canonical launch, as one command:

```powershell
pwsh -NoProfile -File scripts/start-vlm.ps1 -EnableInference -AutomaticInference -PracticeConfig .local/practice-table.json
```

Add `-AnswersLog` with a **new private path** for each attempt. Both consent flags
are required; ordinary launch remains dashboard-only. Keep browser refresh passive.
The current profile intentionally matches the Win32 metadata title `CoinPoker`;
the client can draw an `NLH ...` caption itself. Do not replace the profile with an
NLH fallback because those two titles differ. Metadata remains candidate selection,
not visual proof of a readable table.

Useful existing private tooling, inspect before reuse:

- `.local/laya/train/manual-inference-20261012/run.py`: exclusive command receipts; absolute output prefixes work and their parent must exist.
- `.local/laya/train/automatic-inference-20261012/ownership.ps1` and `stop_receipt_owner.ps1`: the stop guard takes fresh ownership **stdout JSON**, not a `.run.json` receipt. Never reuse historical PID constants.
- Latest verifier: `.local/laya/train/automatic-inference-20261012/retry-5-clock-aligned-20261012/verify_attempt.py`. It imports the older `retry-2-20261012t1430z/verify_attempt.py` beside that attempt directory; inspect both. Adapt paths, fresh-session binding, limits, and current evidence contracts to a new output directory. Do not invoke historical hardcoded analyzers against old folders or reuse append-mode answers logs.

## Verification Standard

Current supporting baseline: **549 Rust tests passed / 3 opt-in checks skipped**,
**315 Python/UI tests passed**, build/clippy/format checks passed. The separately
run 27-frame Rust replay preserved hashes/clocks and increased pixel eligibility
from 7 to 24; it produced no model predictions. A 240-frame synthetic native/feed/
actual-renderer test displayed Pot and five unchanged stacks while withholding the
changing stack, role, and board. None of that proves live readout.

Useful commands:

```powershell
cargo test --workspace --offline --locked
cargo clippy --workspace --all-targets --offline --locked -- -D warnings
cargo fmt --all -- --check
cargo build --offline --locked -p coinpoker
& .\.local\laya-runtime\env\python.exe -B -m unittest discover -s scripts/tests
```

## Definition Of Done

- The actual `127.0.0.1:18090` Monitor displays supported numeric fields from the operator's current table, beginning with Pot and independently supported stacks, without needing a seated/hero assertion.
- Values arrive through real capture -> installed model -> independent admission -> typed feed -> DashboardState -> browser rendering. Model-ready, p0-only classification, score-only answers, a capture border, and test fixtures are not substitutes.
- Minimum functional demonstration: at least three separately source-backed accepted display updates across at least 60 seconds of observation, including an update after a naturally occurring numeric change. Compare Pot and at least two supported stack fields against their corresponding source frames during that window; they need not share a timestamp, but every displayed field must still be current under its own source lease.
- Each value claimed as backchecked must numerically match the visible source after normalizing formatting/units, not merely look plausible. Record mismatches and withhold ambiguous fields; no arbitrary error tolerance or label correction. If the table does not naturally change in a bounded run, record that verification gap and continue an already-authorized run when the source permits.
- Original source identity, timestamps and per-field freshness remain traceable. Changed/expired/unsupported fields clear or remain unknown; missing fields are not filled with old values or zeros. Source loss and stop clear readings safely.
- Record live logs, source hashes, accepted/discarded field reasons, latency/age measurements, API samples and actual browser screenshots. Keep synthetic, saved-frame replay, actual live evidence and human accuracy review separate.
- Report honestly which fields worked and which remain unsupported. Do not declare the goal complete while all readings are null. Update this handoff with the verified outcome and current process/session disposition for the following conversation.

These are functional completion checks, not new per-run approval gates or a claim
of general model accuracy. The operator's standing GO remains in force for the task.

Proceed under the standing GO. The next meaningful milestone is **real, current
values visibly updating in Monitor**, not another authorization request.
