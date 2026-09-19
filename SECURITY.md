# Security policy

## Reporting a vulnerability

Use this repository's private GitHub security-advisory reporting flow when it
is available. If it is not available, contact the maintainers privately before
opening a public issue. Include affected versions, reproduction steps, impact,
and any suggested mitigation. Do not include captured screenshots, credentials,
or other sensitive table data in a public report.

## Data-handling warning

The capture mode sends full CoinPoker window screenshots to the configured VLM
endpoint. The default endpoint is loopback-only. The CLI rejects non-loopback
hosts unless `COINPOKER_ALLOW_REMOTE_VLM=1` (or `true`) is set and the endpoint
uses HTTPS. A remote endpoint can receive sensitive screen contents; use only a
trusted service with suitable authentication and an understood retention policy.

## Supported versions

Until the project publishes versioned releases, only the latest revision of the
default branch is considered for security fixes.
