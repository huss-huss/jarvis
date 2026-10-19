"""Episodic event log — notable moments across sessions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from jarvis.memory.database import connect, init_db


@dataclass
class Episode:
    id: int
    summary: str
    details: str | None
    kind: str
    created_at: str


class EpisodicStore:
    def __init__(self, db_path: str, conn: sqlite3.Connection | None = None) -> None:
        self.db_path = db_path
        self._owns_conn = conn is None
        self._conn = conn or connect(db_path)
        if self._owns_conn:
            init_db(self._conn)

    def add(
        self,
        summary: str,
        *,
        details: str | None = None,
        kind: str = "event",
    ) -> Episode:
        cleaned = summary.strip()
        if not cleaned:
            raise ValueError("Episode summary cannot be empty")
        cur = self._conn.execute(
            """
            INSERT INTO episodic_events (summary, details, kind)
            VALUES (?, ?, ?)
            """,
            (cleaned, details, kind),
        )
        self._conn.commit()
        episode = self.get(int(cur.lastrowid))
        assert episode is not None
        return episode

    def get(self, episode_id: int) -> Episode | None:
        cur = self._conn.execute(
            """
            SELECT id, summary, details, kind, created_at
            FROM episodic_events
            WHERE id = ?
            """,
            (episode_id,),
        )
        row = cur.fetchone()
        return _row_to_episode(row) if row else None

    def recent(self, *, limit: int = 20) -> list[Episode]:
        cur = self._conn.execute(
            """
            SELECT id, summary, details, kind, created_at
            FROM episodic_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_row_to_episode(row) for row in cur.fetchall()]

    def close(self) -> None:
        if self._owns_conn:
            self._conn.close()


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=int(row["id"]),
        summary=row["summary"],
        details=row["details"],
        kind=row["kind"],
        created_at=row["created_at"],
    )
