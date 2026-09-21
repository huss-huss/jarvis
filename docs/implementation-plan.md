# JARVIS Implementation Plan

**Status:** Phase 0 complete (docs only) — implementation starts after architecture review  
**Rule:** Small milestones; tests with each component; no voice until text foundation is stable

---

## Milestone 0 — Discovery (current)

| Field | Content |
|-------|---------|
| **Goal** | Evaluate OSS stack; lock architecture; plan delivery |
| **Components** | Research notes, architecture, this plan |
| **Files** | `docs/research.md`, `docs/architecture.md`, `docs/implementation-plan.md` |
| **Tests** | N/A |
| **Acceptance criteria** | Documents reviewed; stack decisions approved (especially: no OI in V1, sqlite-vec, Kokoro, whisper.cpp, Ollama) |

---

## Milestone 1 — Project skeleton

| Field | Content |
|-------|---------|
| **Goal** | Installable Python package with entrypoint and config |
| **Components** | Packaging, settings, logging, empty agent shell |
| **Files** | `pyproject.toml`, `README.md`, `.env.example`, `config.yaml`, `jarvis/__init__.py`, `jarvis/__main__.py`, `jarvis/main.py`, `jarvis/config.py`, `jarvis/logging.py`, `tests/test_config.py` |
| **Tests** | Config loads defaults; env overrides work; invalid config fails clearly |
| **Acceptance criteria** | `pip install -e .` works; `python -m jarvis --help` or boot prints banner; no network required |

---

## Milestone 2 — Ollama LLM provider

| Field | Content |
|-------|---------|
| **Goal** | Streaming chat behind `LLMProvider` |
| **Components** | `LLMProvider` ABC, Ollama adapter, health check |
| **Files** | `jarvis/llm/base.py`, `jarvis/llm/ollama.py`, `tests/test_llm_ollama.py` |
| **Tests** | Mock HTTP/stream unit tests; optional integration test skipped if Ollama down |
| **Acceptance criteria** | Stream tokens from configured local model; friendly error if daemon unreachable; no cloud host by default |

---

## Milestone 3 — Terminal REPL

| Field | Content |
|-------|---------|
| **Goal** | Text conversation loop with streaming display |
| **Components** | REPL, orchestrator stub (chat-only), message formatting |
| **Files** | `jarvis/agent/orchestrator.py`, `jarvis/agent/prompts.py`, `jarvis/ui/terminal.py`, `tests/test_orchestrator_chat.py` |
| **Tests** | Orchestrator yields assistant text from fake LLM |
| **Acceptance criteria** | Banner shows model + Ready; user can chat; Ctrl+C exits cleanly |

Example:

```text
$ python -m jarvis

JARVIS Local Assistant
Model: qwen3
Status: Ready

You: Hello
Jarvis: ...
```

---

## Milestone 4 — SQLite conversation persistence

| Field | Content |
|-------|---------|
| **Goal** | Persist turns across process restarts |
| **Components** | DB bootstrap, conversation store |
| **Files** | `jarvis/memory/database.py`, `jarvis/memory/conversation.py`, `tests/test_conversation_memory.py` |
| **Tests** | Write/read messages; isolated temp DB |
| **Acceptance criteria** | Restart retains recent history within configured window; DB under `data/` |

---

## Milestone 5 — Tool registry + permission manager

| Field | Content |
|-------|---------|
| **Goal** | Generic tools with SAFE / MODIFICATION / DANGEROUS enforcement |
| **Components** | Tool protocol, registry, permission manager, action log schema |
| **Files** | `jarvis/tools/base.py`, `jarvis/tools/registry.py`, `jarvis/permissions/manager.py`, `jarvis/memory/action_log.py`, `tests/test_permissions.py`, `tests/test_tool_registry.py` |
| **Tests** | DANGEROUS blocked without confirmation; SAFE auto-runs; unknown tool errors |
| **Acceptance criteria** | LLM cannot bypass permissions; confirmations recorded in action log |

---

## Milestone 6 — Basic system tools

| Field | Content |
|-------|---------|
| **Goal** | First real computer actions from chat |
| **Components** | System/time/clipboard/apps tools; macOS `open` / AppleScript where needed |
| **Files** | `jarvis/tools/system.py`, `jarvis/tools/applications.py`, `tests/test_system_tools.py` |
| **Tests** | `get_current_time` deterministic enough; app open mocked; clipboard round-trip where possible |
| **Acceptance criteria** | “What time is it?” and “Open Cursor.” work end-to-end with Ollama tool calling |

---

## Milestone 7 — Agent tool loop (Phase 1 complete)

| Field | Content |
|-------|---------|
| **Goal** | Full text agent: stream + tools + permissions + persistence + logging |
| **Components** | Orchestrator tool loop, structured logs, max-iteration guard |
| **Files** | Updates to `orchestrator.py`, `jarvis/agent/context.py`, logging hooks, `tests/test_agent_tool_loop.py` |
| **Tests** | Fake LLM requesting tools; permission denial path; iteration limit |
| **Acceptance criteria** | Phase 1 definition met: terminal JARVIS with local Ollama, streaming, history, basic tools; **no voice code required** |

**Phase 1 exit checklist**

- [ ] `python -m jarvis` terminal UI
- [ ] Configurable Ollama model
- [ ] Streaming responses
- [ ] Tool registry + permission manager
- [ ] Basic system tools
- [ ] SQLite conversation persistence
- [ ] Structured logging
- [ ] Tests for LLM adapter, registry, permissions, tools

---

## Milestone 8 — Voice I/O (Phase 2)

| Field | Content |
|-------|---------|
| **Goal** | Speak and listen without wake word |
| **Components** | Mic capture, Silero VAD, whisper.cpp STT, Kokoro TTS, barge-in |
| **Files** | `jarvis/audio/microphone.py`, `vad.py`, `stt.py`, `tts.py`, provider adapters, `tests/audio/*` |
| **Tests** | VAD/STT/TTS unit tests with fixtures; barge-in cancels playback |
| **Acceptance criteria** | Push-to-talk or VAD turn works offline; response spoken; text fallback on audio failure |

---

## Milestone 9 — Wake word (Phase 3)

| Field | Content |
|-------|---------|
| **Goal** | “Hey Jarvis” + hotkey activation |
| **Components** | openWakeWord ONNX path, hotkey, state machine Idle→Listening |
| **Files** | `jarvis/audio/wakeword.py`, config flags, tests for state transitions |
| **Tests** | Mock detector fires wake event; failure disables wake word gracefully |
| **Acceptance criteria** | Wake or hotkey starts listen cycle; NC model license noted in README |

---

## Milestone 10 — Memory depth (Phase 4)

| Field | Content |
|-------|---------|
| **Goal** | Long-term + semantic recall across restarts |
| **Components** | Facts, episodic events, Ollama embeddings, sqlite-vec |
| **Files** | `jarvis/memory/semantic.py`, `episodic.py`, `jarvis/rag/embeddings.py`, tests |
| **Tests** | Remember fact → restart → retrieve; semantic top-k |
| **Acceptance criteria** | “Remember my test project is Atlas” / “What is my test project called?” → “Atlas.” |

---

## Milestone 11 — Files + terminal tools (Phase 5a)

| Field | Content |
|-------|---------|
| **Goal** | Safe file ops + restricted shell |
| **Components** | File tools, terminal allowlist, delete confirmation |
| **Files** | `jarvis/tools/files.py`, `terminal.py`, extensive permission tests |
| **Tests** | Delete requires confirm; path traversal blocked; dangerous shell blocked |
| **Acceptance criteria** | File Q&A and controlled commands work; no blind `os.system` |

---

## Milestone 12 — Browser tools (Phase 5b)

| Field | Content |
|-------|---------|
| **Goal** | Playwright behind `BrowserProvider` |
| **Components** | open/navigate/read/click/type/extract |
| **Files** | `jarvis/tools/browser.py`, `jarvis/browser/playwright_provider.py`, tests with mocked page |
| **Tests** | Tool schemas; navigation mocked; permission on downloads/forms |
| **Acceptance criteria** | Basic browse/read works when online; JARVIS still runs if Playwright browsers missing (clear error) |

---

## Milestone 13 — Local RAG (Phase 6)

| Field | Content |
|-------|---------|
| **Goal** | Ingest project docs and answer with evidence |
| **Components** | PDF/TXT/MD/DOCX/CSV/JSON ingest, chunk, embed, retrieve |
| **Files** | `jarvis/rag/ingestion.py`, `retrieval.py`, project context switch |
| **Tests** | Chunking; retrieval returns seeded doc; empty corpus safe |
| **Acceptance criteria** | Question about ingested requirements doc returns grounded answer |

---

## Milestone 14 — Productivity (Phase 7)

| Field | Content |
|-------|---------|
| **Goal** | Reminders + macOS notifications |
| **Components** | APScheduler, reminder store, notification bridge |
| **Files** | `jarvis/scheduler/reminders.py`, tests |
| **Tests** | Schedule/fire reminder in fake clock |
| **Acceptance criteria** | “Remind me at 6 PM…” persists and notifies locally |

---

## Milestone 15 — Proactive + integrations (Phase 8+)

| Field | Content |
|-------|---------|
| **Goal** | Background jobs, MCP, optional cloud skills |
| **Components** | Job runner, MCP bridge, skill installer |
| **Files** | `jarvis/jobs/*`, `jarvis/mcp/*`, `skills/*` |
| **Tests** | MCP tools honor permissions; jobs cannot escalate privileges |
| **Acceptance criteria** | Optional integrations off by default; core offline path unchanged |

---

## Suggested implementation order (calendar)

1. Review & approve architecture  
2. Milestones 1–7 → **Phase 1 TEXT JARVIS**  
3. Pause for UX/stability polish  
4. Milestones 8–9 → voice + wake word  
5. Milestones 10–13 → memory, tools, RAG  
6. Milestones 14–15 → productivity & proactive  

---

## Definition of done (V1)

From requirements §31, mapped to milestones:

| V1 behavior | Milestone |
|-------------|-----------|
| Wake word “Hey Jarvis” | 9 |
| Transcribe + respond by voice | 8 |
| Open Cursor + tell time | 6–7 + 8 |
| Remember fact across restart | 10 |
| Zero paid API | All |

---

## Stop line

**Do not start Milestone 1 until architecture review sign-off.**  
When approved, implement **Phase 1 / Milestones 1–7 only**.
