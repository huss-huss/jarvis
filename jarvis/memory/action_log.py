"""Action log for tool executions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from jarvis.memory.database import connect, init_db


class ActionLog:
    def __init__(self, db_path: str) -> None:
        self._conn = connect(db_path)
        init_db(self._conn)

    def record(
        self,
        *,
        tool: str,
        parameters: dict[str, Any] | None,
        result: str,
        status: str,
        confirmation: str | None = None,
        user_request: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO action_log (user_request, tool, parameters, result, status, confirmation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_request,
                tool,
                json.dumps(parameters or {}),
                result[:4000],
                status,
                confirmation,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
