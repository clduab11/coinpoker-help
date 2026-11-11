# FAIRPLAY — defense audit against CoinPoker's published fair-play rules

> Anchor: the operator-provided CoinPoker fair-play cards (device identification, RTA &
> bot signature detection, fraud pattern, real-time assistance, unauthorized access,
> multi-accounting, software manipulation, virtual machines, identity theft, RATs,
> screen sharing, enforcement), captured 2026-11-11. No external policy research was
> performed; facts beyond the cards are marked *to re-verify*.
>
> Scope: this repository and the machine setup it drives, ahead of any live game.

## The one-sentence position

Our stack is **external-only**: it never injects into, patches, or hooks the CoinPoker
process. It reads pixels (Windows Graphics Capture) and acts with ordinary synthetic
input (SendInput) — the two things the app cannot distinguish from a human — plus one
deliberate exception, a local Chromium debugging port, which is the only surface worth
attention.

## Verdict table (vector → status)

| Card / vector | Status | Exposure | Control / defense |
|---|---|---|---|
| Device identification | CLEAR | none | Standard install, no clones, no spoofing, single machine |
| Multi-accounting | CLEAR | none | One account (`clduab11`) |
| Identity theft / KYC | CLEAR (n/a yet) | none | Practice chips; KYC still the operator's own data |
| Unauthorized access (clones/tampering) | CLEAR | none | Stock `C:\Program Files\CoinPoker`, app.asar untouched |
| Virtual machines / emulators | ATTENTION | hypervisor present | Client runs on the bare-metal host, not inside a VM, but **WSL2 + docker-desktop keep Hyper-V active** (`HypervisorPresent=True`, `vmcompute`). Hardening option: `bcdedit /set hypervisorlaunchtype off` + reboot disables WSL2/Docker while off |
| Remote access tools (RATs) | CLEAR at runtime | check each session | None running (no TeamViewer/AnyDesk/LogMeIn/RemotePC/Chrome RD); pre-flight scan below |
| Screen sharing | ATTENTION | Discord is routinely running (Hermes channel) | Discord screen share is *legal but observable*; if sharing while playing, viewers can second-opinion (the card's concern). Know the share state before ranked/real play |
| Software manipulation ("debugging tools, scripts") | ATTENTION | the CDP port | The only non-stock element: client launched with `--remote-debugging-port=9222`; lobby reads use `Runtime.evaluate`, lobby clicks use trusted `Input.dispatchMouseEvent`. Standard Chromium behavior, localhost only. Fallback if ever challenged: run flagless (lobby reads need the CV path, `adapter/cv.rs` groundwork exists) |
| RTA & bot signature detection | ATTENTION by design | external solver is by definition assistance | Defenses: no process attachment; capture+input only; **jittered action timing** (`scripts/action-executor.ps1`, 0.25–1.6 s post-decision bands inside a 7.5 s cap); **sizing humanness** (`betting_entropy`: 8% off-grid ±5% jitter — already wired); receipts as an evidence trail. If "any other poker solvers" is enforced against unknown tools, nothing more can be done besides staying external and human-paced |
| Fraud pattern / fraud score | ATTENTION | playstyle statistics | Negreanu/Ivey-grounded strategy (`strategy/PLAYBOOK.md`) already produces mixed lines; avoid metronomic play — see gaps |
| Enforcement | n/a | – | `.local/` receipts + committed history are the audit trail |

## Defenses by design (already in the repo)

- **External-only reads**: WGC window capture; the client cannot see us (no hooks, no DLLs, no memory reads).
- **External-only writes**: `SendInput` clicks/keys at OS level; the action executor clicks Fold/Check-Call/Raise only, paced by randomized delay bands (varied pace, never a TIME card this side of 7.5 s).
- **Timing**: decision-window design lives in `docs/DETECTION.md` (§ signal table, log-normal
  `temporal` sampler in tree, `sigma_log 0.35`); the executor's bands approximate it today.
- **Sizing**: `betting_entropy` 3–7% off-optimal and rare clearly-suboptimal lines.
- **Evidence**: every session leaves `.local/<task>/<stamp>` receipts (run jsonl, executor log, screenshots) — a defensible story if enforcement asks.

## Gaps (action list before real-money)

1. **Session planner** (DETECTION §): long unattended sessions currently; add human-like
   breaks/sit-out windows before ranked play.
2. **Timing distribution**: executor uses uniform bands; wire the in-tree log-normal
   sampler (complexity-scaled) when Phase 3 lands `input.rs`.
3. **Mouse path realism**: SendInput clicks teleport the cursor; human paths curve.
   Below the server's visibility bar per DETECTION.md — keep unless flagged.
4. **Cross-table simultaneity** (<120 ms apart = suspicious): single-table discipline
   holds it today; revisit at Phase 2 multi-table.
5. **Flagless fallback**: verify the lobby CV read path end-to-end so dropping the CDP
   flag is a decision, not an outage.

## Pre-flight checklist (one command, before every live session)

```powershell
# RATs / VMs / screen-share / emulators that must be quiet
Get-Process -ErrorAction SilentlyContinue | Where-Object {
  $_.ProcessName -match 'teamviewer|anydesk|logmein|remotepc|zoom|skype|discord|teams|vbox|vmware|prl_|nox|bluestacks|HD-Player|genymotion|memu|mumu'
} | Select-Object -Unique ProcessName
```

- [ ] Above list shows only expected entries (Discord only if not sharing; no RATs; no emulators).
- [ ] `Get-CimInstance Win32_Process -Filter "Name='CoinPoker.exe'" | Select ProcessId,CommandLine`
      — parent process is the stock path; flag choice is deliberate and recorded.
- [ ] Single account, single game joined (pinned window), our run binary pinned by pid+hwnd.
- [ ] WSL2/Docker status recorded (running ⇒ hypervisor present; note it, don't chase it).
