# JARVIS Architecture

**Version:** 0.1  
**Status:** Proposed (Phase 0) — pending review before implementation  
**Related:** [research.md](./research.md) · [requirement.md](./requirement.md) · [implementation-plan.md](./implementation-plan.md)

---

## 1. System architecture

JARVIS is a local-first agent running as a Python process on macOS. External engines (Ollama, STT, TTS, wake word) sit behind provider interfaces. The agent core never imports vendor SDKs directly.

```
                         ┌─────────────────────────────┐
                         │     Input Channels          │
                         │  Terminal · Wake · Hotkey   │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
┌──────────────┐   text    ┌────────────────────────────┐
│ STTProvider  │──────────▶│        AGENT CORE          │
│ (whisper)    │           │  orchestrator · context    │
└──────▲───────┘           │  planner · prompts         │
       │ audio             └─────────┬──────────────────┘
┌──────┴───────┐                     │
│ WakeWord +   │                     ├──▶ MemoryProvider (SQLite + vectors)
│ Mic + VAD    │                     ├──▶ LLMProvider (Ollama)
└──────────────┘                     ├──▶ ToolRegistry → PermissionManager → Tools
                                     │
                                     ▼
                              Response text
                                     │
                        ┌────────────┴────────────┐
                        ▼                         ▼
                 Terminal UI                 TTSProvider
                                             (Kokoro/Piper)
```

High-level capability map (from original sketch, refined):

```
JARVIS
  ├─ Activation: openWakeWord / hotkey / terminal
  ├─ Listen: Microphone → VAD → whisper.cpp
  ├─ Think: Agent Core (Python)
  │    ├─ LLM: Ollama
  │    ├─ Memory: SQLite → sqlite-vec
  │    └─ Tools: Apps · Shell · Files · Browser (Playwright) · Skills
  └─ Speak: Kokoro / Piper
```

---

## 2. Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `jarvis/main.py` | CLI entry (`python -m jarvis`), startup banner, REPL / voice mode selection |
| `jarvis/config` | Load `config.yaml` + env; typed settings; no secrets in logs |
| `jarvis/agent/orchestrator.py` | Turn loop: input → context → LLM → tools → response → persist |
| `jarvis/agent/context.py` | Assemble system prompt, history, memories, project context |
| `jarvis/agent/planner.py` | Optional multi-step planning (later); Phase 1 uses tool-calling loop |
| `jarvis/agent/prompts.py` | Prompt templates; keep model-agnostic |
| `jarvis/llm/base.py` | `LLMProvider` interface: `chat`, `stream_chat`, health check |
| `jarvis/llm/ollama.py` | Ollama adapter only |
| `jarvis/audio/*` | Mic, VAD, wake word, STT, TTS — Phase 2+ |
| `jarvis/memory/*` | Conversation, long-term, episodic, semantic stores |
| `jarvis/tools/base.py` | `Tool` protocol: name, description, params, permission, `execute` |
| `jarvis/tools/registry.py` | Register/discover tools; export LLM tool schemas |
| `jarvis/tools/system.py` | Time, battery, clipboard, system info, apps |
| `jarvis/tools/files.py` | List/find/read/write/move/copy/delete |
| `jarvis/tools/terminal.py` | Restricted command runner |
| `jarvis/tools/browser.py` | Playwright-backed browser tools |
| `jarvis/permissions/manager.py` | SAFE / MODIFICATION / DANGEROUS gates + confirmation UI |
| `jarvis/rag/*` | Ingest, chunk, embed, retrieve |
| `jarvis/scheduler/*` | Reminders / APScheduler (later) |
| `skills/` | Skill packs (instructions + optional tool bundles) |
| `data/` | `jarvis.db`, indexes, non-secret runtime state |

### Provider interfaces (required)

```python
# Conceptual — implemented in Phase 1+

class LLMProvider(Protocol):
    async def stream_chat(self, messages, tools=None) -> AsyncIterator[ChatChunk]: ...
    async def health(self) -> HealthStatus: ...

class STTProvider(Protocol):
    async def transcribe(self, audio: AudioBuffer) -> Transcript: ...

class TTSProvider(Protocol):
    async def synthesize_stream(self, text: AsyncIterator[str]) -> AsyncIterator[AudioChunk]: ...

class WakeWordProvider(Protocol):
    def listen(self) -> Iterator[WakeEvent]: ...

class MemoryProvider(Protocol):
    async def add_message(...): ...
    async def search_semantic(...): ...
    async def remember_fact(...): ...

class Tool(Protocol):
    name: str
    description: str
    permission: PermissionLevel  # SAFE | MODIFICATION | DANGEROUS
    def schema(self) -> dict: ...
    async def execute(self, **params) -> ToolResult: ...
```

---

## 3. Data flow (text turn — Phase 1)

```
User types input
    → Orchestrator creates TurnContext
    → Memory: load recent conversation (+ later semantic hits)
    → LLMProvider.stream_chat(messages, tool_schemas)
    → If tool_calls:
          for each call:
              PermissionManager.authorize(tool, params)
              if denied → return denial to LLM
              ToolRegistry.execute → ActionLog.write
              append tool result message
          loop until final text (max iterations)
    → Stream assistant text to terminal
    → Persist messages to SQLite
```

---

## 4. Voice pipeline (Phase 2–3)

Inspired by LiveKit Agents sequential pipeline; implemented in-process without LiveKit Cloud.

```
Idle
  │ wake word OR hotkey
  ▼
Listening  ── mic frames ──▶ VAD
  │ speech end / silence
  ▼
Transcribing ──▶ STTProvider ──▶ text
  ▼
Processing ──▶ Agent Core (same as text path)
  ▼
Speaking ──▶ sentence buffer ◀── LLM token stream
  │              │
  │              ▼
  │         TTSProvider ──▶ playback
  │
  └─ barge-in: VAD speech while Speaking → cancel TTS + LLM generation → Listening
```

Rules:

- Do not wait for full LLM completion before TTS starts.
- “Stop” / “Cancel” / “Never mind” interrupt when safe.
- Audio buffers are not persisted unless user opts in.
- Hotkey always available if wake word disabled or fails on macOS.

---

## 5. Tool execution pipeline

```
LLM emits tool_call(name, arguments)
        │
        ▼
ToolRegistry.get(name)  ── missing → error result to LLM
        │
        ▼
Validate arguments against schema (outside LLM)
        │
        ▼
PermissionManager.check(level, tool, args, user_settings)
        │
        ├── SAFE → execute
        ├── MODIFICATION → execute or confirm (config)
        └── DANGEROUS → always confirm; no bypass flag for LLM
        │
        ▼
Tool.execute() with timeout
        │
        ├── success → ToolResult + ActionLog
        └── failure → structured error + ActionLog (no crash)
        │
        ▼
Result string/JSON appended as tool message → LLM continues
```

Terminal tool specifics:

- Allowlist / denylist patterns.
- Block destructive patterns unless DANGEROUS confirmation granted.
- Never `shell=True` with raw model strings without validation.
- Capture stdout/stderr with size limits and timeouts.

---

## 6. Permission pipeline

| Level | Behavior | Examples |
|-------|----------|----------|
| **SAFE** | Auto-run | `get_current_time`, `read_file`, `list_files`, `open_application`, `get_clipboard` |
| **MODIFICATION** | Confirm if `permissions.modification_actions: confirm` | `create_file`, `set_clipboard`, non-destructive shell |
| **DANGEROUS** | Always confirm | `delete_file`, destructive shell, send message/email, system config |

Confirmation channel:

- Phase 1: terminal `y/N` prompt.
- Later: desktop UI permission modal.

Invariant: **permission checks live in `PermissionManager`, not in prompts.** Tests must prove DANGEROUS cannot execute without confirmation.

---

## 7. Memory architecture

```
┌─────────────────────────────────────────────┐
│                 SQLite                      │
│  conversations / messages                   │
│  long_term_facts                            │
│  episodic_events                            │
│  action_log                                 │
│  reminders (later)                          │
│  + sqlite-vec virtual tables (embeddings)   │
└─────────────────────────────────────────────┘
```

| Type | Lifetime | Write trigger | Read trigger |
|------|----------|---------------|--------------|
| Conversation | Session / rolling window | Every turn | Every turn |
| Long-term | Permanent until deleted | Explicit “remember…” or curated extract | Semantic + keyword |
| Episodic | Permanent | Important completed actions / user events | “When did I…?” |
| Semantic | Index over facts/docs | On write / ingest | Top-k into context |
| Action log | Permanent | Every tool call | “What did you do today?” |

Project context:

- Configured project roots under `projects/` or user paths.
- “Switch context to X” sets active project; RAG/file tools prefer that root.

---

## 8. Failure handling

| Failure | Behavior |
|---------|----------|
| Ollama down | Health check at start + on error; message: “I couldn't connect to Ollama…”; continue REPL |
| Tool timeout | Cancel; return timeout error to LLM |
| Tool exception | Catch; structured error; log; do not crash process |
| STT/TTS failure | Fall back to text mode; announce failure |
| Wake word init fail | Disable wake word; enable hotkey; warn once |
| Permission denied | Inform user; optional LLM-visible denial message |
| Disk / DB error | Log; degrade gracefully (in-memory turn if needed) |

Every provider exposes `health()` for startup diagnostics.

---

## 9. Security boundaries

```
┌──────────────────────────────────────────────┐
│                 User trust boundary          │
│  confirmation UI · hotkey · config.yaml      │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│ PermissionManager + Tool validators          │  ← hard boundary
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│ OS resources: FS · shell · apps · browser    │
└──────────────────────────────────────────────┘

LLM process/output is UNTRUSTED input to the tool layer.
Network is OPTIONAL; core path works offline.
Secrets never logged; .env for local overrides only.
```

Additional rules:

- No automatic arbitrary shell from the model.
- Browser authenticated sessions require explicit user permission (later).
- MCP / cloud integrations are optional plugins, disabled by default.
- Data stays under `data/` and user-configured project paths.

---

## 10. Configuration sketch

```yaml
assistant:
  name: Jarvis

llm:
  provider: ollama
  host: http://localhost:11434
  model: qwen3   # configurable

speech:
  stt: whisper_cpp
  tts: kokoro
  barge_in: true

wake_word:
  enabled: true
  phrase: hey_jarvis
  backend: openwakeword

memory:
  provider: sqlite
  path: data/jarvis.db
  vector: sqlite_vec

permissions:
  modification_actions: confirm
  dangerous_actions: confirm   # always enforced

logging:
  level: INFO
  structured: true
```

---

## 11. Extensibility (designed now, built later)

| Future capability | Hook |
|-------------------|------|
| MCP | `MCPToolBridge` registering remote tools into `ToolRegistry` |
| GitHub / Notion / Gmail / Drive | Optional skill packs + OAuth; never required for boot |
| Home Assistant / phone | Event bus + remote tool providers |
| Multi-computer | Transport layer outside agent core |
| Screen understanding | New `VisionProvider` interface |
| Proactive tasks | Scheduler → orchestrator jobs with same permissions |
| Custom skills | `skills/<name>/` loaded at startup |

---

## 12. Phase 1 boundary

**In scope:** config, Ollama provider, streaming terminal chat, orchestrator, tool registry, permission manager, basic system tools, SQLite conversation persistence, structured logging, tests, `python -m jarvis`.

**Out of scope until approved later phases:** voice, wake word, RAG, Playwright, Open Interpreter, MCP, reminders UI.
