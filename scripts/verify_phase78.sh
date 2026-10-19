#!/usr/bin/env bash
# Phase 7–8: reminders fire + briefing composes
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

echo "== Phase 7–8 productivity / proactive verify =="
"$PY" - <<'PY'
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from jarvis.jobs.briefing import BriefingService
from jarvis.jobs.runner import JobRunner
from jarvis.productivity.calendar import CalendarService
from jarvis.productivity.tasks import TaskService
from jarvis.scheduler.clock import FakeClock
from jarvis.scheduler.notifications import RecordingNotifier
from jarvis.scheduler.service import ReminderService
from jarvis.scheduler.store import ProductivityStore

with TemporaryDirectory() as td:
    db = str(Path(td) / "p.db")
    clock = FakeClock(datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo("UTC")))
    notifier = RecordingNotifier()
    store = ProductivityStore(db)
    reminders = ReminderService(store, notifier, clock)
    tasks = TaskService(store, clock)
    calendar = CalendarService(store, clock)

    rem = reminders.create("Call John", "in 5 minutes")
    assert rem.status == "pending"
    clock.advance(minutes=6)
    fired = reminders.tick()
    assert fired and fired[0].message == "Call John"
    assert notifier.sent
    print("PASS: reminder scheduled → fired → notified")

    tasks.create("Ship Phase 8", due="today at 6pm")
    calendar.add("Demo", "today at 4pm")
    briefing = BriefingService(
        clock=clock,
        tasks=tasks,
        calendar=calendar,
        reminders=reminders,
        project_path=Path(td),
    )
    body = briefing.compose().body
    assert "Ship Phase 8" in body and "Demo" in body
    print("PASS: briefing includes tasks + calendar")

    runner = JobRunner(db, clock, notifier, briefing=briefing)
    runner.register_defaults(morning_hour=8, morning_minute=0)
    summary = runner.run_job("morning_briefing", force=True)
    assert "Ship Phase 8" in summary
    print("PASS: run_job morning_briefing")
    print("PASS: Phase 7–8 core")
PY
echo "== Phase 7–8 verify done =="
