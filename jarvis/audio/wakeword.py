"""Wake-word detection via openWakeWord (ONNX) + optional hotkey."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from jarvis.audio.base import WakeEvent, WakeWordProvider
from jarvis.logging import get_logger

log = get_logger(__name__)

# openWakeWord frame size: 80 ms @ 16 kHz
CHUNK_SAMPLES = 1280
SAMPLE_RATE = 16000


def _sleep_interruptible(seconds: float, *flags: threading.Event) -> None:
    """Sleep in short slices; return early if any Event is set."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(f.is_set() for f in flags):
            return
        time.sleep(0.02)


def _hey_jarvis_onnx_path() -> Path:
    import openwakeword

    return Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx"


class OpenWakeWordProvider(WakeWordProvider):
    """
    Continuously listens for "Hey Jarvis" using openWakeWord ONNX models.
    Stock models are CC BY-NC-SA 4.0 (personal use OK).
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        debounce_seconds: float = 2.0,
        inference_framework: str = "onnx",
    ) -> None:
        self.threshold = threshold
        self.debounce_seconds = debounce_seconds
        self.inference_framework = inference_framework
        self._model = None
        self._model_key = "hey_jarvis_v0.1"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._events: queue.Queue[WakeEvent] = queue.Queue()
        self._last_fire = 0.0
        self._started = False
        self._load_error: str | None = None
        self._paused = threading.Event()
        self._mic_held = threading.Event()  # set while PortAudio InputStream is open
        self._pause_depth = 0
        self._pause_lock = threading.Lock()

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from openwakeword.model import Model
            from openwakeword.utils import download_models

            model_path = _hey_jarvis_onnx_path()
            if not model_path.exists():
                log.info("downloading_openwakeword_models")
                download_models()
            if not model_path.exists():
                raise FileNotFoundError(f"Missing wake model: {model_path}")

            self._model = Model(
                wakeword_models=[str(model_path)],
                inference_framework=self.inference_framework,
            )
            # Discover actual score key
            keys = list(getattr(self._model, "models", {}).keys())
            if keys:
                self._model_key = keys[0]
            log.info("wakeword_ready", model=self._model_key, framework=self.inference_framework)
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            log.error("wakeword_load_failed", error=str(exc))
            raise

    def start(self) -> None:
        if self._started:
            return
        self._ensure_model()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-wakeword", daemon=True)
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        self._stop.set()
        with self._pause_lock:
            self._pause_depth = 0
            self._paused.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._started = False

    def pause(self, *, wait_release: float = 1.5) -> None:
        """Close the wake InputStream so TTS/STT can use the audio device alone.

        Nested-safe: depth-counted so turn-level + per-speak guards can both call pause.
        """
        with self._pause_lock:
            self._pause_depth += 1
            if self._pause_depth > 1:
                return
            self._paused.set()
        while not self._events.empty():
            try:
                self._events.get_nowait()
            except queue.Empty:
                break
        # Wait until PortAudio actually releases the mic — speaking while it is
        # still open causes a rapid ta-ta-ta tick on macOS (~80ms wake frames).
        deadline = time.monotonic() + wait_release
        while self._mic_held.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        # Let CoreAudio finish tearing the stream down before opening output.
        time.sleep(0.05)

    def resume(self) -> None:
        with self._pause_lock:
            if self._pause_depth <= 0:
                return
            self._pause_depth -= 1
            if self._pause_depth == 0:
                self._paused.clear()

    def wait_for_wake(self, timeout: float | None = None) -> WakeEvent | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self) -> None:
        assert self._model is not None

        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    time.sleep(0.05)
                    continue

                audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=50)

                def callback(indata, frames, time_info, status):  # noqa: ANN001
                    if status:
                        log.debug("wake_mic_status", status=str(status))
                    try:
                        audio_q.put_nowait(indata.copy())
                    except queue.Full:
                        pass

                from jarvis.audio.microphone import AUDIO_DEVICE_LOCK

                got_lock = AUDIO_DEVICE_LOCK.acquire(timeout=2.0)
                if not got_lock:
                    time.sleep(0.2)
                    continue
                self._mic_held.set()
                try:
                    with sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=1,
                        dtype="float32",
                        blocksize=CHUNK_SAMPLES,
                        callback=callback,
                    ):
                        while not self._stop.is_set() and not self._paused.is_set():
                            try:
                                block = audio_q.get(timeout=0.2)
                            except queue.Empty:
                                continue

                            mono = block.reshape(-1)
                            if mono.size < CHUNK_SAMPLES:
                                mono = np.pad(mono, (0, CHUNK_SAMPLES - mono.size))
                            elif mono.size > CHUNK_SAMPLES:
                                mono = mono[:CHUNK_SAMPLES]

                            # openWakeWord expects int16 PCM
                            pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
                            scores = self._model.predict(pcm)
                            score = float(scores.get(self._model_key, 0.0))
                            if score >= self.threshold:
                                now = time.monotonic()
                                if now - self._last_fire >= self.debounce_seconds:
                                    self._last_fire = now
                                    log.info("wakeword_detected", score=score, model=self._model_key)
                                    self._events.put(
                                        WakeEvent(source="wake_word", label="hey_jarvis", score=score)
                                    )
                                    # Interruptible debounce — must yield if main pauses for TTS
                                    _sleep_interruptible(0.5, self._stop, self._paused)
                                    break  # exit stream loop so mic releases for "Yes?" / replies
                except Exception as stream_exc:  # noqa: BLE001
                    log.warning("wake_mic_stream_failed", error=str(stream_exc))
                    time.sleep(0.3)
                finally:
                    self._mic_held.clear()
                    AUDIO_DEVICE_LOCK.release()
                    time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            log.error("wakeword_loop_error", error=str(exc))
            self._load_error = str(exc)


class HotkeyActivator:
    """Global hotkey → WakeEvent. Requires Accessibility permission on macOS."""

    def __init__(self, hotkey: str = "<ctrl>+<alt>+j") -> None:
        self.hotkey = hotkey
        self._events: queue.Queue[WakeEvent] = queue.Queue()
        self._listener = None
        self._error: str | None = None

    def start(self) -> None:
        try:
            from pynput import keyboard

            def on_activate() -> None:
                self._events.put(WakeEvent(source="hotkey", label=self.hotkey))

            mapping = {self.hotkey: on_activate}
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
            log.info("hotkey_ready", hotkey=self.hotkey)
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            log.warning("hotkey_unavailable", error=str(exc))

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None

    def wait_for_hotkey(self, timeout: float | None = None) -> WakeEvent | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None


class ActivationMonitor:
    """
    Combines wake-word + hotkey into one wait API.
    Pause wake mic while TTS/STT run (nested-safe) so replies don't tick.
    """

    def __init__(
        self,
        wake: OpenWakeWordProvider | None,
        hotkey: HotkeyActivator | None,
    ) -> None:
        self.wake = wake
        self.hotkey = hotkey

    def start(self) -> None:
        if self.wake:
            self.wake.start()
        if self.hotkey:
            self.hotkey.start()

    def stop(self) -> None:
        if self.wake:
            self.wake.stop()
        if self.hotkey:
            self.hotkey.stop()

    def pause_wake_mic(self) -> None:
        """Release the wake mic for STT without killing the listener thread."""
        if self.wake:
            self.wake.pause()

    def resume_wake_mic(self) -> None:
        if self.wake:
            try:
                if not getattr(self.wake, "_started", False):
                    self.wake.start()
                else:
                    self.wake.resume()
            except Exception as exc:  # noqa: BLE001
                log.warning("wakeword_resume_failed", error=str(exc))

    def wait(self, timeout: float = 0.25) -> WakeEvent | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            slice_t = min(0.1, remaining)
            if self.wake:
                event = self.wake.wait_for_wake(timeout=slice_t / 2)
                if event:
                    return event
            if self.hotkey:
                event = self.hotkey.wait_for_hotkey(timeout=slice_t / 2)
                if event:
                    return event
        return None
