"""Local desktop UI server (FastAPI + SSE)."""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.config import JarvisConfig
from jarvis.logging import get_logger
from jarvis.ui.session import DesktopSession

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_desktop_app(
    session: DesktopSession,
    config: JarvisConfig,
):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field

    subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
    loop_holder: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}
    sub_lock = threading.Lock()

    def broadcast(message: dict[str, Any]) -> None:
        loop = loop_holder["loop"]
        if loop is None:
            return

        def _fanout() -> None:
            with sub_lock:
                targets = list(subscribers)
            for q in targets:
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        q.put_nowait(message)
                    except Exception:  # noqa: BLE001
                        pass

        try:
            loop.call_soon_threadsafe(_fanout)
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_schedule_broadcast_failed", error=str(exc))

    session.set_broadcast(broadcast)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        yield
        loop_holder["loop"] = None

    app = FastAPI(title="Jarvis Desktop", lifespan=lifespan)

    class ChatBody(BaseModel):
        content: str = Field(min_length=1)

    class ConfirmBody(BaseModel):
        allowed: bool

    def _safe_snapshot() -> dict[str, Any]:
        try:
            return session.snapshot()
        except Exception as exc:  # noqa: BLE001
            log.warning("ui_snapshot_failed", error=str(exc))
            return {
                "status": session.status,
                "busy": False,
                "assistant": config.assistant.name,
                "model": config.llm.model,
                "capabilities": {
                    "voice": session.voice_enabled,
                    "memory": True,
                    "rag": config.rag.enabled,
                    "productivity": config.productivity.enabled,
                    "proactive": config.proactive.enabled,
                    "browser": config.browser.enabled,
                    "terminal": config.terminal.enabled,
                },
                "history": [],
                "reminders": [],
                "tasks": [],
                "jobs": [],
                "error": str(exc),
            }

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "status": session.status,
            "voice": session.voice_enabled,
        }

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        return await asyncio.to_thread(_safe_snapshot)

    @app.post("/api/chat")
    async def chat_http(body: ChatBody) -> dict[str, str]:
        threading.Thread(
            target=session.handle_chat,
            args=(body.content,),
            kwargs={"speak": session.voice_enabled},
            name="jarvis-ui-chat-http",
            daemon=True,
        ).start()
        return {"ok": "true"}

    @app.post("/api/listen")
    async def listen_http() -> JSONResponse:
        if not session.voice_enabled:
            return JSONResponse(
                {"ok": False, "error": "Voice still loading — wait a moment."},
                status_code=503,
            )
        threading.Thread(
            target=session.listen_and_chat,
            name="jarvis-ui-listen-http",
            daemon=True,
        ).start()
        return JSONResponse({"ok": True})

    @app.post("/api/confirm")
    async def confirm_http(body: ConfirmBody) -> dict[str, str]:
        session.resolve_confirm(allowed=body.allowed)
        return {"ok": "true"}

    @app.post("/api/stop")
    async def stop_http() -> dict[str, str]:
        session.stop_speaking()
        return {"ok": "true"}

    @app.post("/api/new-chat")
    async def new_chat() -> dict[str, str]:
        await asyncio.to_thread(session.new_conversation)
        return {"ok": "true"}

    @app.get("/api/events")
    async def event_stream() -> StreamingResponse:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        with sub_lock:
            subscribers.add(queue)

        async def gen() -> AsyncIterator[str]:
            try:
                hello = await asyncio.to_thread(_safe_snapshot)
                hello = {"type": "hello", **hello}
                yield f"data: {json.dumps(hello, ensure_ascii=False)}\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    except TimeoutError:
                        yield ": ping\n\n"
            finally:
                with sub_lock:
                    subscribers.discard(queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def run_desktop_ui(
    orchestrator: AgentOrchestrator,
    config: JarvisConfig,
    *,
    session: DesktopSession | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> int:
    try:
        import uvicorn
    except ImportError:
        print("Desktop UI dependencies missing.")
        print("Install with: uv sync --extra ui")
        return 1

    if session is None:
        session = DesktopSession(orchestrator, config)
    orchestrator.permissions._confirm = session.confirm  # noqa: SLF001
    orchestrator.permissions.voice_style = session.voice_enabled

    rem = getattr(orchestrator, "reminders", None)
    jobs = getattr(orchestrator, "jobs", None)
    if rem is not None:
        rem.notifier = _UiAwareNotifier(rem.notifier, session)
    if jobs is not None:
        jobs.notifier = _UiAwareNotifier(jobs.notifier, session)

    app = create_desktop_app(session, config)
    host = config.ui.host
    port = config.ui.port
    url = f"http://{host}:{port}"

    print(f"Jarvis desktop UI → {url}")
    if session.voice_enabled:
        print("Voice ready: Talk · Ctrl+Alt+J")
    else:
        print("Voice loading in background (UI is already open)…")
    print("Keep this process running. Ctrl+C to stop.")

    if config.ui.open_browser:

        def _open() -> None:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Timer(0.8, _open).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        if on_shutdown:
            on_shutdown()
    return 0


class _UiAwareNotifier:
    """Fan notifications to the existing provider and the desktop UI."""

    def __init__(self, inner, session: DesktopSession) -> None:
        self._inner = inner
        self._session = session

    def notify(self, title: str, message: str) -> None:
        try:
            self._inner.notify(title, message)
        finally:
            self._session.notify(title, message)
