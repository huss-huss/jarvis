"""Voice conversation loop (Phase 2 — no wake word yet)."""

from __future__ import annotations

import re
from collections.abc import Callable

from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.audio.base import STTProvider, TTSProvider, VADProvider
from jarvis.audio.microphone import Microphone
from jarvis.logging import get_logger

log = get_logger(__name__)

CANCEL_PHRASES = {"stop", "cancel", "never mind", "nevermind"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_VOWELS = set("aeiouy")


def looks_garbled(text: str) -> bool:
    """Heuristic: reject nonsense STT fragments instead of sending them to the LLM."""
    cleaned = re.sub(r"[^a-zA-Z\s']", "", text).strip().lower()
    if not cleaned:
        return True
    words = cleaned.split()
    if len(words) == 1 and len(words[0]) <= 3 and words[0] not in {"hi", "hey", "yes", "no", "ok", "time"}:
        # single short mystery token like "kawaru" often has vowels — length alone isn't enough
        pass
    # No vowels at all → almost certainly junk
    if not any(ch in _VOWELS for ch in cleaned.replace(" ", "")):
        return True
    # Very short non-dictionary-looking single tokens with odd patterns
    if len(words) == 1:
        w = words[0]
        if w in {"hi", "hey", "hello", "jarvis", "yes", "no", "ok", "okay", "thanks", "stop", "cancel", "time"}:
            return False
        # one mystery word under 4 chars is often a cut-off
        if len(w) < 4:
            return True
    return False


class VoiceSession:
    """Push-to-talk style: Enter to listen → STT → agent → TTS."""

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        stt: STTProvider,
        tts: TTSProvider,
        vad: VADProvider,
        microphone: Microphone | None = None,
        *,
        barge_in: bool = True,
        silence_seconds: float = 1.2,
        max_listen_seconds: float = 25.0,
        pre_roll_seconds: float = 0.5,
    ) -> None:
        self.orchestrator = orchestrator
        self.stt = stt
        self.tts = tts
        self.vad = vad
        self.microphone = microphone or Microphone()
        self.barge_in = barge_in
        self.silence_seconds = silence_seconds
        self.max_listen_seconds = max_listen_seconds
        self.pre_roll_seconds = pre_roll_seconds

    def listen_once(self) -> str:
        print("Listening… (speak clearly, then pause)")
        audio = self.microphone.record_until_silence(
            self.vad,
            max_seconds=self.max_listen_seconds,
            silence_seconds=self.silence_seconds,
            pre_roll_seconds=self.pre_roll_seconds,
        )
        if audio.samples.size == 0:
            return ""
        transcript = self.stt.transcribe(audio)
        return transcript.text.strip()

    def speak_response(self, text: str) -> None:
        if not text.strip():
            return
        parts = _SENTENCE_END.split(text.strip()) or [text]
        for part in parts:
            chunk = part.strip()
            if not chunk:
                continue
            self.tts.speak(chunk)

    def handle_utterance(self, user_text: str, *, on_token: Callable[[str], None] | None = None) -> str:
        lowered = user_text.lower().strip().rstrip(".!")
        if lowered in CANCEL_PHRASES:
            self.tts.stop()
            return "Okay, cancelled."

        if looks_garbled(user_text):
            msg = "Sorry, I didn't catch that. Please say it again."
            if on_token:
                on_token(msg)
            self.speak_response(msg)
            return msg

        tokens: list[str] = []

        def _collect(token: str) -> None:
            tokens.append(token)
            if on_token:
                on_token(token)

        result = self.orchestrator.handle_user_message(user_text, on_token=_collect)
        spoken = result.text or "".join(tokens)
        self.speak_response(spoken)
        return spoken
