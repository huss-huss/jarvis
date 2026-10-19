"""Project health monitor — local, read-only checks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from jarvis.logging import get_logger

log = get_logger(__name__)


@dataclass
class ProjectHealth:
    path: Path
    ok: bool
    summary: str
    details: list[str]


class ProjectMonitor:
    """
    Safe, allowlisted checks only (git status / short log).
    Never runs install, push, reset, or arbitrary shell.
    """

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path

    def check(self) -> ProjectHealth:
        root = self.project_path.expanduser().resolve()
        details: list[str] = []
        if not root.exists():
            return ProjectHealth(root, False, f"Project path missing: {root}", [])
        if not (root / ".git").exists():
            return ProjectHealth(root, True, f"{root.name}: not a git repo (skipped)", [])

        status = _run(["git", "status", "--porcelain"], cwd=root)
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
        if status is None or branch is None:
            return ProjectHealth(root, False, f"{root.name}: git check failed", details)

        branch_name = (branch or "unknown").strip()
        dirty_lines = [ln for ln in status.splitlines() if ln.strip()]
        if dirty_lines:
            details.append(f"{len(dirty_lines)} uncommitted change(s)")
            details.extend(dirty_lines[:8])
            summary = f"{root.name} ({branch_name}): dirty working tree — {len(dirty_lines)} change(s)"
            return ProjectHealth(root, False, summary, details)

        summary = f"{root.name} ({branch_name}): clean working tree"
        return ProjectHealth(root, True, summary, details)


def _run(argv: list[str], *, cwd: Path) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("project_monitor_cmd_failed", cmd=argv, error=str(exc))
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout or ""
