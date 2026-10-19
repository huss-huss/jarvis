"""Voice / TTS unit tests (no mic required)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy", reason="voice tests need the `voice` extra: pip install -e '.[voice]'")
pytest.importorskip("sounddevice", reason="voice tests need the `voice` extra")

from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.audio.base import AudioBuffer, STTProvider, Transcript, TTSProvider, VADProvider
from jarvis.audio.session import VoiceSession
from jarvis.config import PermissionsConfig
from jarvis.llm.base import ChatChunk, ChatMessage, HealthStatus, LLMProvider, ToolCall
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.registry import ToolRegistry
from jarvis.audio.tts import MacSayTTS


class _FakeSTT(STTProvider):
    def transcribe(self, audio: AudioBuffer) -> Transcript:
        return Transcript(text="What time is it?")


class _FakeTTS(TTSProvider):
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = False

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self.stopped = True


class _AlwaysSpeechVAD(VADProvider):
    def is_speech(self, frame: np.ndarray, sample_rate: int) -> bool:
        return True


class _FakeLLM(LLMProvider):
    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message="ok")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatChunk]:
        yield ChatChunk(content="It is nine twenty-five.", done=True)


def test_voice_session_cancel_phrase(tmp_path: Path):
    db = str(tmp_path / "v.db")
    orch = AgentOrchestrator(
        llm=_FakeLLM(),
        tools=ToolRegistry(),
        permissions=PermissionManager(PermissionsConfig(), confirm=lambda _p: False),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
    )
    tts = _FakeTTS()
    session = VoiceSession(orch, stt=_FakeSTT(), tts=tts, vad=_AlwaysSpeechVAD())
    result = session.handle_utterance("Stop")
    assert result == "Okay, cancelled."
    assert tts.stopped is True


def test_voice_session_speaks_reply(tmp_path: Path):
    db = str(tmp_path / "v.db")
    orch = AgentOrchestrator(
        llm=_FakeLLM(),
        tools=ToolRegistry(),
        permissions=PermissionManager(PermissionsConfig(), confirm=lambda _p: False),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
    )
    tts = _FakeTTS()
    session = VoiceSession(orch, stt=_FakeSTT(), tts=tts, vad=_AlwaysSpeechVAD())
    result = session.handle_utterance("hello")
    assert "nine twenty-five" in result.lower()
    assert tts.spoken


def test_voice_session_rejects_garbled(tmp_path: Path):
    db = str(tmp_path / "v.db")
    orch = AgentOrchestrator(
        llm=_FakeLLM(),
        tools=ToolRegistry(),
        permissions=PermissionManager(PermissionsConfig(), confirm=lambda _p: False),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
    )
    tts = _FakeTTS()
    session = VoiceSession(orch, stt=_FakeSTT(), tts=tts, vad=_AlwaysSpeechVAD())
    result = session.handle_utterance("xyz")
    assert "didn't catch" in result.lower()


def test_mac_say_tts_stop_is_safe():
    tts = MacSayTTS()
    tts.stop()  # should not raise


def test_stt_name_cleanup():
    from jarvis.audio.stt import _clean_transcript

    assert _clean_transcript("Hello Dervis") == "Hello Jarvis"
    assert _clean_transcript("[BLANK_AUDIO]") == ""


def test_parse_text_tool_calls_normalizes_name():
    from jarvis.agent.orchestrator import _parse_text_tool_calls

    calls = _parse_text_tool_calls(
        '{"name": "close_application", "parameters": {"name": "Telegram"}}'
    )
    assert len(calls) == 1
    assert calls[0].name == "close_application"
    assert calls[0].arguments["application_name"] == "Telegram"
