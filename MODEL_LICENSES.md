# Model licenses and provenance

The source code in this repository is licensed under the MIT License in
`LICENSE`. That license does **not** grant rights to model weights downloaded by
`download-model.sh`; each model remains subject to its upstream terms.

The downloader pins these immutable Hugging Face revisions:

| Variant | Repository | Revision | Upstream terms |
| --- | --- | --- | --- |
| E2B | `mlx-community/gemma-4-e2b-it-OptiQ-4bit` | `ffcf5c056bdd0df50627867ee8c7cba890eabe33` | Gemma Terms of Use |
| E4B | `mlx-community/gemma-4-e4b-it-OptiQ-4bit` | `e1404a83551b6eb571dc5fb0de93e52310399bcd` | Gemma Terms of Use |
| E2B QAT | `mlx-community/gemma-4-e2b-it-qat-OptiQ-4bit` | `c6c6572580501e5fcb9248bf12040d25cfc71118` | Ambiguous; see below |

- Gemma terms: <https://ai.google.dev/gemma/terms>
- E2B model card: <https://huggingface.co/mlx-community/gemma-4-e2b-it-OptiQ-4bit>
- E4B model card: <https://huggingface.co/mlx-community/gemma-4-e4b-it-OptiQ-4bit>
- E2B QAT model card: <https://huggingface.co/mlx-community/gemma-4-e2b-it-qat-OptiQ-4bit>

## E2B QAT ambiguity

At the audited revision, the E2B QAT repository metadata identifies the license
as Apache-2.0, while its model card says the Gemma Terms of Use apply and it is
derived from a Gemma base model. This repository does not attempt to resolve
that inconsistency. Treat the QAT artifact as subject to the more restrictive
Gemma terms unless the upstream publisher provides authoritative clarification.

Users are responsible for reviewing and accepting the applicable terms before
downloading, using, modifying, or redistributing any model. The project does not
distribute model weights. Each completed download records its repository and
revision in `SOURCE_REVISION` inside the ignored local model directory.
