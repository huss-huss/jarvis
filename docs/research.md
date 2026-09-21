# JARVIS Technical Discovery

**Date:** 2026-09-21  
**Scope:** Phase 0 — evaluate open-source components before implementation  
**Machine target:** macOS / Apple Silicon (MacBook M4 Pro)  
**Constraint:** $0/month core operation; local-first; no mandatory paid APIs

---

## Repository status

The repository currently contains documentation only (`docs/prompt.md`, `docs/requirement.md`, `docs/architecture.md`). No Python package, tests, or runtime code exists yet.

---

## Decision summary

| Area | Primary choice | Fallback | Notes |
|------|----------------|----------|-------|
| LLM | Ollama + `ollama` Python SDK | — | Already installed; Metal on Apple Silicon |
| STT | whisper.cpp via `pywhispercpp` | faster-whisper | Prefer Metal/Core ML path on M4 |
| Wake word | openWakeWord (`hey_jarvis`) | Hotkey-only mode | Verify ONNX path on macOS arm64 |
| TTS | Kokoro (`kokoro` / optional `kokoro-mlx`) | Piper (MIT archived binary or OHF GPL fork) | Prefer Apache-2.0 Kokoro |
| Computer control | Custom tools + macOS APIs/AppleScript | Optional later OI integration | Do not couple Phase 1 to Open Interpreter |
| Browser | Playwright | — | Behind `BrowserProvider` |
| Voice orchestration | Custom pipeline inspired by LiveKit Agents | — | Patterns only; no LiveKit Cloud dependency |
| Structured memory | SQLite | — | Conversation, long-term, episodic, action log |
| Vectors | sqlite-vec | FAISS | Keep data local and single-file first |
| Embeddings | Ollama embeddings | sentence-transformers | Same local stack as LLM |
| VAD (voice phase) | Silero VAD (ONNX) | webrtcvad | Required for barge-in |

---

## Component evaluation table

| Component | Candidate | Purpose | License | Maintenance | Apple Silicon | Advantages | Disadvantages | Decision |
|-----------|-----------|---------|---------|-------------|---------------|------------|---------------|----------|
| LLM runtime | **Ollama** | Local model serve, streaming chat, tool calling, embeddings | MIT (server + `ollama-python`) | Active; strong community | Excellent (Metal auto) | User already has it; streaming + tools; configurable models; offline | Separate daemon; model quality varies; cloud options exist but must remain optional | **Adopt** — wrap behind `LLMProvider` |
| STT | **whisper.cpp** (+ `pywhispercpp`) | Speech → text | MIT | Active (ggml-org) | First-class (Metal, Core ML/ANE) | Best Mac latency path; VAD helpers; low deps at C++ layer | Bindings lag core; streaming UX needs buffering/VAD | **Primary STT** for Phase 2 |
| STT | **faster-whisper** | Speech → text | MIT | Active | Runs (CPU / Accelerate); no Metal GPU path like whisper.cpp | Excellent Python DX; solid batch/streaming adapters | Weaker GPU story on Mac vs whisper.cpp | **Fallback STT** |
| Wake word | **openWakeWord** | Detect “Hey Jarvis” | Code: Apache-2.0; bundled models: **CC BY-NC-SA 4.0** | Last PyPI 0.6.0 (2024-02); slower release cadence | Problematic: TFLite wheels missing on darwin/arm64; ONNX path needs careful verification | Includes `hey_jarvis`; lightweight; custom training possible | macOS arm64 friction; NC model license for stock models; possible false activations | **Adopt with risk** — Phase 3; require hotkey; train/own model if NC is unacceptable |
| TTS | **Kokoro-82M** (`kokoro`, optional `kokoro-mlx`) | Text → speech | Apache-2.0 (weights + lib); MLX wrapper MIT | Active | Strong; MLX path ideal for M4 | Natural voice; small model; streaming chunks; permissive license | Needs `espeak-ng`; first download; PyTorch or MLX stack | **Primary TTS** for Phase 2 |
| TTS | **Piper** | Text → speech | Original MIT (archived); OHF fork **GPL-3.0** | Original archived Oct 2025; OHF fork active | Works (CPU ONNX) | Very fast, tiny footprint | Lower naturalness; GPL if using OHF fork | **Fallback TTS** — prefer MIT binary or process isolation |
| Computer use | **Open Interpreter** (Python classic) | Shell/code/computer agent | Historically MIT; community fork AGPL-3.0; new Rust project Apache-2.0 | Python classic effectively dormant; Rust rewrite is different product | Works on Mac | Feature-rich agent UX | Heavy deps; maintenance risk; AGPL fork hazard; conflicts with JARVIS permission model if used as black box | **Do not depend on for V1** — study ideas; build JARVIS tools; optional adapter later |
| Browser | **Playwright** | Browser automation | Apache-2.0 | Very active (Microsoft) | Native arm64 browsers | Mature API; Chromium/WebKit/Firefox; agent-friendly | Browser download size; not for always-online requirement | **Adopt** Phase 5 — behind `BrowserProvider` |
| Voice framework | **LiveKit Agents** | Reference for VAD→STT→LLM→TTS streaming | Apache-2.0 (SDK) | Very active | Compatible | Best-in-class barge-in / streaming patterns | Cloud-oriented defaults; extra infra if adopted wholesale | **Reference only** — copy pipeline patterns, not the cloud stack |
| VAD | **Silero VAD** | Speech segment / barge-in | MIT (project); check model card terms | Active | Good via ONNX / Torch | Fast, proven for agents | Echo cancellation still required for barge-in | **Adopt** Phase 2 |
| DB | **SQLite** | Conversations, facts, episodes, action log | Public domain | Ubiquitous | N/A | Zero cost; local file; reliable | Not a vector DB alone | **Adopt** |
| Vectors | **sqlite-vec** | Semantic memory / RAG index | MIT / Apache-2.0 | Active (Mozilla Builders) | Yes | Same file as memory DB; simple ops | Brute-force at small scale; younger than FAISS | **Primary vector store** |
| Vectors | **FAISS** | Semantic search | MIT | Active (Meta) | Available (verify wheel) | Fast ANN at scale | Persistence/metadata DIY; packaging friction historically | **Alternative** if index grows large |
| Embeddings | **Ollama embeddings** | Local vectors | MIT (via Ollama) | Active | Metal via Ollama | One daemon for LLM + embeddings | HTTP overhead vs in-process | **Primary** Phase 4/6 |
| Embeddings | **sentence-transformers** | Local vectors | Apache-2.0 | Active | MPS / CPU | Huge model zoo | Heavier PyTorch dep | **Fallback** |

---

## Integration findings

### Ollama

- REST + official Python client: streaming chat, tool calling (including streamed tool calls as of 2025).
- Configure via `OLLAMA_HOST` / `OLLAMA_MODEL` (e.g. `qwen3`).
- JARVIS must treat Ollama cloud endpoints as **opt-in only**; default `http://localhost:11434`.
- Agent core must not import Ollama types outside `jarvis/llm/ollama.py`.

### whisper.cpp / faster-whisper

- On M4 Pro, whisper.cpp Metal (+ optional Core ML encoder) is the latency winner.
- Real-time UX = microphone → VAD → short utterance buffer → STT (not raw continuous Whisper alone).
- Audio must be ephemeral by default (requirements).

### openWakeWord

- Stock phrase `hey_jarvis` exists.
- macOS Apple Silicon: reported TFLite gaps; prefer ONNX runtime path and document failure → hotkey mode.
- License: runtime OK; **stock models are non-commercial**. For a personal assistant this is usually acceptable; document clearly. If packaging/sharing, train a custom model or obtain appropriate rights.

### Kokoro / Piper

- Kokoro matches “natural English, local, low latency” better than Piper.
- Prefer `kokoro-mlx` on Apple Silicon when Python version allows; keep `TTSProvider` swappable.
- Piper remains the lightweight fallback; avoid pulling GPL into the core package if possible (subprocess CLI preferred).

### Open Interpreter

- Valuable as inspiration (confirm-before-run, tool loop).
- **Not** a Phase 1–5 hard dependency: maintenance/license fragmentation and overlapping permission models.
- JARVIS tools should use:
  - `subprocess` with allowlists for terminal
  - `osascript` / `open` for apps
  - Playwright for browser
  - Optional future `ComputerUseProvider` adapter if OI stabilizes

### Playwright

- Ideal for `open_browser`, `navigate`, `click`, `type_text`, `extract_page`.
- Local browsers; works offline for file:// and local pages; web search still needs network.
- Authenticated sessions later with explicit permission.

### LiveKit Agents

- Steal the architecture: overlapping VAD / STT / LLM / TTS streams, sentence-buffered TTS, cancel on barge-in.
- Do **not** require LiveKit Cloud or Inference for core JARVIS.

### Memory / RAG

- Start with one SQLite database under `data/jarvis.db`.
- Add sqlite-vec extension (or separate vec file) for semantic + RAG indexes.
- Embeddings via Ollama (`nomic-embed-text` or similar) to avoid a second ML stack in early phases.
- FAISS only if profiling shows sqlite-vec insufficient.

---

## What not to reinvent

| Capability | Reuse |
|------------|-------|
| LLM inference | Ollama |
| STT | whisper.cpp |
| TTS | Kokoro |
| Wake word | openWakeWord |
| Browser automation | Playwright |
| Scheduling | APScheduler (later phase) |
| VAD | Silero VAD |
| Vector KNN | sqlite-vec / FAISS |
| Embeddings | Ollama or sentence-transformers |

**Build in-house:** agent orchestrator, permission manager, tool registry, macOS app/file tools, memory schemas, skill loading, config, logging, terminal UI.

---

## Security / license watchlist

1. Never let the LLM execute tools without `PermissionManager`.
2. openWakeWord stock model NC license — document for personal use.
3. Piper OHF GPL — isolate if used.
4. Open Interpreter AGPL fork — do not vendor into core.
5. No silent cloud: Ollama cloud, LiveKit Inference, ElevenLabs, etc. stay off by default.
6. Action log must record confirmations for DANGEROUS tools.

---

## Recommended stack for implementation

```
Phase 1 (text):  Python 3.11+ · pydantic/settings · ollama · SQLite · structlog
Phase 2 (voice): pywhispercpp · kokoro(-mlx) · silero-vad · sounddevice
Phase 3:         openWakeWord (ONNX) · global hotkey
Phase 4–6:       sqlite-vec · Ollama embeddings · Playwright
Later:           APScheduler · MCP clients · optional computer-use adapter
```

---

## Open questions for architecture review

1. Confirm personal-use OK for openWakeWord CC BY-NC-SA models, or budget custom wake-word training.
2. Prefer `kokoro` (PyTorch) vs `kokoro-mlx` given Python version pin (MLX often &lt;3.13).
3. Confirm default Ollama chat model on the M4 Pro (latency vs quality).
4. Approve “no Open Interpreter dependency in V1” decision.
5. Approve sqlite-vec over FAISS for first semantic store.
