# Windows VLM compatibility record

## Active Laya-only candidate

**Status:** iteration-1 Gate F **FAIL**, human verification **UNVERIFIED**;
no seated advice. The active backend is Laya, not an evaluation-only install
or a Gemma alternative. Reuse the completed local checkpoint
`models/laya-vision/finetuned/20261009T190322Z-it1`, derived from
`thaitea/laya-vision@f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc`.
Download, training, calibration, dumps, scoring and pin verification already
happened; the dashboard follow-on needs neither redownload nor retraining.
A fresh installation lacks this user's local fine-tuned derivative.

The active pin record is [`scripts/laya-pins.json`](../scripts/laya-pins.json).
It records snapshot/runtime and fine-tuned artifact provenance and hashes;
`download-model.ps1 -Verify` checks existing local files. Recorded runtime:
Python 3.12.15 at `.local/laya-runtime/env`, Laya 0.1.7 at code commit
`9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c`, PyTorch `2.11.0+cu128`,
torchvision `0.26.0+cu128`, transformers `5.19.0`. This is a local CUDA
inference path, not GGUF/llama.cpp/Vulkan. Repository source is MIT; the pinned
Laya fork and upstream SmolVLM are Apache-2.0; Laya base and derived weights are
CC-BY-NC-SA-4.0, local-only and not redistributed. See
[MODEL_LICENSES.md](../MODEL_LICENSES.md).

| Surface | Canonical local address / meaning |
| --- | --- |
| Read-only browser | `http://127.0.0.1:18090/` |
| Sanitized status/history snapshot | `http://127.0.0.1:18090/api/state` |
| Model metadata | `http://127.0.0.1:18090/v1/models`, alias `coinpoker-laya-vision` |
| Typed image/question prediction | `http://127.0.0.1:18090/v1/laya/predict` |

No current chat-completions backend, remote opt-in, retired `18080`/`8080`
product endpoint or automatic alternate-port fallback is supported. Explicit
retired product endpoints should be configuration errors, not connections to
an unrelated application. Host/Origin, request bounds and sanitized read-only
DTO handling are follow-on test requirements, not assumed acceptance.

`scripts/start-vlm.ps1 -DashboardOnly` is planned to bind the dashboard with no
GPU/model load. Default startup asynchronously verifies, loads and warms the
pinned model while status remains independent; predictions stay unavailable
on loading/failed verification and do not queue concurrent GPU work. Optional
`-LiveConfig .local/profile.json` explicitly supervises one operator-configured
native passive feed; neither default mode starts live capture. These launcher
and concurrency instructions remain subject to the coordinator's actual tests.
No first-phase client capture, training or advice is implied by a healthy page.
The native feed is capture-health only (`recording_enabled:false`,
`recorded_frames:0`), not an image recorder. Typed `-LiveConfig` target settings
do not forward a `--record-dir` option. Actual recorder/profile readiness stays
pending; a frame counter alone cannot establish `COLLECTOR_READY`.

Loaded temperature calibration (`meta.calibrated:true` in the baseline server)
is not capability approval. Source/vendor `thresholds.calibrated:false` stays
unchanged. The 66 agent-reviewed frames had board raw accuracy
`307/330 = 93.03%` but **0/330 confident board units** at threshold `1.0`;
annotation matches do not mean all model answers were correct. Warm p95 was
p0 `271.0 ms`, tier01 `1497.9 ms`, full unseated battery `3027.3 ms`.
The full battery failed the original `<2000 ms` Gate F criterion. The proposed
`<5000 ms` warm capture-to-browser p95 and hard 5000 ms total deadline are
prospective full end-to-end tests; the old nine-pass benchmark is neither a
seated nor an end-to-end pass. Do not lower thresholds or extend freshness
leases to reclassify this failure. See [the baseline receipt](LAYA_VISION_PHASE_A.md#7-phase-gates).

The actual Practice Games development scope uses the same representation and
guards as cash, without a validation bypass or real-money acceptance. Positive
real hero-card/control UI data and approved human-held-out calibration/evaluation
are still missing. Root charts/PDF are mathematical references, not positive
seated screenshots. Planned private bounded per-session history lives under
`.local/` with opaque IDs and explicit gaps, never public names or cross-session
guesses.

Current release packaging omits the Laya server/dashboard support path and the
user's fine-tuned weights. The orphaned `scripts/vlm-pins.json` below is retained
only as history; no release/workflow update is made in this phase.

## Historical Gemma candidate and expected hashes

The remainder records the retired 2026-09-23 Gemma/llama.cpp candidate. Its
ports, hashes, timings and generated-image receipts are preserved, not current
startup instructions or evidence for Laya. Pinned GGUF, projector and server
were verified on that host; both image-dependent 64×64 generated color probes
passed. They proved that historical API image path, not table recognition.

The historical machine-readable record is [`scripts/vlm-pins.json`](../scripts/vlm-pins.json).
At that time, `download-model.ps1 -Verify` checked the GGUF and projector;
`setup-windows.ps1` checked the server ZIP and executable. The pinned build
were verified on this host. The downloaded model and projector passed their pinned
size and SHA-256 checks, and the live doctor confirmed the exact model alias and
both generated multimodal probes. These checks do not prove poker accuracy.

| Asset | Immutable source | Expected SHA-256 |
| --- | --- | --- |
| `gemma-4-E2B-it-Q4_0.gguf` | `ggml-org/gemma-4-E2B-it-GGUF` revision `b4243c156154b6dca9324415f8c7ccc098b4aed1` | `8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52` |
| `mmproj-gemma-4-E2B-it-BF16.gguf` | Same immutable revision | `711e1e8f43fa0664adbac493129be1e6c25b81af4b4cdea97c7d798b25c0a3a4` |
| `llama-b10964-bin-win-vulkan-x64.zip` | `ggml-org/llama.cpp` release `b10964`, commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` | `1ee3ad952f4ba71f438bd6d7bebef19e1c7af04adcaa35d08b4ddabb27d4c642` |

In this retired configuration, the separate BF16 projector was essential for
image input. The model directory was `models/gemma-4-E2B-it-GGUF/`. The server
asset lived under ignored `.local/vlm-runtime/b10964/` and served model alias
`coinpoker-gemma-4-e2b` on `127.0.0.1:18080`. The runtime was a foreground
process started by `scripts/start-vlm.ps1`, not a Windows service. Model terms
are documented in [MODEL_LICENSES.md](../MODEL_LICENSES.md).

The first generated red probe took 48.02 seconds after server startup; the next
blue probe took 2.09 seconds. Doctor permits up to 120 seconds for this setup
check. The live Rust request timeout remains 30 seconds, so a cold result that
arrives late is discarded. No p50/p95/p99 table-sized latency claim follows from
two tiny generated images.

## Historical runtime decision

GGUF through llama.cpp was the chosen Windows implementation. The approved ONNX
comparison required the same representative table images and request contract,
no loss of vision correctness, and at least 20% lower warm end-to-end p95 latency.
No same-contract Windows ONNX Gemma 4 VLM endpoint was demonstrated, so no ONNX p95
comparison or adoption was claimed. That comparison was not adopted and is
not a pending task for the Laya/dashboard phase. Microsoft ORT GenAI
[issue 2098](https://github.com/microsoft/onnxruntime-genai/issues/2098)
documents the Gemma 4 model registration, cache shapes and vision preprocessing
that an ONNX spike would need to investigate.

## Historical transport and acceptance checks

The historical Rust chat client sent system/user messages with a PNG data URL,
temperature/max-token bounds, `stream:false` and a strict stop reason. It capped
responses at 1 MiB and rejected redirects/environment proxies. The old remote
capture option is retired; current product routes are local Laya only. HTTP 200
alone never established a valid strict screen envelope or quality approval.

Retired acceptance sequence, not current installation instructions:

1. Download and verify all three pinned assets; deliberately corrupt a local copy
   and confirm verification/startup refuses it.
2. Start the server and confirm `/v1/models` lists the exact alias. Run doctor:
   generated red and blue images must produce different correct color JSON with
   `finish_reason:"stop"`.
3. Run representative table-sized images under the actual prompt/request contract.
   Record cold and warm end-to-end p50/p95/p99, memory use, timeouts and failures.
4. Apply all held-out real-image extraction and decision thresholds in
   [VISUAL_EVALUATION_V2.md](VISUAL_EVALUATION_V2.md). A 5-second default advice
   lease still discards a late result even when server inference succeeds.

Those checks do not transfer to the active Laya candidate. No runtime
substitution or alias change should make a failing gate appear green.
