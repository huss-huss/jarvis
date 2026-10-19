"""Local notification providers (macOS + console fallback)."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod

from jarvis.logging import get_logger

log = get_logger(__name__)


class NotificationProvider(ABC):
    @abstractmethod
    def notify(self, title: str, message: str) -> None:
        raise NotImplementedError


class MacNotificationProvider(NotificationProvider):
    """macOS Notification Center via osascript."""

    def notify(self, title: str, message: str) -> None:
        safe_title = _escape_applescript(title or "Jarvis")
        safe_body = _escape_applescript(message or "")
        script = (
            f'display notification "{safe_body}" with title "{safe_title}" '
            f'sound name "Glass"'
        )
        try:
            completed = subprocess.run(  # noqa: S603
                ["osascript", "-e", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("macos_notification_failed", error=str(exc))
            raise
        err = (completed.stderr or "").strip()
        if completed.returncode != 0 or "invalid" in err.lower() or "denied" in err.lower():
            log.warning(
                "macos_notification_rejected",
                returncode=completed.returncode,
                stderr=err[:300] or None,
            )
            raise RuntimeError(err or f"osascript failed ({completed.returncode})")


class ConsoleNotificationProvider(NotificationProvider):
    def notify(self, title: str, message: str) -> None:
        # Leading/trailing newlines so it shows even while waiting at "You:"
        print(f"\n[{title}] {message}\n", flush=True)
        try:
            print("\a", end="", flush=True)  # terminal bell
        except Exception:  # noqa: BLE001
            pass


class CompositeNotificationProvider(NotificationProvider):
    """Always alert in-terminal; also try the OS banner when available."""

    def __init__(self, *providers: NotificationProvider) -> None:
        self.providers = list(providers)

    def notify(self, title: str, message: str) -> None:
        errors: list[str] = []
        for provider in self.providers:
            try:
                provider.notify(title, message)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(provider).__name__}: {exc}")
        if errors and len(errors) == len(self.providers):
            log.warning("all_notifiers_failed", errors=errors)


class RecordingNotifier(NotificationProvider):
    """Test double that records notifications."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, message: str) -> None:
        self.sent.append((title, message))


def create_notifier(*, prefer_macos: bool = True) -> NotificationProvider:
    console = ConsoleNotificationProvider()
    if prefer_macos:
        return CompositeNotificationProvider(console, MacNotificationProvider())
    return console


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
