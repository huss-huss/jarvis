"""Document ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.rag.chunking import chunk_text
from jarvis.rag.extract import SUPPORTED_SUFFIXES, ExtractError, extract_text
from jarvis.rag.store import RagDocument, RagStore
from jarvis.tools.paths import PathDenied, resolve_in_roots


@dataclass
class IngestResult:
    document: RagDocument
    skipped: bool
    message: str


class RagIngestor:
    def __init__(
        self,
        store: RagStore,
        roots: list[Path],
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        self.store = store
        self.roots = roots
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def ingest_path(
        self,
        user_path: str,
        *,
        project: str | None = None,
    ) -> IngestResult:
        path = resolve_in_roots(user_path, self.roots, must_exist=True)
        if path.is_dir():
            raise ExtractError(f"Path is a directory — use ingest_folder: {path}")
        return self._ingest_file(path, project=project or self.store.active_project())

    def ingest_folder(
        self,
        user_path: str,
        *,
        project: str | None = None,
        recursive: bool = True,
        limit: int = 100,
    ) -> list[IngestResult]:
        root = resolve_in_roots(user_path, self.roots, must_exist=True)
        if not root.is_dir():
            raise ExtractError(f"Not a directory: {root}")
        project_name = project or self.store.active_project()
        paths = sorted(root.rglob("*") if recursive else root.iterdir())
        results: list[IngestResult] = []
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if path.name.startswith("."):
                continue
            try:
                results.append(self._ingest_file(path, project=project_name))
            except (ExtractError, OSError, PathDenied) as exc:
                results.append(
                    IngestResult(
                        document=RagDocument(
                            id=0,
                            path=str(path),
                            title=path.name,
                            project=project_name,
                            content_hash="",
                            byte_size=0,
                            chunk_count=0,
                            updated_at="",
                        ),
                        skipped=True,
                        message=str(exc),
                    )
                )
            if len([r for r in results if not r.skipped]) >= limit:
                break
        return results

    def _ingest_file(self, path: Path, *, project: str) -> IngestResult:
        text = extract_text(path)
        if not text.strip():
            raise ExtractError(f"Empty document: {path}")
        pieces = chunk_text(text, chunk_size=self.chunk_size, overlap=self.chunk_overlap)
        chunks = [(c.text, c.start_char, c.end_char) for c in pieces]
        existing = self.store.get_by_path(str(path.resolve()), project)
        doc = self.store.upsert_document(
            path=str(path.resolve()),
            title=path.name,
            project=project,
            text=text,
            chunks=chunks,
        )
        if existing and existing.content_hash == doc.content_hash and existing.id == doc.id:
            return IngestResult(
                document=doc,
                skipped=True,
                message=f"Unchanged (already indexed): {doc.path}",
            )
        return IngestResult(
            document=doc,
            skipped=False,
            message=f"Indexed {doc.path} → {doc.chunk_count} chunks (project={doc.project})",
        )
