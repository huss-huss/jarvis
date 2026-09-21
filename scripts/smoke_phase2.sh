#!/usr/bin/env bash
# Phase 1–2 smoke checks for JARVIS (local, $0).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Unit tests =="
uv run pytest -q

echo
echo "== Ollama health =="
uv run python - <<'PY'
from jarvis.config import load_config
from jarvis.llm.ollama import OllamaProvider
cfg = load_config()
h = OllamaProvider(host=cfg.llm.host, model=cfg.llm.model).health()
print(h.message)
raise SystemExit(0 if h.ok else 1)
PY

echo
echo "== Tool: time =="
uv run python - <<'PY'
from jarvis.tools.system import GetCurrentTimeTool
r = GetCurrentTimeTool().execute()
assert r.success, r
print(r.output)
PY

echo
echo "== Tool: open/close Calculator (verified) =="
uv run python - <<'PY'
from jarvis.tools.system import OpenApplicationTool, CloseApplicationTool, is_app_running
open_r = OpenApplicationTool().execute(application_name="Calculator")
print("open:", open_r.output or open_r.error)
assert open_r.success and is_app_running("Calculator"), open_r
close_r = CloseApplicationTool().execute(application_name="Calculator")
print("close:", close_r.output or close_r.error)
assert close_r.success and not is_app_running("Calculator"), close_r
print("open/close verified OK")
PY

echo
echo "== Text agent: greeting should not use system tool =="
uv run python - <<'PY'
from pathlib import Path
import tempfile
from jarvis.config import load_config
from jarvis.main import build_registry, create_app
from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.llm.ollama import OllamaProvider
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager

cfg = load_config()
llm = OllamaProvider(host=cfg.llm.host, model=cfg.llm.model, temperature=0.1)
db = str(Path(tempfile.mkdtemp()) / "t.db")
orch = AgentOrchestrator(
    llm=llm,
    tools=build_registry(cfg),
    permissions=PermissionManager(cfg.permissions, confirm=lambda _p: True),
    memory=ConversationStore(db),
    action_log=ActionLog(db),
)
r = orch.handle_user_message("Hello Jarvis")
print("tools:", r.tool_names)
print("text:", r.text)
assert "get_system_information" not in r.tool_names
print("greeting OK")
PY

echo
echo "All automated Phase 1–2 checks passed."
echo "Manual voice check:  uv run python -m jarvis --voice"
echo "  1) Enter → say: What time is it?"
echo "  2) Enter → say: Open Calculator"
echo "  3) Enter → say: Close Calculator  (confirm y if asked)"
echo "  4) Enter → say: Hello"
