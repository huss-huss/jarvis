"""Wake-word / activation tests (mocked — no mic required)."""

from __future__ import annotations

import queue
import time

import pytest

pytest.importorskip("numpy", reason="needs the `voice` extra: pip install -e '.[voice]'")

from jarvis.audio.base import WakeEvent  # noqa: E402
from jarvis.audio.wakeword import ActivationMonitor  # noqa: E402


class _FakeWake:
    def __init__(self) -> None:
        self._q: queue.Queue[WakeEvent] = queue.Queue()
        self.started = False
        self.stopped = False
        self.paused = False
        self.pause_count = 0
        self._started = False
        self._depth = 0

    def start(self) -> None:
        self.started = True
        self._started = True
        self.paused = False

    def stop(self) -> None:
        self.stopped = True
        self._started = False

    def pause(self, *, wait_release: float = 1.5) -> None:
        self._depth += 1
        self.pause_count += 1
        self.paused = True

    def resume(self) -> None:
        self._depth = max(0, self._depth - 1)
        self.paused = self._depth > 0

    def wait_for_wake(self, timeout: float | None = None) -> WakeEvent | None:
        try:
            return self._q.get(timeout=timeout or 0.01)
        except queue.Empty:
            return None

    def fire(self) -> None:
        self._q.put(WakeEvent(source="wake_word", label="hey_jarvis", score=0.9))


class _FakeHotkey:
    def __init__(self) -> None:
        self._q: queue.Queue[WakeEvent] = queue.Queue()

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def wait_for_hotkey(self, timeout: float | None = None) -> WakeEvent | None:
        try:
            return self._q.get(timeout=timeout or 0.01)
        except queue.Empty:
            return None

    def fire(self) -> None:
        self._q.put(WakeEvent(source="hotkey", label="<ctrl>+<alt>+j"))


def test_activation_monitor_wake():
    wake = _FakeWake()
    hot = _FakeHotkey()
    mon = ActivationMonitor(wake, hot)  # type: ignore[arg-type]
    mon.start()
    assert wake.started
    wake.fire()
    event = mon.wait(timeout=1.0)
    assert event is not None
    assert event.source == "wake_word"
    mon.pause_wake_mic()
    assert wake.paused
    mon.pause_wake_mic()  # nested
    mon.resume_wake_mic()
    assert wake.paused  # still held by outer
    mon.resume_wake_mic()
    assert not wake.paused
    mon.stop()


def test_audio_exclusive_tts_pauses_around_speak():
    from jarvis.audio.tts import AudioExclusiveTTS

    class _Inner:
        def __init__(self) -> None:
            self.spoken: list[str] = []
            self.paused_during_speak = False

        def speak(self, text: str) -> None:
            self.paused_during_speak = wake.paused
            self.spoken.append(text)

        def stop(self) -> None:
            return None

    wake = _FakeWake()
    mon = ActivationMonitor(wake, None)  # type: ignore[arg-type]
    mon.start()
    inner = _Inner()
    tts = AudioExclusiveTTS(inner, mon.pause_wake_mic, mon.resume_wake_mic)  # type: ignore[arg-type]
    tts.speak("hello")
    assert inner.spoken == ["hello"]
    assert inner.paused_during_speak is True
    assert wake.paused is False
    mon.stop()


def test_activation_monitor_hotkey():
    wake = _FakeWake()
    hot = _FakeHotkey()
    mon = ActivationMonitor(wake, hot)  # type: ignore[arg-type]
    mon.start()
    hot.fire()
    event = mon.wait(timeout=1.0)
    assert event is not None
    assert event.source == "hotkey"


def test_activation_monitor_timeout():
    wake = _FakeWake()
    hot = _FakeHotkey()
    mon = ActivationMonitor(wake, hot)  # type: ignore[arg-type]
    mon.start()
    event = mon.wait(timeout=0.15)
    assert event is None
