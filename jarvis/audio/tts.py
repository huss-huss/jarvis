"""TTS providers: Kokoro (preferred) and macOS `say` fallback."""

from __future__ import annotations

import contextlib
import io
import subprocess
import threading
from typing import Any

import numpy as np
import sounddevice as sd

from jarvis.audio.base import TTSProvider
from jarvis.logging import get_logger

log = get_logger(__name__)


class MacSayTTS(TTSProvider):
    """Built-in macOS TTS — always free, no model download."""

    def __init__(self, voice: str = "Samantha", rate: int = 185) -> None:
        self.voice = voice
        self.rate = rate
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self.stop()
        with self._lock:
            self._proc = subprocess.Popen(
                ["say", "-v", self.voice, "-r", str(self.rate), cleaned],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc = self._proc
        if proc is not None:
            proc.wait()
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None


class KokoroTTS(TTSProvider):
    def __init__(self, voice: str = "af_heart", lang_code: str = "a", sample_rate: int = 24000) -> None:
        from kokoro import KPipeline

        self.voice = voice
        self.sample_rate = sample_rate
        self._pipeline = KPipeline(lang_code=lang_code)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fallback = MacSayTTS()

    def speak(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self._stop.clear()
        # App lists / long answers: Kokoro often prints "words count mismatch" — use say.
        if len(cleaned) > 160 or cleaned.count(",") >= 3:
            self._fallback.speak(cleaned)
            return
        try:
            sink = io.StringIO()
            chunks: list[np.ndarray] = []
            with self._lock:
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    stream = self._pipeline(cleaned, voice=self.voice)
                    for _gs, _ps, audio in stream:
                        if self._stop.is_set():
                            break
                        samples = _to_numpy(audio)
                        if samples.size:
                            chunks.append(samples)
            noise = sink.getvalue()
            if "words count mismatch" in noise.lower() and not self._stop.is_set():
                # Synthesis was unreliable — speak cleanly via say instead
                self._fallback.speak(cleaned)
                return
            if not chunks or self._stop.is_set():
                return
            # One continuous write + trailing silence so PortAudio doesn't click at stop.
            waveform = _fade_edges(np.concatenate(chunks), sample_rate=self.sample_rate)
            pad = np.zeros(int(self.sample_rate * 0.05), dtype=np.float32)
            waveform = np.concatenate([waveform, pad])
            _play_exclusive(waveform, self.sample_rate, self._stop)
        except Exception as exc:  # noqa: BLE001
            log.warning("kokoro_speak_failed_fallback_say", error=str(exc))
            if not self._stop.is_set():
                self._fallback.speak(cleaned)

    def stop(self) -> None:
        self._stop.set()
        sd.stop()
        self._fallback.stop()


class AudioExclusiveTTS(TTSProvider):
    """
    Pause the wake-word mic around every speak().
    Speaking while the wake InputStream is open causes a rapid ta-ta-ta on macOS —
    and that hits *every* reply, not just the wake ack.
    """

    def __init__(self, inner: TTSProvider, pause, resume) -> None:
        self._inner = inner
        self._pause = pause
        self._resume = resume

    def speak(self, text: str) -> None:
        self._pause()
        try:
            self._inner.speak(text)
        finally:
            self._resume()

    def stop(self) -> None:
        self._inner.stop()


def _to_numpy(audio: Any) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    arr = np.asarray(audio, dtype=np.float32)
    return arr.reshape(-1)


def _fade_edges(samples: np.ndarray, fade_ms: float = 8.0, sample_rate: int = 24000) -> np.ndarray:
    """Tiny fade in/out so PortAudio start/stop doesn't click."""
    out = np.asarray(samples, dtype=np.float32).copy()
    n = int(sample_rate * fade_ms / 1000.0)
    if n <= 0 or out.size < n * 2:
        return out
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def _play_exclusive(waveform: np.ndarray, sample_rate: int, stop: threading.Event) -> None:
    """Write-based OutputStream — more reliable than sd.play while avoiding underrun ticks."""
    data = np.asarray(waveform, dtype=np.float32).reshape(-1, 1)
    with sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=2048,
        latency="high",
    ) as stream:
        step = 4096
        for i in range(0, len(data), step):
            if stop.is_set():
                break
            stream.write(data[i : i + step])


def create_tts(provider: str = "macos_say", **kwargs: Any) -> TTSProvider:
    if provider == "macos_say":
        return MacSayTTS(**{k: v for k, v in kwargs.items() if k in {"voice", "rate"}})
    if provider == "kokoro":
        try:
            return KokoroTTS(**{k: v for k, v in kwargs.items() if k in {"voice", "lang_code", "sample_rate"}})
        except Exception as exc:  # noqa: BLE001
            log.warning("kokoro_unavailable_falling_back_to_say", error=str(exc))
            return MacSayTTS()
    raise ValueError(f"Unknown TTS provider: {provider}")
