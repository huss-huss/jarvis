#!/usr/bin/env bash
# Phase 6 acceptance: ingest requirements-style doc → retrieve grounded answer
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

WS="$(mktemp -d -t jarvis-phase6)"
trap 'rm -rf "$WS"' EXIT
DB="$WS/rag.db"
DOC="$WS/requirements.md"

cat > "$DOC" <<'EOF'
# Client requirements

The client said the Atlas dashboard must load in under two seconds.
Offline mode is required for field technicians.
EOF

echo "== Phase 6 RAG verify =="
"$PY" - <<PY
from pathlib import Path
from jarvis.rag.embeddings import HashingEmbeddings
from jarvis.rag.service import RagService

ws = Path("$WS")
rag = RagService("$DB", HashingEmbeddings(), [ws], top_k=3)
rag.switch_project("jarvis")
result = rag.ingest_document(str(ws / "requirements.md"), project="jarvis")
assert not result.skipped, result.message
print(result.message)

hits = rag.search("What did the client say about Atlas dashboard performance?")
assert hits, "expected retrieval hits"
assert any("two seconds" in h.text.lower() for h in hits), hits
print("recalled:", hits[0].text[:120].replace("\n", " "))
print("PASS: ingest → retrieve grounded Atlas requirement")
rag.close()
PY

echo "== Phase 6 verify done =="
