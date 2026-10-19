"""Parse natural 'when' phrases into datetimes."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from jarvis.scheduler.clock import Clock

_IN_RE = re.compile(
    r"^\s*in\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\s*$",
    re.IGNORECASE,
)
_AT_RE = re.compile(
    r"^\s*(?:(today|tomorrow)\s+)?(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$",
    re.IGNORECASE,
)
_ISO_HINT = re.compile(r"^\d{4}-\d{2}-\d{2}")


class WhenParseError(ValueError):
    pass


def parse_when(text: str, clock: Clock) -> datetime:
    """
    Parse common reminder times:
    - ISO: 2026-09-21T18:00:00
    - relative: in 5 minutes / in 2 hours / in 1 day
    - clock: at 6pm / at 18:30 / tomorrow at 9:00
    """
    raw = (text or "").strip()
    if not raw:
        raise WhenParseError("Empty time expression")

    now = clock.now()

    if _ISO_HINT.match(raw):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WhenParseError(f"Invalid ISO datetime: {raw}") from exc
        return clock.ensure_aware(dt)

    m = _IN_RE.match(raw)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("s"):
            delta = timedelta(seconds=amount)
        elif unit.startswith("m"):
            delta = timedelta(minutes=amount)
        elif unit.startswith("h"):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return now + delta

    m = _AT_RE.match(raw)
    if m:
        day_word = (m.group(1) or "today").lower()
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        ampm = (m.group(4) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise WhenParseError(f"Invalid clock time: {raw}")
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_word == "tomorrow":
            target = target + timedelta(days=1)
        elif target <= now:
            # "at 6pm" already passed today → tomorrow
            target = target + timedelta(days=1)
        return target

    raise WhenParseError(
        f"Could not parse time '{raw}'. Try 'in 10 minutes', 'at 6pm', "
        f"'tomorrow at 9:00', or an ISO datetime."
    )


def format_when(dt: datetime, clock: Clock) -> str:
    local = clock.ensure_aware(dt)
    return local.strftime("%Y-%m-%d %H:%M %Z")
