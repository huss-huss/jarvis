"""Semantic index over facts/episodes — vectors in SQLite, cosine in Python."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from jarvis.memory.database import connect, init_db
from jarvis.rag.embeddings import EmbeddingProvider, cosine_similarity


@dataclass
class SemanticHit:
    owner_type: str
    owner_id: int
    text: str
    score: float
    meta: dict


class SemanticIndex:
    def __init__(
        self,
        db_path: str,
        embeddings: EmbeddingProvider,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = db_path
        self.embeddings = embeddings
        self._owns_conn = conn is None
        self._conn = conn or connect(db_path)
        if self._owns_conn:
            init_db(self._conn)

    def upsert(self, owner_type: str, owner_id: int, text: str) -> None:
        vector = self.embeddings.embed(text)
        model = self.embeddings.model_name
        payload = json.dumps(vector)
        self._conn.execute(
            """
            INSERT INTO memory_embeddings (owner_type, owner_id, model, dim, vector)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_type, owner_id, model) DO UPDATE SET
                dim = excluded.dim,
                vector = excluded.vector,
                created_at = datetime('now')
            """,
            (owner_type, owner_id, model, len(vector), payload),
        )
        self._conn.commit()

    def delete(self, owner_type: str, owner_id: int) -> None:
        self._conn.execute(
            "DELETE FROM memory_embeddings WHERE owner_type = ? AND owner_id = ?",
            (owner_type, owner_id),
        )
        self._conn.commit()

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        owner_type: str | None = None,
        min_score: float = 0.15,
    ) -> list[tuple[str, int, float]]:
        """Return (owner_type, owner_id, score) ranked by cosine similarity."""
        query_vec = self.embeddings.embed(query)
        model = self.embeddings.model_name
        if owner_type:
            cur = self._conn.execute(
                """
                SELECT owner_type, owner_id, vector
                FROM memory_embeddings
                WHERE model = ? AND owner_type = ?
                """,
                (model, owner_type),
            )
        else:
            cur = self._conn.execute(
                """
                SELECT owner_type, owner_id, vector
                FROM memory_embeddings
                WHERE model = ?
                """,
                (model,),
            )
        scored: list[tuple[str, int, float]] = []
        for row in cur.fetchall():
            try:
                vec = json.loads(row["vector"])
            except json.JSONDecodeError:
                continue
            if not isinstance(vec, list):
                continue
            score = cosine_similarity(query_vec, [float(x) for x in vec])
            if score >= min_score:
                scored.append((row["owner_type"], int(row["owner_id"]), float(score)))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored[:top_k]

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()
