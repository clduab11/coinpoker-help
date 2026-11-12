# Plan — Land main, decruft, then self-sufficient play

Status: awaiting user approval. Owner decisions taken 2026-11-12:

1. Merge **via GitHub PR #13** (local resolution + validation first; GitHub writes the merge commit on `main`).
2. Order: **merge → decruft → self-play**, and **no CoinPoker client launch until the tree is provably error-free** (offline battery green, nothing unverified that can be verified before launch).
3. Decruft scope this pass: **stale docs + superseded root `HANDOFF.md`** only (other candidates listed as deferred, §6).
4. Overlay: **port main's overlay/ws into `bin/ui/` and wire it to the live decision path** (no crate resurrection, no `bin/src` lib split now).

Governing doc for Stage 3: the handoff at `.local/handoffs/HANDOFF-SELF-SUFFICIENT-PLAY-20261111.md` (becomes root `HANDOFF.md` in Stage 2). It governs its own phases; this plan adds only the merge/decruft stages and the pre-launch gate.

---

## 0. Measured state (verify before relying)

- Current branch `checkpoint/seated-read-mechanism-2-20261002` @ `0e516ec3` (= pushed to origin). `main` @ `4a91af94` (= origin/main), frozen since 2026-09-20. Merge base `0dfe5fa8`.
- Branch has 43 commits main lacks (the entire Windows/live/laya/seated/self-play line, Sept→Nov 10). Main has 7 commits the branch lacks: `ba8c07c7` quality tooling + `29174a3a` VLM-ingestion refactor + 5 commits of a working **study overlay** (`--ui`, egui click-through window, ws mirror, adaptive settings).
- PR #13 is open (branch → main). 12 stale dependabot PRs are open.
- The branch consolidated `crates/ui` → `bin/ui`, `ghost-layer`/`opponent-model` → `core-engine::{mimicry,opponent}`. Main still edited the old crate paths — the merge must port those deltas (see §2 resolution table).
- `insta`/`proptest` (main's dev-deps for snapshots/proptests) are **not** in the local cargo cache; one `cargo fetch`-style online resolution will be needed once, then `--offline --locked` holds.
- Handoff baseline at `0e516ec3`: `cargo test --workspace --offline --locked` = 661 pass / 6 ignored; toolchain 1.95.0; python env `.local/laya-runtime/env/python.exe`. Re-verify at merged tip.

Guardrails (apply to every stage): work in QUIET lane unless a step needs INPUT/CLIENT (announce per `docs/OPERATIONS.md`, then "machine free"); soft-delete only (`to-be-deleted/` staging + manifest, Chris empties); no co-author/generated-by lines; receipts under `.local/<task>/<UTC>/`, never overwrite an old receipt dir; no policy-derived gates.

---

## Stage 1 — Land on main via PR #13

Definition of done: `origin/main` contains everything (branch's 43 commits + main's 7, reconciled), PR #13 shows merged, local `main` == `origin/main`, full offline battery green at the merged tip, overlay builds and its unit tests pass.

### 1.1 Preflight (no mutations)

1. Confirm clean tree; record HEADs; note the node: `git status --short` empty.
2. Safety refs: `git branch backup/premerge-main 4a91af94` and `git branch backup/premerge-checkpoint 0e516ec3` (local only; never force-moved).
3. `.local/merge-<UTC>/` receipt dir for all logs below.

### 1.2 Merge main into the branch (resolve on the branch)

1. `git checkout checkpoint/seated-read-mechanism-2-20261002` (already), then `git merge origin/main`.
2. Resolve per the table. Rule: **branch content wins on shared files; main-only assets land; main's deltas on old paths are ported into the branch's new locations.** No "accept both" duplication.

| From main | Destination / action |
|---|---|
| `crates/ui/src/overlay.rs` | `bin/ui/overlay.rs`; rewrite `crate::widgets` → `super::widgets` |
| `crates/ui/src/ws.rs` | `bin/ui/ws.rs`; rewrite `crate::overlay` → `super::overlay` |
| `crates/ui/tests/ws.rs` | `bin/tests/ws.rs` via `#[path = "../ui/mod.rs"] mod ui;` (precedent: `bin/tests/pipeline_smoke.rs`), gated `#[cfg(feature = "ws")]` |
| `crates/ui/src/snapshots/*.snap` | `bin/ui/snapshots/` (+ `insta` dev-dep in `bin/Cargo.toml`); review via insta, do not blind-accept |
| `crates/ui/src/app.rs`, `widgets.rs`, `headless.rs` deltas | port onto `bin/ui/app.rs`, `bin/ui/widgets.rs`, `bin/ui/headless.rs` (`run_overlay`, overlay panel, decision-view changes) |
| `crates/ui/src/lib.rs` module list | fold into `bin/ui/mod.rs`: `pub mod overlay;` always, `pub mod ws;` behind `ws`, `app` behind `desktop` |
| keep branch's deletion of `crates/ui` directory | yes — do not resurrect the crate |
| `bin/Cargo.toml` | keep branch package; features `desktop = ["dep:egui","dep:eframe"]`, `ws = []`, `default = ["desktop"]`; dev-dep `insta`; `[[test]] ws` with `required-features = ["ws"]` |
| `bin/config.rs` | replace `--ui` "unavailable" error with real `Mode::Ui`; port `--overlay-opacity` / `--overlay-position` parsing + validation from main's `bin/src/cli.rs` |
| `bin/live.rs` | add event sink: on emitted decision → `OverlayEvent::Decision`, clear reasons → `Clear(reason)`, window bounds → `Position`; `--ui` spawns the live loop on a worker thread and runs `run_overlay` on the main thread (eframe); ws mirror behind feature `ws` |
| `bin/src/{cli,config,lib,pipeline}.rs`, `bin/build.rs` | superseded by branch layout — **do not keep `bin/src/`**; port anything the kept tests need (fixtures `bin/tests/fixtures/*.json`, `pipeline_smoke`/`cli` deltas, `MIN_PERCEPTION_CONFIDENCE` usage). Note the deliberate call in the merge commit message; optional lib-split refactor deferred |
| `crates/ingest/src/{vlm,parser,state_machine,capture,change_detect,lib}.rs` | branch files win; port main-only files `consensus.rs`, `schema.rs`, `record.rs`, `roi.rs`, `build.rs`, `proptest-regressions/*`, `src/snapshots/*.snap`, `tests/zone_detect.rs` + PNG fixtures. Wire into `lib.rs`; if a module cannot compile against branch APIs, adapt it or stage it out **with a manifest note** — no dead module silently kept |
| `crates/ghost-layer/*`, `crates/opponent-model/*` deltas | 3-way diff each old-path file against the branch's `crates/core-engine/src/{mimicry,opponent}/*`; port missing deltas (e.g. adaptive study-settings wiring in `betting_entropy`) |
| `Cargo.toml` (workspace) | branch members; add main's workspace dev-deps `proptest`, `insta`; adopt `serde_json` `float_roundtrip`; keep main's coverage metadata comment |
| `Cargo.lock` | regenerate (see 1.3 step 1) |
| `.github/workflows/ci.yml` | branch file wins; add back main's `doc tests`, `audit`, `shellcheck` jobs on branch's pinned 1.95 + win/ubuntu matrix; adopt `coverage` job only if locally green (`llvm-cov` install may be needed), else keep and let CI decide — record which |
| `README.md`, `CONTRIBUTING.md` | branch wins; add a short "Study overlay (`--ui`)" section + justfile mention; no stale claims |
| `justfile`, `.env.example`, `rust-toolchain.toml` | keep `justfile` (adjust shellcheck recipe target if needed); rewrite `.env.example` to the branch's actual env keys (`COINPOKER_EXE_NAME`, `COINPOKER_WINDOW_TITLE`, `COINPOKER_LOBBY_TITLE`, `COINPOKER_PID`, `COINPOKER_WINDOW_HWND`, `COINPOKER_LOBBY_SIZE`, `COINPOKER_CDP_PORT`, `COINPOKER_VLM_ENDPOINT` = `http://127.0.0.1:18090/v1/laya/predict`, `COINPOKER_SEED`; confirm against `bin/config.rs` literals). Toolchain stays 1.95.0 |

3. The only expected network touch: first resolution of `insta`/`proptest` (`cargo fetch` or a `cargo check` without `--offline`). After that, everything runs `--offline --locked`.
4. One merge commit (resolve + port + lock in it), repo-style message, no co-author lines. If the merge explodes beyond the table, stop, keep the partial resolution, record it in the receipt dir.

### 1.3 Validation battery (the "error-free" gate — run at the merged tip)

All green, output saved to `.local/merge-<UTC>/`:

```powershell
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --offline --locked -- -D warnings
cargo build --offline --locked -p coinpoker
cargo build --offline --locked -p coinpoker --features desktop,ws
cargo test --workspace --offline --locked
cargo test --workspace --all-targets --all-features --offline --locked
.local/laya-runtime/env/python.exe -B -m unittest discover -s scripts/tests
cargo run --locked --bin coinpoker -- --evaluate fixtures/synthetic/manifest.json
target/debug/coinpoker.exe --help          # and a --stdin smoke with a fixture line
pwsh -NoProfile -Command "<the CI PowerShell-syntax parse for download-model.ps1 + scripts/*.ps1>"
python -B -c "<the CI workflow-YAML validation call: scripts.validate.validate_workflow_workflows>"
```

No client launch in this stage. Test count must be ≥ handoff baseline (661) plus the ported tests; any snapshot mismatch is eyeballed, not `--accept` blindly.

### 1.4 Push and merge the PR

1. `git push origin checkpoint/seated-read-mechanism-2-20261002` (updates PR #13; its CI re-runs).
2. Wait for `gh pr checks 13` green (win + ubuntu quality incl. python suite, synthetic evaluate, PS syntax; any failure → fix on the branch and push again).
3. `gh pr merge 13 --merge` (merge commit; GitHub-side). If a repo setting forces another strategy, use it and note.
4. Local sync: `git fetch origin`, fast-forward `main` to `origin/main`; `git checkout main`; verify `git rev-parse main` == `git rev-parse origin/main`. Keep `checkpoint/*` branch and `backup/*` refs as archive.
5. Receipt: PR URL, merge commit sha, battery summary into `.local/merge-<UTC>/RESULT.md`.

Rollback: before the PR merge everything is local/branch-only; after, revert via `git revert -m 1` on a fixed main, or restore from `backup/premerge-*` refs. No force-push unless needed (note `--force-with-lease` accepted by policy).

---

## Stage 2 — Decruft: docs + superseded HANDOFF (approved scope)

Definition of done: every `docs/*.md` classified; superseded ones archived with a manifest; root `HANDOFF.md` replaced by the self-play handoff; zero dangling references; battery still green; nothing hard-deleted.

### 2.1 Sweep (evidence before any move)

1. Inventory all root `*.md` and `docs/*.md`. For each, build the reference list: live code/tests/CI/scripts, `README.md`, `AGENTS.md`, `docs/OPERATIONS.md`, `docs/PLAN.md`, `docs/PHASE0.md`, `docs/FAIRPLAY.md`, root `HANDOFF.md`, `.github/workflows/*`. Record in `.local/decruft-<UTC>/SWEEP.md`.
2. Classify: **keep** (referenced by anything live), **archive** (only historical refs, or superseded by the handoff/PLAN), **update** (kept but with stale links/claims to fix). The handoff's mandated reading and runbook set are keep-by-definition: `OPERATIONS.md`, `PLAN.md`, `PHASE0.md`, plus `FAIRPLAY.md`, `DETECTION.md`, `EVENTS_V2.md`, `SEATED_DIAGNOSTIC.md`, `INVENTORY.md` unless the sweep proves a doc dead and its live references are updated in the same commit.
3. Archive candidates (confirm by sweep; do not force): `WINDOWS_ACCEPTANCE_V1.md`, `WINDOWS_VALIDATION.md`, `VLM_COMPATIBILITY.md`, `VISUAL_EVALUATION_V2.md`, `LAYA_VISION_PHASE_A.md`, `INSTALL_WINDOWS.md`.

### 2.2 Mechanics

1. `git mv` archives to `docs/archive/`; append a table row per file to `docs/archive/README.md` (path, one-line reason, last-commit sha, date). `git mv` preserves history — no staging copy needed for moves.
2. True deletions (if any) → `to-be-deleted/20261112-decruft/` with `MANIFEST.md` (path, reason, sha), and add `/to-be-deleted/` to `.gitignore`. Chris empties the folder later.
3. HANDOFF: `git mv HANDOFF.md docs/archive/HANDOFF-20261025.md`; copy `.local/handoffs/HANDOFF-SELF-SUFFICIENT-PLAY-20261111.md` → root `HANDOFF.md` **verbatim** (it addresses the workspace root; no edits).
4. Fix inbound references (grep each archived filename across live files; update to the new path or to the root HANDOFF). Grep proof in the receipt.
5. Commits: small and classed (archive moves; ref fixups; HANDOFF replacement), repo-style messages.

### 2.3 Validation & push

Battery re-run (fmt/clippy/tests/python/evaluate; docs changes cannot break build, prove it anyway). Then push `main` to origin (Stage-1 push pattern; PR #13 is already merged, so this is a direct push — say so before pushing). Receipt: `.local/decruft-<UTC>/RESULT.md` with the manifest and grep proof.

Rollback: `git mv` back / restore from git history; staging folder means nothing is gone.

---

## Stage 3 — Handoff execution (self-sufficient play, Phases 0–6)

Governing doc: root `HANDOFF.md`. Everything in it applies unchanged (phases, acceptance tests, invariants, traps, reporting). Deltas and pointers from this merge/decruft:

1. **Pre-launch gate (user constraint):** no CoinPoker launch and no CLIENT lane until (a) Stage 1 battery green at the final tip, (b) Stage 2 battery green, (c) handoff §0 reading done, (d) a client-free smoke suite passes: `--help`, `--list-windows` (works without client), `--stdin` replay, `--evaluate`. Only then announce the CLIENT lane, launch per `docs/OPERATIONS.md`, and start Phase 0. Record the gate result in the first receipt.
2. **Re-baseline everything handoff-side:** all `.local/` receipts predate the current code (and now the merge) — treat as shape/history only; re-grep handoff file:line anchors after the merge (they may have shifted) before citing them.
3. **New capability available:** `--ui` overlay now runs on the merged tree (`--features desktop,ws` for the mirror). Use it opportunistically as extra evidence in Phases 4–5; it is not a gate.
4. **Phase 3.0 pointer:** `.local/phase1-seated/20261111T001424Z/` holds seated 800×613 material (`p1probe-hero_card_1/2.png`, `p0probe-body.json`, `run5–18.jsonl`). Verify freshness/labels first; use as the measurement source for the seven `provisional` regions if valid, else take a fresh seated capture. Promote regions only from measured evidence, per the handoff.
5. **Operator touchpoints** (announce each, per lanes): client running with `--remote-debugging-port=9222`; open exactly one table; keep it unobscured; seat the hero when Phase 3 requires; the handoff's seat-flow traps apply. Executor/input steps announce "taking input now" / "machine free".
6. **No commits during Stage 3** (handoff §0.4). Leave diffs + receipts; when Chris asks, commit per-phase with receipts referenced.
7. Phases run in handoff order 0→6, each ending with its acceptance receipt. If a phase blocks on an operator-only action or missing fact, record the exact predicate and continue to the next independent phase — never launch the client "to check" outside the gate.

---

## 4. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Overlay port breaks build/tests | smallest adaptation only (import rewrites + feature gates); unit tests must pass; all-features build is in the battery |
| `insta`/`proptest` offline resolution fails | one controlled `cargo fetch` (QUIET); then lock committed; CI is online anyway |
| Snapshot churn from merged parser | eyeball diffs; `--accept` only after review |
| Wrong conflict resolution silently drops Sept fixes (betting_entropy adaptive settings, quality fixtures) | explicit port list in §1.2 + 3-way diffs; battery + `gh pr checks` green before merge |
| Decruft over-removal | sweep evidence first, manifest per move, archive dir retains content, grep proof |
| eframe on ubuntu CI | already exercised by branch CI (`--all-features` with `desktop` feature); ws module is std-only |
| PR merge mechanics | `gh pr checks` green required; fallback strategy recorded if repo settings differ |
| Live-run interruptions during Stage 3 | lanes + announcements; long batches flagged; client untouched until gate |

## 5. Deferred candidates (not in this decruft pass; re-approve later)

- Untrack `graphify-out/` (~20 MB, regenerable) → gitignore + staged removal.
- Dead-script sweep (`scripts/*` + their tests; strict reference sweep, keep list: `action-executor.ps1`, `table-input.ps1`, `start-vlm.ps1`, `laya-server.py`, `laya_dashboard.py` + `scripts/dashboard/*`, `laya_capture.py`, `laya_prep.py`, `validate.py`, `doctor.py`).
- Dependabot triage (12 open PRs → rebase or close), `checkpoint/*` branch retirement, old `.local/` receipts.

## 6. Receipts and reporting

- `.local/merge-<UTC>/RESULT.md`, `.local/decruft-<UTC>/RESULT.md`; Stage 3 per handoff §8 format. Include "still unproven" lines in every report; a green battery never counts as live proof.

## 7. Open items resolved during execution

- Final archive set (from the sweep, §2.1) — recorded in the manifest before any move.
- Whether the coverage CI job stays (only if locally green; else CI decides and the outcome is recorded).
- Exact `--ui` threading details in `bin/live.rs` (follow main's `run_ui_overlay` shape; eframe on main thread).
