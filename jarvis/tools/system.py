"""macOS-oriented system tools."""

from __future__ import annotations

import json
import platform
import subprocess
import time
from datetime import datetime
from typing import Any

from jarvis.tools.base import PermissionLevel, Tool, ToolResult

# Common spoken/typed names → macOS application name
APP_ALIASES: dict[str, str] = {
    "cursor": "Cursor",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "finder": "Finder",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "notes": "Notes",
    "mail": "Mail",
    "messages": "Messages",
    "music": "Music",
    "spotify": "Spotify",
    "slack": "Slack",
    "discord": "Discord",
    "telegram": "Telegram",
    "zoom": "zoom.us",
    "zoom.us": "zoom.us",
    "activity monitor": "Activity Monitor",
    "tv": "TV",
    "music": "Music",
    "messages": "Messages",
    "message": "Messages",
    "figma": "Figma",
    "calculator": "Calculator",
    "calendar": "Calendar",
    "preview": "Preview",
    "system settings": "System Settings",
    "settings": "System Settings",
}

PROTECTED_APPS = {
    "finder",
    "system events",
    "systemui server",
    "windowserver",
    "dock",
    "loginwindow",
}


def resolve_app_name(raw: str) -> str:
    key = raw.strip().lower()
    return APP_ALIASES.get(key, raw.strip())


def extract_app_name(kwargs: dict[str, Any]) -> str:
    """Accept common LLM argument aliases."""
    for key in ("application_name", "name", "app", "application", "app_name"):
        value = kwargs.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def list_foreground_apps() -> list[str]:
    script = (
        'tell application "System Events" to get name of every process '
        "whose background only is false"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return [a.strip() for a in result.stdout.split(",") if a.strip()]


def list_all_process_names() -> list[str]:
    script = 'tell application "System Events" to get name of every process'
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return [a.strip() for a in result.stdout.split(",") if a.strip()]


def is_app_running(app_name: str) -> bool:
    target = app_name.casefold()
    try:
        names = list_all_process_names()
    except (subprocess.SubprocessError, FileNotFoundError):
        proc = subprocess.run(
            ["pgrep", "-if", f"^{app_name}$|{app_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())

    for name in names:
        n = name.casefold()
        if n == target or target in n or n in target:
            return True
    return False


def wait_until(predicate, *, timeout: float = 8.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _run_osascript(script: str, *, timeout: float = 20.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def activate_app(app_name: str) -> None:
    _run_osascript(f'tell application "{app_name}" to activate', timeout=12)
    # Also via System Events (helps with fullscreen spaces)
    _run_osascript(
        f'''
        tell application "System Events"
          if exists process "{app_name}" then
            set frontmost of process "{app_name}" to true
          end if
        end tell
        ''',
        timeout=12,
    )


def exit_fullscreen_if_needed(app_name: str) -> None:
    """Best-effort exit from macOS fullscreen before quit."""
    script = f'''
    tell application "System Events"
      if not (exists process "{app_name}") then return
      set frontmost of process "{app_name}" to true
      delay 0.35
      try
        tell process "{app_name}"
          -- Standard macOS toggle fullscreen
          keystroke "f" using {{control down, command down}}
        end tell
      end try
    end tell
    '''
    _run_osascript(script, timeout=15)
    time.sleep(0.6)


def force_kill_app(app_name: str) -> None:
    # Exact name first, then case-insensitive
    subprocess.run(["killall", app_name], capture_output=True, text=True, timeout=8)
    if is_app_running(app_name):
        subprocess.run(["killall", "-9", app_name], capture_output=True, text=True, timeout=8)
    if is_app_running(app_name):
        subprocess.run(["pkill", "-9", "-if", app_name], capture_output=True, text=True, timeout=8)


def quit_app_robust(app_name: str) -> tuple[bool, str]:
    """
    Quit an app even when it is in fullscreen.
    Returns (success, message).
    """
    if not is_app_running(app_name):
        return True, f"{app_name} is not running."

    activate_app(app_name)
    exit_fullscreen_if_needed(app_name)

    # 1) Graceful AppleScript quit
    proc = _run_osascript(f'tell application "{app_name}" to quit', timeout=20)
    if wait_until(lambda: not is_app_running(app_name), timeout=5.0):
        return True, f"Closed {app_name} and verified it is no longer running."

    # 2) Menu Quit via System Events (works for some stubborn GUI apps)
    _run_osascript(
        f'''
        tell application "System Events"
          if exists process "{app_name}" then
            set frontmost of process "{app_name}" to true
            delay 0.2
            try
              tell process "{app_name}" to keystroke "q" using command down
            end try
          end if
        end tell
        ''',
        timeout=15,
    )
    if wait_until(lambda: not is_app_running(app_name), timeout=4.0):
        return True, f"Closed {app_name} via Quit shortcut and verified it is no longer running."

    # 3) Force kill
    force_kill_app(app_name)
    if wait_until(lambda: not is_app_running(app_name), timeout=4.0):
        return True, f"Force-quit {app_name} and verified it is no longer running."

    detail = (proc.stderr or proc.stdout or "").strip()
    return False, (
        f"Tried to quit {app_name} (including fullscreen exit and force-quit), "
        f"but it is still running.{(' ' + detail) if detail else ''}"
    )


class GetCurrentTimeTool(Tool):
    name = "get_current_time"
    description = "Get the current local date and time."
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        now = datetime.now().astimezone()
        human = now.strftime("%I:%M %p").lstrip("0")
        full = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        return ToolResult(
            success=True,
            output=f"It is {human} ({full}).",
            data={"iso": now.isoformat(), "human": human},
        )


class GetSystemInformationTool(Tool):
    name = "get_system_information"
    description = (
        "Get basic local system information (OS, machine, Python). "
        "ONLY use when the user explicitly asks about their computer, OS, chip, or hardware specs. "
        "Do NOT use for greetings or unrelated questions."
    )
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        info = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "node": platform.node(),
        }
        return ToolResult(success=True, output=json.dumps(info, indent=2), data=info)


class GetBatteryStatusTool(Tool):
    name = "get_battery_status"
    description = "Get the Mac battery charge percentage and charging state."
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip() or "No battery information available."
            return ToolResult(success=True, output=output)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return ToolResult(success=False, output="", error=str(exc))


class GetRunningAppsTool(Tool):
    name = "get_running_apps"
    description = "List names of currently running applications on macOS."
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            apps = list_foreground_apps()
            return ToolResult(
                success=True,
                output=", ".join(apps) if apps else "No foreground apps found.",
                data={"apps": apps},
            )
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return ToolResult(success=False, output="", error=str(exc))


class OpenApplicationTool(Tool):
    name = "open_application"
    description = (
        "Open (launch or focus) a macOS application by name, then verify it is running. "
        "Works even if the app is on another Space / fullscreen. "
        "Examples: Cursor, Terminal, Calculator, Safari, Telegram, Google Chrome, Notes."
    )
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "application_name": {
                "type": "string",
                "description": "Application name to open",
            }
        },
        "required": ["application_name"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        raw = extract_app_name(kwargs)
        if not raw:
            return ToolResult(success=False, output="", error="application_name is required")

        app_name = resolve_app_name(raw)
        try:
            if is_app_running(app_name):
                activate_app(app_name)
                return ToolResult(
                    success=True,
                    output=f"{app_name} was already running; I brought it to the front.",
                    data={"application": app_name, "action": "activate"},
                )

            proc = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "unknown error").strip()
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Could not open {app_name}: {err}",
                )

            ok = wait_until(lambda: is_app_running(app_name), timeout=8.0)
            if not ok:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Tried to open {app_name}, but it is not running after launch. "
                        "Check the application name."
                    ),
                )

            activate_app(app_name)
            return ToolResult(
                success=True,
                output=f"Opened {app_name} and verified it is running.",
                data={"application": app_name, "action": "open", "verified": True},
            )
        except FileNotFoundError:
            return ToolResult(success=False, output="", error="`open` / osascript not available")
        except subprocess.SubprocessError as exc:
            return ToolResult(success=False, output="", error=str(exc))


class CloseApplicationTool(Tool):
    name = "close_application"
    description = (
        "Quit a macOS application by name, then verify it is no longer running. "
        "Handles fullscreen apps (exits fullscreen, quits, force-quits if needed). "
        "Use when the user asks to close/quit an app. "
        "Argument must be application_name. Never claim success unless verified."
    )
    # SAFE for all apps: action is verified after quit. No confirm prompts.
    # DANGEROUS tools (delete, etc.) still use voice/text confirmation.
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "application_name": {
                "type": "string",
                "description": "Application name to quit",
            }
        },
        "required": ["application_name"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        raw = extract_app_name(kwargs)
        if not raw:
            return ToolResult(success=False, output="", error="application_name is required")

        app_name = resolve_app_name(raw)
        if app_name.casefold() in PROTECTED_APPS:
            return ToolResult(
                success=False,
                output="",
                error=f"Refusing to quit protected app: {app_name}",
            )

        try:
            ok, message = quit_app_robust(app_name)
            if ok:
                return ToolResult(
                    success=True,
                    output=message,
                    data={"application": app_name, "action": "quit", "verified": True},
                )
            return ToolResult(success=False, output="", error=message)
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return ToolResult(success=False, output="", error=str(exc))


class GetClipboardTool(Tool):
    name = "get_clipboard"
    description = "Read the current text content of the system clipboard."
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        try:
            result = subprocess.run(
                ["pbpaste"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = result.stdout
            preview = text if len(text) <= 500 else text[:500] + "…"
            return ToolResult(success=True, output=preview or "(empty clipboard)", data={"length": len(text)})
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return ToolResult(success=False, output="", error=str(exc))


class SetClipboardTool(Tool):
    name = "set_clipboard"
    description = "Set the system clipboard to the provided text."
    permission = PermissionLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to place on the clipboard",
            }
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        text = kwargs.get("text")
        if text is None:
            return ToolResult(success=False, output="", error="text is required")
        try:
            subprocess.run(
                ["pbcopy"],
                input=str(text),
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Verify
            check = subprocess.run(
                ["pbpaste"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if check.stdout != str(text):
                return ToolResult(success=False, output="", error="Clipboard write did not verify")
            return ToolResult(success=True, output="Clipboard updated.", data={"length": len(str(text))})
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return ToolResult(success=False, output="", error=str(exc))


def build_default_tools() -> list[Tool]:
    return [
        GetCurrentTimeTool(),
        GetSystemInformationTool(),
        GetBatteryStatusTool(),
        GetRunningAppsTool(),
        OpenApplicationTool(),
        CloseApplicationTool(),
        GetClipboardTool(),
        SetClipboardTool(),
    ]
