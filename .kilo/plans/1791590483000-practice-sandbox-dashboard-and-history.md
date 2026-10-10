# Practice-Sandbox Dashboard, Observed History, and Seated Data

## Plan Adjustment: Role-Aware Monitor + Reference (2026-10-10)

**Checkpoint A completed (software/UI only):** 402 Rust passes (one ignored),
79 Python passes and 47 desktop/400px browser passes. Reference is bundled and
works on the retained canonical server; Python DTO/route refresh is deferred to
the controlled B restart. No live source/recorder or physical role/latency
acceptance yet. Actual receipts and limitations are in readiness Addendum 12 and
`.local/laya/train/role-aware-20261010/`. B remains an explicit question-tool gate.

**Authorization update `2026-10-10T06:27:30Z`:** the user explicitly requested a
thoughtful commit and push of all updates before checkpoint B. This supersedes
the no-commit/no-push/user-commits restriction for this reviewed batch only.
Private captures, local weights, environments and secrets remain excluded; no
release/workflow edits, new `.ps1` source files or permission to skip the B
checkpoint/human-session/training gates is implied.

Binding request received `2026-10-10T05:37:13Z`. This section supersedes the
P1 dashboard content/design and its operator-launched CLI profile step, together
with conflicting replay/diagnostic presentation and manual-connect instructions
below. Historical results and the original Gate F FAIL remain unchanged.

- Exactly two user-facing views: **Monitor** and **Reference**. Remove Replay and
  Checkpoint from the app. Keep diagnostics, freshness checks, private ledgers and
  fixtures in logs, optional hidden debug endpoints or test-only code.
- Monitor is action-first: a separate highlighted **Suggested action** box with
  move, amount and one short reason. Supporting readings cover phase, board, hero
  cards, pot, visible wagers, amount to call, stack, independently available actions
  (multi-label; Raise includes re-raises), hand rank, pot odds, draw outs/odds,
  equity and recent folds/bets/raises with known 3-bet/4-bet context.
- Automatically follow Observing, Seated/waiting, Your turn and Uncertain states.
  Observing continuously tracks table readings/history and labels pot odds with
  the acting seat, never a fabricated "your call". Waiting says "Waiting for your
  turn"; highlight suggestions only on the user's current turn. Uncertainty is
  one short "Reading uncertain" line. Sitting down does not restart monitoring
  or discard observing history. Disconnected/empty Monitor is one compact message.
- No connect controls: calibrate the practice executable/title once using local
  `--list-windows`, asking only if ambiguous, then attach automatically through
  the existing launcher. Never seat, click, type, or play for the user.
- Research a concise locally bundled, searchable/collapsible Reference from
  several reputable education sources: rankings; pot odds/required equity; outs,
  rule of 2/4 versus exact odds; six-max positions/opening ranges; facing raises,
  3-bets/4-bets; glossary. Independently check arithmetic and identify strategy
  applicability. Root charts/PDF remain reference material, not seated UI data.
- Warm capture-to-Monitor p95 must be <5000 ms across all measured stages; late
  results are withheld. Optimize measured bottlenecks without relaxing freshness
  or fitted thresholds. Reuse the pinned it1 checkpoint; never duplicate GPU work.
- Practice Games/practice chips are the target. Practice and cash share the same
  repo/mechanism; this is not real-money acceptance. Suggestions remain OFF until
  explicitly verified positive seated data and all quality/performance gates pass.
- Preserve every uncommitted change and it1 dataset/weights. No commits, pushes,
  uploads, release/workflow edits or new `.ps1` files; extend existing scripts.
  Root `lobby-screengrab.png` is for the user to delete, not the agent.

### Ordered Checkpoints (Explicit Question-Tool Approval Required)

A. Simplify Monitor/Reference, implement role/observing presentation, research the
Reference, update desktop/~400px tests and retain security/freshness guarantees.
Stop and ask before B; silence is not approval.

B. Integrate a private bounded native image recorder under
`.local/captures/<UTC>-practice/` with hashed manifest, calibrated auto-attach and
source-current history connection. Run deterministic tests, then use existing
`scripts/start-vlm.ps1` and verify the canonical `http://127.0.0.1:18090/`. Inspect
OS listeners/processes before any model launch; reuse an existing instance.
Stop and ask before C.

C. LIVE SESSION 1: user opens a six-max Practice Games table without sitting and
watches Monitor beside it for about 10 minutes. Verify Observing, timely board/
pot/wagers, betting activity/gaps and private frames. Record UTC, latency p50/p95
and human observations; fix/repeat only if needed. Stop and ask before D.

D. LIVE SESSION 2: suggestions OFF; user seats with practice chips and chooses
every action during 20-30 minutes. Verify role transitions without history loss;
collect genuine hero/cards/turn/buttons (presence/enabled/disabled), amounts,
stack/raise bounds and opponent badges; measure actual seated regions. Stop and
ask before E and separately before GPU training.

E. Create a NEW versioned local dataset, split by hand/session/time, leaving it1
unchanged. Explicit human verification of a finite >=60-frame held-out checklist
is required; agent review is not approval. Only after GPU approval train one
candidate from it1, sequentially. Fit calibration only, score held-out/late data:
screen_kind >=98% precision/95% coverage; phase/path >=98%; hero/board cards and
critical amounts >=99% precision/85% coverage; each action button >=98% precision/
95% recall with >=20 distinct positive opportunities; warm end-to-end p95 <5000 ms.
Never lower fitted thresholds or clamp; no confident items is a failure. Stop and
ask before F.

F. Only if gates pass enable validated, current-turn suggestions, retaining
heads-up-only raising and multiway all-in guards. LIVE SESSION 3 verifies manual
practice play, turn-bound appearance/clearing and screen-matching readings/odds.
If any gate fails, report honestly, keep suggestions OFF and Monitor useful for
readings/history, update records and stop.

Record command UTC start/end, exit codes and stderr privately; append actual
results to Addendum 12, update `LAYA_VISION_PHASE_A.md` section 7, README and
`EVENTS_V2.md`. Report six-max-only coverage, thin lobby evaluation, omitted
release server packaging, cursor compositing, local-only weights and untested
currency glyphs. Template matching remains an option for the user's decision.

Planned 2026-10-10. Repo: `C:\Users\cld-main\Desktop\github-projects\coinpoker-help`.
Branch at the preceding closeout: `checkpoint/seated-read-mechanism-2-20261002`, HEAD `4ccad18`.
Inspect the actual branch/worktree before implementation; preserve every existing change. The user commits.

## 1. Decisions and Scope

- Pixel source: the actual CoinPoker client using Practice Games and practice chips, as confirmed by the user. This is development/testing, not a real-money deployment or acceptance claim.
- One repo, representation, and mechanism for table states. Do not create a separate practice-mode model or repo, or a practice-only bypass of validation.
- Canonical service and browser address: `http://127.0.0.1:18090/`. No production `8080`/`18080` endpoints or automatic alternate-port fallback.
- Browser controls are read-only. Existing scripts/CLI launch and stop processes. Do not implement HTTP Start/Pause/Stop, seating, betting, or poker-client input controls.
- History: private, bounded per-session ledger under `.local/`, with opaque session/table/seat-occupant identities. No public player names, uploads, or cross-session identity merging by guessed OCR names or seat numbers.
- The user's later practice-sandbox clarification supersedes the earlier offline-only selection. This plan targets actual Practice Games development, not real-money/public deployment or a production-readiness claim.
- No automated poker actions, hotkeys, client clicks/keystrokes, financial operations, concealment, or evasion. The user alone seats, plays, and leaves.
- A first seated session is conditional on a tested recorder and a separate explicit go-ahead. The initial collector-first question was dismissed, not approved. Do not interpret willingness to play later as permission to start a capture or training job now.
- Proposed performance requirement: warm capture-to-display p95 <5000 ms, with a hard 5000 ms end-to-end deadline. This is an upper bound, not an intentional delay. Accuracy, confidence, and freshness safeguards are not relaxed.
- Implement UI/docs/history infrastructure first. Actual seated collection, paid/GPU training work, and advice activation each have later checkpoints below. No automatic it2/it3 or retraining of completed work.

This is the active follow-on plan. Preserve the earlier Gate F plan and Addendum 10 as history; do not execute their obsolete pending tasks, eight-label lobby import, or threshold-clamping branch.

## 2. Verified Starting Point

- Existing it1 checkpoint: `models/laya-vision/finetuned/20261009T190322Z-it1`; base `thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc`. Download, training, dumps, calibration, scoring, and pin verification already happened. Reuse them.
- Existing outcome is Gate F FAIL, human verification UNVERIFIED, source/vendor `calibrated:false`. On 66 agent-reviewed frames, board raw accuracy was 307/330 = 93.03%, but fitted threshold 1.0 produced 0/330 confident units. Never clamp that threshold down.
- Warm benchmark p95: p0 271.0 ms, tier01 1497.9 ms, full observation battery 3027.3 ms. The latter is numerically below the newly proposed 5-second budget, but it is not a seated or end-to-end decision benchmark. The historical failure remains an honest historical result.
- `screenshot-1.png` is a draw-odds reference, `screenshot-2.png` a six-handed raise-first-in reference, and `poker-info-sheet.pdf` a 15-page rules/strategy document. None is an actual seated CoinPoker UI capture. Do not label them as positive hero-button/card examples.
- `scripts/laya-server.py` currently serves model metadata/predictions only; `/` is 404. It verifies/loads/warms before binding a single-thread HTTP server, so predictions block all HTTP requests and a failed model prevents a dashboard from opening.
- `crates/ingest/src/laya/assembly.rs:231-242` admits only confidently unseated observations. Its state has no players or available actions. Changing the calibrated flag alone cannot enable seated advice.
- `bin/main.rs:100-102` hardcodes opponent archetype Unknown; watching-history accumulation is not connected. Existing `opponent-model` statistics are reusable, not a complete observer.
- Existing table events contain cards/action-required but no current-actions lease. They are weaker than advice admission and cannot be presented as trustworthy current hero controls.

## 3. Meaning of the Metrics and Timing

Raw accuracy compares model answers with labeled image units before confidence filtering, not with the reference charts and not with whole hands or optimal decisions.

- Card unit: one slot; both rank and suit must match. Existing aggregates include empty slots; additionally report actual-card and no-card strata so empty-board accuracy cannot conceal missed cards.
- Amount unit: a complete correctly segmented/labeled glyph sequence; every glyph must match. Incomplete units do not count as correct.
- Binary/control unit: one answer. The old all-negative `act_*` corpus tests absence, not positive-button recognition. Report positive-class TP/FP/FN, precision and recall separately from selective answer accuracy and coverage.
- Reference tests: exact ranks, draw-completion probabilities, opening-range membership, and pot-odds arithmetic. These are tests of deterministic calculations, not perception accuracy or guaranteed poker equity.

The current full benchmark makes nine serial HTTP passes: p0, board, pot, and six stacks. A larger seated/history battery could be slower. Profile capture/stability, crop/encode, HTTP, GPU, glyph processing, history, equity/decision, transport, and browser rendering separately. Do not assume the maths is the bottleneck or that a multimodal transformer must take five seconds to decide.

## 4. P0: Preserve the Baseline and Decruft Active Instructions

1. Inspect OS processes and persisted logs before any model start; never duplicate a GPU instance. Preserve old checkpoints, datasets, labels, scores, and the failed-gate receipt.
2. Correct `README.md` and `MODEL_LICENSES.md` first. Cross-check active instructions in `INSTALL_WINDOWS.md`, `VLM_COMPATIBILITY.md`, `CONTRIBUTING.md`, `SECURITY.md`, `EVENTS_V2.md`, and current sections of `LAYA_VISION_PHASE_A.md`, `WINDOWS_ACCEPTANCE_V1.md`, and `WINDOWS_VALIDATION.md`. Historical evidence rows remain historical.
3. Document the actual Laya alias, predict API, local runtime, verified checkpoint, temperature calibration versus quality approval, and the new read-only dashboard. Remove the obsolete remote opt-in instructions.
4. Make every active default, launcher, doctor probe, new example, and browser/feed target use 18090. Reject an explicit retired product endpoint with a useful configuration error rather than connecting to another application on 8080. Do not kill an unowned process if 18090 is occupied.
5. Do not globally replace historical port numbers, immutable run logs, deliberately hostile URL tests, or third-party dependencies. Mark retained Gemma evidence as historical. `scripts/vlm-pins.json` remains an orphaned historical manifest until the separately restricted release packaging is addressed.
6. Keep current provenance truthful: source MIT, Laya code/backbone licenses, CC-BY-NC-SA-4.0 base/derivative weights, private captures, local-only weights. A fresh install cannot download this user's fine-tuned derivative.
7. No commits, pushes, uploads, release/workflow edits, or new `.ps1` files. Extend existing launch scripts if necessary. Record packaging omissions; do not silently fix a prohibited workflow change.

Root `lobby-screengrab.png` remains for user deletion; its eval-only copy stays intact. Do not delete the two reference PNGs or PDF, or import them into the vision dataset.

## 5. P1: Read-Only Browser Dashboard on the Same Port

Use local HTML/CSS/vanilla JS, not a new framework/backend or native desktop workstream. Suggested files: a small `scripts/dashboard/` static asset set plus a narrow service/state helper used by `laya-server.py`.

### Service and Feed

- `GET /` serves the dashboard; `GET /api/state` returns a bounded, sanitized snapshot. Preserve `/v1/models` and `/v1/laya/predict`.
- Bind the UI/status listener independently of asynchronous model verification/loading. Keep predictions unavailable until existing pin/runtime verification succeeds; expose loading/verification-failed states without inventing model readiness.
- Use concurrent bounded HTTP handling. Keep a single nonblocking GPU admission slot; busy predictions fail safely rather than accumulating. A timed-out client does not cancel GPU work; hold the slot until actual completion and discard late results.
- Keep UI/status requests independent of the GPU lock. Add a test where slow prediction cannot block `/api/state` or clearing.
- Operator-launched capture uses existing scripts/CLI. Prefer an explicit launcher option supervising exactly one Rust passive process and reading its UTF-8 JSONL stdout through a local pipe; no second port or HTTP event-writer endpoint. Default UI-only/replay startup must not start live capture.
- Continuously drain and validate the feed independently of browser polling. Bound record size/state buffers, assign stream-session identity and monotonic event sequence numbers, and stop only owned children on shutdown.
- Start with one outstanding browser poll every 200-250 ms. SSE is not needed initially.

### Dashboard Content

- Prominent source/readiness strip: reference/demo, practice-development capture, capture healthy/unavailable, model loading/ready, quality gate failed/pending/passed, and observation age.
- Separate cards for observed hero controls, history, detected cards/hand rank, pot/call/raise amounts, calculation assumptions, and eventual recommendation. Never equate seating controls, available actions, and recommended actions.
- Controls use independent presence and enabled-state labels: present/absent/unknown and enabled/disabled/unknown. The first model may show only experimental diagnostics, not trusted legal actions.
- Model loading, schema validity, and freshness do not establish perception quality. Until the relevant capability gate is approved, label its fields experimental and do not use them for advice or eligible opponent statistics. Legacy unseated `to_call=0`/`hero_chips=0` placeholders render as unavailable, not verified zero amounts.
- All 66 prior checklist rows being matched is annotation verification, not a claim that all model answers were correct. Keep that distinction visible in reports.
- Reference/replay panel uses existing `outs.rs`, `pot_odds.rs`, `ranges.rs`, and verified hand-ranking examples from the root references. Reference charts are not live advice or UI-positive training data.
- Label draw-completion chance separately from win equity. Pot odds are `to_call / (pot + to_call)` and undefined without a verified call amount. The opening chart applies only to verified unopened-pot/position context, not a 3-bet defense range.
- Show starting-hand notation preflop; calculate a best-five hand rank only when enough verified cards exist. Unknown hero cards/amounts produce unavailable metrics, not fabricated zero values.
- Use a compact dark instrument-panel layout, clear text badges and suited-card colors; no external fonts/CDNs, gratuitous animation, or color-only safety indications.

### Freshness and Privacy

- Rust remains the authority for admitted observations and recommendations. Raw model responses and answer logs are diagnostics, not advice inputs.
- Add a separately admitted current-observation/actions event with source ticket, capture time, table/session/epoch, validity, and expiry. Do not reuse the current weaker `table.action_required` event.
- Add invalidation and capture-health heartbeat even when no advice exists; current `clear` only occurs for an active recommendation. EOF, new stream, target loss/change, stale/obsolete frame, turn/state change, errors, and expiry clear current controls and advice.
- A poll must not renew an old lease. Browser expiry uses the stricter source absolute expiry and locally tracked monotonic remaining lifetime; resume/background changes clear first and revalidate. Old/out-of-order responses cannot reactivate cleared content.
- Bind loopback only; validate Host/Origin, avoid wildcard CORS, use restrictive CSP and safe text rendering, and cap request/response sizes. No arbitrary file-serving paths, raw images/responses, backend bodies, or player names in the browser DTO.
- Save any new test/capture pixels only under `.local/captures/`. Static reference facts can be rendered without copying PDF images into public assets.

## 6. P2: Hero-Independent Watching History

Add a pure, bounded observer/ledger in `crates/opponent-model`, independently of `Pipeline::decide` and whether hero cards exist. Feed it evidence-bearing observations, not browser snapshots or legacy table messages.

- Snapshot fields include table/capture session, sequence/time/ticket, known-or-unknown hand/street, physical seat and occupant generation, trusted action-badge occurrences, optional stack/current-street commitment, and per-field validity/confidence.
- A missing/default `bet_amount=0` is not observed zero. Missing or stale fields stay unknown. Six physical seat slots must not be confused with vector indices or player identities.
- Track fold/check/call/bet/raise as observed action kinds; all-in is an independent flag and may have unknown subtype. Keep this schema distinct from the recommendation enum.
- Count badge occurrences once, not every frame. Handle persistent/flickering badges and renewed identical actions; process duplicate capture IDs idempotently.
- Reconcile commitments with the prior wager when known. Distinguish forced blinds/antes, calls, opening bets, full raises, short all-in calls/raises, refunds, winnings, top-ups, and pot collection. Contradictions stay unknown.
- Derive 3-bet/4-bet context only from a trusted ordered preflop aggressive prefix. Simultaneous changes or missed opening/intervening actions make the ordinal unknown. Incomplete all-in raises are recorded separately; do not silently treat them as full raises or reopened action.
- Hand boundaries require a readable hand ID or corroborated new-deal evidence. Board disappearance, payout, or clearing bets alone is insufficient. Mid-hand entry is partial.
- Target/session/occupant changes interrupt continuity. Preserve confirmed history while marking gaps; never fabricate skipped action order from seat order.
- Private JSONL ledger under `.local/` stores opaque IDs and observations/gaps/coverage, not public names. Initial defaults: last 200 events in the browser, at most 10,000 events or 25 MiB per ledger session. At the limit, preserve the prefix and explicitly report recording/coverage incomplete; never silently discard evidence and claim continuity. Do not delete unrelated captures or prior records.
- Show observed counts/lower bounds and coverage first. Rates use only known eligible opportunities. `observe_hand(bool,bool)` cannot represent unknown: update once only when VPIP/PFR outcomes are established, never unknown=false.
- Retain Unknown profiles until enough trustworthy eligible hands/action opportunities exist. Existing minimum 20 hands and AF threshold-distance confidence are not observation-quality guarantees; zero-call AF is not evidence of reliable aggression.
- Initial decision baseline still estimates equity against unknown/uniform opponents. Do not claim that merely wiring counters creates history-conditioned ranges or measured fold equity. Any later profile adjustment needs explicit eligibility, visible assumptions, and separate tests; weighted/history-conditioned range modelling is not an automatic addition.

Semantic action extraction needs actual badge/bet examples and a quality gate. Start ledger/UI tests with synthetic/annotated replay DTOs. New real-model history extraction stays experimental until validated. Lightweight capture can continue while advice inference is busy, but do not promise complete history at a sampling rate that misses actions; record those gaps.

## 7. P3: UI and Recorder Readiness Checkpoint

Complete deterministic UI/feed/history tests first, then sequential model/status checks using the already downloaded it1 checkpoint. Do not refit or repeat old dumps merely to test the page.

`COLLECTOR_READY` means the dashboard, intended target/capture profile, source timestamps, recorder counters, and private output location have been tested. It is not a recommendation or a signal that the model knows when to call.

Provide an operator checklist in the dashboard/docs:

1. Launch the existing local service/script and open `http://127.0.0.1:18090/`.
2. See the baseline model/quality status and exercise explicitly marked replay cases; confirm clearing/disconnect/busy behavior.
3. Open/select the Practice Games table manually. Verify six-max and a measured capture size/profile; record exact app/window identity rather than guessing a table from its title.
4. Start the explicitly configured passive capture from the existing launcher/CLI. Confirm counter/timestamp progress before changing the game state.
5. Only after a separate user go-ahead, start the seated-data session. The user uses the client's Find Seat/empty-seat/Join Wait List UI and all buy-in/play controls themselves. Do not promise that a full table immediately has an available seat.

If the user does not want to make independent plays before advice exists, stop at dashboard/replay/watching infrastructure and await genuine UI examples. The dismissed planning question is not authorization to proceed.

## 8. P4: Positive Seated Data, New Versioned Dataset

This is a separately authorized session in this repo. No client input is automated, and advice remains blocked during initial collection.

- Capture genuine hero cards, hero turn/waiting states, and offered Fold/Check/Call/Bet/Raise/All-in controls, including present-but-disabled, negative, occluded, and ambiguous cases. Do not mistake opponent FOLD/RAISE badges for hero buttons.
- Measure hero-card, controls, to-call, hero-stack, raise-bound, button/position, opponent-badge and commitment regions from actual practice captures. Existing provisional rectangles are not validated measurements.
- Initially support one explicitly measured six-max seated profile/size; add another only with its own evidence. Record geometry/DPI/profile metadata and unknown currency/glyph cases; do not fork the representation for practice versus cash.
- Label positive/negative classes independently and keep uncertainty explicit. Do not carry the old hardcoded false action labels into new seated data. Presence is not enabled/legal availability.
- Keep existing it1 inputs immutable. New manifests, labels, region versions, examples and provenance live under a separate `.local/` dataset generation. Split by hand/session/time blocks, never adjacent frames of the same opportunity across train/calib/eval.
- Preserve the single eval-only lobby import; reference PNGs/PDF are never synthetic seated positives. Root references support deterministic tests and explanations only.
- Capture distinct opportunities across hands; twenty repeated frames of one button state are not twenty independent positive opportunities. Report per-class event counts. Do not force the user to make particular bets/all-ins just to fill a dataset.
- Use a new question/region version for new semantic fields (proposed 0.5.x). Preserve existing qid/option ordering where reused; record migration and hashes. Do not overwrite the 0.4 baseline or silently relabel its raw predictions.
- Present a finite selected held-out checklist with at least 60 explicitly verified eval frames, precise row/frame IDs and uncertainty exclusions. Agent review is useful but is not automatically human certification; omitted rows and silence remain unverified.

## 9. P5: Bounded Training, Quality and Performance

Only after dataset/labels and a specific compute budget are approved: train one separately named candidate initialized from the existing checkpoint when appropriate. No base redownload, automatic it2/it3 loop, or concurrent server/dump/training GPU jobs. Hash frozen inputs at start/end; retain the old checkpoint and all outcomes.

Proposed seated/history acceptance, approved before training:

- Preserve existing pass-level targets: screen_kind >=98% precision/95% coverage; phase/path questions >=98% selective accuracy; required card and complete-amount units >=99% precision/85% coverage.
- Apply card/amount targets to new critical hero cards, board, pot, call cost, hero stack, required commitments and raise bounds. Report real-card and empty-slot results separately.
- For each enabled-action class, report positive precision/recall, negatives, unknowns and coverage. Proposed minima: >=98% positive precision and >=95% positive recall, with at least 20 distinct positive opportunities in calibration and held-out evaluation, plus meaningful negative/disabled examples. Report uncertainty/sample sizes; this does not establish population accuracy with statistical certainty.
- Classes with no positive support are unvalidated, not perfect. Missing critical capabilities keep advice blocked; do not promote an unknown All-in/disabled-state detector to false.
- Observer action/order/count tests use labeled sequences. Ambiguous/gapped sequences must remain partial; confident invented events are failures. Statistics are not calibrated merely because the ledger's code tests pass.
- Fit on calibration only; score held-out and late/sensitivity data. Use pass thresholds never below fitted values. No confident units/undefined precision is a fail. No 1.0-to-0.99 clamp or hand-answer repair.
- Keep confidence calibration, model-loaded status, per-capability quality approval, and advice activation separate. Preserve the original FAIL/UNVERIFIED record regardless of the new candidate outcome.

Performance work follows measurement: batch compatible crops/questions, avoid repeated encoding/token work, gate inference on validated changed regions, and consider safe feature reuse only with complete source/epoch invalidation. Keep one model instance. A different classifier/template primary path is a later explicit decision, not an unannounced new workstream or a shortcut evaluated against its own auto-labeler.

Add an explicit total decision deadline anchored to the source capture/opportunity timestamp, rather than assuming the existing 5-second per-request timeout limits an entire multi-pass battery. Each downstream phase receives only the remaining budget, with time reserved for event transport and browser polling/rendering. Newly delivered results after the deadline are withheld, not given a fresh display lease. Existing max-frame-age/refresh/lease defaults remain independent and are not enlarged to make the benchmark pass.

Benchmark p0, normal observation, full history/seated battery, and actual capture-to-browser result paths separately. Include stability/capture, all required inference, history, equity/decision, admission, transport and rendering in end-to-end timing. No eligible/confident decisions is not a latency success. Warm p95 must be <5000 ms for usable eligible results; any result finishing after the hard deadline is withheld. UI/status must remain responsive throughout and clear within one bounded poll/expiry cycle.

## 10. P6: Validated Seated Branch and Sandbox Guidance

Implement the future seated branch behind explicit capability approval; do not simply remove R17 or flip `calibrated:true`.

- Require trusted hero mapping/cards, board/street, amounts, enabled offered actions, and any required raise bounds. Validate card uniqueness, unit consistency, legal availability and source freshness.
- Keep unknown/partial states non-actionable. Currency glyphs, unmapped layouts, contradictory actions, incomplete fields, and unsupported situations produce a clear reason, not guessed state.
- Publish current controls independently from advice, both with source-bound expiry/invalidation. Decision publication still requires the full Rust admission and lease checks.
- Use exact hand ranking and deterministic pot odds; label Monte Carlo equity assumptions and uncertainty. Recommendations are highest modelled EV among validated legal choices, not guaranteed optimal plays or guaranteed wins.
- Use history context only when verified. Opening ranges are not 3-bet defense ranges. Keep Unknown/uniform-range assumptions visible until a separately validated history-aware range policy exists.
- Preserve current heads-up-only raising and multiway all-in/side-pot guards. Six-max capture support is not complete six-player strategy support. Do not widen these guards to make the UI look complete.
- `ADVICE_READY` requires verified positive data, quality/performance gates and an explicitly approved manual practice-development acceptance session. Each displayed recommendation still expires or clears immediately when its turn/state is no longer current.
- Practice and cash remain the same technical mechanism, but this plan provides no cash/real-money acceptance. No automated actions are added at any stage.

## 11. Validation Matrix and Completion Records

- Docs/defaults: active code/help/scripts/docs agree on 18090/Laya; no old endpoint fallback; licenses/provenance and current capability gaps are accurate. Historical receipts stay intact.
- Server/UI: model-loading/failed-pin states, root page, alias/routes, slow/busy inference, request bounds, origin/host rejection, XSS/text safety, no raw data leakage, no arbitrary file serving.
- Freshness: no-active-advice invalidation, old table event, stream reset/EOF, wrong session/table/epoch, delayed/out-of-order snapshots, expired leases, browser background/resume, heartbeat loss, timeout without GPU cancellation, no lease renewal by polling.
- History: repeated badges, legitimate repeated actions, duplicate captures, occupant/table replacement, partial hand, missed/multiple transitions, blinds/antes, short all-in, refunds/top-ups/payout, uncertain new hand, 3-/4-bet known and unknown sequences, eligible-rate denominators and low-sample Unknown profiles.
- Maths/reference/replay: PDF hand rankings/kickers/ace-low/ties, known odds examples, exact versus approximate draw probabilities, pot-odds undefined cases, RFI context restrictions, and legal raise caps. Demo/replay must not be mistaken for live guidance or actual positive UI data.
- Data/model: immutable prior inputs/weights, new hashes and split provenance, explicit verified frame filters, all per-class positives/negatives, threshold failures honestly retained, no training/eval leakage or self-validating template ground truth.
- Integration: Rust tests, relevant Python tests, browser desktop/small-window tests, build/doctor where permitted after code changes. These are new-change validations, not repetition of old model work. No release/workflow edits.
- Record UTC command start/end, exit codes, stderr, model/version/hash, quality and p50/p95 results, session scope, source/verification authority and outstanding gaps. Add a new follow-on addendum; do not rewrite Addendum 10's historical failed acceptance.

Phase-one completion means cleaned active docs plus tested read-only dashboard/feed/ledger infrastructure, with an honest baseline-failed/no-advice state. Stop at the manual data checkpoint. Positive collection, compute and final guidance are separately gated milestones, not actions to launch during planning or silently after the first implementation pass.
