# Windows VLM compatibility record

**Status:** pinned GGUF, projector and server verified on the target Windows host
on 2026-09-23 UTC. Both image-dependent 64×64 generated color probes passed.
Representative table-image accuracy and warm table-sized latency remain separate
evidence gates. The color probes verify the API's image path, not table recognition.

## Selected candidate and expected hashes

The machine-readable source of truth is [`scripts/vlm-pins.json`](../scripts/vlm-pins.json).
`download-model.ps1 -Verify` checks the GGUF and projector; `setup-windows.ps1`
checks the server ZIP and executable. The pinned server ZIP and executable build
were verified on this host. The downloaded model and projector passed their pinned
size and SHA-256 checks, and the live doctor confirmed the exact model alias and
both generated multimodal probes. These checks do not prove poker accuracy.

| Asset | Immutable source | Expected SHA-256 |
| --- | --- | --- |
| `gemma-4-E2B-it-Q4_0.gguf` | `ggml-org/gemma-4-E2B-it-GGUF` revision `b4243c156154b6dca9324415f8c7ccc098b4aed1` | `8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52` |
| `mmproj-gemma-4-E2B-it-BF16.gguf` | Same immutable revision | `711e1e8f43fa0664adbac493129be1e6c25b81af4b4cdea97c7d798b25c0a3a4` |
| `llama-b10964-bin-win-vulkan-x64.zip` | `ggml-org/llama.cpp` release `b10964`, commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` | `1ee3ad952f4ba71f438bd6d7bebef19e1c7af04adcaa35d08b4ddabb27d4c642` |

The separate BF16 projector is essential for image input. The selected model
directory is `models/gemma-4-E2B-it-GGUF/`. The server asset lives under ignored
`.local/vlm-runtime/b10964/` and serves model alias `coinpoker-gemma-4-e2b` on
`127.0.0.1:18080`. The runtime is a foreground process started by
`scripts/start-vlm.ps1`; it is not a Windows service. Model terms are documented
in [MODEL_LICENSES.md](../MODEL_LICENSES.md).

The first generated red probe took 48.02 seconds after server startup; the next
blue probe took 2.09 seconds. Doctor permits up to 120 seconds for this setup
check. The live Rust request timeout remains 30 seconds, so a cold result that
arrives late is discarded. No p50/p95/p99 table-sized latency claim follows from
two tiny generated images.

## Runtime decision

GGUF through llama.cpp is the chosen Windows implementation. The approved ONNX
comparison required the same representative table images and request contract,
no loss of vision correctness, and at least 20% lower warm end-to-end p95 latency.
No same-contract Windows Gemma 4 VLM endpoint was demonstrated, so no ONNX p95
comparison or adoption is claimed. The ONNX option remains a research spike;
the GGUF path is the candidate being validated. Microsoft ORT GenAI
[issue 2098](https://github.com/microsoft/onnxruntime-genai/issues/2098)
documents the Gemma 4 model registration, cache shapes and vision preprocessing
that an ONNX spike would need to investigate.

## Transport and acceptance checks

The Rust client sends system and user messages with a PNG data URL, explicit
temperature and max-token bounds, `stream:false`, and a strict stop reason. It
caps response size at 1 MiB, rejects redirects and environment proxies, and
requires explicit opt-in plus HTTPS for remote capture. Doctor and evaluator are
loopback-only. The model must return a valid strict screen envelope with every
required evidence field; HTTP 200 alone is insufficient.

Acceptance order:

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

No runtime substitution or alias change should make a failing gate appear green.
Record new pins, hashes and acceptance evidence before changing the candidate.
