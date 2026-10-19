"""RAG / embedding helpers (Phase 4+) and document RAG (Phase 6)."""

from jarvis.rag.embeddings import EmbeddingProvider, HashingEmbeddings, OllamaEmbeddings, create_embeddings
from jarvis.rag.service import RagService

__all__ = [
    "EmbeddingProvider",
    "HashingEmbeddings",
    "OllamaEmbeddings",
    "RagService",
    "create_embeddings",
]
