# coinpoker-help

A modular decision-support framework for stochastic gaming environments,
structured for academic study. The system integrates probabilistic game
theory with statistical opponent modeling, wrapped in a behavioral-parity
layer that preserves human-like variance in its outputs.

**Design posture:** semi-autonomous. The system observes, computes, and
recommends; a human operator confirms every action. No input is injected
into the game client.

## Architecture

```
crates/
├── ingest/           Vision pipeline: window capture → change detection →
│                     VLM analysis → structured game state
├── core-engine/      Decision kernel: pot odds, implied odds, Monte Carlo
│                     equity, expected value, Fold/Call/Raise recommendation
├── ghost-layer/      Behavioral mimicry: log-normal reaction-time sampling,
│                     discretized bet sizing with rare off-grid events
├── opponent-model/   Adaptive modeling: feature extraction (VPIP/PFR/AF),
│                     threshold archetype classification (LAG/TAG/LP/TP),
│                     exploit adjustments
└── ui/               Minimalist output: egui decision panel + headless
                      JSON-lines emitter
bin/                  `coinpoker` binary: wiring, CLI modes, event loop
```

### Pipeline

```
capture (10fps) → pixel-diff change detection → VLM (on change only)
    → JSON state parse + validation → phase state machine
    → equity estimation → decision engine → ghost-layer sizing
    → decision view (panel or JSON lines)
```

## Model (MLX format)

The vision model is **Gemma 4 E2B in MLX format** (Apple's framework
layout — not GGUF). MLX models are directories of safetensors files.

```bash
./download-model.sh          # Gemma 4 E2B (default, 2B)
./download-model.sh e4b      # Gemma 4 E4B (4B)
```

> Model note: early MLX quantizations of Gemma 4 produced garbage output
> because PLE (per-layer embedding) layers were quantized incorrectly. The
> script fetches the PLE-safe `OptiQ` variants.

Inference runs against a local MLX VLM server exposing an OpenAI-compatible
chat-completions API (e.g. a Rust-native MLX server such as `rMLX` or
`mlxcel`, or the `mlx-vlm` reference server). Point the server at the
downloaded model directory and start `coinpoker` with the default endpoint
`http://127.0.0.1:8080/v1/chat/completions` (configurable in
`ingest::vlm::VlmConfig`).

## Build & run

Requires Rust 1.75+. The capture backend targets macOS 14+ (Apple Silicon)
and uses ScreenCaptureKit; the workspace still builds on other hosts.

```bash
cargo build --release

# Headless capture pipeline (macOS, Screen Recording permission required)
cargo run --release --bin coinpoker

# Replay mode: GameState JSON lines on stdin → decision JSON lines on stdout
cargo run --release --bin coinpoker -- --stdin

# Desktop decision panel
cargo run --release --bin coinpoker -- --ui

# Calibration: list capture candidates
cargo run --release --bin coinpoker -- --list-windows
```

Example stdin session:

```json
{"game_phase":"flop","hero_cards":[{"rank":"A","suit":"spades"},{"rank":"K","suit":"hearts"}],
 "board":[{"rank":"A","suit":"diamonds"},{"rank":"7","suit":"clubs"},{"rank":"2","suit":"spades"}],
 "pot_size":1000,"to_call":500,"hero_chips":5000,
 "players":[{"name":"Hero","chips":5000}],
 "action_required":true,"available_actions":["fold","call","raise"]}
```

## Testing

```bash
cargo test --workspace
```

86 tests cover pot-odds math, Monte Carlo equity (validated against known
matchups), change detection, VLM response handling (against a mock server),
state-machine transitions, archetype classification, and an end-to-end
pipeline smoke test.

## Roadmap

- `linfa`-backed classifier (optional feature) replacing the threshold v1
- Range-based equity estimation in the opponent model
- WebSocket transport for headless output
- In-process MLX inference via `mlxrs` once Gemma 4 architecture support
  lands upstream

## License

MIT
