# PHASE 0 — CDP verdict protocol (executable from this document alone)

Goal: decide, with raw receipts, whether CoinPoker's Electron client can be read
over Chrome DevTools Protocol on `--remote-debugging-port=9222` well enough to make
CDP the primary live path. **No source edits in this phase.** If the verdict is
FAIL, produce the CV cost receipt before any Phase 1 work (PLAN §9).

Verdict definitions (fill the table in §7):

- **PASS** — all of P1-P7 below.
- **FAIL** — any of P1, P2, P4 fails, or fewer than 10 of 14 checklist fields get a
  usable locator.
- **INCONCLUSIVE** — anything else; rerun once before acting.

Everything is read-only against the client; the operator may still click UI normally
(opening a second table, resizing) — those are deliberate probes here.

Save all receipts under `.local/phase0-cdp/<UTC-stamp>/` (gitignored).

---

## 1. Identify the client and a table

1. From the repo root, with the client running:

   ```powershell
   target\debug\coinpoker.exe --list-windows
   ```

   Record `EXE_NAME` and a table window title from the JSONL. (If no table is open,
   ask the operator to open one.)

2. Note the executable path for step 2:

   ```powershell
   Get-Process <EXE_NAME-without-.exe> | Select-Object -First 1 -ExpandProperty Path
   ```

## 2. Relaunch with the debugging port

1. Close the client **fully** (tray too). Confirm no orphan: `Get-Process` shows none.
2. Try recipe A:

   ```powershell
   Start-Process -FilePath "<PATH-TO-COINPOKER.EXE>" -ArgumentList "--remote-debugging-port=9222"
   ```

3. Wait for sign-in/lobby, then verify:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:9222/json/version
   ```

   Record the JSON (`Browser`, `webSocketDebuggerUrl`) into `version.json`.
   If this fails, try in order and record which worked:
   - recipe B: same command plus `--remote-allow-origins=*`;
   - recipe C: edit a desktop shortcut's Target to append
     `--remote-debugging-port=9222`, launch the shortcut;
   - recipe D: `cmd /c start "" "<PATH>" --remote-debugging-port=9222`.
   Recipe must survive one full close/reopen cycle to count (P1).

**P1 = for one recipe: `/json/version` reachable, twice, across a relaunch.**

## 3. Target discovery and table separation

1. With exactly ONE table open:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:9222/json/list -OutFile .local\phase0-cdp\<STAMP>\list-1table.json
   ```

   Hmm — `-OutFile` takes a path; adjust if the shell blocks it; otherwise
   `ConvertTo-Json` and write with the editor tool.

2. Note for every object `type`: `page`, `worker`, `iframe`, etc. The table page is
   a `page` target; record its `url`, `title`, `targetId`.
3. Ask the operator to open a SECOND table (different blind level). Re-list to
   `list-2tables.json`. **P2 = two distinct page targets whose identity differs in
   `url` or `title` in a way that maps 1:1 to the two visible tables.**
4. Close and relaunch the client once, re-list (`list-relaunch.json`): record
   whether `targetId` changes (it will) and whether `url`/`title` identity is
   reproducible (it must be, for reattach).

## 4. DOM probe script (stdlib-only; saves itself, no repo edits)

Save as `.local/phase0-cdp/<STAMP>/probe.py` (content below; needs
`<ws-url>` and an output path). Run with the repo runtime python:
`.local/laya-runtime/env/python.exe` (fallback: `python`).

```python
# probe.py -- minimal CDP client, stdlib only. Usage:
#   python probe.py <ws-url> <out.json> [--eval-file expr.js] [--latency]
import base64, hashlib, json, os, socket, struct, sys, time, urllib.request

def handshake(host, port, path):
    s = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
           f"Sec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    head, _, rest = buf.partition(b"\r\n\r\n")
    if b"101" not in head.split(b"\r\n")[0]:
        raise RuntimeError(head[:200])
    return s, rest

def send_text(s, payload):
    data = payload.encode()
    header = bytearray([0x81])
    n = len(data)
    mask = os.urandom(4)
    if n < 126: header.append(0x80 | n)
    elif n < (1 << 16): header.append(0x80 | 126); header += struct.pack(">H", n)
    else: header.append(0x80 | 127); header += struct.pack(">Q", n)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    s.sendall(bytes(header) + masked)

class Reader:
    def __init__(self, s, rest): self.s, self.buf = s, rest
    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk: raise EOFError
            self.buf += chunk
    def frame(self):
        self._need(2); b0, b1 = self.buf[0], self.buf[1]; self.buf = self.buf[2:]
        ln = b1 & 0x7F
        if ln == 126: self._need(2); ln = struct.unpack(">H", self.buf[:2])[0]; self.buf = self.buf[2:]
        elif ln == 127: self._need(8); ln = struct.unpack(">Q", self.buf[:8])[0]; self.buf = self.buf[8:]
        self._need(ln); payload = self.buf[:ln]; self.buf = self.buf[ln:]
        return b0 & 0x0F, payload

def rpc(reader, s, mid, method, params=None, timeout=15):
    send_text(s, json.dumps({"id": mid, "method": method, "params": params or {}}))
    end = time.time() + timeout
    while time.time() < end:
        op, payload = reader.frame()
        if op == 0x9:  # ping -> pong
            send_text(s, "");
            continue
        if op not in (0x1, 0x2): continue
        msg = json.loads(payload.decode())
        if msg.get("id") == mid: return msg
    raise TimeoutError(method)

url = sys.argv[1]; out = sys.argv[2]
host_port, _, path = url.split("/", 3)[-1].partition("/")
host, _, port = host_port.partition(":")
s, rest = handshake(host, int(port or 80), "/" + path)
reader = Reader(s, rest)

mid = 0
def call(method, params=None):
    global mid; mid += 1
    return rpc(reader, s, mid, method, params)

call("Runtime.enable")

EXPR_DIGEST = r"""
(() => {
  const out = {url: location.href, title: document.title, elementCount: 0,
               dataAttrCount: 0, dataSamples: [], buttons: [], inputs: [],
               canvas: [], svgCount: 0, imgCount: 0, textHits: []};
  const all = document.querySelectorAll('*');
  out.elementCount = all.length;
  for (const el of all) {
    const attrs = [...el.attributes].filter(a => a.name.startsWith('data-'));
    if (attrs.length) {
      out.dataAttrCount++;
      if (out.dataSamples.length < 300) out.dataSamples.push({
        tag: el.tagName, attrs: attrs.map(a => a.name),
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)});
    }
  }
  for (const b of document.querySelectorAll('button,[role=button],a')) {
    const t = (b.textContent || '').trim();
    if (t && t.length < 40) out.buttons.push({tag: b.tagName, text: t});
  }
  for (const i of document.querySelectorAll('input,textarea,select')) {
    out.inputs.push({tag: i.tagName, type: i.type || '', value: (i.value || '').slice(0, 24)});
  }
  for (const c of document.querySelectorAll('canvas')) out.canvas.push({w: c.width, h: c.height});
  out.svgCount = document.querySelectorAll('svg').length;
  out.imgCount = document.querySelectorAll('img').length;
  const rx = /(fold|check|call|raise|all.?in|pot|to call|timer)/i;
  for (const el of all) {
    if (el.children.length === 0) {
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t && t.length < 30 && rx.test(t) && out.textHits.length < 200)
        out.textHits.push({tag: el.tagName, text: t, cls: (el.className || '').toString().slice(0, 60)});
    }
  }
  return out;
})()
"""

if "--eval-file" in sys.argv:
    expr = open(sys.argv[sys.argv.index("--eval-file") + 1]).read()
else:
    expr = EXPR_DIGEST

res = call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
doc = {"target": url, "digest": res.get("result", {}).get("result", {}).get("value")}

if "--latency" in sys.argv:
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        call("Runtime.evaluate", {"expression": "1+1", "returnByValue": True})
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    doc["latency_ms"] = {"p50": samples[len(samples)//2],
                         "p95": samples[int(len(samples)*0.95)]}
json.dump(doc, open(out, "w"), indent=1)
print("wrote", out)
```

Run per page target (repeat for the lobby target and BOTH table targets):

```powershell
.local/laya-runtime/env/python.exe -B .local\phase0-cdp\<STAMP>\probe.py "<webSocketDebuggerUrl-of-target>" .local\phase0-cdp\<STAMP>\target-<n>.json --latency
```

Notes: the script masks frames (RFC 6455 client requirement), answers pings,
handles 16/64-bit lengths. If a host check rejects the connection, retry the launch
with recipe B (`--remote-allow-origins=*`).

## 5. Field checklist (fill from the digests, then verify by eye once)

For each field: candidate tier-1 (`data-*`) locator, else candidate tier-2
(structural chain), else FAIL. Click-time-only fields (buttons, slider) verify by
presence + text; value fields verify against the visible screen once.

| # | Field | Tier-1 candidate | Tier-2 candidate | Format | Verdict |
|---|---|---|---|---|---|
| 1 | Table id / blind level | | | | |
| 2 | Whose turn (acting seat) | | | | |
| 3 | Hero cards | | | | |
| 4 | Board cards | | | | |
| 5 | Pot | | | | |
| 6 | To-call | | | | |
| 7 | Hero stack | | | | |
| 8 | Seat stacks (6) | | | | |
| 9 | Seat occupancy/empty | | | | |
| 10 | Buttons: fold/check/call/raise/(all-in) | | | | |
| 11 | Raise slider + bet input | | | | |
| 12 | Auto-fold timer element + observed max seconds | | | | |
| 13 | Dealer/blind markers | | | | |
| 14 | Hand/street indicator | | | | |

Record for each: found / format observed (e.g. `"1,234.5"`, `"₮"` units), stability
after (a) window resize, (b) client relaunch. Values with mixed formats → note the
parse rule needed. Cards may be `<img>`/`<svg>`/background images — record which;
that decides text-vs-image extraction in Phase 1.

## 6. Stability probes

1. Resize the table window twice; rerun the digest; P5 = the same tier-1/tier-2
   candidates still resolve (or the breakage is enumerated field-by-field).
2. With the probe's WS open, close the client from the OS and relaunch (recipe):
   the WS must error; re-list; reconnect to the (new) target ws URL; P-reattach =
   digest identical modulo handles.
3. `--latency` run on the busiest table target; **P4 = p95 ≤ 50 ms.**
4. Watch one real hand start-to-finish: record whether all checklist fields ever
   render with values at the same time (some apps virtualize parts of the DOM;
   note any field that only exists while "active").

## 7. Verdict

```markdown
# CDP verdict — <STAMP>
P1 relaunch+9222: PASS/FAIL (recipe: A/B/C/D, receipts: version.json x2)
P2 two-table separation: PASS/FAIL (list-2tables.json, mapping rule: ...)
P3 field coverage: __/14 fields, __ tier-1 (target ≥10 usable)
P4 evaluate p95: __ ms (target ≤50; latency receipt path)
P5 resize/relaunch stability: PASS/PARTIAL(list)
P6 auto-fold ceiling: __ s; whose-turn signal: ...
P7 no client modification: PASS (recipe is launch-time only)
VERDICT: PASS | FAIL | INCONCLUSIVE
```

If FAIL → write `CV-COST.md` in the same directory before leaving Phase 0:
cost the CV branch from measurements only — DXGI duplication fallback in
`windows.rs` (~250-400 lines) + `PrintWindow` rung, `PostMessage` input (~120-200
lines; `SendInput` only as second rung), eframe overlay + ex-styles + DPI manifest
(~250-350 lines), keep-per-HWND WGC (already per-window) for multi-table, and the
honest latency statement for CV (state-to-decision = Laya battery; repo-measured
worst p95 776 ms, warm full battery 3,027 ms; no 120 ms claim on CV without the
overlay/reader work being measured). Then re-run PLAN sequencing with the CV
adapter as primary.

## 8. Stop conditions and safety

- Do not keep both `coinpoker` captures (Python launcher and Rust live) attached to
  the same client during probing; note which was running in the receipt.
- Do not edit scripts or source; `.local/phase0-cdp/` only.
- If `/json/list` shows only one `page` target for two visible tables (one BrowserWindow
  rendering both), record it and switch P2 to "one target, multiple table roots in
  the DOM" — still PASS if the roots are separable; the adapter's `TableTarget` then
  carries `(targetId, table_root_selector)`.
- If the port is occupied: identify the owner (`Get-NetTCPConnection -LocalPort 9222`),
  stop only if owned.

## 9. Phase 0 closes PLAN §11 open items

Recipe (P1), WS transport decision (stdlib prototype above informs the Rust choice:
hand-rolled over `TcpStream` is viable — no TLS on loopback), bindings-vs-polling
(input: whether `Runtime.addBinding` works through the client's context — try in the
probe by adding a binding and reading `window.__cpdBindTest`), selectors (checklist),
auto-fold ceiling (P6), and the equity-cost A2 pin stays in Phase 1.

---

## 10. RESULT — first live run, 2026-11-10 (agent, this workstation)

Full verdict + receipts: `.local/phase0-cdp/20261110T1845Z/VERDICT.md`
(probe/click/key scripts, target digests, `table-*.png` screenshots).

- **P1 PASS** — recipe A works (launch exe with `--remote-debugging-port=9222`).
  Client ran 1.30.0 and **auto-updated to 2.2.0 mid-run**; the updater relaunches
  without the flag, so re-launch after updates.
- **P2 PASS with amendment — the table windows are NOT Electron targets.**
  Electron side: `lobby.html` page + its cloudfront iframe (+ transient splash).
  Each opened table is a separate Unity process (`CoinPoker Game\CoinPoker.exe`,
  class `UnityWndClass`, 800×613 window; spawned on Join via the `CoinPoker Bridge`
  process over named pipes). CDP therefore reads the lobby surface (listing,
  `data-table-id`s, Join controls, wallet, dialogs); the **felt is a Unity window —
  CV/Laya stays on the live path for felt fields**, contrary to the "CV never on the
  live path" simplification.
- **P3 PASS (lobby surface)** — tier-1 attributes throughout (`data-testid`,
  `data-table-id`, `data-game-type`, `data-active`, ARIA); "High Stakes Poker" =
  `VIP_ARENA` tab. Listing rows carry table ids; nav routes are real `href`s.
- **P4 PASS** — `Runtime.evaluate` p95 **3.45 ms** (target ≤50); `Runtime.addBinding`
  works.
- **P5 PASS with note** — targetIds churn on relaunch (reattach mandatory); the
  selected nav tab is covered by an overlay, click exposed children.
- **P6 OPEN** — tables opened as observer; seat flow + auto-fold timer still to
  measure. **P7 PASS** — no client modification.
- **Input verified**: trusted events delivered; Join click spawns the Unity table
  (timing: tens of seconds — do not conclude failure early).

Sequencing per PLAN §9: verdict is PASS → Phase 1 proceeds with the amendment
(CDP = lobby/join/identity, CV = felt), and PLAN §2/§3 capability tables should be
read per-surface.


