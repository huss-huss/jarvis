"""Reminder / task / calendar persistence."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from jarvis.memory.database import connect, init_db


@dataclass
class Reminder:
    id: int
    message: str
    scheduled_at: str
    status: str
    created_at: str
    fired_at: str | None = None


@dataclass
class Task:
    id: int
    title: str
    notes: str | None
    status: str
    due_at: str | None
    priority: int
    created_at: str
    completed_at: str | None = None


@dataclass
class CalendarEvent:
    id: int
    title: str
    starts_at: str
    ends_at: str | None
    location: str | None
    notes: str | None
    created_at: str


class ProductivityStore:
    """Thread-safe SQLite store (main thread + reminder/job pollers)."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        # Shared across threads; guarded by _lock
        self._conn = connect(db_path, check_same_thread=False)
        init_db(self._conn)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    # --- reminders ---
    def create_reminder(self, message: str, scheduled_at: datetime) -> Reminder:
        cleaned = message.strip()
        if not cleaned:
            raise ValueError("Reminder message cannot be empty")
        when = scheduled_at.isoformat()
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO reminders (message, scheduled_at, status)
                VALUES (?, ?, 'pending')
                """,
                (cleaned, when),
            )
            conn.commit()
            rem_id = int(cur.lastrowid)
        rem = self.get_reminder(rem_id)
        assert rem is not None
        return rem

    def get_reminder(self, reminder_id: int) -> Reminder | None:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, message, scheduled_at, status, created_at, fired_at
                FROM reminders WHERE id = ?
                """,
                (reminder_id,),
            )
            row = cur.fetchone()
        return _row_reminder(row) if row else None

    def list_reminders(self, *, status: str | None = "pending", limit: int = 50) -> list[Reminder]:
        with self._db() as conn:
            if status:
                cur = conn.execute(
                    """
                    SELECT id, message, scheduled_at, status, created_at, fired_at
                    FROM reminders WHERE status = ?
                    ORDER BY scheduled_at ASC LIMIT ?
                    """,
                    (status, limit),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, message, scheduled_at, status, created_at, fired_at
                    FROM reminders ORDER BY scheduled_at DESC LIMIT ?
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
        return [_row_reminder(r) for r in rows]

    def due_reminders(self, now: datetime) -> list[Reminder]:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, message, scheduled_at, status, created_at, fired_at
                FROM reminders
                WHERE status = 'pending' AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
                """,
                (now.isoformat(),),
            )
            rows = cur.fetchall()
        return [_row_reminder(r) for r in rows]

    def mark_fired(self, reminder_id: int, fired_at: datetime) -> Reminder | None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = 'fired', fired_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (fired_at.isoformat(), reminder_id),
            )
            conn.commit()
        return self.get_reminder(reminder_id)

    def cancel_reminder(self, reminder_id: int, when: datetime) -> Reminder | None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = 'cancelled', cancelled_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (when.isoformat(), reminder_id),
            )
            conn.commit()
        return self.get_reminder(reminder_id)

    # --- tasks ---
    def create_task(
        self,
        title: str,
        *,
        notes: str | None = None,
        due_at: datetime | None = None,
        priority: int = 0,
    ) -> Task:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Task title cannot be empty")
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, notes, due_at, priority, status)
                VALUES (?, ?, ?, ?, 'open')
                """,
                (cleaned, notes, due_at.isoformat() if due_at else None, int(priority)),
            )
            conn.commit()
            task_id = int(cur.lastrowid)
        task = self.get_task(task_id)
        assert task is not None
        return task

    def get_task(self, task_id: int) -> Task | None:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, title, notes, status, due_at, priority, created_at, completed_at
                FROM tasks WHERE id = ?
                """,
                (task_id,),
            )
            row = cur.fetchone()
        return _row_task(row) if row else None

    def list_tasks(self, *, status: str | None = "open", limit: int = 50) -> list[Task]:
        with self._db() as conn:
            if status:
                cur = conn.execute(
                    """
                    SELECT id, title, notes, status, due_at, priority, created_at, completed_at
                    FROM tasks WHERE status = ?
                    ORDER BY priority DESC, due_at IS NULL, due_at ASC, id ASC
                    LIMIT ?
                    """,
                    (status, limit),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, title, notes, status, due_at, priority, created_at, completed_at
                    FROM tasks ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
        return [_row_task(r) for r in rows]

    def tasks_due_on_or_before(self, day_end: datetime) -> list[Task]:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, title, notes, status, due_at, priority, created_at, completed_at
                FROM tasks
                WHERE status = 'open' AND due_at IS NOT NULL AND due_at <= ?
                ORDER BY due_at ASC
                """,
                (day_end.isoformat(),),
            )
            rows = cur.fetchall()
        return [_row_task(r) for r in rows]

    def complete_task(self, task_id: int, when: datetime) -> Task | None:
        with self._db() as conn:
            conn.execute(
                """
                UPDATE tasks SET status = 'done', completed_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (when.isoformat(), task_id),
            )
            conn.commit()
        return self.get_task(task_id)

    # --- calendar (architecture / local events) ---
    def create_event(
        self,
        title: str,
        starts_at: datetime,
        *,
        ends_at: datetime | None = None,
        location: str | None = None,
        notes: str | None = None,
    ) -> CalendarEvent:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("Event title cannot be empty")
        with self._db() as conn:
            cur = conn.execute(
                """
                INSERT INTO calendar_events (title, starts_at, ends_at, location, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cleaned,
                    starts_at.isoformat(),
                    ends_at.isoformat() if ends_at else None,
                    location,
                    notes,
                ),
            )
            conn.commit()
            event_id = int(cur.lastrowid)
        event = self.get_event(event_id)
        assert event is not None
        return event

    def get_event(self, event_id: int) -> CalendarEvent | None:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, title, starts_at, ends_at, location, notes, created_at
                FROM calendar_events WHERE id = ? AND cancelled_at IS NULL
                """,
                (event_id,),
            )
            row = cur.fetchone()
        return _row_event(row) if row else None

    def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        with self._db() as conn:
            cur = conn.execute(
                """
                SELECT id, title, starts_at, ends_at, location, notes, created_at
                FROM calendar_events
                WHERE cancelled_at IS NULL
                  AND starts_at >= ? AND starts_at <= ?
                ORDER BY starts_at ASC
                """,
                (start.isoformat(), end.isoformat()),
            )
            rows = cur.fetchall()
        return [_row_event(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _row_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=int(row["id"]),
        message=row["message"],
        scheduled_at=row["scheduled_at"],
        status=row["status"],
        created_at=row["created_at"],
        fired_at=row["fired_at"],
    )


def _row_task(row: sqlite3.Row) -> Task:
    return Task(
        id=int(row["id"]),
        title=row["title"],
        notes=row["notes"],
        status=row["status"],
        due_at=row["due_at"],
        priority=int(row["priority"]),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def _row_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=int(row["id"]),
        title=row["title"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        location=row["location"],
        notes=row["notes"],
        created_at=row["created_at"],
    )
