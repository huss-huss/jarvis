"""whisper.cpp STT via pywhispercpp — tuned for robust English recognition."""

from __future__ import annotations

import re

import numpy as np
from pywhispercpp.model import Model

from jarvis.audio.base import AudioBuffer, STTProvider, Transcript
from jarvis.logging import get_logger

log = get_logger(__name__)

# Bias decoder toward assistant vocabulary (helps accents + "Jarvis" name)
DEFAULT_INITIAL_PROMPT = (
    "Hey Jarvis. Hello Jarvis. What time is it? Open Cursor. "
    "Remember that. Cancel. Stop. Never mind."
)

# Common Whisper mishearings of the wake/name phrase
_NAME_FIXES = (
    (re.compile(r"\b[Dd]ervis\b"), "Jarvis"),
    (re.compile(r"\b[Jj]arvice?\b"), "Jarvis"),
    (re.compile(r"\b[Jj]arvis'?s\b"), "Jarvis"),
    (re.compile(r"\b[Gg]ervis\b"), "Jarvis"),
    (re.compile(r"\b[Cc]harvis\b"), "Jarvis"),
    (re.compile(r"\b[Tt]ervis\b"), "Jarvis"),
)

_JUNK = re.compile(
    r"^(\[?(BLANK_AUDIO|INAUDIBLE|MUSIC|SILENCE|NOISE|APPLAUSE|laughter)\]?|"
    r"\(?(BLANK_AUDIO|INAUDIBLE)\)?)$",
    re.IGNORECASE,
)


def _normalize_audio(samples: np.ndarray) -> np.ndarray:
    """Peak-normalize so quiet / accented speech isn't under-amplified."""
    audio = samples.astype(np.float32, copy=False)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-6:
        return audio
    target = 0.9
    if peak < target:
        audio = audio * (target / peak)
    return np.clip(audio, -1.0, 1.0).astype(np.float32)


def _resample_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == 16000:
        return samples.astype(np.float32, copy=False)
    duration = len(samples) / float(sample_rate)
    target_len = max(1, int(duration * 16000))
    return np.interp(
        np.linspace(0, 1, target_len, endpoint=False),
        np.linspace(0, 1, len(samples), endpoint=False),
        samples.astype(np.float32, copy=False),
    ).astype(np.float32)


def _clean_transcript(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned or _JUNK.match(cleaned):
        return ""
    for pattern, replacement in _NAME_FIXES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip()


class WhisperCppSTT(STTProvider):
    def __init__(
        self,
        model_name: str = "small",
        language: str = "en",
        *,
        initial_prompt: str = DEFAULT_INITIAL_PROMPT,
        beam_size: int = 5,
    ) -> None:
        self.model_name = model_name
        self.language = language
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        log.info("loading_whisper", model=model_name)
        # params_sampling_strategy=1 → beam search (more accurate than greedy)
        self._model = Model(
            model_name,
            params_sampling_strategy=1,
            redirect_whispercpp_logs_to=False,
            print_progress=False,
            print_realtime=False,
            print_timestamps=False,
        )

    def transcribe(self, audio: AudioBuffer) -> Transcript:
        if audio.samples.size == 0:
            return Transcript(text="")

        samples = _normalize_audio(_resample_16k(audio.samples, audio.sample_rate))
        # Drop near-silent buffers early
        if float(np.sqrt(np.mean(np.square(samples)))) < 0.005:
            return Transcript(text="")

        segments = self._model.transcribe(
            samples,
            language=self.language,
            initial_prompt=self.initial_prompt,
            temperature=0.0,
            suppress_blank=True,
            suppress_non_speech_tokens=True,
            no_speech_thold=0.5,
            beam_search={"beam_size": self.beam_size, "patience": 1.0},
        )

        parts: list[str] = []
        for seg in segments:
            text = getattr(seg, "text", None)
            if text is None and isinstance(seg, dict):
                text = seg.get("text")
            if text:
                parts.append(str(text).strip())

        joined = _clean_transcript(" ".join(p for p in parts if p))
        return Transcript(text=joined, language=self.language)
