"""Productivity tools — reminders, tasks, calendar, briefings, jobs."""

from __future__ import annotations

from typing import Any

from jarvis.jobs.briefing import BriefingService
from jarvis.jobs.runner import JobRunner
from jarvis.mcp import mcp_status
from jarvis.productivity.calendar import CalendarService
from jarvis.productivity.tasks import TaskService
from jarvis.scheduler.service import ReminderService
from jarvis.scheduler.when import WhenParseError
from jarvis.tools.base import PermissionLevel, Tool, ToolResult


class CreateReminderTool(Tool):
    name = "create_reminder"
    description = (
        "Schedule a local reminder with macOS notification. "
        "when examples: 'in 10 minutes', 'at 6pm', 'tomorrow at 9:00', ISO datetime."
    )
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "when": {"type": "string"},
        },
        "required": ["message", "when"],
    }

    def __init__(self, reminders: ReminderService) -> None:
        self.reminders = reminders

    def execute(self, **kwargs: Any) -> ToolResult:
        message = str(kwargs.get("message") or "").strip()
        when = str(kwargs.get("when") or "").strip()
        if not message or not when:
            return ToolResult(success=False, output="", error="message and when are required")
        try:
            rem = self.reminders.create(message, when)
        except (WhenParseError, ValueError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=f"Reminder set: {self.reminders.describe(rem)}")


class ListRemindersTool(Tool):
    name = "list_reminders"
    description = "List pending reminders (or all if status=all)."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "pending|fired|cancelled|all"},
        },
    }

    def __init__(self, reminders: ReminderService) -> None:
        self.reminders = reminders

    def execute(self, **kwargs: Any) -> ToolResult:
        status = str(kwargs.get("status") or "pending").lower()
        if status == "all":
            items = self.reminders.list(status=None)
        else:
            items = self.reminders.list(status=status)
        if not items:
            return ToolResult(success=True, output="No reminders found.")
        lines = [self.reminders.describe(r) for r in items]
        return ToolResult(success=True, output="Reminders:\n" + "\n".join(lines))


class CancelReminderTool(Tool):
    name = "cancel_reminder"
    description = "Cancel a pending reminder by id."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {"reminder_id": {"type": "integer"}},
        "required": ["reminder_id"],
    }

    def __init__(self, reminders: ReminderService) -> None:
        self.reminders = reminders

    def execute(self, **kwargs: Any) -> ToolResult:
        rid = int(kwargs.get("reminder_id"))
        rem = self.reminders.cancel(rid)
        if rem is None or rem.status != "cancelled":
            return ToolResult(success=False, output="", error=f"Could not cancel reminder #{rid}")
        return ToolResult(success=True, output=f"Cancelled reminder #{rid}.")


class CreateTaskTool(Tool):
    name = "create_task"
    description = "Create a to-do task. Optional due: 'tomorrow at 5pm' / ISO."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "notes": {"type": "string"},
            "due": {"type": "string"},
            "priority": {"type": "integer"},
        },
        "required": ["title"],
    }

    def __init__(self, tasks: TaskService) -> None:
        self.tasks = tasks

    def execute(self, **kwargs: Any) -> ToolResult:
        title = str(kwargs.get("title") or "").strip()
        if not title:
            return ToolResult(success=False, output="", error="title is required")
        try:
            task = self.tasks.create(
                title,
                notes=str(kwargs["notes"]) if kwargs.get("notes") else None,
                due=str(kwargs["due"]) if kwargs.get("due") else None,
                priority=int(kwargs.get("priority") or 0),
            )
        except (WhenParseError, ValueError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        due_bit = f", due {task.due_at}" if task.due_at else ""
        return ToolResult(success=True, output=f"Task #{task.id} created: {task.title}{due_bit}")


class ListTasksTool(Tool):
    name = "list_tasks"
    description = "List open tasks."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, tasks: TaskService) -> None:
        self.tasks = tasks

    def execute(self, **kwargs: Any) -> ToolResult:
        items = self.tasks.list_open()
        if not items:
            return ToolResult(success=True, output="No open tasks.")
        lines = []
        for t in items:
            due = f" (due {t.due_at})" if t.due_at else ""
            lines.append(f"- #{t.id} {t.title}{due}")
        return ToolResult(success=True, output="Open tasks:\n" + "\n".join(lines))


class CompleteTaskTool(Tool):
    name = "complete_task"
    description = "Mark a task as done."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    }

    def __init__(self, tasks: TaskService) -> None:
        self.tasks = tasks

    def execute(self, **kwargs: Any) -> ToolResult:
        tid = int(kwargs.get("task_id"))
        task = self.tasks.complete(tid)
        if task is None or task.status != "done":
            return ToolResult(success=False, output="", error=f"Could not complete task #{tid}")
        return ToolResult(success=True, output=f"Completed task #{tid}: {task.title}")


class AddCalendarEventTool(Tool):
    name = "add_calendar_event"
    description = "Add a local calendar event (local store; not iCloud sync yet)."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "starts": {"type": "string"},
            "ends": {"type": "string"},
            "location": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["title", "starts"],
    }

    def __init__(self, calendar: CalendarService) -> None:
        self.calendar = calendar

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            event = self.calendar.add(
                str(kwargs.get("title") or ""),
                str(kwargs.get("starts") or ""),
                ends=str(kwargs["ends"]) if kwargs.get("ends") else None,
                location=str(kwargs["location"]) if kwargs.get("location") else None,
                notes=str(kwargs["notes"]) if kwargs.get("notes") else None,
            )
        except (WhenParseError, ValueError) as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(
            success=True,
            output=f"Event #{event.id}: {event.title} at {event.starts_at}",
        )


class ListCalendarTool(Tool):
    name = "list_calendar"
    description = "List local calendar events for today."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, calendar: CalendarService) -> None:
        self.calendar = calendar

    def execute(self, **kwargs: Any) -> ToolResult:
        events = self.calendar.today()
        if not events:
            return ToolResult(success=True, output="No local calendar events today.")
        lines = [f"- #{e.id} {e.title} @ {e.starts_at}" for e in events]
        return ToolResult(success=True, output="Today's events:\n" + "\n".join(lines))


class GetBriefingTool(Tool):
    name = "get_briefing"
    description = "Compose a morning-style briefing now (tasks, reminders, calendar, project)."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, briefing: BriefingService) -> None:
        self.briefing = briefing

    def execute(self, **kwargs: Any) -> ToolResult:
        brief = self.briefing.compose(include_project=True)
        return ToolResult(success=True, output=brief.body)


class ListJobsTool(Tool):
    name = "list_jobs"
    description = "List proactive background jobs and whether they are enabled."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, runner: JobRunner) -> None:
        self.runner = runner

    def execute(self, **kwargs: Any) -> ToolResult:
        jobs = self.runner.list_jobs()
        if not jobs:
            return ToolResult(success=True, output="No jobs registered.")
        lines = []
        for j in jobs:
            state = "on" if j["enabled"] else "off"
            lines.append(f"- {j['name']} [{state}] every {int(j['interval_seconds'])}s — {j['description']}")
        return ToolResult(success=True, output="Jobs:\n" + "\n".join(lines))


class RunJobTool(Tool):
    name = "run_job"
    description = "Run a proactive job now (morning_briefing or project_monitor)."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    def __init__(self, runner: JobRunner) -> None:
        self.runner = runner

    def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        try:
            summary = self.runner.run_job(name, force=True)
        except KeyError as exc:
            return ToolResult(success=False, output="", error=str(exc))
        return ToolResult(success=True, output=summary)


class SetJobEnabledTool(Tool):
    name = "set_job_enabled"
    description = "Enable or disable a background job."
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
        "required": ["name", "enabled"],
    }

    def __init__(self, runner: JobRunner) -> None:
        self.runner = runner

    def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        enabled = bool(kwargs.get("enabled"))
        ok = self.runner.set_enabled(name, enabled)
        if not ok:
            return ToolResult(success=False, output="", error=f"Unknown job: {name}")
        return ToolResult(success=True, output=f"Job '{name}' enabled={enabled}")


class McpStatusTool(Tool):
    name = "mcp_status"
    description = "Report MCP integration status (disabled by default)."
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output=mcp_status(enabled=self.enabled))


def build_productivity_tools(
    *,
    reminders: ReminderService,
    tasks: TaskService,
    calendar: CalendarService,
    briefing: BriefingService,
    runner: JobRunner,
    mcp_enabled: bool = False,
) -> list[Tool]:
    return [
        CreateReminderTool(reminders),
        ListRemindersTool(reminders),
        CancelReminderTool(reminders),
        CreateTaskTool(tasks),
        ListTasksTool(tasks),
        CompleteTaskTool(tasks),
        AddCalendarEventTool(calendar),
        ListCalendarTool(calendar),
        GetBriefingTool(briefing),
        ListJobsTool(runner),
        RunJobTool(runner),
        SetJobEnabledTool(runner),
        McpStatusTool(enabled=mcp_enabled),
    ]
