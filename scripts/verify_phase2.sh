#!/usr/bin/env bash
# Full Phase 1–2 verification for JARVIS.
set -euo pipefail
cd "$(dirname "$0")/.."
PASS=0
FAIL=0

ok() { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

echo "======== PHASE 1–2 VERIFICATION ========"

echo
echo "[1] Unit tests"
if uv run pytest -q; then ok "pytest"; else bad "pytest"; fi

echo
echo "[2] Ollama"
uv run python - <<'PY' && ok "ollama health" || bad "ollama health"
from jarvis.config import load_config
from jarvis.llm.ollama import OllamaProvider
cfg = load_config()
h = OllamaProvider(host=cfg.llm.host, model=cfg.llm.model).health()
print(" ", h.message)
raise SystemExit(0 if h.ok else 1)
PY

echo
echo "[3] Local tools"
uv run python - <<'PY'
from jarvis.tools.system import (
    GetCurrentTimeTool, GetBatteryStatusTool, GetSystemInformationTool,
    GetRunningAppsTool, GetClipboardTool, SetClipboardTool,
    OpenApplicationTool, CloseApplicationTool, is_app_running,
    extract_app_name,
)

checks = []

def check(name, cond, detail=""):
    checks.append((name, cond, detail))
    print(("  PASS" if cond else "  FAIL") + f": {name}" + (f" — {detail}" if detail else ""))

r = GetCurrentTimeTool().execute()
check("get_current_time", r.success and "It is" in r.output, r.output)

r = GetBatteryStatusTool().execute()
check("get_battery_status", r.success, (r.output or r.error or "")[:80])

r = GetSystemInformationTool().execute()
check("get_system_information", r.success and ("arm64" in r.output.lower() or "x86" in r.output.lower() or "Darwin" in r.output or "system" in r.output.lower()))

r = GetRunningAppsTool().execute()
check("get_running_apps", r.success and len(r.data.get("apps", [])) > 0, f"{len(r.data.get('apps', []))} apps")

# clipboard roundtrip
token = "jarvis-clipboard-probe-42"
r = SetClipboardTool().execute(text=token)
check("set_clipboard", r.success, r.output or r.error)
r = GetClipboardTool().execute()
check("get_clipboard", r.success and token in r.output, r.output[:60])

# arg alias
check("extract_app_name alias", extract_app_name({"name": "Calculator"}) == "Calculator")

# open/close calculator
CloseApplicationTool().execute(application_name="Calculator")  # ensure clean
r = OpenApplicationTool().execute(application_name="Calculator")
check("open Calculator", r.success and is_app_running("Calculator"), r.output or r.error)

# open again = activate path
r = OpenApplicationTool().execute(application_name="Calculator")
check("activate Calculator", r.success and is_app_running("Calculator"), r.output or r.error)

# close with wrong key alias (simulates LLM bug)
r = CloseApplicationTool().execute(name="Calculator")
check("close Calculator via name=", r.success and not is_app_running("Calculator"), r.output or r.error)

# reopen and close via application_name
OpenApplicationTool().execute(application_name="Calculator")
r = CloseApplicationTool().execute(application_name="Calculator")
check("close Calculator", r.success and not is_app_running("Calculator"), r.output or r.error)

# protected app
r = CloseApplicationTool().execute(application_name="Finder")
check("refuse quit Finder", (not r.success) and "Refusing" in (r.error or ""))

failed = [n for n,c,_ in checks if not c]
raise SystemExit(1 if failed else 0)
PY
if [[ $? -eq 0 ]]; then ok "local tools suite"; else bad "local tools suite"; fi

echo
echo "[4] Agent tool calling (live Ollama)"
uv run python - <<'PY'
from pathlib import Path
import tempfile
from jarvis.config import load_config
from jarvis.main import build_registry
from jarvis.agent.orchestrator import AgentOrchestrator, _parse_text_tool_calls
from jarvis.llm.ollama import OllamaProvider
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.system import is_app_running, CloseApplicationTool

cfg = load_config()
llm = OllamaProvider(host=cfg.llm.host, model=cfg.llm.model, temperature=0.1)

def orch(db):
    return AgentOrchestrator(
        llm=llm,
        tools=build_registry(cfg),
        permissions=PermissionManager(cfg.permissions, confirm=lambda _p: True),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
    )

checks = []
def check(name, cond, detail=""):
    checks.append((name, cond))
    print(("  PASS" if cond else "  FAIL") + f": {name}" + (f" — {detail}" if detail else ""))

# text tool-call fallback parser
parsed = _parse_text_tool_calls('{"name": "close_application", "parameters": {"name": "Telegram"}}')
check("parse dumped JSON tool call", len(parsed)==1 and parsed[0].arguments.get("application_name")=="Telegram")

db = str(Path(tempfile.mkdtemp()) / "a.db")
r = orch(db).handle_user_message("What time is it?")
check("agent time uses tool", "get_current_time" in r.tool_names, r.tool_names)
check("agent time answer", "It is" in r.text or ":" in r.text or "AM" in r.text or "PM" in r.text, r.text[:80])

db = str(Path(tempfile.mkdtemp()) / "b.db")
CloseApplicationTool().execute(application_name="Calculator")
r = orch(db).handle_user_message("Open Calculator")
check("agent open Calculator tool", "open_application" in r.tool_names, r.tool_names)
check("agent open Calculator real", is_app_running("Calculator"), r.text[:100])

db = str(Path(tempfile.mkdtemp()) / "c.db")
r = orch(db).handle_user_message("Close Calculator")
check("agent close Calculator tool", "close_application" in r.tool_names, r.tool_names)
check("agent close Calculator real", not is_app_running("Calculator"), r.text[:120])

db = str(Path(tempfile.mkdtemp()) / "d.db")
r = orch(db).handle_user_message("Hello Jarvis")
check("greeting no system_information", "get_system_information" not in r.tool_names, r.tool_names)
check("greeting no darwin spam", "darwin" not in r.text.lower() and "arm64" not in r.text.lower(), r.text[:120])

failed = [n for n,c in checks if not c]
raise SystemExit(1 if failed else 0)
PY
if [[ $? -eq 0 ]]; then ok "agent suite"; else bad "agent suite"; fi

echo
echo "[5] Voice stack imports / STT / TTS"
uv run python - <<'PY'
import numpy as np
from jarvis.audio.stt import WhisperCppSTT, _clean_transcript
from jarvis.audio.tts import MacSayTTS, create_tts
from jarvis.audio.vad import SileroVAD
from jarvis.audio.base import AudioBuffer
from jarvis.audio.session import looks_garbled

checks=[]
def check(name, cond, detail=""):
    checks.append((name,cond))
    print(("  PASS" if cond else "  FAIL") + f": {name}" + (f" — {detail}" if detail else ""))

check("name cleanup", _clean_transcript("Hello Dervis")=="Hello Jarvis")
check("garbled detect", looks_garbled("xyz"))
check("hello not garbled", not looks_garbled("hello"))

vad = SileroVAD(threshold=0.4)
silence = np.zeros(512, dtype=np.float32)
check("vad silence", vad.is_speech(silence, 16000) is False)

stt = WhisperCppSTT(model_name="small", language="en")
t = stt.transcribe(AudioBuffer(samples=np.zeros(16000, dtype=np.float32), sample_rate=16000))
check("stt blank audio empty", t.text == "" or t.text.upper()=="")

MacSayTTS().speak("Phase two verification.")
check("macos say tts", True)

# Kokoro may be slow; just ensure factory works
tts = create_tts("macos_say")
check("tts factory", tts is not None)

failed=[n for n,c in checks if not c]
raise SystemExit(1 if failed else 0)
PY
if [[ $? -eq 0 ]]; then ok "voice stack"; else bad "voice stack"; fi

echo
echo "======== SUMMARY ========"
echo "Passed groups-ish checks above. Fail count marker: PASS=$PASS FAIL=$FAIL"
if [[ "$FAIL" -gt 0 ]]; then
  echo "Phase 1–2 NOT fully green."
  exit 1
fi
echo "Phase 1–2 automated verification GREEN."
echo
echo "Manual mic check still recommended:"
echo "  uv run python -m jarvis --voice"
echo "  Open Calculator → put it fullscreen → say Close Calculator"
exit 0
