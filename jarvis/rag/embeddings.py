"""Local embedding providers — Ollama primary, hashing fallback ($0)."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any

from jarvis.logging import get_logger

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def health(self) -> tuple[bool, str]:
        try:
            vec = self.embed("health check")
            return True, f"{self.model_name} dim={len(vec)}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


class HashingEmbeddings(EmbeddingProvider):
    """
    Deterministic local bag-of-words hashing.
    Used for tests and when Ollama embedding models are unavailable.
    Good enough for short personal facts; not a substitute for real embeddings at scale.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def model_name(self) -> str:
        return f"hashing/{self.dim}"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall((text or "").lower())
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        return _l2_normalize(vec)


class OllamaEmbeddings(EmbeddingProvider):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        *,
        fallback: EmbeddingProvider | None = None,
    ) -> None:
        import ollama

        self.host = host
        self.model = model
        self._client = ollama.Client(host=host)
        self._fallback = fallback or HashingEmbeddings()
        self._using_fallback = False
        self._warned = False

    @property
    def model_name(self) -> str:
        if self._using_fallback:
            return self._fallback.model_name
        return self.model

    def embed(self, text: str) -> list[float]:
        cleaned = (text or "").strip()
        if not cleaned:
            return self._fallback.embed("")
        try:
            response = self._client.embed(model=self.model, input=cleaned)
            vectors = _extract_embeddings(response)
            if not vectors:
                raise RuntimeError("empty embedding response")
            self._using_fallback = False
            return _l2_normalize([float(x) for x in vectors[0]])
        except Exception as exc:  # noqa: BLE001
            if not self._warned:
                log.warning(
                    "ollama_embeddings_unavailable_using_hashing",
                    model=self.model,
                    error=str(exc),
                    hint=f"ollama pull {self.model}",
                )
                self._warned = True
            self._using_fallback = True
            return self._fallback.embed(cleaned)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        cleaned = [(t or "").strip() or " " for t in texts]
        if not cleaned:
            return []
        try:
            response = self._client.embed(model=self.model, input=cleaned)
            vectors = _extract_embeddings(response)
            if len(vectors) != len(cleaned):
                raise RuntimeError("embedding count mismatch")
            self._using_fallback = False
            return [_l2_normalize([float(x) for x in v]) for v in vectors]
        except Exception as exc:  # noqa: BLE001
            if not self._warned:
                log.warning(
                    "ollama_embeddings_unavailable_using_hashing",
                    model=self.model,
                    error=str(exc),
                    hint=f"ollama pull {self.model}",
                )
                self._warned = True
            self._using_fallback = True
            return [self._fallback.embed(t) for t in cleaned]


def create_embeddings(
    *,
    provider: str = "ollama",
    host: str = "http://localhost:11434",
    model: str = "nomic-embed-text",
) -> EmbeddingProvider:
    if provider in {"hashing", "local"}:
        return HashingEmbeddings()
    if provider == "ollama":
        return OllamaEmbeddings(host=host, model=model)
    raise ValueError(f"Unknown embedding provider: {provider}")


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 1e-12:
        return vec
    return [x / norm for x in vec]


def _extract_embeddings(response: Any) -> list[list[float]]:
    if response is None:
        return []
    if isinstance(response, dict):
        data = response.get("embeddings") or response.get("embedding")
    else:
        data = getattr(response, "embeddings", None) or getattr(response, "embedding", None)
    if data is None:
        return []
    if data and isinstance(data[0], (int, float)):
        return [list(data)]
    return [list(v) for v in data]
