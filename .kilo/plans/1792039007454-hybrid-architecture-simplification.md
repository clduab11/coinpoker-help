# Hybrid Rust/Python Architecture Simplification Plan

## 1. Goal & Architectural Findings

Simplify the hybrid Rust/Python codebase by unifying duplicated geometry/region configuration, factoring internal modules in `scripts/laya-server.py`, and consolidating shared session/receipt/test boundaries in `bin/` without changing any external CLI, HTTP API, or test behavior.

### Validated Codebase Boundaries (vs. Initial Assumptions)
1. **Runtime Python Coupling**:
   - `scripts/laya-server.py` imports `laya_dashboard` and `laya_capture` at module load time, and `laya_dashboard.ManualSessionFeed.__init__` (used in `serve` mode) instantiates `laya_visual.VisualWorker`, which transitively imports `laya_board`, `laya_actions`, `laya_showdown`, `laya_numeric`, `laya_context`, `laya_evidence`, and `laya_prep`.
   - Over 20 test modules under `scripts/tests/` import `laya_*.py` directly from `scripts/` and resolve `ROOT = Path(__file__).resolve().parents[1]`. Therefore, existing top-level module paths in `scripts/` must remain intact.
2. **Supervisor/Child Split (`laya_capture.py` vs. `bin/manual_capture.rs`)**:
   - `scripts/laya_capture.py` (with `laya_attach.py`) is the parent supervisor that confirms windows, writes `.local/laya/manual-capture/<session_id>/approval.json`, manages `active.lock` / `status.json` / `STOP` / `run.json` / `summary.json`, and spawns `coinpoker --capture-only` or `coinpoker --manual-inference` (`bin/manual_capture.rs` and `bin/manual_inference.rs`). Both sides are required.
3. **Existing Hygiene & Manifests**:
   - `.gitignore` already excludes `/.conda/`, `/.local/`, `__pycache__/`, and `*.pyc`.
   - `scripts/vlm-pins.json` is still referenced by `.github/workflows/release-windows.yml` and documented as a retained historical manifest, so it must not be deleted.

---

## 2. Ordered Implementation Tasks

### Phase 1: Unify Geometry & Region Configuration (`regions.json` Single Source of Truth)

**Files**:
- `crates/ingest/assets/laya/regions.json` (canonical source, read-only)
- `scripts/laya_prep.py`
- `scripts/laya_visual.py`
- `scripts/laya_numeric.py`
- `crates/ingest/src/laya/geometry.rs`
- `scripts/tests/test_laya_board.py` (or dedicated geometry parity test in `scripts/tests/test_laya_server.py`)

**Steps**:
1. **Centralize `regions.json` loading in `scripts/laya_prep.py`**:
   - Add `REGIONS_REL_PATH = "crates/ingest/assets/laya/regions.json"` and a stdlib-only helper `load_regions(root=None)` in `scripts/laya_prep.py` that loads and parses `crates/ingest/assets/laya/regions.json` (using `functools.lru_cache` when `root is None`, and resolving relative to `Path(root)` when a custom root is supplied).
   - Derive `TITLE_BAR_PX`, `TITLE_BAR_RANGE`, and `CONTENT_ASPECT` in `scripts/laya_prep.py` from `load_regions()["geometry"]` (`title_bar_px`, `tuple(title_bar_range_px)`, `content_aspect`) while keeping those module-level constant names exported for backward compatibility.
   - Add `region_px(name, w, h, *, regions=None)` in `scripts/laya_prep.py` mirroring `crates/ingest/src/laya/geometry.rs::region_px`.
   - Keep `numpy` and `PIL` imports strictly lazy inside `_text_score`, `_text_mask`, `_components`, and `segment_glyphs` so importing `laya_prep` for geometry remains stdlib-only.
2. **Reuse `laya_prep.load_regions` across Python consumers**:
   - Update `scripts/laya_visual.py` (`VisualWorker._load`) and `scripts/laya_numeric.py` (`NumericReader.__init__`) to call `laya_prep.load_regions(self.root)` instead of duplicating raw `(self.root / "crates/ingest/assets/laya/regions.json").read_bytes()` JSON loads.
3. **Add cross-language Rust/Python geometry parity coverage**:
   - Expand `crates/ingest/src/laya/geometry.rs` tests and Python unit tests to verify identical `(x0, y0, cw, ch)` and `box_px` outputs across all 20 named regions in `regions.json` and across standard, letterboxed, pillarboxed, tiny, and `.5` half-to-even tie dimensions (e.g., dimensions where `w / content_aspect` or `avail_h * content_aspect` lands near `.5`).

---

### Phase 2: Internal Modularization of `scripts/laya-server.py`

**Files**:
- `scripts/laya-server.py`
- `scripts/laya_server_validation.py` (new internal helper module)
- `scripts/tests/test_laya_server.py`

**Constraints & Test Contracts to Preserve**:
- `scripts/tests/test_laya_server.py` and `scripts/tests/test_laya_dashboard.py` load `scripts/laya-server.py` via `importlib.util.spec_from_file_location` and access/patch module attributes on `srv`:
  - `srv.ROOT`, `srv.REPO`, `srv.HOST`, `srv.PORT`, `srv.PNG_SIG`, `srv.MAX_BODY`, `srv.MAX_READOUT_QUESTIONS`, `srv.MAX_ACCEPTANCE_REPORT`
  - `srv.ACCEPTANCE_PASSES`, `srv.STACK_PASSES`, `srv.WAGER_PASSES`, `srv.SCENE_PASSES`, `srv.WAGER_NOTE`, `srv.SCENE_NOTE`, `srv.EXPERIMENTAL_WAGER_NOTE`, `srv.EXPERIMENTAL_CHECKPOINT`, `srv.EXPERIMENTAL_MODEL_SHA256`, `srv.EXPERIMENTAL_BOUNDS`, `srv.SCENE_QUESTIONS`
  - `srv.RequestError`, `srv.load_pins`, `srv.png_size`, `srv.validate_request`, `srv.shape_answers`, `srv.answer_diagnostics`, `srv.wager_questions`, `srv.readout_core_template`
  - `srv.load_acceptance_floors`, `srv.load_seat_registry`, `srv.load_wager_registry`, `srv.load_scene_registry`, `srv.pinned_file_entries`, `srv.experimental_descriptor`, `srv.load_experimental_metadata`
  - `srv.Engine`, `srv.Service`, `srv.BoundedHTTPServer`, `srv.make_handler`, `srv.handle_predict`, `srv.handle_predict_batch`, `srv.verify`, `srv.cmd_verify`, `srv.cmd_fetch`, `srv.cmd_serve`, `srv.main`
- `test_invalid_report_precedes_every_heavy_import_and_model_load` intercepts `builtins.__import__` and forbids importing `laya`, `laya_prep`, `torch`, `PIL`, or `numpy` before `load_acceptance_floors(pins)` succeeds inside `Engine.__init__`.
- `AcceptanceTests` and experimental metadata tests patch `srv.ROOT` and `srv.REPO` via `unittest.mock.patch.object(srv, ...)`.

**Steps**:
1. **Extract pure request/protocol validation & diagnostics into `scripts/laya_server_validation.py`**:
   - Move protocol constants (`MAX_*`, `ID_RE`, `LAYOUTS`, `GLYPH_STYLES`, `PNG_SIG`, `ACCEPTANCE_PASSES`, `STACK_PASSES`, `WAGER_PASSES`, `SCENE_PASSES`, `WAGER_NOTE`, `SCENE_NOTE`, `EXPERIMENTAL_*`, `SCENE_QUESTIONS`), `RequestError`, `png_size`, `validate_request`, `shape_answers`, `answer_diagnostics`, `pinned_file_entries`, and `experimental_descriptor` into `scripts/laya_server_validation.py` (stdlib-only, zero heavy imports).
   - For filesystem-bound loaders (`load_acceptance_floors`, `load_seat_registry`, `load_experimental_metadata`, `wager_questions`, `readout_core_template`), accept explicit `root` / `repo` parameters in `laya_server_validation.py` and keep thin wrappers in `scripts/laya-server.py` that pass `srv.ROOT` / `srv.REPO` so `patch.object(srv, "ROOT", ...)` and `patch.object(srv, "REPO", ...)` in `test_laya_server.py` continue to work identically.
2. **Deduplicate `handle_predict` and `handle_predict_batch` decode/glyph-prep helpers**:
   - Extract shared image decode + glyph segmentation + question filtering logic used by both `handle_predict` and `handle_predict_batch` into a single internal helper `_decode_and_prepare_pass(engine, layout, style, raw, questions)` so single and batch prediction paths do not duplicate decode/segmentation error handling.
3. **Re-export all public/tested symbols in `scripts/laya-server.py`**:
   - Import and expose every constant, exception, and helper in `scripts/laya-server.py` so external callers and `test_laya_server.py` / `test_laya_dashboard.py` require zero test modifications.

---

### Phase 3: Factor Shared Rust `bin/` Session Helpers & Inline Test Modules

**Files**:
- `bin/manual_capture.rs`
- `bin/manual_inference.rs`
- `bin/live.rs`
- `bin/manual_capture/tests.rs` (or `#[path = ...]` submodule if extracted)
- `bin/manual_inference/tests.rs`
- `bin/live/tests.rs`

**Steps**:
1. **Consolidate shared manual session receipt & source-matching helpers in `bin/manual_capture.rs`**:
   - Extract a shared helper in `bin/manual_capture.rs` for computing `recording_end_reason` + base `manual_capture` status JSON fields (`elapsed_ms`, `stop_reason`, `recording_end_reason`, `recording`, `capture_failures`, `capture_directory`, `latest_frame`, `updated_at_unix_ms`) used by both `manual_capture::emit_status` and `manual_inference::ManualSource::progress`.
   - Extract a shared single-window discovery matcher (`find_approved_window(windows: &[WindowInfo], approved: &WindowInfo) -> Option<&WindowInfo>`) used by both `manual_capture::capture_loop` and `manual_inference::ManualSource::current_window`.
2. **Split oversized inline `#[cfg(test)] mod tests` out of `bin/` production files**:
   - `bin/manual_inference.rs` is 3,504 lines (2,500+ lines of tests starting at line 1001), `bin/live.rs` is 2,189 lines (1,277 lines of tests starting at line 912), and `bin/manual_capture.rs` is 808 lines (381 lines of tests starting at line 426).
   - Move the inline `#[cfg(test)] mod tests` blocks into dedicated test submodule files (`bin/manual_capture_tests.rs`, `bin/manual_inference_tests.rs`, `bin/live_tests.rs` wired via `#[cfg(test)] #[path = "..."] mod tests;`) so the production modules in `bin/` remain under ~1,000 lines and easy to navigate while keeping `super::*` private item visibility and test names 100% identical.

---

## 3. Risks & Failure Modes

| Risk | Impact | Mitigation |
|---|---|---|
| Breaking `patch.object(srv, "ROOT", ...)` or `patch.object(srv, "REPO", ...)` in `scripts/tests/test_laya_server.py` | Unit tests in `AcceptanceTests` and `ExperimentalBetActionTests` fail | Keep `ROOT` and `REPO` in `scripts/laya-server.py` and pass them from wrapper functions into any extracted helper in `laya_server_validation.py`. |
| Triggering heavy imports (`laya_prep`, `numpy`, `PIL`, `torch`) before `load_acceptance_floors` in `Engine.__init__` | `test_invalid_report_precedes_every_heavy_import_and_model_load` fails | Ensure `laya_server_validation.py` is strictly stdlib-only and `laya_prep` remains lazily imported inside `Engine.__init__` after floor validation. |
| Breaking `scripts/validate.py` or release packaging workflows | CI or local validation fails | Keep all existing entrypoint paths (`scripts/laya-server.py`, `scripts/laya_prep.py`, `scripts/vlm-pins.json`, `bin/main.rs`) unchanged. |
| Subtle rounding divergence between Rust `f64::round_ties_even` and Python `round` | Region crops differ by 1px on tie dimensions | Both languages use round-half-to-even (`round()` in Python 3, `f64::round_ties_even()` in Rust); verify with explicit `.5` tie test cases in both test suites. |

---

## 4. Verification Plan

Run the full validation suite in order after implementation:

1. **Rust formatting, compilation, and lints**:
   - `cargo fmt --all -- --check`
   - `cargo check --workspace --all-targets --all-features --locked`
   - `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`
2. **Rust unit & integration tests (all 622+ tests)**:
   - `cargo test --workspace --all-targets --all-features --locked`
3. **Python test suite (all `scripts/tests/test_*.py` modules)**:
   - `python -m unittest discover -s scripts/tests -v`
4. **Full repository validation runner**:
   - `python scripts/validate.py`
