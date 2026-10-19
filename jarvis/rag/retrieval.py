"""RAG retrieval helpers."""

from __future__ import annotations

from jarvis.rag.store import RagHit, RagStore


def format_hits_for_prompt(hits: list[RagHit], *, max_chars: int = 6000) -> str:
    if not hits:
        return ""
    lines = [
        "Relevant document excerpts (cite the source path; do not invent details beyond these):"
    ]
    used = 0
    for i, hit in enumerate(hits, start=1):
        header = f"[{i}] {hit.path} (project={hit.project}, score={hit.score:.2f})"
        body = hit.text.strip()
        block = f"{header}\n{body}"
        if used + len(block) > max_chars:
            remain = max_chars - used - len(header) - 20
            if remain < 80:
                break
            body = body[:remain] + "…"
            block = f"{header}\n{body}"
        lines.append(block)
        used += len(block)
    return "\n\n".join(lines)


def format_hits_for_tool(hits: list[RagHit]) -> str:
    if not hits:
        return "No matching document chunks found. Ingest files first with ingest_document / ingest_folder."
    parts = []
    for i, hit in enumerate(hits, start=1):
        parts.append(
            f"{i}. {hit.path} [project={hit.project} chunk={hit.chunk_index} score={hit.score:.2f}]\n"
            f"{hit.text.strip()}"
        )
    return "Retrieved excerpts:\n\n" + "\n\n---\n\n".join(parts)


class RagRetriever:
    def __init__(self, store: RagStore, *, top_k: int = 5) -> None:
        self.store = store
        self.top_k = top_k

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        project: str | None = None,
        prefer_active: bool = True,
    ) -> list[RagHit]:
        k = top_k or self.top_k
        active = self.store.active_project() if prefer_active else None
        scope = project if project is not None else active
        hits = self.store.search(query, top_k=k, project=scope)
        # If active project is empty, fall back to all projects
        if not hits and scope and project is None:
            hits = self.store.search(query, top_k=k, project=None)
        return hits

    def format_for_prompt(self, query: str, *, top_k: int | None = None) -> str:
        return format_hits_for_prompt(self.search(query, top_k=top_k))
