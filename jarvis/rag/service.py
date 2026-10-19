"""High-level RAG service used by tools and the agent."""

from __future__ import annotations

from pathlib import Path

from jarvis.rag.embeddings import EmbeddingProvider
from jarvis.rag.ingestion import IngestResult, RagIngestor
from jarvis.rag.retrieval import RagRetriever, format_hits_for_prompt, format_hits_for_tool
from jarvis.rag.store import RagDocument, RagHit, RagStore


class RagService:
    def __init__(
        self,
        db_path: str,
        embeddings: EmbeddingProvider,
        roots: list[Path],
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        top_k: int = 5,
    ) -> None:
        self.store = RagStore(db_path, embeddings)
        self.ingestor = RagIngestor(
            self.store,
            roots,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.retriever = RagRetriever(self.store, top_k=top_k)
        self.top_k = top_k

    def ingest_document(self, path: str, *, project: str | None = None) -> IngestResult:
        return self.ingestor.ingest_path(path, project=project)

    def ingest_folder(
        self,
        path: str,
        *,
        project: str | None = None,
        recursive: bool = True,
        limit: int = 100,
    ) -> list[IngestResult]:
        return self.ingestor.ingest_folder(
            path, project=project, recursive=recursive, limit=limit
        )

    def search(self, query: str, *, top_k: int | None = None, project: str | None = None) -> list[RagHit]:
        return self.retriever.search(query, top_k=top_k or self.top_k, project=project)

    def format_for_prompt(self, query: str) -> str:
        return format_hits_for_prompt(self.search(query))

    def format_tool_hits(self, query: str, *, top_k: int | None = None, project: str | None = None) -> str:
        return format_hits_for_tool(self.search(query, top_k=top_k, project=project))

    def list_documents(self, *, project: str | None = None) -> list[RagDocument]:
        return self.store.list_documents(project=project)

    def list_projects(self) -> list[tuple[str, int]]:
        return self.store.list_projects()

    def active_project(self) -> str:
        return self.store.active_project()

    def switch_project(self, project: str) -> str:
        return self.store.set_active_project(project)

    def close(self) -> None:
        self.store.close()
