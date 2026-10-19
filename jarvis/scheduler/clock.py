"""Clock abstraction for schedulers and tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class Clock:
    def __init__(self, tz_name: str = "local") -> None:
        self.tz_name = tz_name

    @property
    def tz(self) -> ZoneInfo | timezone:
        if self.tz_name in {"local", "system", ""}:
            return datetime.now().astimezone().tzinfo or timezone.utc
        return ZoneInfo(self.tz_name)

    def now(self) -> datetime:
        return datetime.now(tz=self.tz)

    def ensure_aware(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=self.tz)
        return dt.astimezone(self.tz)


class FakeClock(Clock):
    """Deterministic clock for tests."""

    def __init__(self, start: datetime | None = None, tz_name: str = "UTC") -> None:
        super().__init__(tz_name=tz_name)
        base = start or datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo("UTC"))
        if base.tzinfo is None:
            base = base.replace(tzinfo=ZoneInfo("UTC"))
        self._now = base

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now

    def set(self, when: datetime) -> None:
        self._now = self.ensure_aware(when)
