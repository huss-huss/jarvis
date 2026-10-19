"""Local calendar event service (cloud sync optional later)."""

from __future__ import annotations

from datetime import timedelta

from jarvis.scheduler.clock import Clock
from jarvis.scheduler.store import CalendarEvent, ProductivityStore
from jarvis.scheduler.when import parse_when


class CalendarService:
    def __init__(self, store: ProductivityStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    def add(
        self,
        title: str,
        starts: str,
        *,
        ends: str | None = None,
        location: str | None = None,
        notes: str | None = None,
    ) -> CalendarEvent:
        starts_at = parse_when(starts, self.clock)
        ends_at = parse_when(ends, self.clock) if ends else None
        return self.store.create_event(
            title, starts_at, ends_at=ends_at, location=location, notes=notes
        )

    def today(self) -> list[CalendarEvent]:
        now = self.clock.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.store.events_between(start, end)

    def upcoming(self, *, hours: int = 24) -> list[CalendarEvent]:
        now = self.clock.now()
        return self.store.events_between(now, now + timedelta(hours=hours))
