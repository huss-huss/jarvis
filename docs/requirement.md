# JARVIS

## Local-First Personal AI Assistant

Version: 0.1
Platform: macOS / Apple Silicon
Primary Development Machine: MacBook M4 Pro
Primary IDE: Cursor
Primary Language: Python
Cost Target: $0/month
Architecture: Local-first, modular, privacy-focused

---

# 1. Vision

JARVIS is a personal AI assistant running primarily on the user's Mac.

It should provide a natural voice interface to the computer and eventually function as an intelligent operating layer between the user, local files, applications, browser, projects, reminders, automation systems and external services.

The assistant should be capable of:

* listening for "Hey Jarvis"
* understanding natural speech
* speaking naturally
* remembering information
* answering questions
* searching local information
* operating applications
* performing computer actions
* running terminal commands
* working with files
* controlling a browser
* executing multi-step tasks
* learning reusable skills

The system should run locally whenever technically possible.

No paid AI API should be required for core operation.

---

# 2. Core Principles

## 2.1 Local First

Core functionality must operate without:

* OpenAI API
* Anthropic API
* ElevenLabs
* Deepgram
* paid vector databases
* paid automation platforms
* paid cloud hosting

Internet connectivity may still be used for tasks that inherently require the internet, such as web searches.

---

## 2.2 Privacy

Voice recordings, conversations, memories and files should remain local by default.

No data should be uploaded unless required by an explicitly invoked integration.

---

## 2.3 Modular Architecture

Every major capability should have an interface so components can later be replaced.

Examples:

STTProvider

TTSProvider

LLMProvider

MemoryProvider

WakeWordProvider

ToolProvider

BrowserProvider

---

# 3. Existing Open-Source Components

Do not reinvent components that already have mature open-source implementations.

Preferred technologies:

## Local LLM

Ollama

Responsibilities:

* model management
* local inference
* streaming responses
* tool-selection reasoning

The implementation must not tightly couple JARVIS to one specific Ollama model.

Configuration example:

OLLAMA_MODEL=qwen3
OLLAMA_HOST=http://localhost:11434

Models should be configurable.

---

# 4. Speech-to-Text

Preferred engine:

whisper.cpp

Alternative:

faster-whisper

Requirements:

* completely local
* streaming or near-real-time transcription
* Apple Silicon optimization
* automatic microphone capture
* configurable language
* interruption support

Audio recordings should not be permanently stored unless explicitly requested.

---

# 5. Wake Word

Preferred engine:

openWakeWord

Default phrase:

"Hey Jarvis"

Architecture:

Idle
↓
Wake word detected
↓
Listening
↓
Speech transcription
↓
Processing
↓
Speaking
↓
Idle

A keyboard shortcut must also activate JARVIS when wake-word detection is disabled.

---

# 6. Text-to-Speech

Preferred first implementation:

Kokoro

Fallback:

Piper

Requirements:

* local
* natural English voice
* low latency
* streaming where possible
* configurable voice
* interruption support

JARVIS must stop speaking when the user begins speaking.

This feature is called barge-in.

---

# 7. Agent Core

Implement the agent core in Python.

Responsibilities:

1. Receive user input.
2. Load relevant context.
3. Retrieve memories.
4. Determine user intent.
5. Determine whether tools are necessary.
6. Generate tool calls.
7. Execute authorized tools.
8. inspect tool results.
9. Continue reasoning when necessary.
10. Generate final response.
11. Send response to TTS.
12. Store appropriate conversation/memory data.

Avoid a single giant agent.py file.

Use modular services.

---

# 8. Tool System

Create a generic tool interface.

Each tool must contain:

* name
* description
* parameters
* permission level
* execute()
* result
* error handling

Example:

Tool:
open_application

Input:
application_name

Permission:
safe

Example:

Tool:
delete_file

Input:
file_path

Permission:
dangerous

---

# 9. Initial Tools

Implement the following tools.

## System

open_application()

close_application()

get_running_apps()

get_system_information()

get_battery_status()

get_current_time()

get_clipboard()

set_clipboard()

---

## Files

list_files()

find_file()

read_file()

create_file()

move_file()

copy_file()

summarize_file()

search_files()

Dangerous:

delete_file()

Deletion must always require explicit confirmation.

---

## Terminal

run_command()

Use a restricted execution layer.

Commands modifying the system or deleting information require confirmation.

Never blindly execute arbitrary model-generated shell commands.

---

# 10. Computer Control

Investigate integration with Open Interpreter rather than implementing computer-use capabilities from scratch.

Possible capabilities:

* shell execution
* browser interaction
* application interaction
* screenshots
* UI understanding
* keyboard/mouse actions

JARVIS should wrap these capabilities behind its own Tool interface.

This prevents dependency on Open Interpreter's internal architecture.

---

# 11. Browser

Phase 1:

Use Playwright.

Capabilities:

open_browser()

navigate()

search_web()

read_page()

click()

type_text()

extract_page()

download_file()

Later:

Allow JARVIS to operate authenticated browser sessions with explicit user permission.

---

# 12. Memory Architecture

Memory is critical.

Implement multiple memory types.

## Conversation Memory

Current conversation.

Short-lived.

---

## Long-Term Memory

Facts intentionally remembered about the user.

Examples:

preferred applications

common projects

working preferences

frequent contacts

custom instructions

Store initially in SQLite.

---

## Semantic Memory

Use local embeddings.

Possible stack:

sentence-transformers + FAISS

or

Ollama embeddings + SQLite/vector storage.

Semantic search should retrieve only relevant memories rather than injecting the entire memory database into prompts.

---

## Episodic Memory

Store important completed actions.

Example:

User:
"Jarvis, remember that I submitted the client report."

Later:

User:
"When did I submit the report?"

JARVIS should retrieve the event.

---

# 13. Project Knowledge

JARVIS should support project folders.

Example:

projects/
client-a/
jarvis/
research/
personal/

Users should be able to say:

"Jarvis, switch context to the Jarvis project."

JARVIS should then retrieve information primarily from that project.

---

# 14. Local RAG

Implement document ingestion.

Supported initial formats:

PDF
TXT
Markdown
DOCX
CSV
JSON

Pipeline:

Document
↓
Extract text
↓
Chunk
↓
Create local embeddings
↓
Store index
↓
Semantic retrieval
↓
LLM

Command:

"Jarvis, what did the client say in the requirements document?"

JARVIS should locate the relevant evidence and answer.

---

# 15. Skills

Create a skills architecture.

Directory:

skills/

Example:

skills/
browser/
files/
coding/
research/
reminders/
system/
projects/

Each skill should contain instructions and optional tools.

Future skills can be installed without modifying the core agent.

---

# 16. MCP Support

Design JARVIS to support Model Context Protocol servers.

MCP integrations should be optional.

Possible future connections:

GitHub
Notion
Google Drive
databases
developer tools
custom APIs

Do not make MCP mandatory for the basic assistant.

---

# 17. Reminders

Implement a local scheduler.

Example:

"Jarvis, remind me at 6 PM to call John."

Store:

task
created_at
scheduled_at
status

Use APScheduler or an equivalent local scheduler.

macOS notifications should be supported.

---

# 18. Application Control

Initial applications:

Cursor
Terminal
Finder
Chrome/Safari
VS Code
Notes

Examples:

"Jarvis, open Cursor."

"Jarvis, open my Jarvis project."

"Jarvis, open Terminal."

Use native macOS commands or AppleScript where reliable.

---

# 19. Developer Assistant

JARVIS should eventually understand development projects.

Example:

"Jarvis, check the Jarvis project."

Possible workflow:

git status
↓
git diff
↓
summarize changes
↓
report

Future:

"Run the tests."

"Why are they failing?"

"Show me the latest commits."

"Start the backend."

---

# 20. Safety / Permission System

Implement three action levels.

LEVEL 1 — SAFE

No confirmation.

Examples:

read file
search
open application
get system information

LEVEL 2 — MODIFICATION

May require confirmation depending on settings.

Examples:

create file
edit file
send form
install package

LEVEL 3 — DANGEROUS

Always confirm.

Examples:

delete files
send messages
send emails
financial actions
system configuration changes
execute destructive shell commands

The model must never bypass this system.

---

# 21. Action Log

Every tool action should be recorded.

Store:

timestamp
user request
tool
parameters
result
status
confirmation

The user should be able to ask:

"Jarvis, what did you do today?"

---

# 22. Voice Interaction

Conversation should feel natural.

Required features:

* wake word
* VAD
* streaming transcription
* streaming LLM output
* streaming TTS
* barge-in
* silence detection
* cancel command

Important phrases:

"Stop."

"Cancel."

"Never mind."

These should immediately interrupt execution where safely possible.

---

# 23. UI

Do not build a complex UI initially.

V1 interfaces:

Terminal UI
+
voice interface

Later build a small desktop interface showing:

JARVIS status

Idle
Listening
Thinking
Executing
Speaking

Also show:

transcription
response
tool calls
permission requests

---

# 24. Configuration

Create:

config.yaml

Example:

assistant:
name: Jarvis

llm:
provider: ollama
model: configurable

speech:
stt: whisper
tts: kokoro

wake_word:
enabled: true
phrase: hey_jarvis

memory:
provider: sqlite

permissions:
dangerous_actions: confirm

---

# 25. Suggested Repository Structure

jarvis/
│
├── README.md
├── pyproject.toml
├── .env.example
├── config.yaml
│
├── jarvis/
│   ├── main.py
│   │
│   ├── agent/
│   │   ├── orchestrator.py
│   │   ├── prompts.py
│   │   ├── context.py
│   │   └── planner.py
│   │
│   ├── llm/
│   │   ├── base.py
│   │   └── ollama.py
│   │
│   ├── audio/
│   │   ├── microphone.py
│   │   ├── vad.py
│   │   ├── wakeword.py
│   │   ├── stt.py
│   │   └── tts.py
│   │
│   ├── memory/
│   │   ├── database.py
│   │   ├── conversation.py
│   │   ├── semantic.py
│   │   └── episodic.py
│   │
│   ├── tools/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── system.py
│   │   ├── files.py
│   │   ├── terminal.py
│   │   ├── browser.py
│   │   └── applications.py
│   │
│   ├── permissions/
│   │   └── manager.py
│   │
│   ├── rag/
│   │   ├── ingestion.py
│   │   ├── embeddings.py
│   │   └── retrieval.py
│   │
│   ├── scheduler/
│   │   └── reminders.py
│   │
│   └── utils/
│
├── skills/
│
├── data/
│   ├── jarvis.db
│   ├── memory/
│   └── indexes/
│
├── tests/
│
└── scripts/

---

# 26. Development Phases

## Phase 0 — Repository Research

Before writing significant code:

Study:

* Ollama
* Open Interpreter
* whisper.cpp
* openWakeWord
* Kokoro
* Piper
* LiveKit Agents
* existing local Jarvis implementations

Identify reusable architecture and libraries.

Do not copy code with incompatible licenses.

Document findings in:

docs/research.md

---

## Phase 1 — Text JARVIS

Goal:

Terminal conversation with local Ollama.

Features:

text input
Ollama
streaming response
conversation history
basic tool calling

Success:

User can type:

"Open Cursor."

JARVIS executes the tool.

---

## Phase 2 — Voice

Add:

microphone
Whisper
TTS
VAD

Success:

User speaks.

JARVIS understands and responds verbally.

---

## Phase 3 — Wake Word

Add:

openWakeWord

Success:

"Hey Jarvis"

activates the assistant.

---

## Phase 4 — Memory

Add:

SQLite
semantic retrieval
long-term memory

Success:

JARVIS remembers selected information between restarts.

---

## Phase 5 — Computer Tools

Add:

applications
files
terminal
browser

Investigate Open Interpreter integration.

---

## Phase 6 — RAG

Add:

document ingestion
project knowledge
semantic file search

---

## Phase 7 — Personal Productivity

Add:

reminders
notifications
calendar architecture
task management

Cloud integrations remain optional.

---

## Phase 8 — Proactive JARVIS

Eventually support:

scheduled checks
background jobs
project monitoring
notifications
morning briefings

Example:

"Good morning. You have three tasks due today and your Jarvis repository has two failing tests."

---

# 27. Performance Requirements

Optimize for Apple Silicon.

Target interaction:

Wake detection:
near instantaneous

STT:
near real-time

First LLM token:
preferably <2 seconds

TTS start:
preferably <1 second after sufficient response text

Do not wait for the complete LLM response before beginning speech.

Pipeline:

LLM streaming
↓
sentence buffer
↓
TTS
↓
playback

---

# 28. Reliability

Every external component must have:

timeouts
error handling
logging
health checks

JARVIS should gracefully report failures.

Example:

"I couldn't connect to Ollama. It may not be running."

instead of crashing.

---

# 29. Testing

Tests should cover:

LLM provider
tool registry
permission manager
memory
file tools
command execution
RAG retrieval
scheduler

Dangerous actions must have explicit tests proving confirmation cannot be bypassed.

---

# 30. Logging

Use structured logging.

Development mode should expose:

transcription
retrieved memories
tool selection
tool parameters
tool result
latency
errors

Do not log passwords, tokens or sensitive credentials.

---

# 31. Definition of V1

JARVIS V1 is complete when the following works reliably:

User:

"Hey Jarvis."

Jarvis:

"Yes?"

User:

"Open Cursor and tell me what time it is."

JARVIS:

1. detects wake word
2. transcribes speech
3. interprets intent
4. calls open_application
5. retrieves local time
6. opens Cursor
7. generates response
8. speaks response

And:

User:

"Remember that my test project is called Atlas."

Restart JARVIS.

User:

"What is my test project called?"

Jarvis:

"Atlas."

All of this must function without a paid AI API.

---

# 32. Long-Term Goal

JARVIS should evolve from:

voice chatbot

→ assistant

→ tool-using agent

→ computer assistant

→ persistent personal AI operating layer.

The architecture should prioritize reliability, privacy and modularity over attempting maximum autonomy immediately.
