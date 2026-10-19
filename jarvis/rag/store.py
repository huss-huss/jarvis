"""RAG document / chunk store in SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from jarvis.memory.database import connect, init_db
from jarvis.rag.embeddings import EmbeddingProvider, cosine_similarity


@dataclass
class RagDocument:
    id: int
    path: str
    title: str | None
    project: str
    content_hash: str
    byte_size: int
    chunk_count: int
    updated_at: str


@dataclass
class RagHit:
    chunk_id: int
    document_id: int
    path: str
    project: str
    title: str | None
    text: str
    score: float
    chunk_index: int


class RagStore:
    def __init__(self, db_path: str, embeddings: EmbeddingProvider) -> None:
        self.db_path = db_path
        self.embeddings = embeddings
        self._conn = connect(db_path)
        init_db(self._conn)

    def get_setting(self, key: str, default: str = "") -> str:
        cur = self._conn.execute("SELECT value FROM rag_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO rag_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def active_project(self) -> str:
        return self.get_setting("active_project", "default") or "default"

    def set_active_project(self, project: str) -> str:
        name = _normalize_project(project)
        self.set_setting("active_project", name)
        return name

    def list_projects(self) -> list[tuple[str, int]]:
        cur = self._conn.execute(
            """
            SELECT project, COUNT(*) AS n
            FROM rag_documents
            GROUP BY project
            ORDER BY project
            """
        )
        return [(str(r["project"]), int(r["n"])) for r in cur.fetchall()]

    def list_documents(self, *, project: str | None = None, limit: int = 50) -> list[RagDocument]:
        if project:
            cur = self._conn.execute(
                """
                SELECT id, path, title, project, content_hash, byte_size, chunk_count, updated_at
                FROM rag_documents
                WHERE project = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (_normalize_project(project), limit),
            )
        else:
            cur = self._conn.execute(
                """
                SELECT id, path, title, project, content_hash, byte_size, chunk_count, updated_at
                FROM rag_documents
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [_row_doc(r) for r in cur.fetchall()]

    def get_by_path(self, path: str, project: str) -> RagDocument | None:
        cur = self._conn.execute(
            """
            SELECT id, path, title, project, content_hash, byte_size, chunk_count, updated_at
            FROM rag_documents
            WHERE path = ? AND project = ?
            """,
            (path, _normalize_project(project)),
        )
        row = cur.fetchone()
        return _row_doc(row) if row else None

    def delete_document(self, document_id: int) -> None:
        cur = self._conn.execute("SELECT id FROM rag_chunks WHERE document_id = ?", (document_id,))
        chunk_ids = [int(r["id"]) for r in cur.fetchall()]
        for cid in chunk_ids:
            self._conn.execute(
                "DELETE FROM memory_embeddings WHERE owner_type = ? AND owner_id = ?",
                ("rag_chunk", cid),
            )
        self._conn.execute("DELETE FROM rag_chunks WHERE document_id = ?", (document_id,))
        self._conn.execute("DELETE FROM rag_documents WHERE id = ?", (document_id,))
        self._conn.commit()

    def upsert_document(
        self,
        *,
        path: str,
        title: str,
        project: str,
        text: str,
        chunks: list[tuple[str, int, int]],
    ) -> RagDocument:
        """chunks: list of (text, start_char, end_char)."""
        project = _normalize_project(project)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.get_by_path(path, project)
        if existing and existing.content_hash == content_hash:
            return existing
        if existing:
            self.delete_document(existing.id)

        cur = self._conn.execute(
            """
            INSERT INTO rag_documents (path, title, project, content_hash, byte_size, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (path, title, project, content_hash, len(text.encode("utf-8")), len(chunks)),
        )
        doc_id = int(cur.lastrowid)
        model = self.embeddings.model_name
        vectors = self.embeddings.embed_many([c[0] for c in chunks]) if chunks else []

        for idx, ((chunk_text, start, end), vector) in enumerate(zip(chunks, vectors, strict=True)):
            ccur = self._conn.execute(
                """
                INSERT INTO rag_chunks (document_id, chunk_index, text, start_char, end_char)
                VALUES (?, ?, ?, ?, ?)
                """,
                (doc_id, idx, chunk_text, start, end),
            )
            chunk_id = int(ccur.lastrowid)
            self._conn.execute(
                """
                INSERT INTO memory_embeddings (owner_type, owner_id, model, dim, vector)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_type, owner_id, model) DO UPDATE SET
                    dim = excluded.dim,
                    vector = excluded.vector,
                    created_at = datetime('now')
                """,
                ("rag_chunk", chunk_id, model, len(vector), json.dumps(vector)),
            )
        self._conn.commit()
        doc = self.get_by_path(path, project)
        assert doc is not None
        return doc

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        project: str | None = None,
        min_score: float = 0.12,
    ) -> list[RagHit]:
        query_vec = self.embeddings.embed(query)
        model = self.embeddings.model_name
        project_norm = _normalize_project(project) if project else None

        if project_norm:
            cur = self._conn.execute(
                """
                SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.text,
                       d.path, d.project, d.title, e.vector
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                JOIN memory_embeddings e
                  ON e.owner_type = 'rag_chunk' AND e.owner_id = c.id AND e.model = ?
                WHERE d.project = ?
                """,
                (model, project_norm),
            )
        else:
            cur = self._conn.execute(
                """
                SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.text,
                       d.path, d.project, d.title, e.vector
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                JOIN memory_embeddings e
                  ON e.owner_type = 'rag_chunk' AND e.owner_id = c.id AND e.model = ?
                """,
                (model,),
            )

        scored: list[RagHit] = []
        q_lower = query.lower()
        q_tokens = [t for t in q_lower.replace("?", " ").split() if len(t) > 2]
        for row in cur.fetchall():
            try:
                vec = [float(x) for x in json.loads(row["vector"])]
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            score = cosine_similarity(query_vec, vec)
            text = row["text"] or ""
            # Light keyword bonus for exact phrase / tokens
            if q_lower.strip("? ") and q_lower.strip("? ") in text.lower():
                score += 0.15
            elif q_tokens:
                hits = sum(1 for t in q_tokens if t in text.lower())
                score += 0.03 * hits
            if score >= min_score:
                scored.append(
                    RagHit(
                        chunk_id=int(row["chunk_id"]),
                        document_id=int(row["document_id"]),
                        path=row["path"],
                        project=row["project"],
                        title=row["title"],
                        text=text,
                        score=float(score),
                        chunk_index=int(row["chunk_index"]),
                    )
                )
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]

    def close(self) -> None:
        self._conn.close()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_project(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (name or "").strip().lower())
    cleaned = cleaned.strip("_") or "default"
    return cleaned[:64]


def _row_doc(row: sqlite3.Row) -> RagDocument:
    return RagDocument(
        id=int(row["id"]),
        path=row["path"],
        title=row["title"],
        project=row["project"],
        content_hash=row["content_hash"],
        byte_size=int(row["byte_size"]),
        chunk_count=int(row["chunk_count"]),
        updated_at=row["updated_at"],
    )
