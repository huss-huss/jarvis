"""Microphone capture helpers."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from jarvis.audio.base import AudioBuffer, VADProvider
from jarvis.logging import get_logger

log = get_logger(__name__)

# PortAudio on macOS aborts the whole process if two InputStreams open at once.
AUDIO_DEVICE_LOCK = threading.RLock()


class Microphone:
    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    def record_until_silence(
        self,
        vad: VADProvider,
        *,
        max_seconds: float = 20.0,
        silence_seconds: float = 1.0,
        pre_roll_seconds: float = 0.5,
        speech_obligatory: bool = True,
        frame_ms: int = 32,
        on_listening: Callable[[], None] | None = None,
    ) -> AudioBuffer:
        """Record from the default mic until trailing silence after speech."""
        frame_size = int(self.sample_rate * frame_ms / 1000)
        q: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):  # noqa: ANN001
            if status:
                log.debug("mic_status", status=str(status))
            q.put(indata.copy())

        if on_listening:
            on_listening()

        chunks: list[np.ndarray] = []
        speech_seen = False
        silence_started: float | None = None
        started = time.monotonic()
        pre_roll_frames = int(pre_roll_seconds * 1000 / frame_ms)
        ring: list[np.ndarray] = []

        acquired = AUDIO_DEVICE_LOCK.acquire(timeout=8.0)
        if not acquired:
            log.warning("mic_busy_timeout")
            return AudioBuffer(samples=np.zeros(0, dtype=np.float32), sample_rate=self.sample_rate)
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=frame_size,
                callback=callback,
            ):
                while True:
                    if time.monotonic() - started > max_seconds:
                        break
                    try:
                        block = q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    mono = block.reshape(-1)
                    if mono.size == 0:
                        continue

                    ring.append(mono)
                    if len(ring) > pre_roll_frames and not speech_seen:
                        ring = ring[-pre_roll_frames:]

                    speaking = vad.is_speech(mono, self.sample_rate)
                    if speaking:
                        if not speech_seen:
                            chunks.extend(ring)
                            ring.clear()
                            speech_seen = True
                        chunks.append(mono)
                        silence_started = None
                    elif speech_seen:
                        chunks.append(mono)
                        if silence_started is None:
                            silence_started = time.monotonic()
                        elif time.monotonic() - silence_started >= silence_seconds:
                            break
        except Exception as exc:  # noqa: BLE001
            log.warning("mic_record_failed", error=str(exc))
            return AudioBuffer(samples=np.zeros(0, dtype=np.float32), sample_rate=self.sample_rate)
        finally:
            AUDIO_DEVICE_LOCK.release()

        if not chunks:
            return AudioBuffer(samples=np.zeros(0, dtype=np.float32), sample_rate=self.sample_rate)

        samples = np.concatenate(chunks).astype(np.float32, copy=False)
        if speech_obligatory and not speech_seen:
            return AudioBuffer(samples=np.zeros(0, dtype=np.float32), sample_rate=self.sample_rate)
        return AudioBuffer(samples=samples, sample_rate=self.sample_rate)
