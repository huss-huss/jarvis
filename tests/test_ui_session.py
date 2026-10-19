"""Desktop UI session smoke tests (no browser)."""

from __future__ import annotations

from jarvis.config import JarvisConfig
from jarvis.ui.session import DesktopSession


class _FakeMemory:
    def recent_messages(self, limit: int = 40):
        return []

    def new_conversation(self) -> int:
        return 1

    def add_message(self, *args, **kwargs) -> None:
        return None


class _FakeOrch:
    def __init__(self) -> None:
        self.memory = _FakeMemory()
        self.long_term = None
        self.rag = None
        self.reminders = None
        self.jobs = None
        self._events: list[tuple] = []

    def handle_user_message(self, text, *, on_token=None, on_event=None):
        from jarvis.agent.orchestrator import TurnResult

        if on_event:
            on_event("status", {"status": "thinking"})
        if on_token:
            on_token("Hello ")
            on_token("world")
        if on_event:
            on_event("status", {"status": "idle"})
        return TurnResult(text="Hello world", tool_names=[])


def test_desktop_session_chat_broadcasts():
    messages: list[dict] = []
    orch = _FakeOrch()
    session = DesktopSession(orch, JarvisConfig(), broadcast=messages.append)
    session.handle_chat("hi")
    types = [m["type"] for m in messages]
    assert "user" in types
    assert "token" in types
    assert "done" in types
    assert any(m["type"] == "status" for m in messages)


def test_desktop_session_confirm_roundtrip():
    messages: list[dict] = []
    session = DesktopSession(_FakeOrch(), JarvisConfig(), broadcast=messages.append)

    def _answer() -> None:
        import time

        time.sleep(0.05)
        assert session.resolve_confirm(allowed=True)

    import threading

    threading.Thread(target=_answer, daemon=True).start()
    assert session.confirm("Allow delete?") is True
    assert any(m["type"] == "confirm_request" for m in messages)


def test_snapshot_voice_flag_false_by_default():
    session = DesktopSession(_FakeOrch(), JarvisConfig(), broadcast=lambda _m: None)
    snap = session.snapshot()
    assert snap["capabilities"]["voice"] is False
