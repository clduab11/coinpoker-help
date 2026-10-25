# Security policy

## Reporting

Use the repository's private GitHub security-advisory flow when available, or
contact the maintainers privately. Include affected revision, reproduction, impact
and mitigation. Never attach captured tables, credentials, private model requests
or window listings to a public issue.

## Screenshot and output boundaries

Explicit native capture requests a selected window and sends local PNG region
requests to the sole Laya backend. The pixel boundary still needs physical
Windows evidence. The canonical browser/service is loopback-only at
`http://127.0.0.1:18090/`, with `/v1/models` (alias `coinpoker-laya-vision`)
and `/v1/laya/predict`. There is no supported remote opt-in, Gemma fallback,
retired product endpoint or automatic alternate port. The local listener is
unauthenticated; do not expose it through a proxy or tunnel. An occupied 18090
is a conflict, not permission to stop an unowned process.

UI/status requests must remain independent of model loading and the single GPU
admission slot, with bounded requests, Host/Origin validation, restrictive CSP and
safe text rendering. State DTOs contain no PNG bytes or data URLs. The bounded
`GET /api/evidence/<sha256>` route serves only registered, hash-allowlisted local
original/crop PNGs; it does not provide arbitrary file serving. Local on-screen
player labels are allowed, but raw private paths, raw model answers, backend
bodies, HWND, PID and window class are not public browser fields. Public capture
and popup bindings use opaque identities while full provenance remains local.
These are implementation-test requirements, not an accepted live-security receipt.

`POST /api/capture/start` and `/api/capture/stop` use explicit JSON requests bound
to the current service and control token, with same-origin/session checks. Stop
also binds the active session when present and can cancel pending discovery.
Status polling does not implicitly start or stop capture.

Live decisions are scoped to an executable name, PID and HWND, plus observation
generation and expiry. Consumers must clear on `clear`, lease expiry, EOF or process
replacement; see [EVENTS_V2.md](docs/EVENTS_V2.md). Public process metadata and
configured title fragments are calibration aids, not executable authentication or
proof that a window is a poker table. Visual extraction can still be wrong.
Raw answers and legacy table events do not establish current hero controls or
eligible history. Follow-on observation invalidation/capture health must clear
current views even when no advice exists; polling cannot renew an expired lease.

Public event/state DTOs must exclude PNG data URLs, raw Laya payloads and server
error bodies. The hash-registered original/crop evidence route above is the only
browser PNG path; it does not make local images anonymous or permit path
selection. `--list-windows` may expose personal titles. Private answer logs are
diagnostics, never advice inputs. Historical Gemma color probes are not the
current typed Laya API. Keep doctor/evaluation local, and review local server
logs, swap and crash dumps separately.

Keep new real capture pixels under ignored `.local/captures/`; existing local
fixture/label records remain private. Planned bounded per-session history under
`.local/` stores opaque session/table/seat-occupant identities and explicit gaps,
not public names, uploads or guessed cross-session merges. At a recording limit,
preserve the evidence prefix and report incomplete coverage. Demo/replay browser
requests must not start capture, write live history or trigger training.

Reuse the local `20261009T190322Z-it1` checkpoint; fresh installs lack this
user's fine-tuned derivative. Repository source is MIT; the pinned Laya fork and
upstream backbone are Apache-2.0, and Laya base/derivative weights CC-BY-NC-SA-4.0; weights
are not redistributed. Historical candidate archives omit current Laya
server/dashboard support and local weights, as well as credentials/private
fixtures/logs. The helper does not hide processes, inspect client memory,
intercept traffic or send client input.

The project is a user-directed bug-bounty proof of concept. Gate F remains FAIL;
model/temperature readiness is not quality
approval. Positive real UI data and approved human-held-out calibration/evaluation
are required before seated advice. The proposed 5-second full end-to-end budget
does not retroactively pass the original 3.0273-second/<2-second failed benchmark.

## Supported versions

Until versioned releases exist, security fixes target the latest revision of the
default branch.
