"""Audio / speech provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class Transcript:
    text: str
    language: str | None = None


@dataclass
class AudioBuffer:
    samples: np.ndarray  # float32 mono
    sample_rate: int

    def duration_seconds(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return float(len(self.samples)) / float(self.sample_rate)


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: AudioBuffer) -> Transcript:
        raise NotImplementedError


class TTSProvider(ABC):
    @abstractmethod
    def speak(self, text: str) -> None:
        """Synthesize and play text; should return when playback finishes or is stopped."""

    @abstractmethod
    def stop(self) -> None:
        """Interrupt current playback (barge-in)."""


class VADProvider(ABC):
    @abstractmethod
    def is_speech(self, frame: np.ndarray, sample_rate: int) -> bool:
        raise NotImplementedError


@dataclass
class WakeEvent:
    source: str  # "wake_word" | "hotkey" | "manual"
    label: str | None = None
    score: float | None = None


class WakeWordProvider(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def wait_for_wake(self, timeout: float | None = None) -> WakeEvent | None:
        """Block until wake detected or timeout. None = timeout."""
        raise NotImplementedError
