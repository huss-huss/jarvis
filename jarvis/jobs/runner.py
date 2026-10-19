"""Background job runner for proactive JARVIS."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.jobs.briefing import BriefingService
from jarvis.logging import get_logger
from jarvis.memory.database import connect, init_db
from jarvis.scheduler.clock import Clock
from jarvis.scheduler.notifications import NotificationProvider

log = get_logger(__name__)

JobFunc = Callable[[], str]


@dataclass
class JobSpec:
    name: str
    description: str
    interval_seconds: float
    func: JobFunc
    enabled: bool = True


class JobRunner:
    """
    Lightweight local job loop (no cloud).
    Jobs are allowlisted in code; config can enable/disable and set intervals.
    """

    def __init__(
        self,
        db_path: str,
        clock: Clock,
        notifier: NotificationProvider,
        *,
        briefing: BriefingService | None = None,
        poll_seconds: float = 5.0,
    ) -> None:
        self.db_path = db_path
        self.clock = clock
        self.notifier = notifier
        self.briefing = briefing
        self.poll_seconds = max(1.0, poll_seconds)
        self._lock = threading.RLock()
        # Shared with background poller; guarded by _lock
        self._conn = connect(db_path, check_same_thread=False)
        init_db(self._conn)
        self._jobs: dict[str, JobSpec] = {}
        self._last_run: dict[str, datetime] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._conn

    def register(self, spec: JobSpec) -> None:
        enabled = self._load_enabled(spec.name, default=spec.enabled)
        self._jobs[spec.name] = JobSpec(
            name=spec.name,
            description=spec.description,
            interval_seconds=spec.interval_seconds,
            func=spec.func,
            enabled=enabled,
        )

    def register_defaults(
        self,
        *,
        morning_hour: int = 8,
        morning_minute: int = 0,
        project_interval_minutes: int = 60,
        morning_enabled: bool = True,
        project_enabled: bool = True,
    ) -> None:
        if self.briefing is not None:

            def morning_job() -> str:
                now = self.clock.now()
                last = self._last_run.get("morning_briefing")
                if last and last.date() == now.date():
                    return "Morning briefing already delivered today."
                due = (now.hour > morning_hour) or (
                    now.hour == morning_hour and now.minute >= morning_minute
                )
                if not due:
                    return "Waiting for morning window."
                brief = self.briefing.compose(include_project=True)
                self.notifier.notify(brief.title, _notify_trim(brief.body))
                return brief.body

            self.register(
                JobSpec(
                    name="morning_briefing",
                    description=f"Daily briefing around {morning_hour:02d}:{morning_minute:02d}",
                    interval_seconds=60.0,
                    func=morning_job,
                    enabled=morning_enabled,
                )
            )

            def project_job() -> str:
                assert self.briefing is not None
                brief = self.briefing.compose(include_project=True)
                health_line = next((ln for ln in brief.lines if ln.startswith("Project:")), "")
                lowered = health_line.lower()
                if any(word in lowered for word in ("dirty", "failed", "missing")):
                    self.notifier.notify("Jarvis project check", health_line or "Project issue detected")
                return health_line or "Project check complete."

            self.register(
                JobSpec(
                    name="project_monitor",
                    description="Periodic local git status for configured project",
                    interval_seconds=max(60.0, float(project_interval_minutes) * 60.0),
                    func=project_job,
                    enabled=project_enabled,
                )
            )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-jobs", daemon=True)
        self._thread.start()
        log.info("job_runner_started", jobs=list(self._jobs))

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def list_jobs(self) -> list[dict[str, Any]]:
        out = []
        for spec in self._jobs.values():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "enabled": spec.enabled,
                    "interval_seconds": spec.interval_seconds,
                    "last_run": self._last_run.get(spec.name).isoformat() if spec.name in self._last_run else None,
                }
            )
        return out

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self._jobs:
            return False
        self._jobs[name].enabled = enabled
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO job_settings (job_name, enabled, config_json)
                VALUES (?, ?, '{}')
                ON CONFLICT(job_name) DO UPDATE SET enabled = excluded.enabled
                """,
                (name, 1 if enabled else 0),
            )
            conn.commit()
        return True

    def run_job(self, name: str, *, force: bool = True) -> str:
        spec = self._jobs.get(name)
        if spec is None:
            raise KeyError(f"Unknown job: {name}")
        if not force and not spec.enabled:
            return f"Job '{name}' is disabled."
        return self._execute(spec)

    def tick(self) -> list[str]:
        """Run any due jobs (tests / poller)."""
        summaries: list[str] = []
        now = self.clock.now()
        for spec in list(self._jobs.values()):
            if not spec.enabled:
                continue
            last = self._last_run.get(spec.name)
            if last and (now - last).total_seconds() < spec.interval_seconds:
                continue
            summaries.append(self._execute(spec))
        return summaries

    def _execute(self, spec: JobSpec) -> str:
        started = self.clock.now()
        status = "success"
        summary = ""
        try:
            summary = spec.func() or "(no output)"
        except Exception as exc:  # noqa: BLE001
            status = "error"
            summary = str(exc)
            log.warning("job_failed", job=spec.name, error=str(exc))
        finished = self.clock.now()
        self._last_run[spec.name] = finished
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO job_runs (job_name, status, summary, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (spec.name, status, summary[:4000], started.isoformat(), finished.isoformat()),
            )
            conn.commit()
        return summary

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                log.warning("job_tick_error", error=str(exc))
            self._stop.wait(self.poll_seconds)

    def _load_enabled(self, name: str, *, default: bool) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                "SELECT enabled FROM job_settings WHERE job_name = ?",
                (name,),
            )
            row = cur.fetchone()
        if row is None:
            return default
        return bool(row["enabled"])

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._conn.close()


def _notify_trim(text: str, limit: int = 180) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"
