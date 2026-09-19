# coinpoker-help

An experimental, human-confirmed decision-support framework for studying
probabilistic poker decisions. It can ingest structured game state directly or,
on supported macOS systems, capture a CoinPoker window and ask a separately run
vision-language model (VLM) server to extract state. It emits recommendations;
it does not inject mouse, keyboard, or game-client input.

Users are responsible for complying with applicable laws, platform rules, and
model licenses.

## Current architecture

```text
macOS capture or JSON-lines stdin
    -> state parsing and validation
    -> phase state machine
    -> Monte Carlo equity and EV calculations
    -> bounded bet-size humanization
    -> JSON-lines recommendation output
```

Workspace crates:

- `ingest`: ScreenCaptureKit capture on macOS, change detection, VLM client,
  parsing, and state transitions.
- `core-engine`: pot odds, equity estimation, expected value, and legal action
  selection.
- `ghost-layer`: bet-size entropy, timing primitives, and profile storage.
- `opponent-model`: feature accumulation, archetype classification, and exploit
  adjustment primitives.
- `ui`: lightweight decision-view/JSON-lines output plus an unwired egui panel
  behind the optional `desktop` feature.
- `bin`: the `coinpoker` CLI and pipeline wiring.

## Requirements

- Rust 1.95+; `rust-toolchain.toml` pins 1.95.0 with `rustfmt` and `clippy`.
- `--stdin` works on Windows, Linux, and macOS.
- Live capture requires macOS 14+, Screen Recording permission, and a
  discoverable CoinPoker window.
- Local Gemma 4 MLX inference requires suitable Apple Silicon hardware and a
  separate server that accepts OpenAI-compatible multimodal chat-completions.

CI compiles and tests the workspace on Windows, Linux, and macOS. It does not
exercise runtime ScreenCaptureKit permission prompts, live window discovery, or
capture against the CoinPoker application.

## CLI modes

```bash
# macOS capture pipeline; emits recommendation JSON lines
cargo run --release --bin coinpoker

# Cross-platform replay mode: GameState JSON lines in, recommendations out
cargo run --release --bin coinpoker -- --stdin

# macOS calibration: list all shareable windows
cargo run --release --bin coinpoker -- --list-windows

# Show supported options
cargo run --release --bin coinpoker -- --help
```

`--ui` is recognized but currently exits with status 2 because no live pipeline
to the egui panel has been implemented. Use JSON-lines output instead.

## Screenshot and VLM data flow

Capture mode takes a full image of the selected CoinPoker window. When change
detection fires, the image is encoded as PNG, embedded in a data URL, and sent
to the configured chat-completions endpoint. The default endpoint is local:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Changing `COINPOKER_VLM_ENDPOINT` to a non-loopback address sends screenshots
to that host. The CLI refuses remote endpoints by default. Remote use requires
`COINPOKER_ALLOW_REMOTE_VLM=1` and an HTTPS endpoint; it can expose sensitive
screen contents and should only be enabled with a trusted service, suitable
authentication, and a reviewed retention policy. This client does not currently
add an authorization header.

The project does not bundle or start a VLM server. Confirm that the chosen
server supports Gemma 4 vision input, the downloaded OptiQ layout, and the
OpenAI-compatible image-message shape used by the client.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `COINPOKER_WINDOW_TITLE` | `CoinPoker` | Window-title substring used for capture selection |
| `COINPOKER_APP_NAME` | `CoinPoker` | Owning-application substring used as a fallback capture match |
| `COINPOKER_VLM_ENDPOINT` | `http://127.0.0.1:8080/v1/chat/completions` | Chat-completions endpoint used in capture mode |
| `COINPOKER_VLM_MODEL` | `gemma-4-e2b-it-OptiQ-4bit` | Model name sent to the VLM server |
| `COINPOKER_ALLOW_REMOTE_VLM` | unset | Set to `1` or `true` to permit a non-loopback HTTPS endpoint |

Empty values are ignored. Title matches are selected before application-name
fallbacks. If several windows match the same selector, use `--list-windows` and
a more specific `COINPOKER_WINDOW_TITLE`; matching within that tier selects the
first on-screen result. If another model variant is served, set
`COINPOKER_VLM_MODEL` to the name expected by that server.

## Pinned MLX models

`download-model.sh` downloads into `models/` using immutable Hugging Face
revisions, verifies required configuration/tokenizer files, the vision sidecar,
and every safetensors shard referenced by the index, then records provenance in
`SOURCE_REVISION`.

```bash
./download-model.sh          # E2B OptiQ
./download-model.sh e4b      # E4B OptiQ
./download-model.sh e2b-qat  # E2B QAT OptiQ
```

The script requires Bash, Python 3, and preferably the current `hf` CLI
(install with `curl -LsSf https://hf.co/cli/install.sh | bash -s`). A compatible
deprecated `huggingface-cli` is retained only as a warned fallback.
Downloads are large: allow roughly 5.3 GB for E2B/E2B-QAT or 7.5 GB for E4B,
plus temporary working space.

| Variant | Revision | Terms |
| --- | --- | --- |
| E2B | `ffcf5c056bdd0df50627867ee8c7cba890eabe33` | Gemma Terms of Use |
| E4B | `e1404a83551b6eb571dc5fb0de93e52310399bcd` | Gemma Terms of Use |
| E2B QAT | `c6c6572580501e5fcb9248bf12040d25cfc71118` | Upstream metadata/card conflict; treat as Gemma terms pending clarification |

Review `MODEL_LICENSES.md` before downloading or using weights. The repository's
MIT license applies to source code, not to model artifacts.

## Structured stdin mode

Each input line must be a complete `GameState` JSON object. `pot_size`,
`to_call`, and `hero_chips` are required even when zero. Player names must not
have surrounding whitespace, the exact `Hero` player's stack must match
`hero_chips`, and actionable states require two hero cards plus at least one
active opponent. States facing a bet must offer fold and call (or a short
all-in), and exact `min_raise_to`/`max_raise_to` values are required whenever
`raise` is offered. Invalid states are reported to stderr and skipped. If a
recommendation is active, invalid input emits a `clear` record. A flop example
is:

```json
{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],"board":[{"rank":"A","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],"pot_size":1000,"to_call":500,"hero_chips":5000,"min_raise_to":1500,"max_raise_to":5000,"players":[{"name":"Hero","chips":5000,"last_action":"check","bet_amount":0},{"name":"Villain","chips":4500,"last_action":"bet","bet_amount":500}],"action_required":true,"available_actions":["fold","call","raise"]}
```

## Current limitations

- The desktop UI feed is unavailable; `--ui` does not launch the panel.
- Opponent-history accumulation is not integrated into the binary pipeline, so
  live decisions currently classify the opponent as unknown.
- Unknown-opponent equity uniformly samples distinct random holdings for every
  visibly active opponent. It is multiway-aware for single-pot states, but it
  is not yet conditioned on positions, action history, or learned/weighted
  ranges. Multiway all-in states are suppressed until side-pot eligibility is
  modeled.
- The ghost-layer temporal sampler exists as a library primitive but is not
  applied by the active CLI pipeline. Recommendations are emitted immediately
  after calculation.
- Capture, change detection, VLM inference, parsing, and decision output still
  run serially. A post-inference capture suppresses results when the visible
  frame changed during inference, but there is no cancellable latest-frame work
  queue yet.
- Change/freshness checks are pixel-threshold based and can miss semantically
  important changes below that threshold.
- Raise EV uses Hero's visible street contribution, exact raise-to bounds, and
  an aggregate expected caller contribution. Until caller-count and
  range-conditioned raise equity are modeled, the runtime does not recommend
  raises with more than one visibly active opponent.
- Headless consumers receive `{"event":"clear",...}` records when a prior
  recommendation is no longer actionable; they must handle those invalidations.
- The program provides recommendations only and does not execute actions.

## Development validation

```bash
cargo fmt --all -- --check
cargo check --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
bash -n download-model.sh
```

See `CONTRIBUTING.md` for contribution expectations and `SECURITY.md` for
private vulnerability reporting and screenshot-data guidance.

## Future experiments

- Integrate observed hand history into opponent feature accumulation and
  range-based equity estimation.
- Wire an optional desktop feed without making it mandatory for headless use.
- Add WebSocket transport for headless consumers.
- Evaluate [Jev](https://typesafe.ai) only as an optional, feature-gated
  shadow-mode semantic classifier for comparison, labeling, or diagnostics.
  Jev is not intended to provide core poker mathematics, equity/EV calculations,
  legality checks, or action selection, and any future integration must remain
  non-authoritative until independently validated against a versioned dataset.

## License

Source code is licensed under the MIT License. See `LICENSE`. Downloaded models
have separate terms described in `MODEL_LICENSES.md`.
