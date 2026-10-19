"""Reminder scheduler service — poll due items and notify."""

from __future__ import annotations

import threading
from datetime import datetime

from jarvis.logging import get_logger
from jarvis.scheduler.clock import Clock
from jarvis.scheduler.notifications import NotificationProvider
from jarvis.scheduler.store import ProductivityStore, Reminder
from jarvis.scheduler.when import format_when, parse_when

log = get_logger(__name__)


class ReminderService:
    """
    Creates/cancels reminders in SQLite and fires due ones via notifications.
    A background poller keeps timing reliable without depending on process uptime tricks.
    """

    def __init__(
        self,
        store: ProductivityStore,
        notifier: NotificationProvider,
        clock: Clock,
        *,
        poll_seconds: float = 2.0,
    ) -> None:
        self.store = store
        self.notifier = notifier
        self.clock = clock
        self.poll_seconds = max(0.5, poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-reminders", daemon=True)
        self._thread.start()
        log.info("reminder_scheduler_started", poll_seconds=self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def create(self, message: str, when_text: str) -> Reminder:
        when = parse_when(when_text, self.clock)
        if when <= self.clock.now():
            # still allow immediate-ish ("in 0 minutes") by bumping 1s
            when = self.clock.now().replace(microsecond=0)
        reminder = self.store.create_reminder(message, when)
        log.info("reminder_created", id=reminder.id, scheduled_at=reminder.scheduled_at)
        return reminder

    def list(self, *, status: str | None = "pending") -> list[Reminder]:
        return self.store.list_reminders(status=status)

    def cancel(self, reminder_id: int) -> Reminder | None:
        return self.store.cancel_reminder(reminder_id, self.clock.now())

    def tick(self) -> list[Reminder]:
        """Fire all due reminders (used by poller and tests)."""
        fired: list[Reminder] = []
        with self._lock:
            due = self.store.due_reminders(self.clock.now())
            for rem in due:
                marked = self.store.mark_fired(rem.id, self.clock.now())
                if marked is None or marked.status != "fired":
                    continue
                title = "Jarvis reminder"
                body = rem.message
                try:
                    self.notifier.notify(title, body)
                except Exception as exc:  # noqa: BLE001
                    log.warning("reminder_notify_failed", id=rem.id, error=str(exc))
                fired.append(marked)
                log.info("reminder_fired", id=rem.id)
        return fired

    def describe(self, reminder: Reminder) -> str:
        try:
            dt = datetime.fromisoformat(reminder.scheduled_at)
            when = format_when(dt, self.clock)
        except ValueError:
            when = reminder.scheduled_at
        return f"#{reminder.id} [{reminder.status}] {when} — {reminder.message}"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("reminder_tick_error", error=str(exc))
            self._stop.wait(self.poll_seconds)
