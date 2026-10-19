"""Long-term fact storage."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from jarvis.memory.database import connect, init_db

_KEY_RE = re.compile(r"[^a-z0-9_]+")


def normalize_fact_key(raw: str | None) -> str | None:
    if not raw:
        return None
    key = _KEY_RE.sub("_", raw.strip().lower()).strip("_")
    return key or None


@dataclass
class Fact:
    id: int
    key: str | None
    content: str
    category: str
    source: str
    created_at: str
    updated_at: str


class FactStore:
    def __init__(self, db_path: str, conn: sqlite3.Connection | None = None) -> None:
        self.db_path = db_path
        self._owns_conn = conn is None
        self._conn = conn or connect(db_path)
        if self._owns_conn:
            init_db(self._conn)

    def remember(
        self,
        content: str,
        *,
        key: str | None = None,
        category: str = "general",
        source: str = "user",
    ) -> Fact:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Fact content cannot be empty")
        norm_key = normalize_fact_key(key)

        if norm_key:
            existing = self.get_by_key(norm_key)
            if existing:
                self._conn.execute(
                    """
                    UPDATE long_term_facts
                    SET content = ?, category = ?, source = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (cleaned, category, source, existing.id),
                )
                self._conn.commit()
                updated = self.get(existing.id)
                assert updated is not None
                return updated

        cur = self._conn.execute(
            """
            INSERT INTO long_term_facts (key, content, category, source)
            VALUES (?, ?, ?, ?)
            """,
            (norm_key, cleaned, category, source),
        )
        self._conn.commit()
        fact = self.get(int(cur.lastrowid))
        assert fact is not None
        return fact

    def get(self, fact_id: int) -> Fact | None:
        cur = self._conn.execute(
            """
            SELECT id, key, content, category, source, created_at, updated_at
            FROM long_term_facts
            WHERE id = ? AND deleted_at IS NULL
            """,
            (fact_id,),
        )
        row = cur.fetchone()
        return _row_to_fact(row) if row else None

    def get_by_key(self, key: str) -> Fact | None:
        norm = normalize_fact_key(key)
        if not norm:
            return None
        cur = self._conn.execute(
            """
            SELECT id, key, content, category, source, created_at, updated_at
            FROM long_term_facts
            WHERE key = ? AND deleted_at IS NULL
            """,
            (norm,),
        )
        row = cur.fetchone()
        return _row_to_fact(row) if row else None

    def list_facts(self, *, limit: int = 50) -> list[Fact]:
        cur = self._conn.execute(
            """
            SELECT id, key, content, category, source, created_at, updated_at
            FROM long_term_facts
            WHERE deleted_at IS NULL
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_row_to_fact(row) for row in cur.fetchall()]

    def forget(self, *, fact_id: int | None = None, key: str | None = None) -> Fact | None:
        fact: Fact | None = None
        if fact_id is not None:
            fact = self.get(fact_id)
        elif key:
            fact = self.get_by_key(key)
        if fact is None:
            return None
        self._conn.execute(
            "UPDATE long_term_facts SET deleted_at = datetime('now') WHERE id = ?",
            (fact.id,),
        )
        self._conn.commit()
        return fact

    def keyword_search(self, query: str, *, limit: int = 8) -> list[Fact]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
        facts = self.list_facts(limit=200)
        if not tokens:
            return facts[:limit]
        scored: list[tuple[int, Fact]] = []
        for fact in facts:
            hay = f"{fact.key or ''} {fact.content}".lower()
            score = sum(1 for t in tokens if t in hay)
            if score:
                scored.append((score, fact))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [fact for _, fact in scored[:limit]]

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=int(row["id"]),
        key=row["key"],
        content=row["content"],
        category=row["category"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
