# JARVIS

Local-first personal AI assistant for macOS (Apple Silicon).

**Cost:** $0/month for core operation. Uses local [Ollama](https://ollama.com) — no OpenAI, Anthropic, or other paid APIs required.

## Phase 1 — Text

Terminal assistant with streaming Ollama chat, tools, permissions, SQLite history.

## Phase 2 — Voice

Microphone → Silero VAD → whisper.cpp STT → agent → Kokoro TTS (macOS `say` fallback).

Wake word (“Hey Jarvis”) comes in Phase 3.

## Requirements

- macOS + Apple Silicon recommended
- Python 3.11+
- [Ollama](https://ollama.com) installed and running
- A local model with tool support (e.g. `llama3.1`)

```bash
ollama pull llama3.1
```

Optional for Kokoro TTS quality (if Homebrew works on your machine):

```bash
brew install espeak-ng
```

If `espeak-ng` is missing, JARVIS can still speak via macOS `say` (`speech.tts: macos_say`).

## Setup

```bash
uv sync --dev
uv sync --extra voice   # Phase 2 audio stack
```

## Run

Text mode:

```bash
python -m jarvis
```

Voice mode (press Enter to talk, or type):

```bash
python -m jarvis --voice
```

Example (text):

```text
JARVIS Local Assistant
Model: llama3.1
Status: Ready

You: What time is it?
Jarvis: It is 9:25 AM.
```

## Permissions

Every tool declares a permission level, and `PermissionManager` checks it before the tool runs.
The model can ask for a tool, but it can't skip this check. Every decision is logged.

| Level | What happens | Config |
|---|---|---|
| `safe` | Runs immediately | none |
| `modification` | Runs immediately when `permissions.modification_actions: allow`; otherwise asks first | `modification_actions: allow \| confirm` |
| `dangerous` | **Always** asks, whatever the config says. A denial or an unclear answer means no | `dangerous_actions: confirm` |

Confirmation works in both modes. In text mode it's a `[y/N]` prompt. In voice mode Jarvis reads out the action and its arguments, then listens for a yes or no. Phrases like "yeah, do it" count as yes; anything unclear counts as no.

Current tools:

| Tool | Level | Notes |
|---|---|---|
| `get_current_time`, `get_system_information`, `get_battery_status`, `get_running_apps`, `get_clipboard` | safe | read-only |
| `open_application` | safe | |
| `close_application` | safe | Quits, then checks the app actually stopped. Refuses system processes (Finder, Dock, WindowServer, loginwindow...). It can force-quit a stuck app, so unsaved work in that app may be lost |
| `set_clipboard` | safe | overwrites the clipboard |

No current tool uses `modification` or `dangerous`. Those levels are there for tools that write files or delete things. A new tool picks its level by setting `permission = PermissionLevel.DANGEROUS` (or another level) on its class.

## Config

Edit `config.yaml` or set:

- `OLLAMA_HOST` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (default `llama3.1`)

Speech section:

```yaml
speech:
  stt_model: base      # whisper.cpp model
  tts: kokoro          # or macos_say
  tts_voice: af_heart
```

## Tests

```bash
pytest
```

## License

MIT
