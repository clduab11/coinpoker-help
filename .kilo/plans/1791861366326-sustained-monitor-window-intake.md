# Sustained Monitor Window Intake

## Goal and Decisions

Make Monitor visibly consume independently validated readings from the selected CoinPoker table for as long as that same readable window remains open, rather than ending observation at the diagnostic recorder's 10-minute limit. The user explicitly selected sustained observation with bounded resource use.

- Add an explicit sustained observation opt-in. Preserve dashboard-only defaults, existing bounded automatic runs, and manual capture/inference behavior.
- Keep historical quality status unchanged. Partial readouts cannot supply advice; genuine current full native state and a matched legal decision may display only as experimental analysis with `quality_approved:false`. No poker-input implementation is added. Model readiness is not perception acceptance.
- Observe only one validated executable/PID/HWND/title binding. Closing/replacing that source, ambiguity, capture failure, model failure, operator stop, or owner failure stops the run; no silent source switching or terminal-session resurrection.
- Preserve current fail-closed visibility behavior. Pause/resume after occlusion or minimization is out of scope; that question was dismissed, not approved.
- Read existing supported fields: upper Pot, six physical-seat displayed stacks, and board/phase/role only when independently admitted. Unknown fields remain unknown; observing does not require being seated.
- Table countdown recognition is out of scope. The countdown question was dismissed; do not turn the reported 45 minutes into a fabricated field or a 45-minute capture authorization.

## Verified Diagnosis

Read-only inspection on 2026-10-13 found:

| Evidence | Meaning |
| --- | --- |
| Canonical `GET http://127.0.0.1:18090/api/state`: model `ready`, inference enabled, automatic startup `stopped`, reason `duration-limit` | The model service is available; the observation owner has ended. |
| Session elapsed `600140` ms, limit `600000` ms, saved `859/1200` frames, zero capture failures, remaining `0` | The confirmed immediate cause is duration exhaustion, not frame exhaustion or capture failure. |
| Private matching `run.json`: start `2026-10-12T23:39:04Z`, end `23:49:04Z`, exit 0, complete receipt, no forced stop | The current service remains associated with an older terminal source session. A new observer session has not appeared in its state despite the reported restart. |
| Browser: `Automatic observation stopped`, `Reading expired`, `No admitted table reading` | Refreshing/reopening the page does not start capture. |
| Recorded evidence already totals approximately 625 MiB for ten minutes | Increasing duration alone would also create a storage problem. |

Source boundaries:

- `scripts/laya_capture.py:270-342,371-585,605-692`: strict bounded receipts, supervisor time/frame/log stops, one-shot startup with no rearm.
- `bin/manual_capture.rs:17-45,57-134` and `bin/manual_inference.rs:163-368`: native approval/budget checks and save-before-infer coupling.
- `scripts/laya_dashboard.py:1415-1424,1473-1525`: inference authorization and passive feed depend on recorder budget/deadline and bounded disk-backed stdout.
- `scripts/dashboard/app.js:1085-1117`: browser independently freezes a 600000-ms/1200-frame budget; changing the launcher alone cannot fix this.
- `scripts/laya_attach.py:23-28,149-154`: supported NLH-prefix and explicitly confirmed generic CoinPoker selectors. The private current profile uses the latter; visible table captions do not prove the OS window title.

No source changes, capture, inference requests, process restarts, or tests were performed during planning. The checkout contains extensive pre-existing modifications; preserve them. Process ownership inspection was blocked by terminal permissions, so rollout must establish ownership afresh.

## Implementation Tasks

1. **Define a separately authorized sustained policy and receipt contract.**
   Add `-ContinuousObservation` to `scripts/start-vlm.ps1`, requiring both existing inference/automatic opt-ins; old invocations remain bounded. Propagate the corresponding server flag and native `automatic-sustained` policy. Use a distinct sustained assertion, never the old bounded assertion. For sustained approvals use an explicit new receipt version with the immutable source binding, service instance, fresh confirmation, and an evidence budget of 600 seconds / 1200 saved frames / 1 GiB. Continue reading existing version-1 bounded receipts under their original semantics. Reject mixed policies, missing consent, future/stale approvals, and unauthorized experimental modes. Sustained mode does not enable experimental p6/p7 diagnostics.

2. **Separate observation lifetime from evidence recording in native capture.**
   Update `bin/manual_capture.rs`, `bin/manual_inference.rs`, and only necessary recorder APIs. For sustained mode, STOP/source continuity/owner failures govern observation termination; expected recording time/frame/byte exhaustion ends recording only. Freeze saved-frame/byte counters and publish the recording end reason separately from observation stop reason. After recording ends, validate each newly acquired live frame directly and retain its original capture-call monotonic/UTC timestamps; never replay the last saved PNG. Manual/bounded modes retain save-before-infer and all existing terminal limits. Unexpected recorder I/O failure remains terminal. Apply automatic cadence/probe/field-only/GDI behavior consistently to both automatic variants; keep one capture owner and one inference worker.

3. **Update Python ownership, authorization, transport, and public projection together.**
   Refactor `AutomaticStart`, `supervise`, `public_snapshot`, `ManualSessionFeed`/shared admission, and `Service.predict` authorization. A sustained observation remains live only while its original receipt heartbeat, source binding, service instance, and model are valid, independently of evidence exhaustion. Preserve existing three-second receipt staleness, capture heartbeat expiry, finite request/job deadlines, five-second reading leases, terminal tombstones, and monotonic timing protections. For the public sustained `capture_session` variant expose policy/status/session/elapsed/heartbeat, no finite observation budget (`max_duration_ms`, `remaining_ms`, `max_frames` null), and a separately labeled `evidence` object with finite budgets, status, end reason, and counters. Validators must branch on explicit policy, not accept missing bounds for old modes. Polling remains read-only and never starts or rearms a session.

   Sustained readout must not depend on an ever-growing `stdout.jsonl`: drain native stdout through a bounded pipe/queue into the existing DashboardState validation path. Retain the disk-backed passive feed for existing bounded sessions. Reuse existing record/unread-byte bounds; overflow or broken transport clears readings and fails closed. Cap any optional answer/error/diagnostic logs and stop appending at their limits without ending healthy observation. Keep the private history ledger bounded and mark incomplete when exhausted. No automatic PNG-directory rollover, deletion of prior evidence, unbounded queues, or duplicate child/feed. Native first-request authorization must still work before the next consumer tick, and late completions must fail after owner termination.

4. **Fix admission scheduling without changing confidence or freshness requirements.**
   In `bin/manual_inference.rs:619-639`, Board currently runs once after Pot x3 and each Stack x3. Runtime compares consecutive partial candidates, so Board cannot obtain its required distinct-capture consensus. Schedule consecutive Board captures and add a positive scheduler-to-runtime admission test, not merely a below-floor/null fixture. Retain the Board floor and all fitted floors.

   The 22-job cycle takes at least 11 seconds at the 500-ms capture cadence, exceeding the five-second source lease before any model latency. Make scheduling age-aware: prioritize repeated distinct captures for upper Pot and rotate supported seat lanes; evaluate the existing `Numbers(seat)` lane for combined Pot/stack reads using measured request latency. Publish fresh independently admitted fields promptly rather than waiting for a full table bundle. Do not merge unrelated generations or fill holes with old values. All six stacks need not be simultaneously current: display each current result or its explicitly stale last-read value honestly. Repeated Board work must not starve Pot. Keep role optional; whole-frame cosmetic churn currently invalidates it, and a new cropped-role capability is out of scope. If core p0 or a target floor fails, expose that reason rather than substituting a guess.

5. **Make Monitor distinguish live observation, recording, and field admission.**
   Update `scripts/dashboard/app.js`, `index.html`, and minimal styles while preserving the current design. Sustained source liveness replaces recorder-budget gating only for the new policy; old monotonic bounded leases remain unchanged. Show `Observing same table`, current capture/reading ages, independently labeled fields, and `Evidence recording ended; observation continues` when applicable. An unknown role or verifying activity does not hide valid independent numeric fields. On a terminal run, put the actual stop reason and explicit-launch recovery instruction in the main Monitor view, not only collapsed diagnostics. Preserve scoped last-read labels and clearing on source/epoch/service/session loss. Page load/refresh remains passive; do not add hidden browser-start behavior or assume a saved profile is consent.

6. **Provide one explicit launch/restart workflow and revalidate the real source.**
   The sustained launch is `scripts/start-vlm.ps1 -EnableInference -AutomaticInference -ContinuousObservation` after implementation. Provide an equivalent named Monitor launch entry if this checkout has an operator launcher; do not claim browser refresh is a restart. Before deployment, establish the canonical 18090 listener's checkout, PID and ownership with authorized read-only tools; stop only an owned approved process, never an unrelated listener, and never use a spare-port workaround. Rebuild the native binary from the changed checkout before launch. Validate current window metadata and its confirmed profile; do not automatically rewrite the generic CoinPoker selector, widen it to lobby/all windows, or assume an internal NLH caption is the OS title. Use fresh explicit source confirmation if the saved profile no longer selects exactly the intended table. Start a new session; never revive the stopped receipt observed during diagnosis.

## Validation and Acceptance

Run synthetic/mock coverage first. Suggested Python command after implementation: `python -m unittest discover -s scripts/tests -p "test_*.py"`. Add targeted Rust approval/recorder/runtime/partial/scheduler tests and run their `cargo test` filters, then workspace tests where appropriate. Tests/builds write artifacts: several existing native automatic tests write directly under `.local`, so isolate new fixtures in temporary directories and document any existing artifact-producing tests before executing them.

- Fake-clock sustained tests pass 600 seconds and 1200 acquisitions with the same session/source; observation stays live while evidence counters freeze at their approved caps. Exercise count, time, byte, stdout/log, and ledger caps independently.
- Manual and bounded automatic modes still stop at the first original time/frame/byte limit. Forged status rewrites, clock rollback, browser refresh, and recovered terminal receipts cannot renew them.
- Fresh unsaved live frames after recording ends are admissible; stale saved images, invalid frames, stale timestamps, malformed receipts, mismatched instances/sources, and late completions are rejected.
- Source close/replacement, multiple eligible sources, capture occlusion/minimization, owner/model failure, STOP, and feed failure immediately invalidate current/retained readings and do not rearm. Clearing must precede child teardown.
- Positive distinct-capture fixtures demonstrate real Pot/stack publication and paired Board consensus through native scheduling, Python projection, and browser rendering. Below-floor and missing-capability fields remain unavailable.
- Unseated/unknown role and activity-verifying cases can show admitted partial numbers but never fabricated hero cards, strategy, actions, or history. Real p0 failure remains an explicit blocker, not a successful intake claim.
- Browser tests distinguish evidence-budget closure from observation termination. Current readings still expire by original source age at five seconds; last-read values remain labeled not current.
- Before approved live validation, arrange the table and Monitor side-by-side without overlap. Inspect API and screen for acquisition heartbeat, fresh admitted upper Pot and at least one readable occupied-seat stack matching the visible window, plus honest reasons for other fields. Capture health/model-ready alone is not success.
- Complete an approved same-table live observation beyond ten minutes and, for the reported scenario, through the available approximately 45-minute observation window. Verify one owner/worker, bounded storage, continued new acquisitions after evidence closure, measured inference latency/field age, and no stale field presented as current. Do not promise a field that never reaches its floor; report that acceptance failure separately.

## Rollout and Out of Scope

Deliver native, supervisor, feed, API, browser, and launch changes as one coordinated change; a partial deployment will still stop or reject the new receipt. Update affected existing launch/safety documentation in implementation only. Keep old default and bounded launch paths available; rollback means stopping the owned sustained run and explicitly relaunching the unchanged bounded/dashboard-only path, not modifying recorded evidence.

Do not retrain models, recalibrate ROIs, lower confidence floors, lengthen reading TTLs, add timer OCR, enable recommendations, infer unsupported actions, manipulate the poker client, or change unrelated dirty files. Future automatic pause/resume and countdown recognition require separate scope decisions and validation.
