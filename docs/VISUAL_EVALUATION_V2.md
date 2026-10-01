# Local visual evaluation, manifest format 2

No real screenshot corpus is included. The committed
`fixtures/synthetic/manifest.json` contains generated gradients and scripted
model envelopes. It checks parsing, gating and freshness contracts, not table
recognition. In a source checkout, regenerate it with
`python scripts/generate-synthetic-fixtures.py`; that development script is not
included in a source-free candidate archive.

## Run

From a source checkout with Cargo:

```powershell
cargo run --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
New-Item -ItemType Directory -Force .local/fixtures | Out-Null
cargo run --release --locked --bin coinpoker -- --evaluate .local/fixtures/manifest.json
```

From the source-free candidate archive:

```powershell
& .\coinpoker.exe --evaluate fixtures/synthetic/manifest.json
New-Item -ItemType Directory -Force .local/fixtures | Out-Null
& .\coinpoker.exe --evaluate .local/fixtures/manifest.json
```

Use the second command only with an authorized local image corpus and a running
local VLM. Evaluation refuses non-loopback endpoints even when live capture remote
opt-in is set. Images are read relative to the manifest, sent to the VLM, then
discarded from evaluator memory after each case. Absolute paths or links escaping
the manifest directory are rejected. Local-image cases cannot substitute recorded
responses or synthetic images. The evaluator prints aggregate metrics, not images,
names, model replies or per-case states. It invokes no capture or client input.

## Fixture schema

Top level is `format:2`, `source:"local_images"` or `"synthetic"`, and nonempty
`cases`. The generated manifest provides full valid examples.

| Field | Meaning |
| --- | --- |
| `id`, `sequence` | Sanitized unique ID and temporal sequence; cases run in manifest order. |
| `identity` | `{exe_name,process_id,hwnd}` with pseudonymous but consistent values; `hwnd` is a lowercase `0x` hex string. Change PID/HWND for restart or replacement cases. |
| `metadata` | `candidate`, `table_title`, `lobby_title`, or `other`; independently calibrated metadata, never a model guess. |
| `expected_kind` | `lobby`, `poker_table`, `other_coin_poker_window`, or `unknown`. |
| `expected_state` | Complete labeled `GameState`, or null for non-table/unreadable content. |
| `recommendation_allowed` | True only after readable hero turn, title gate, stability and two-observation consensus. |
| `tags` | Sanitized type, phase, resolution, DPI, readability and lifecycle labels. |
| `image` | Relative PNG/JPEG path for `local_images`, otherwise null. |
| `synthetic_image`, `response` | Synthetic-only gradient parameters and scripted strict screen envelope, otherwise null. |
| `freshness` | Optional independent freshness label described below. |

`freshness` contains `generation`, `current_generation`, `epoch`,
`current_epoch`, `age_ms`, `current_identity` or null, `fresh_capture`, and
`expected_fresh`. The evaluator calls the same freshness predicate as live mode.
A stale admission counts as failure even if another screen gate also suppresses
the case. This is not an asynchronous capture test; injected capture/clock/inference
runtime tests and physical gate 15 cover scheduling.

Screen envelopes require `screen_kind`, all six evidence booleans
(`table_layout`, `hero_cards`, `board_area`, `pot`, `action_controls`, `readable`),
and `state`. Every table state/player field must be explicit. Missing values do not
silently become zero, false or an empty card. Non-table payloads are discarded
separately from poker decision parsing.

Advice requires a configured table-only title, plausible nonblank pixels,
model table classification and readability, poker invariants, continuity and two
matching fresh observations. An HWND pin does not bypass the table-title gate.
There is no calibrated positive pixel classifier; repeated model agreement may
repeat the same mistake.

## Required held-out local corpus

Record revision/hash and independent label review. Include at least:

- 100 lobby, 100 unknown/obscured, and 50 unrelated client dialog observations.
- 200 readable table observations across cash/tournament layouts, all five phases,
  hero and non-hero turns, check/call/raise/all-in availability, nonzero street
  contributions and exact raise bounds.
- Two window sizes and at least 100%, 125%, and 150% Windows display scaling.
  Record logical window bounds and captured image pixels separately.
- Animation, partial obstruction, unreadable values/cards, minimized or off-screen
  windows, empty seats, folded/mucked cards and hand boundaries.
- Multi-window ambiguity, table close/reopen, client restart, pending-inference
  changes and deliberate expiry. Identity labels must prevent cross-window consensus.

Tags are open-ended. Coverage counts do not certify sufficiency. Synthetic layout
or DPI tags represent fictional scenarios. Two copies of one image are not two
independent captures. Use frames representative of the actual window capture,
without private preprocessing that the running pipeline does not perform.

## Acceptance thresholds

Rates with no denominator are null and cannot pass. Exact match requires every
applicable labeled value to agree.

| Metric | Required on held-out real corpus |
| --- | --- |
| Actionable decision from lobby, unknown or other screen | 0 critical failures |
| Lobby-to-table and non-table-to-table false positives | 0 observed; report sample counts and confusion matrix without claiming zero population risk |
| Whole hero-plus-board card exact match | At least 99% overall, 100% on emitted actionable decisions |
| Pot, stack and to-call exact match | Each at least 99%; 100% on emitted actionable decisions |
| Action-required precision and recall | 100% precision, at least 95% recall |
| Available-action and raise-bound exact match | At least 99% and 100%, respectively, where applicable |
| Eligible-decision recall after consensus | At least 95%; always abstaining fails |
| Stale admission and duplicate-clear regressions | 0 failures |
| Warm end-to-end latency | p95 at most 3,000 ms and p99 under 5,000 ms; record cold/warm separately |
| Physical Windows acceptance | All twenty gates have evidence |

The aggregate report includes `screen_kind_confusion_matrix`, extraction/action
rates, `eligible_decision_recall`, `recommendations_emitted`,
`critical_actionable_false_positives`, `request_errors`,
`stale_result_suppression_failures` with `stale_cases`, `coverage_tags`, and
`latency_ms` with `p50`, `p95`, and `p99`. Synthetic latency measures local
contract work only.
Real-image evaluator latency includes request, parse, gate and decision, but not
OS capture or the full two-request activation delay; measure those physically.

Nonzero exit signals a critical false positive, stale admission or HTTP error.
Zero exit does not certify corpus coverage or thresholds; inspect every metric.
`beta_acceptance` is always false. Per-actionable-decision exactness and coverage
need manual review, because aggregate accuracy can hide consequential errors.

## Retention

Keep real images and labels under ignored `.local/`, with local access and a
defined retention period. Avoid real images in CI, issues and candidate archives.
The tool does not delete user fixtures. Review local server logs, crash dumps and
OS swap separately. Only sanitized aggregate reports belong in acceptance evidence.
