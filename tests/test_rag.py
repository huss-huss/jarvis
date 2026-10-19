"""Phase 6 RAG tests."""

from __future__ import annotations

from pathlib import Path

from jarvis.rag.chunking import chunk_text
from jarvis.rag.embeddings import HashingEmbeddings
from jarvis.rag.service import RagService
from jarvis.tools.rag import build_rag_tools
from jarvis.tools.registry import ToolRegistry


def test_chunk_text_overlap():
    text = ("Paragraph one. " * 40) + "\n\n" + ("Paragraph two. " * 40)
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) >= 2
    assert all(c.text for c in chunks)


def test_ingest_and_retrieve_requirements_style(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    req = docs / "requirements.md"
    req.write_text(
        "# Client requirements\n\n"
        "The client said the Atlas dashboard must load in under two seconds.\n"
        "Also support offline mode for field technicians.\n",
        encoding="utf-8",
    )
    other = docs / "notes.txt"
    other.write_text("Grocery list: milk and eggs.\n", encoding="utf-8")

    rag = RagService(str(tmp_path / "rag.db"), HashingEmbeddings(), [tmp_path])
    rag.switch_project("jarvis")
    result = rag.ingest_document(str(req), project="jarvis")
    assert not result.skipped
    assert result.document.chunk_count >= 1

    hits = rag.search("What did the client say about Atlas dashboard load time?")
    assert hits
    assert any("two seconds" in h.text.lower() or "atlas" in h.text.lower() for h in hits)

    # empty corpus project still safe
    empty_hits = rag.search("nothing here", project="emptyproj")
    assert empty_hits == [] or isinstance(empty_hits, list)
    rag.close()


def test_skip_unchanged_reingest(tmp_path: Path):
    f = tmp_path / "a.md"
    f.write_text("hello world " * 20, encoding="utf-8")
    rag = RagService(str(tmp_path / "rag.db"), HashingEmbeddings(), [tmp_path])
    first = rag.ingest_document(str(f))
    second = rag.ingest_document(str(f))
    assert first.skipped is False
    assert second.skipped is True
    rag.close()


def test_rag_tools_roundtrip(tmp_path: Path):
    f = tmp_path / "spec.md"
    f.write_text(
        "Phase 6 success means answering from the requirements document with evidence.\n",
        encoding="utf-8",
    )
    rag = RagService(str(tmp_path / "rag.db"), HashingEmbeddings(), [tmp_path], top_k=3)
    registry = ToolRegistry()
    for tool in build_rag_tools(rag):
        registry.register(tool)

    ingested = registry.execute("ingest_document", {"path": str(f), "project": "jarvis"})
    assert ingested.success, ingested.error
    searched = registry.execute(
        "search_docs",
        {"query": "requirements document evidence Phase 6", "project": "jarvis"},
    )
    assert searched.success
    assert "Phase 6" in searched.output or "requirements" in searched.output.lower()
    listed = registry.execute("list_ingested", {"project": "jarvis"})
    assert listed.success
    assert "spec.md" in listed.output
    rag.close()


def test_switch_project(tmp_path: Path):
    rag = RagService(str(tmp_path / "rag.db"), HashingEmbeddings(), [tmp_path])
    assert rag.switch_project("Atlas App") == "atlas_app"
    assert rag.active_project() == "atlas_app"
    rag.close()
