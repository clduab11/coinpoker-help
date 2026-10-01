# Model and runtime provenance

The repository's MIT license covers its source code. Model weights and the
llama.cpp runtime come from separate upstream projects. This repository does
not distribute either artifact.

`scripts/vlm-pins.json` is the single pin manifest used by the Windows
downloader, setup, starter, and doctor. It fixes these local artifacts:

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

Run `pwsh -File download-model.ps1 -Verify` to check both local model files and
the recorded source revision without network access. `scripts/start-vlm.ps1`
requires that verification before serving local images.
