"""Phase 7–8 productivity + proactive tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.jobs.briefing import BriefingService
from jarvis.jobs.monitors import ProjectMonitor
from jarvis.jobs.runner import JobRunner
from jarvis.productivity.calendar import CalendarService
from jarvis.productivity.tasks import TaskService
from jarvis.scheduler.clock import FakeClock
from jarvis.scheduler.notifications import RecordingNotifier
from jarvis.scheduler.service import ReminderService
from jarvis.scheduler.store import ProductivityStore
from jarvis.scheduler.when import WhenParseError, parse_when
from jarvis.tools.productivity import build_productivity_tools
from jarvis.tools.registry import ToolRegistry


def test_parse_when_relative_and_clock():
    clock = FakeClock(datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo("UTC")))
    assert parse_when("in 5 minutes", clock).minute == 5
    later = parse_when("at 6pm", clock)
    assert later.hour == 18
    assert later.day == 21  # still today afternoon relative to noon
    clock.set(datetime(2026, 9, 21, 19, 0, tzinfo=ZoneInfo("UTC")))
    tomorrow = parse_when("at 6pm", clock)
    assert tomorrow.day == 22


def test_parse_when_rejects_garbage():
    clock = FakeClock()
    try:
        parse_when("next blue moon", clock)
        assert False, "expected error"
    except WhenParseError:
        pass


def test_reminder_fires_with_fake_clock(tmp_path: Path):
    clock = FakeClock(datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo("UTC")))
    notifier = RecordingNotifier()
    store = ProductivityStore(str(tmp_path / "p.db"))
    service = ReminderService(store, notifier, clock, poll_seconds=0.5)
    rem = service.create("Call John", "in 10 minutes")
    assert rem.status == "pending"
    assert service.tick() == []
    clock.advance(minutes=11)
    fired = service.tick()
    assert len(fired) == 1
    assert fired[0].status == "fired"
    assert notifier.sent
    assert "Call John" in notifier.sent[0][1]


def test_tasks_and_briefing(tmp_path: Path):
    clock = FakeClock(datetime(2026, 9, 21, 8, 0, tzinfo=ZoneInfo("UTC")))
    store = ProductivityStore(str(tmp_path / "p.db"))
    tasks = TaskService(store, clock)
    calendar = CalendarService(store, clock)
    reminders = ReminderService(store, RecordingNotifier(), clock)
    tasks.create("Ship Phase 7", due="today at 5pm", priority=1)
    calendar.add("Standup", "today at 9am")
    reminders.create("Stretch", "in 2 hours")
    briefing = BriefingService(
        clock=clock,
        tasks=tasks,
        calendar=calendar,
        reminders=reminders,
        project_path=tmp_path,
    )
    brief = briefing.compose(include_project=True)
    assert "Good morning" in brief.body
    assert "Ship Phase 7" in brief.body
    assert "Standup" in brief.body
    assert "Stretch" in brief.body


def test_project_monitor_non_git(tmp_path: Path):
    health = ProjectMonitor(tmp_path).check()
    assert health.ok is True
    assert "not a git repo" in health.summary


def test_job_runner_run_briefing(tmp_path: Path):
    clock = FakeClock(datetime(2026, 9, 21, 8, 5, tzinfo=ZoneInfo("UTC")))
    notifier = RecordingNotifier()
    store = ProductivityStore(str(tmp_path / "p.db"))
    reminders = ReminderService(store, notifier, clock)
    tasks = TaskService(store, clock)
    calendar = CalendarService(store, clock)
    tasks.create("Write tests", due="today at 6pm")
    briefing = BriefingService(
        clock=clock,
        tasks=tasks,
        calendar=calendar,
        reminders=reminders,
        project_path=tmp_path,
    )
    runner = JobRunner(str(tmp_path / "p.db"), clock, notifier, briefing=briefing)
    runner.register_defaults(morning_hour=8, morning_minute=0)
    summary = runner.run_job("morning_briefing", force=True)
    assert "Write tests" in summary
    assert notifier.sent


def test_productivity_tools_roundtrip(tmp_path: Path):
    clock = FakeClock(datetime(2026, 9, 21, 12, 0, tzinfo=ZoneInfo("UTC")))
    notifier = RecordingNotifier()
    store = ProductivityStore(str(tmp_path / "p.db"))
    reminders = ReminderService(store, notifier, clock)
    tasks = TaskService(store, clock)
    calendar = CalendarService(store, clock)
    briefing = BriefingService(
        clock=clock, tasks=tasks, calendar=calendar, reminders=reminders, project_path=tmp_path
    )
    runner = JobRunner(str(tmp_path / "p.db"), clock, notifier, briefing=briefing)
    runner.register_defaults()
    registry = ToolRegistry()
    for tool in build_productivity_tools(
        reminders=reminders,
        tasks=tasks,
        calendar=calendar,
        briefing=briefing,
        runner=runner,
        mcp_enabled=False,
    ):
        registry.register(tool)

    r = registry.execute("create_reminder", {"message": "Tea", "when": "in 15 minutes"})
    assert r.success, r.error
    r = registry.execute("create_task", {"title": "Review PR", "due": "tomorrow at 10am"})
    assert r.success, r.error
    r = registry.execute("list_tasks", {})
    assert "Review PR" in r.output
    r = registry.execute("get_briefing", {})
    assert r.success
    assert "Review PR" in r.output or "Tea" in r.output
    r = registry.execute("mcp_status", {})
    assert "disabled" in r.output.lower()
