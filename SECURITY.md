# Security policy

## Reporting

Use the repository's private GitHub security-advisory flow when available, or
contact the maintainers privately. Include affected revision, reproduction, impact
and mitigation. Never attach captured tables, credentials, private model requests
or window listings to a public issue.

## Screenshot and output boundaries

Live capture requests a selected window and sends its image to the configured
VLM. The pixel boundary is a physical Windows acceptance gate. Loopback is the
default. Remote capture requires `COINPOKER_ALLOW_REMOTE_VLM=1` (or `true`)
and HTTPS; the remote service then receives everything visible in that window.
The client rejects redirects and endpoint URLs with credentials or query strings.
The local VLM port is unauthenticated, so do not expose it through a proxy or tunnel.

Live decisions are scoped to an executable name, PID and HWND, plus observation
generation and expiry. Consumers must clear on `clear`, lease expiry, EOF or process
replacement; see [EVENTS_V2.md](docs/EVENTS_V2.md). Public process metadata and
configured title fragments are calibration aids, not executable authentication or
proof that a window is a poker table. Visual extraction can still be wrong.

Capture logs exclude screenshots, PNG data URLs, raw VLM payloads and server error
bodies. The model prompt uses pseudonyms for people in extracted states, but the
input image itself is not anonymized. `--list-windows` may expose personal titles.
Doctor uses generated color images and no capture API; evaluation refuses remote
endpoints. Check local server logs, swap and crash dumps separately.

Keep authorized real images and labels under ignored `.local/fixtures/` with local
access and retention controls. Candidate archives contain no weights, credentials,
private fixtures or logs. The helper does not hide processes, inspect client
memory, intercept traffic, or send client input.

## Supported versions

Until versioned releases exist, security fixes target the latest revision of the
default branch.
