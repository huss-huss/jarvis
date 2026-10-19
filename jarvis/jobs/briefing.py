"""Morning / on-demand briefing composer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jarvis.jobs.monitors import ProjectHealth, ProjectMonitor
from jarvis.productivity.calendar import CalendarService
from jarvis.productivity.tasks import TaskService
from jarvis.scheduler.clock import Clock
from jarvis.scheduler.service import ReminderService
from jarvis.scheduler.when import format_when


@dataclass
class Briefing:
    title: str
    body: str
    lines: list[str]


class BriefingService:
    def __init__(
        self,
        *,
        clock: Clock,
        tasks: TaskService,
        calendar: CalendarService,
        reminders: ReminderService,
        project_path: Path | None = None,
    ) -> None:
        self.clock = clock
        self.tasks = tasks
        self.calendar = calendar
        self.reminders = reminders
        self.project_path = project_path

    def compose(self, *, include_project: bool = True) -> Briefing:
        now = self.clock.now()
        greeting = _greeting(now.hour)
        lines: list[str] = [f"{greeting} Here's your Jarvis briefing."]

        overdue = self.tasks.overdue()
        due_today = [t for t in self.tasks.due_today() if t not in overdue]
        open_tasks = self.tasks.list_open()

        if overdue:
            lines.append(f"Overdue tasks ({len(overdue)}):")
            for t in overdue[:5]:
                lines.append(f"  • #{t.id} {t.title}" + (f" (due {t.due_at})" if t.due_at else ""))
        if due_today:
            lines.append(f"Due today ({len(due_today)}):")
            for t in due_today[:5]:
                lines.append(f"  • #{t.id} {t.title}")
        if not overdue and not due_today:
            open_n = len(open_tasks)
            lines.append(f"Tasks: {open_n} open, none due today.")

        upcoming = self.reminders.list(status="pending")[:5]
        if upcoming:
            lines.append(f"Upcoming reminders ({len(upcoming)} shown):")
            for r in upcoming:
                lines.append(f"  • {self.reminders.describe(r)}")
        else:
            lines.append("Reminders: none pending.")

        events = self.calendar.today()
        if events:
            lines.append(f"Calendar today ({len(events)}):")
            for e in events[:5]:
                lines.append(f"  • {e.title} @ {e.starts_at}")
        else:
            lines.append("Calendar: no local events today.")

        health: ProjectHealth | None = None
        if include_project and self.project_path is not None:
            health = ProjectMonitor(self.project_path).check()
            lines.append(f"Project: {health.summary}")
            for d in health.details[:5]:
                lines.append(f"  • {d}")

        lines.append(f"Generated {format_when(now, self.clock)}.")
        body = "\n".join(lines)
        return Briefing(title="Jarvis morning briefing", body=body, lines=lines)


def _greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning."
    if hour < 18:
        return "Good afternoon."
    return "Good evening."
