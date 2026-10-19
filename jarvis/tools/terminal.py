"""Restricted terminal runner — allowlist only, no shell=True."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from jarvis.tools.base import PermissionLevel, Tool, ToolResult

# Binary names that may run (first token only).
DEFAULT_ALLOWLIST = frozenset(
    {
        "ls",
        "pwd",
        "echo",
        "date",
        "whoami",
        "uname",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "egrep",
        "fgrep",
        "find",
        "which",
        "file",
        "du",
        "df",
        "git",
        "python3",
        "python",
        "pip",
        "pip3",
        "uv",
        "npm",
        "node",
        "rg",
        "sed",
        "awk",
        "sort",
        "uniq",
        "tr",
        "cut",
        "basename",
        "dirname",
        "realpath",
        "stat",
        "tree",
        "env",
        "printenv",
    }
)

# Substrings / patterns that always block — even if binary is allowlisted.
_DENY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brm\b",
        r"\bmv\b",
        r"\bdd\b",
        r"\bsudo\b",
        r"\bdoas\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bmkfs\b",
        r"\bdiskutil\b",
        r"\blaunchctl\b",
        r"\bkill\b",
        r"\bkillall\b",
        r"\breboot\b",
        r"\bshutdown\b",
        r"\bpasswd\b",
        r"\bcurl\b.*\s-o\b",
        r"\bwget\b",
        r">\s*/",
        r"\|\s*sh\b",
        r"\|\s*bash\b",
        r"\beval\b",
        r"`",
        r"\$\(",
        r"\brm\s+-rf\b",
        r"git\s+push\s+.*--force",
        r"git\s+reset\s+--hard",
        r"git\s+clean\s+-fd",
        r"pip\s+uninstall",
        r"npm\s+(-g\s+)?uninstall",
    ]
]

_SAFE_GIT = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "branch",
        "rev-parse",
        "remote",
        "describe",
        "tag",
        "ls-files",
        "shortlog",
        "blame",
        "stash",  # list only typically; still disallow drop via pattern
    }
)


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run a restricted shell command from an allowlist (no arbitrary shell). "
        "Destructive commands are blocked. Prefer file tools for reading/writing files."
    )
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Command string, e.g. 'ls -la' or 'git status'.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Optional timeout (default from config).",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        *,
        cwd: Path,
        allowlist: set[str] | frozenset[str] | None = None,
        timeout_seconds: float = 30.0,
        max_output_chars: int = 20_000,
    ) -> None:
        self.cwd = cwd
        self.allowlist = frozenset(allowlist or DEFAULT_ALLOWLIST)
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def permission_for(self, **kwargs: Any) -> PermissionLevel:
        command = str(kwargs.get("command") or "")
        if _looks_destructive(command):
            return PermissionLevel.DANGEROUS
        return PermissionLevel.MODIFICATION

    def execute(self, **kwargs: Any) -> ToolResult:
        raw = str(kwargs.get("command") or "").strip()
        if not raw:
            return ToolResult(success=False, output="", error="command is required")

        denied = _deny_reason(raw, self.allowlist)
        if denied:
            return ToolResult(success=False, output="", error=denied)

        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            return ToolResult(success=False, output="", error=f"Could not parse command: {exc}")
        if not argv:
            return ToolResult(success=False, output="", error="Empty command")

        binary = Path(argv[0]).name
        if binary not in self.allowlist:
            return ToolResult(
                success=False,
                output="",
                error=f"Command '{binary}' is not on the allowlist",
            )

        if binary == "git":
            git_err = _validate_git(argv)
            if git_err:
                return ToolResult(success=False, output="", error=git_err)

        timeout = float(kwargs.get("timeout_seconds") or self.timeout_seconds)
        timeout = max(1.0, min(timeout, 120.0))

        try:
            completed = subprocess.run(  # noqa: S603 — argv list, no shell
                argv,
                cwd=str(self.cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return ToolResult(success=False, output="", error=f"Executable not found: {binary}")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Timed out after {timeout}s")
        except OSError as exc:
            return ToolResult(success=False, output="", error=str(exc))

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = stdout
        if stderr.strip():
            combined = (combined + "\n[stderr]\n" + stderr).strip()
        if len(combined) > self.max_output_chars:
            combined = combined[: self.max_output_chars] + "\n…[truncated]"
        status = "ok" if completed.returncode == 0 else f"exit {completed.returncode}"
        return ToolResult(
            success=completed.returncode == 0,
            output=f"$ {' '.join(argv)}  ({status})\ncwd={self.cwd}\n\n{combined or '(no output)'}",
            error=None if completed.returncode == 0 else f"exit code {completed.returncode}",
        )


def _looks_destructive(command: str) -> bool:
    return any(p.search(command) for p in _DENY_PATTERNS)


def _deny_reason(command: str, allowlist: frozenset[str]) -> str | None:
    if "\n" in command or "\r" in command:
        return "Multiline commands are not allowed"
    if _looks_destructive(command):
        return "Command blocked by safety policy (destructive / elevated pattern)"
    # Disallow shell chaining / redirects that bypass argv model when we still parse
    if any(ch in command for ch in [";", "&&", "||", "|", ">", "<"]):
        # Allow simple pipes? No — keep strict for Phase 5 quality
        return "Shell operators (; && || | < >) are not allowed — run one simple command"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"Could not parse command: {exc}"
    if not argv:
        return "Empty command"
    binary = Path(argv[0]).name
    if binary not in allowlist:
        return f"Command '{binary}' is not on the allowlist"
    return None


def _validate_git(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "git requires a subcommand (e.g. status, log, diff)"
    sub = argv[1]
    if sub.startswith("-"):
        # e.g. git -C ... still block for simplicity
        return "git global options are not allowed; use a simple subcommand"
    if sub not in _SAFE_GIT:
        return f"git subcommand '{sub}' is not allowed (safe: {', '.join(sorted(_SAFE_GIT))})"
    joined = " ".join(argv[2:])
    if re.search(r"--force|-f\b", joined) and sub in {"push", "checkout"}:
        return "Forced git operations are blocked"
    if sub == "stash" and any(x in argv[2:] for x in ("drop", "clear", "pop")):
        return "git stash drop/clear/pop is blocked"
    return None


def build_terminal_tools(
    *,
    cwd: Path,
    allowlist: list[str] | None = None,
    timeout_seconds: float = 30.0,
) -> list[Tool]:
    allowed = frozenset(allowlist) if allowlist else DEFAULT_ALLOWLIST
    return [
        RunCommandTool(cwd=cwd, allowlist=allowed, timeout_seconds=timeout_seconds),
    ]
