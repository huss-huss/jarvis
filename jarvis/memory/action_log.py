"""Action log for tool executions."""

from __future__ import annotations

import json
import threading
from typing import Any

from jarvis.memory.database import connect, init_db


class ActionLog:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.RLock()
        self._conn = connect(db_path, check_same_thread=False)
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
        with self._lock:
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
        with self._lock:
            self._conn.close()
