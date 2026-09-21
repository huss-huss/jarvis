"""Conversation persistence."""

from __future__ import annotations

import sqlite3

from jarvis.llm.base import ChatMessage, Role
from jarvis.memory.database import connect, init_db


class ConversationStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = connect(db_path)
        init_db(self._conn)
        self.conversation_id = self._ensure_conversation()

    def _ensure_conversation(self) -> int:
        cur = self._conn.execute("SELECT id FROM conversations ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur = self._conn.execute("INSERT INTO conversations DEFAULT VALUES")
        self._conn.commit()
        return int(cur.lastrowid)

    def new_conversation(self) -> int:
        cur = self._conn.execute("INSERT INTO conversations DEFAULT VALUES")
        self._conn.commit()
        self.conversation_id = int(cur.lastrowid)
        return self.conversation_id

    def add_message(
        self,
        role: Role | str,
        content: str | None,
        tool_name: str | None = None,
    ) -> None:
        role_value = role.value if isinstance(role, Role) else role
        self._conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, tool_name)
            VALUES (?, ?, ?, ?)
            """,
            (self.conversation_id, role_value, content, tool_name),
        )
        self._conn.commit()

    def recent_messages(self, limit: int = 40) -> list[ChatMessage]:
        cur = self._conn.execute(
            """
            SELECT role, content, tool_name
            FROM messages
            WHERE conversation_id = ?
              AND role IN ('system', 'user', 'assistant')
              AND content IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (self.conversation_id, limit),
        )
        rows = list(reversed(cur.fetchall()))
        messages: list[ChatMessage] = []
        for row in rows:
            try:
                role = Role(row["role"])
            except ValueError:
                continue
            messages.append(ChatMessage(role=role, content=row["content"] or ""))
        return messages

    def close(self) -> None:
        self._conn.close()
