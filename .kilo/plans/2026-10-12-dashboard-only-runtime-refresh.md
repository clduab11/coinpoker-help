# Approval Plan: Controlled Dashboard-Only Runtime Refresh

## Objective

Replace the stale legacy helper with the committed companion runtime, verify an
explicitly idle dashboard, and prepare metadata-only source selection. Stop at
READY FOR MANUAL SOURCE CONFIRMATION / CAPTURE, not trusted live recognition.

This setup does not make the Monitor read the open game. Actual collection and
inference remain separate, explicitly authorized steps.

## Approval Scope

Approval of this plan authorizes the implementation agent to:

- Inspect this repository, its local helper listener and owned process tree.
- Stop only the positively identified legacy repository helper and its owned
  attachment/capture children, without restarting the legacy automatic feed.
- Build the existing committed native code offline into the normal local target.
- Start exactly one updated dashboard-only helper on 127.0.0.1:18090.
- Verify read-only status, browser presentation and the absence of capture/model
  activation; list candidate source-window metadata without capturing pixels.
- If necessary, make only a small idle-status wording fix and its regression test
  so a known absent manual session is not mislabeled as unavailable.
- Write private UTC/command/exit/stdout/stderr receipts and a concise handoff.

Approval does NOT authorize:

- Capture, recording, prediction calls, model loading/warm-up, training, downloads,
  threshold changes, p6/p7 activation or automatic attachment.
- Deleting prior captures, changing draft labels, resetting recorder limits,
  removing stale locks automatically, or treating markers as human approval.
- Killing unidentified processes, using another port, changing unrelated files,
  making a new commit or pushing the branch.

This dashboard-only setup produces no observations or analysis. R17 stays strict,
Gate F historical FAIL, labels DRAFT and human review PENDING.

## Baseline and Preservation

Repository: C:\Users\cld-main\Desktop\github-projects\coinpoker-help

Expected branch: checkpoint/seated-read-mechanism-2-20261002

Last verified implementation commit: 2f80e2f. At the last runtime inspection on
2026-10-11, PID87008 served the older helper; capture was unavailable and the old
recorder had reached its configured disk budget. These are historical findings,
not current process identities or permission to kill a reused PID. The table and
time remaining reported in the previous conversation must also be rechecked.

Preserve checkpoint B/stage2, all handoffs, private evidence and any new user
changes. Do not reset, checkout over changes, reinstall dependencies or replace
models. Review the current runbook at docs/SEATED_DIAGNOSTIC.md.

## Execution Steps

### 1. Revalidate ownership and record the starting state

Inspect git status, current branch and relevant launcher/source changes. Identify
the actual listener on 127.0.0.1:18090 and its executable, command line, creation
time, parent launcher and owned descendants. Read /api/state without calling a
prediction endpoint. Save a private pre-change receipt.

Do not trust the old PID alone. If the listener cannot be tied to this repository,
stop and report the exact ownership ambiguity. Never target CoinPoker.exe or
unrelated Python processes.

### 2. Shut down the legacy automatic runtime

Use its tracked launcher/session to stop it gracefully. Stop the supervisor before
cleaning up owned children so it cannot reattach or respawn them. If graceful
shutdown fails, use targeted termination only after rechecking the exact process
identity and creation time; the approval covers no broader process group.

Confirm that port18090 is free and that no owned attachment/capture child remains
or restarts. Preserve the disk-limited recording prefix and all prior receipts.
Do not restart the legacy helper as a fallback.

### 3. Build and check the non-capturing entry point

Run from the repository root:

```powershell
cargo build --offline --locked -p coinpoker
& .\.local\laya-runtime\env\python.exe scripts/laya_capture.py --help
```

This updates the ordinary executable used by the manual CLI; the earlier test
build used an isolated target. Verify command exit codes and the built executable.
Do not run the binary in live mode, run a real-HWND smoke test or download missing
dependencies. A failed offline build blocks capture preparation, not all read-only
diagnosis.

### 4. Start the updated dashboard-only service

Start one tracked process from the repository root:

```powershell
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

Do not add -EnableInference, -LiveConfig or automatic-attachment flags. Retain its
terminal/process handle and private error-log location for an explicit stop path.
If the port is occupied again, investigate ownership; do not kill an unknown
listener, create a duplicate or choose an alternate port.

### 5. Verify the idle state end to end

Refresh the existing browser page. Check:

| Item | Required result |
| --- | --- |
| Listener | Exactly one owned helper, bound to loopback18090 |
| API | /api/state responds successfully from the new process |
| Inference | inference_enabled false; model disabled, not loading or warming |
| Observation | No current observation or partial observation |
| Recorder | No active manual session, no capture child and no new frame writes |
| History | Legacy counts/gaps are not presented as the new session's observations |
| Browser | Monitor/Reference usable, explicit inference OFF, no console errors |
| Refresh | Does not activate a model, attachment or recording |

No current source is expected before capture. Distinguish an explicitly absent
session from an unavailable or malformed status response. If the page still says
Recorder status unavailable for an explicit no-session response from the new
server, narrowly fix that wording and add a synthetic regression test. Preserve
unavailable/stale warnings for genuinely missing or invalid status information.
Do not populate fake table readings or begin inference to improve the appearance.

### 6. Prepare source identification, without capture

Run only the metadata listing:

```powershell
& .\.local\laya-runtime\env\python.exe scripts/laya_capture.py list
```

Report candidate title, PID, HWND and dimensions privately. Do not infer the
intended source from an old screenshot or select an ambiguous candidate. If no
intended table is available, finish the dashboard setup and report source selection
as pending.

Listing is not recording approval. Any identified PID/HWND is provisional and
must be checked again when the operator later starts the manual session.

### 7. Deliver the bounded next-session handoff and stop

Report the new helper identity, checked UTC times, verification results, private
receipt paths and how to stop the dashboard through its owned terminal/session.

Prepare, but DO NOT execute, this future capture command using a freshly listed
source:

```powershell
& .\.local\laya-runtime\env\python.exe scripts/laya_capture.py start --pid <PID> --hwnd <HWND> --max-seconds 600 --max-frames 1200
```

Starting collection requires only the fresh exact PID/HWND/nonce challenge,
identity recheck and 30-second confirmation deadline; no seating assertion is
required. New manual receipts use `operator_assertion:null`; the known old seated
string is accepted only for receipt compatibility. Inference retains its separate
explicit resource opt-in and remains off during the first capture-only session.

The future session stops at600seconds or1200savedframes, whichever comes first,
even if fewer than20distinct positive opportunities are available. Repeated frames
do not count as distinct opportunities. Preserve draft incorrect/missing markers,
loss/gap receipts and the final target deficit.

Current capture stop paths are Monitor's **Stop capture**, Ctrl+C in the capture
terminal, or the CLI below. The browser uses `POST /api/capture/stop` with the
current exact session/service IDs and same-origin checks; 200 acknowledges a stop
request, not finished teardown. No model/GPU is required and GET polling is passive.

```powershell
& .\.local\laya-runtime\env\python.exe scripts/laya_capture.py stop --session <SESSION_ID>
```

## Failure Handling

- Unidentified listener/child: stop before termination and report the exact blocker.
- Build/startup failure: retain stderr and keep capture/inference off; no legacy
  auto-attach rollback, duplicate instance, alternate port or dependency download.
- Wrong or ambiguous source: leave selection pending; do not guess or capture.
- Unexpected user changes: preserve them and stop only if they directly conflict
  with this bounded setup.

## Completion Criteria

The updated dashboard-only helper is running, legacy automatic attachment is
stopped, inference and recorder are explicitly off, and source metadata is either
identified for later confirmation or truthfully pending. The operator has exact
start/stop instructions. No frame was collected, no prediction or model load was
started, and no poker-client input was performed by this setup.

Stop at READY FOR MANUAL SOURCE CONFIRMATION / CAPTURE, or report the precise
technical blocker. Never label this trusted live recognition.
