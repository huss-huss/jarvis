You are acting as the lead software architect and senior Python engineer for a project called JARVIS.

JARVIS is a completely local-first personal AI assistant for macOS running on an Apple Silicon MacBook M4 Pro.

The project must have ZERO mandatory recurring cost.

The user already has Ollama installed.

Read the project's REQUIREMENTS.md completely before making architectural decisions.

IMPORTANT DEVELOPMENT RULES:

1. Do not attempt to build the entire project at once.

2. Do not reinvent mature open-source functionality.

3. Before implementing a subsystem, investigate whether an established open-source library already provides it.

4. Prefer mature, actively maintained projects with strong communities.

5. Core operation must not require paid APIs.

6. Keep providers modular so they can be replaced later.

7. Prioritize macOS and Apple Silicon performance.

8. Never allow an LLM to execute destructive actions without passing through the permission system.

9. Write maintainable production-quality Python rather than prototype spaghetti code.

10. Add tests as components are implemented.

11. Keep commits/features small and understandable.

12. Do not silently introduce cloud dependencies.

13. Do not require OpenAI, Anthropic, ElevenLabs, Deepgram or other paid APIs.

14. Internet-dependent tools such as web search are allowed, but JARVIS itself must continue functioning locally without them.

TECHNOLOGIES TO INVESTIGATE FIRST:

LLM:
Ollama

Speech-to-text:
whisper.cpp
faster-whisper

Wake word:
openWakeWord

Text-to-speech:
Kokoro
Piper

Computer interaction:
Open Interpreter

Browser:
Playwright

Voice orchestration/reference:
LiveKit Agents

Memory:
SQLite initially

Semantic search:
FAISS or another lightweight local vector solution

Embeddings:
local sentence-transformers or Ollama embeddings

FIRST TASK — DO NOT IMPLEMENT JARVIS YET.

Perform a technical discovery pass.

Inspect the repository.

Read REQUIREMENTS.md.

Then research the architecture and integration points of the open-source components listed above.

Pay special attention to:

* current maintenance status
* license
* macOS compatibility
* Apple Silicon compatibility
* Python integration
* local/offline capability
* streaming capability
* latency
* dependency complexity
* whether functionality can be reused instead of rebuilt

Create:

docs/research.md

The document should contain a table:

Component
Candidate
Purpose
License
Maintenance
Apple Silicon
Advantages
Disadvantages
Decision

Then create:

docs/architecture.md

Include:

* system architecture
* module responsibilities
* data flow
* voice pipeline
* tool execution pipeline
* permission pipeline
* memory architecture
* failure handling
* security boundaries

Then create:

docs/implementation-plan.md

Break development into small milestones.

Each milestone must contain:

Goal
Components
Files
Tests
Acceptance criteria

STOP after producing these documents.

Do not begin the full implementation until the architecture has been reviewed.

When implementation is approved, start ONLY with Phase 1:

TEXT-ONLY JARVIS.

Phase 1 should contain:

Python project structure

configuration management

Ollama provider

streaming chat

agent orchestrator

tool registry

permission manager

basic system tools

SQLite conversation persistence

structured logging

tests

The initial executable should support:

python -m jarvis

The interface should initially be terminal based.

Example:

$ python -m jarvis

JARVIS Local Assistant
Model: <configured Ollama model>
Status: Ready

You: What time is it?

Jarvis: It is 9:25 AM.

You: Open Cursor.

Jarvis: Opening Cursor.

Do NOT implement voice until this text-based foundation is stable.

ARCHITECTURAL REQUIREMENT:

Every major external dependency must sit behind an internal interface.

For example:

LLMProvider
STTProvider
TTSProvider
WakeWordProvider
MemoryProvider
Tool

JARVIS's agent core should depend on those interfaces rather than directly depending on Ollama, Whisper, Kokoro, etc.

SECURITY:

Tools must be classified as:

SAFE
MODIFICATION
DANGEROUS

DANGEROUS actions always require explicit user confirmation.

Never execute arbitrary shell commands automatically simply because the language model requested them.

Implement command validation and permission checks outside the LLM.

LOCAL-FIRST:

The project should remain usable when the internet is disconnected.

The following should continue working offline:

LLM
voice recognition
voice synthesis
wake word
memory
local file search
application control
local RAG
basic computer control

DESIGN FOR FUTURE CAPABILITIES:

Do not implement these immediately, but ensure the architecture can later support:

MCP
GitHub
Google Calendar
Gmail
Notion
Google Drive
phone companion app
Home Assistant
multiple computers
custom skills
proactive background tasks
screen understanding
browser automation
project monitoring

QUALITY STANDARD:

Treat this as a long-lived personal software project, not a hackathon demo.

Prefer:

simple
modular
testable
observable
secure
replaceable

over:

clever
monolithic
over-engineered
fragile

Before changing architecture later, explain why the change is necessary.

Begin now with the technical discovery phase only.
