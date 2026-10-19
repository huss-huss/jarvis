"""Desktop UI session — bridges WebSocket clients to the orchestrator."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.audio.session import VoiceSession, looks_garbled
from jarvis.config import JarvisConfig
from jarvis.logging import get_logger
from jarvis.permissions.voice_confirm import is_affirmative

log = get_logger(__name__)

BroadcastFn = Callable[[dict[str, Any]], None]


@dataclass
class _PendingConfirm:
    prompt: str
    event: threading.Event = field(default_factory=threading.Event)
    allowed: bool = False


class DesktopSession:
    """Thread-safe hub for chat turns, status, tools, voice, and permission prompts."""

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        config: JarvisConfig,
        *,
        broadcast: BroadcastFn | None = None,
        voice: VoiceSession | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = config
        self.voice = voice
        self._broadcast = broadcast or (lambda _msg: None)
        self._lock = threading.RLock()
        self._busy = False
        self.status = "idle"
        self._pending: _PendingConfirm | None = None
        self._confirm_timeout = 120.0
        self._pause_wake: Callable[[], None] | None = None
        self._resume_wake: Callable[[], None] | None = None

    def set_broadcast(self, broadcast: BroadcastFn) -> None:
        self._broadcast = broadcast

    def set_voice(self, voice: VoiceSession | None) -> None:
        self.voice = voice

    def set_wake_guards(
        self,
        pause: Callable[[], None] | None,
        resume: Callable[[], None] | None,
    ) -> None:
        self._pause_wake = pause
        self._resume_wake = resume

    @property
    def voice_enabled(self) -> bool:
        return self.voice is not None

    def confirm(self, prompt: str) -> bool:
        """Blocking confirm — UI modal, plus spoken yes/no when voice is on."""
        request_id = uuid.uuid4().hex[:12]
        pending = _PendingConfirm(prompt=prompt)
        with self._lock:
            self._pending = pending
        self._emit(
            {
                "type": "confirm_request",
                "id": request_id,
                "prompt": prompt,
            }
        )
        self._set_status("awaiting_confirm")

        if self.voice is not None:
            threading.Thread(
                target=self._voice_confirm_side,
                args=(prompt,),
                name="jarvis-ui-voice-confirm",
                daemon=True,
            ).start()

        ok = pending.event.wait(timeout=self._confirm_timeout)
        with self._lock:
            self._pending = None
        if not ok:
            log.warning("ui_confirm_timeout", prompt=prompt[:120])
            self._set_status("idle")
            return False
        return pending.allowed

    def _voice_confirm_side(self, prompt: str) -> None:
        assert self.voice is not None
        try:
            self._pause_wake_safe()
            self.voice.tts.speak(prompt)
            if self._pending is None or self._pending.event.is_set():
                return
            heard = self.voice.listen_once()
            decision = is_affirmative(heard)
            if decision is None:
                self.voice.tts.speak("Please say yes or no.")
                heard = self.voice.listen_once()
                decision = is_affirmative(heard)
            if decision is not None:
                self.resolve_confirm(allowed=decision)
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_voice_confirm_failed", error=str(exc))
        finally:
            self._resume_wake_safe()

    def resolve_confirm(self, *, allowed: bool) -> bool:
        with self._lock:
            pending = self._pending
            if pending is None:
                return False
            pending.allowed = allowed
            pending.event.set()
        return True

    def snapshot(self) -> dict[str, Any]:
        reminders: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        rem = getattr(self.orchestrator, "reminders", None)
        job_runner = getattr(self.orchestrator, "jobs", None)
        try:
            if rem is not None:
                for item in rem.list(status="pending")[:12]:
                    reminders.append(
                        {
                            "id": item.id,
                            "message": item.message,
                            "scheduled_at": item.scheduled_at,
                            "status": item.status,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_reminders_snapshot_failed", error=str(exc))
        try:
            if rem is not None and hasattr(rem.store, "list_tasks"):
                for item in rem.store.list_tasks(status="open", limit=12):
                    tasks.append(
                        {
                            "id": item.id,
                            "title": item.title,
                            "due_at": item.due_at,
                            "priority": item.priority,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_tasks_snapshot_failed", error=str(exc))
        try:
            if job_runner is not None:
                jobs = job_runner.list_jobs()
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_jobs_snapshot_failed", error=str(exc))

        history = []
        for msg in self.orchestrator.memory.recent_messages(limit=40):
            content = msg.content or ""
            # Hide internal tool-trail notes from the visible transcript
            if content.startswith("[tool ") or content.startswith("(using tools:"):
                continue
            history.append({"role": msg.role.value, "content": content})

        return {
            "status": self.status,
            "busy": self._busy,
            "assistant": self.config.assistant.name,
            "model": self.config.llm.model,
            "capabilities": {
                "memory": self.orchestrator.long_term is not None,
                "rag": self.orchestrator.rag is not None,
                "productivity": self.config.productivity.enabled,
                "proactive": self.config.proactive.enabled,
                "browser": self.config.browser.enabled,
                "terminal": self.config.terminal.enabled,
                "voice": self.voice_enabled,
            },
            "rag_project": (
                self.orchestrator.rag.active_project() if self.orchestrator.rag else None
            ),
            "history": history,
            "reminders": reminders,
            "tasks": tasks,
            "jobs": jobs,
            "pending_confirm": (
                {"prompt": self._pending.prompt} if self._pending is not None else None
            ),
            "wake_hint": (
                "Tap Talk or press Ctrl+Alt+J"
                if self.voice_enabled
                else "Voice loading…"
            ),
        }

    def new_conversation(self) -> None:
        self.orchestrator.memory.new_conversation()
        self._emit({"type": "history", "messages": []})
        self._set_status("idle")

    def listen_and_chat(self) -> None:
        """Push-to-talk from the UI / hotkey."""
        if self.voice is None:
            self._emit({"type": "error", "message": "Voice is not available in this session."})
            return
        with self._lock:
            if self._busy:
                self._emit(
                    {
                        "type": "error",
                        "message": "Jarvis is still working on the previous request.",
                    }
                )
                return
            self._busy = True

        text = ""
        try:
            self._pause_wake_safe()
            time.sleep(0.15)  # let PortAudio fully release before opening STT mic
            self._set_status("listening")
            self._emit({"type": "listening"})
            text = self.voice.listen_once()
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_listen_failed", error=str(exc))
            self._emit({"type": "error", "message": f"Mic/STT error: {exc}"})
            with self._lock:
                self._busy = False
            self._set_status("idle")
            self._resume_wake_safe()
            return

        with self._lock:
            self._busy = False

        if not text.strip():
            self._emit({"type": "error", "message": "No speech detected — try again."})
            self._set_status("idle")
            self._resume_wake_safe()
            return

        if looks_garbled(text):
            msg = "Sorry, I didn't catch that. Please say it again."
            self._emit({"type": "user", "content": text})
            self._emit({"type": "token", "content": msg})
            self._emit({"type": "done", "text": msg, "tools": []})
            self._set_status("speaking")
            try:
                self.voice.speak_response(msg)
            finally:
                self._set_status("idle")
                self._resume_wake_safe()
            return

        # handle_chat will pause/resume wake around TTS
        self._resume_wake_safe()
        self.handle_chat(text, speak=True)

    def handle_chat(self, text: str, *, speak: bool = False) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        with self._lock:
            if self._busy:
                self._emit(
                    {
                        "type": "error",
                        "message": "Jarvis is still working on the previous request.",
                    }
                )
                return
            self._busy = True

        should_speak = speak and self.voice is not None
        self._emit({"type": "user", "content": cleaned})
        self._set_status("thinking")

        def on_token(token: str) -> None:
            self._emit({"type": "token", "content": token})

        def on_event(kind: str, payload: dict[str, Any]) -> None:
            if kind == "status":
                self._set_status(str(payload.get("status") or "thinking"))
            elif kind == "tool":
                self._emit({"type": "tool", **payload})
            elif kind == "assistant_reset":
                self._emit({"type": "assistant_reset"})

        try:
            if should_speak:
                self._pause_wake_safe()
            result = self.orchestrator.handle_user_message(
                cleaned,
                on_token=on_token,
                on_event=on_event,
            )
            self._emit(
                {
                    "type": "done",
                    "text": result.text,
                    "tools": result.tool_names,
                }
            )
            if should_speak and result.text:
                self._set_status("speaking")
                assert self.voice is not None
                self.voice.speak_response(result.text)
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_chat_failed", error=str(exc))
            self._emit({"type": "error", "message": str(exc)})
        finally:
            with self._lock:
                self._busy = False
            self._set_status("idle")
            if should_speak:
                self._resume_wake_safe()
            snap = self.snapshot()
            self._emit(
                {
                    "type": "panels",
                    "reminders": snap["reminders"],
                    "tasks": snap["tasks"],
                    "jobs": snap["jobs"],
                }
            )

    def stop_speaking(self) -> None:
        """Interrupt TTS immediately (Stop button)."""
        if self.voice is not None:
            try:
                self.voice.tts.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("ui_stop_speak_failed", error=str(exc))
        if self.status == "speaking":
            self._set_status("idle")
        self._emit({"type": "stopped"})

    def notify(self, title: str, message: str) -> None:
        self._emit({"type": "notification", "title": title, "message": message})
        # Speak reminders only — not noisy startup job banners
        if self.voice is None or not message:
            return
        if "reminder" not in (title or "").lower():
            return
        try:
            self.voice.tts.speak(f"{title}. {message}")
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_notify_speak_failed", error=str(exc))

    def _set_status(self, status: str) -> None:
        self.status = status
        self._emit({"type": "status", "status": status})

    def _emit(self, message: dict[str, Any]) -> None:
        try:
            self._broadcast(message)
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_broadcast_failed", error=str(exc))

    def _pause_wake_safe(self) -> None:
        if self._pause_wake:
            try:
                self._pause_wake()
            except Exception:  # noqa: BLE001
                pass

    def _resume_wake_safe(self) -> None:
        if self._resume_wake:
            try:
                self._resume_wake()
            except Exception:  # noqa: BLE001
                pass
