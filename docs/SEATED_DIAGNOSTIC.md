# Manual seated diagnostic / capture

This is a bounded evidence-collection session, **not a recognition-accuracy
acceptance test**. Suggestions remain OFF, R17 strict, Gate F historical FAIL,
and labels DRAFT / human review PENDING. The operator controls the client,
seating and all poker actions. The companion has no poker input controls.

## Launch without collection

Run these commands from the repository root on the already provisioned host:

```powershell
cargo build --offline --locked -p coinpoker
$py = '.\.local\laya-runtime\env\python.exe'
pwsh -File scripts/start-vlm.ps1 -DashboardOnly
```

Open `http://127.0.0.1:18090/`. Ordinary `start-vlm.ps1` and `laya-server.py serve`
now also default to dashboard-only. They never attach, record or load a model.
An occupied port is refused, not killed or moved. An older helper was intentionally
left untouched during this checkpoint; its old Python behavior does not become
the new behavior by refreshing a browser. Only the operator should stop that
owned helper in its terminal and start the dashboard-only version when ready.
Do not run two helpers or use the old automatic-attachment instructions.

Use a normal desktop browser at 100% zoom, with device emulation off. Approximately
800x520 **outer** pixels is the target window, not the CSS viewport. In the measured
100%-DPI Chrome window, 800x520 outer yielded 784x425 CSS. Chrome consumed 16 pixels
in width and 95 in height. The separate regression viewports were 780x400,
640x360 and 1000x600 CSS. Reference and expanded diagnostics use one page scrollbar.

Inference is a separate runtime choice: `-EnableInference` / `--enable-inference`
only enables loading the existing pinned it1 model; it does not start capture.
That flag is **not authorized by this checkpoint**. Do not use it for the first
capture-only session. A later saved-frame inference diagnostic needs its own
explicit approval; no training, download, new model or threshold fitting is needed
to use this runbook. The capture-only CLI never imports or invokes the model.

## Confirm and start

In a second terminal, list window metadata only:

```powershell
$py = '.\.local\laya-runtime\env\python.exe'
& $py scripts/laya_capture.py list
```

The operator opens the intended table and seats manually. Use the actual PID and
HWND printed by `list`, not values copied from an old receipt:

```powershell
& $py scripts/laya_capture.py start --pid <PID> --hwnd <HWND> --max-seconds 600 --max-frames 1200
```

This command first displays the exact private executable/title/PID/HWND/dimensions.
It requires the fresh `CAPTURE <PID> <HWND> <nonce>` challenge shown in that terminal,
then the exact statement **`I am seated and ready`**. Confirmation expires after
30 seconds and metadata is rechecked before the child starts. A changed source
needs a new confirmation. It never follows a replacement window automatically.
Same-identity resize is handled separately; it is not approval of a new source.

The terminal prints an opaque session ID, elapsed time, saved-frame count and limits.
Monitor shows the same recorder status separately from observation/model status.
Capture-only can save evidence while every recognition field is unavailable; that
is not a failure to start capture and is not live recognition.

## Stop and annotate

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

## First-session checklist

1. Confirm this is the intended manually operated table, with the default budget
   and inference OFF; do not resize, focus or operate the client through the agent.
2. Select the actual source, repeat its challenge and explicitly state seated-ready.
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
| Upper Pot text | Saved PNG hashes/crops and existing answers through Rust partial assembly, Python projection; browser contract render | Three saved table candidates retained, not fresh live recognition. Literal text preserved; pot accounting convention unknown. |
| Six physical stacks | Same saved-source path; independent slots and zero values | 3/5/5 candidates at 900x686/800x613/879x670. Other fields remain unknown; no universal accuracy claim. |
| Board cards/count/phase | Per-slot witnesses/admission; one changed slot no longer clears unrelated slots; browser contracts | Existing saved card answers remain below unchanged 1.0 floor. Zero accepted cards is a failure, not approval. |
| Visible wagers | Separate qualified-registry path and synthetic rendering | Disabled/untrained p6. Physical-seat1 draft positives exist; they do not activate recognition. |
| Occupancy/status/badges/dealer/blinds/actor | Separate qualified fields and synthetic contracts | Disabled/untrained p7. Payout glow is not an acting-seat proof. |
| Explicit hero cards/stack, waiting/acting, control labels | Typed/projection/browser contracts; uncertain turn does not erase independently evidenced hero stack | No established actual seated hero/control positives. Physical seat 4 is never assumed to be hero. |
| Lower center chips, contributions, boundaries, actions, positions and pot convention | Separate unknowns, never filled by Pot/wager arithmetic | Missing validated temporal/accounting context; six draft complete board progressions are not complete betting histories. |
| Capture-only workflow | Synthetic native source, mocked subprocess, private recorder/hash/gap and HTTP no-activation tests | First actual seated collection remains UNRUN; source/window behavior during that session is operator-supervised. |
| Unavailable reasons / stale clearing | Six closed reason codes; source-bound diagnostics; expiry/replacement/browser tests | Contract evidence, not model confidence or human acceptance. |

## Verification boundaries

Synthetic DTOs exercise the real renderer, not a replacement production feed.
Saved-source replay reuses existing answers: it verifies hashes, crop geometry,
assembly, admission and projection without re-running the model. Historical
timestamps are refused by the current-time dashboard rather than rewritten.
The desktop measurements test the browser window only, not the poker client.
No fresh model diagnostic, live capture, seated accuracy measurement, training,
client input or helper reload was performed by this checkpoint.

Private verification receipts: `.local/laya/train/companion-20261011/`.
Before/after screenshots and browser checks:
`.local/captures/20261011-companion-ui/`. Keep both directories private.
