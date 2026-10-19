#!/usr/bin/env bash
# Phase 5 acceptance: files + terminal safety (+ browser optional)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

WS="$(mktemp -d -t jarvis-phase5)"
trap 'rm -rf "$WS"' EXIT

echo "== Phase 5 computer-tools verify =="
echo "Workspace: $WS"

"$PY" - <<PY
from pathlib import Path
from jarvis.tools.files import build_file_tools
from jarvis.tools.paths import PathDenied, resolve_in_roots
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.terminal import RunCommandTool

ws = Path("$WS")
registry = ToolRegistry()
for t in build_file_tools([ws]):
    registry.register(t)

r = registry.execute("create_file", {"path": "hello.txt", "content": "phase5-ok", "overwrite": True})
assert r.success, r.error
r = registry.execute("read_file", {"path": "hello.txt"})
assert r.success and "phase5-ok" in r.output
r = registry.execute("list_files", {"path": "."})
assert r.success and "hello.txt" in r.output

# path escape blocked
try:
    resolve_in_roots("/etc/passwd", [ws])
    raise SystemExit("FAIL: expected PathDenied")
except PathDenied:
    print("PASS: path traversal blocked")

term = RunCommandTool(cwd=ws)
assert term.execute(command="pwd").success
assert term.execute(command="rm -rf /").success is False
assert term.execute(command="echo hi; ls").success is False
print("PASS: terminal allowlist + deny")

r = registry.execute("delete_file", {"path": "hello.txt"})
assert r.success
print("PASS: file create/read/delete")
print("PASS: Phase 5 core")
PY

"$PY" - <<'PY' || true
from jarvis.browser import create_browser
b = create_browser(enabled=True, headless=True)
ok, msg = b.health()
if ok:
    print(f"browser: ready — {msg}")
else:
    print(f"browser: unavailable — {msg}")
    print("tip: uv sync --extra browser && playwright install chromium")
PY

echo "== Phase 5 verify done =="
