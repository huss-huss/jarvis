"""Task management service."""

from __future__ import annotations

from jarvis.scheduler.clock import Clock
from jarvis.scheduler.store import ProductivityStore, Task
from jarvis.scheduler.when import parse_when


class TaskService:
    def __init__(self, store: ProductivityStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def create(
        self,
        title: str,
        *,
        notes: str | None = None,
        due: str | None = None,
        priority: int = 0,
    ) -> Task:
        due_at = parse_when(due, self.clock) if due else None
        return self.store.create_task(title, notes=notes, due_at=due_at, priority=priority)

    def list_open(self) -> list[Task]:
        return self.store.list_tasks(status="open")

    def complete(self, task_id: int) -> Task | None:
        return self.store.complete_task(task_id, self.clock.now())

    def due_today(self) -> list[Task]:
        now = self.clock.now()
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return self.store.tasks_due_on_or_before(end)

    def overdue(self) -> list[Task]:
        return self.store.tasks_due_on_or_before(self.clock.now())
