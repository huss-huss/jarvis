"""Text chunking for RAG."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TextChunk:
    text: str
    start_char: int
    end_char: int
    index: int


def chunk_text(
    text: str,
    *,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[TextChunk]:
    """
    Character-window chunking with overlap, preferring paragraph/sentence breaks.
    """
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return []
    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))

    chunks: list[TextChunk] = []
    start = 0
    n = len(cleaned)
    index = 0
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            window = cleaned[start:end]
            # Prefer break at paragraph, then sentence, then space
            break_at = max(
                window.rfind("\n\n"),
                window.rfind(". "),
                window.rfind("\n"),
                window.rfind(" "),
            )
            if break_at >= chunk_size // 3:
                end = start + break_at + 1
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(TextChunk(text=piece, start_char=start, end_char=end, index=index))
            index += 1
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks
