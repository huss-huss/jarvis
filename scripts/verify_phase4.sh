#!/usr/bin/env bash
# Phase 4 acceptance: remember Atlas → reopen DB → recall Atlas
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

export JARVIS_CONFIG="${ROOT}/config.yaml"
DB="$(mktemp -t jarvis-phase4.XXXXXX).db"
trap 'rm -f "$DB"' EXIT

echo "== Phase 4 memory verify =="
echo "DB: $DB"

"$PY" - <<PY
from jarvis.memory.long_term import LongTermMemory
from jarvis.rag.embeddings import create_embeddings, HashingEmbeddings
from jarvis.config import load_config

cfg = load_config()
# Prefer hashing for CI determinism; still exercises full store path.
emb = HashingEmbeddings()
mem = LongTermMemory("$DB", emb)
fact = mem.remember_fact(
    "The user's test project is called Atlas.",
    key="test_project",
)
assert fact.key == "test_project"
print("stored:", fact.content)
mem.close()

mem2 = LongTermMemory("$DB", HashingEmbeddings())
hits = mem2.search("What is my test project called?")
assert hits, "expected semantic/keyword hits"
assert any("Atlas" in h.text for h in hits), hits
print("recalled:", hits[0].text)
print("PASS: remember → restart → recall Atlas")
mem2.close()
PY

# Optional live Ollama embed smoke (non-fatal)
"$PY" - <<'PY' || true
from jarvis.rag.embeddings import OllamaEmbeddings
emb = OllamaEmbeddings(model="nomic-embed-text")
ok, msg = emb.health()
print("ollama embeddings:", "ok" if ok and not emb._using_fallback else f"fallback ({msg})")
if ok and not emb._using_fallback:
    print("tip: embeddings model ready")
else:
    print("tip: ollama pull nomic-embed-text  # better semantic recall")
PY

echo "== Phase 4 verify done =="
