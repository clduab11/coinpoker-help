# Model and runtime provenance

The repository's **MIT** license covers its source code, not model weights.
The active perception backend is **Laya Vision only**, using the existing local
iteration-1 checkpoint. Gemma/llama.cpp provenance below is historical, not a
second supported backend or a fallback.

## Active Laya Vision provenance

`scripts/laya-pins.json` records the pinned base snapshot, runtime and local
fine-tuned artifacts. The base download, iteration-1 training, calibration,
scoring and pin verification already completed on 2026-10-09. Reuse
`models/laya-vision/finetuned/20261009T190322Z-it1`; no redownload or retraining
is needed for the dashboard follow-on. A fresh checkout does not include or
download this user's local fine-tuned derivative.

| Artifact | Upstream revision or local provenance | Digest record |
| --- | --- | --- |
| `thaitea/laya-vision/model.safetensors` (201M, fp32) | `f2fe3c12cb6d04c59d8a190250bf3fb40fc828dc` | SHA-256 `31220803f38b44b8b1649b207c632612c9a35dee0da2ef1ea35d21e4b424be68` |
| `models/laya-vision/finetuned/20261009T190322Z-it1` | Local derivative of the pinned base, trained 2026-10-09 | Per-artifact sizes and SHA-256 in `scripts/laya-pins.json` |
| `r33drichards/laya-vision` code (package `laya` 0.1.7) | commit `9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c` | git commit |
| `torch` / `torchvision` | `2.11.0+cu128` / `0.26.0+cu128` (download.pytorch.org cu128) | Pinned runtime record |

Licenses are distinct:

- **Repository source:** MIT.
- **Pinned Laya fork code:** Apache-2.0. Both the
  [LICENSE at the pinned commit](https://github.com/r33drichards/laya-vision/blob/9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c/LICENSE)
  and [package metadata at that commit](https://github.com/r33drichards/laya-vision/blob/9e1e2419d855ad3e1a2af4d4bd1ef6be5418842c/pyproject.toml)
  declare Apache-2.0, rechecked 2026-10-10. The earlier MIT correction in these
  docs was incorrect for this pinned fork; `scripts/laya-pins.json` already
  records the correct source attribution. This does not change weight terms.
- **Upstream backbone:** Hugging Face SmolVLM-256M-Instruct, Apache-2.0.
  Its config and processor are bundled in the base snapshot. This license does
  not replace the trained Laya weights' terms.
- **Laya weights:** CC-BY-NC-SA-4.0; the training data includes ScienceQA and
  CrisisMMD. The local fine-tuned derivative inherits the non-commercial and
  share-alike constraints. Attribution and upstream notices still apply.
  This workflow keeps base and derived weights local and does not redistribute
  them. Source MIT is not a license to redistribute the weights as MIT.

The recorded inference environment is Python 3.12.15 at
`.local/laya-runtime/env`, with the pinned Laya/PyTorch runtime; it is not the
retired GGUF/Vulkan runtime. Dependency notices remain separate upstream terms.
`download-model.ps1 -Verify` checks existing Laya artifacts without downloading
or training. Successful verification or loaded temperature calibration does
not establish quality approval: iteration-1 Gate F remains **FAIL**, human
verification **UNVERIFIED**, and source/vendor `calibrated:false`. See
[the preserved receipt](docs/LAYA_VISION_PHASE_A.md#7-phase-gates).

Current service/browser target: `http://127.0.0.1:18090/`, with `/v1/models`
(alias `coinpoker-laya-vision`) and `/v1/laya/predict` on the same loopback
listener. The dashboard and launcher are subject to
implementation tests, not accepted live guidance. Release packaging currently
omits the Laya server/support path and
the user's local fine-tuned weights; no packaging change is claimed here.

## Historical Gemma and llama.cpp provenance

The following immutable hashes and upstream links belong to the retired
Gemma candidate. `scripts/vlm-pins.json` remains an orphaned historical
manifest; it is not the active downloader/setup/starter/doctor source of truth.
Retaining it does not authorize fallback or redistribution of old artifacts.

| Artifact | Upstream revision or release | SHA256 |
| --- | --- | --- |
| `ggml-org/gemma-4-E2B-it-GGUF/gemma-4-E2B-it-Q4_0.gguf` | `b4243c156154b6dca9324415f8c7ccc098b4aed1` | `8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52` |
| `ggml-org/gemma-4-E2B-it-GGUF/mmproj-gemma-4-E2B-it-BF16.gguf` | same revision | `711e1e8f43fa0664adbac493129be1e6c25b81af4b4cdea97c7d798b25c0a3a4` |
| `llama-b10964-bin-win-vulkan-x64.zip` | `ggml-org/llama.cpp` release `b10964`, commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4` | `1ee3ad952f4ba71f438bd6d7bebef19e1c7af04adcaa35d08b4ddabb27d4c642` |

The [Google Gemma 4 E2B model card](https://huggingface.co/google/gemma-4-E2B-it)
and [ggml-org GGUF repository](https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF)
identify this model family and conversion as Apache-2.0. The upstream GGUF
repository's `.src_sha` links its `PRIMARY` source to Google revision
`3e22461f65e89153144f8adb70e3b8c2cc9845a7`. The
[llama.cpp release](https://github.com/ggml-org/llama.cpp/releases/tag/b10964)
publishes the Windows asset digest; review its packaged notices before
redistributing the runtime.

The former GGUF/projector verification and llama.cpp startup procedure is
historical. Do not use this manifest or these artifacts for current startup.
