"""Silero VAD adapter."""

from __future__ import annotations

import numpy as np
import torch
from silero_vad import load_silero_vad

from jarvis.audio.base import VADProvider


class SileroVAD(VADProvider):
    def __init__(self, threshold: float = 0.4, energy_floor: float = 0.008) -> None:
        self.threshold = threshold
        self.energy_floor = energy_floor
        self._model = load_silero_vad()

    def is_speech(self, frame: np.ndarray, sample_rate: int) -> bool:
        if frame.size == 0:
            return False
        audio = frame.astype(np.float32, copy=False)
        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms < self.energy_floor:
            return False

        if sample_rate != 16000:
            duration = len(audio) / float(sample_rate)
            target_len = max(1, int(duration * 16000))
            audio = np.interp(
                np.linspace(0, 1, target_len, endpoint=False),
                np.linspace(0, 1, len(audio), endpoint=False),
                audio,
            ).astype(np.float32)

        needed = 512
        if len(audio) < needed:
            audio = np.pad(audio, (0, needed - len(audio)))
        elif len(audio) > needed:
            audio = audio[:needed]

        tensor = torch.from_numpy(audio)
        with torch.no_grad():
            prob = float(self._model(tensor, 16000).item())
        return prob >= self.threshold
