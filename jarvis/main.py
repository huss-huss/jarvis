"""JARVIS CLI entrypoint."""

from __future__ import annotations

import argparse
import select
import sys
import threading
from typing import Any

from jarvis import __version__
from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.config import (
    JarvisConfig,
    load_config,
    resolve_file_roots,
    resolve_project_monitor_path,
    resolve_terminal_cwd,
)
from jarvis.llm.ollama import OllamaProvider
from jarvis.logging import get_logger, setup_logging
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.memory.long_term import LongTermMemory
from jarvis.permissions.manager import PermissionManager
from jarvis.rag.embeddings import create_embeddings
from jarvis.browser import create_browser
from jarvis.tools.browser import build_browser_tools
from jarvis.tools.files import build_file_tools
from jarvis.tools.memory import build_memory_tools
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import build_default_tools
from jarvis.tools.terminal import build_terminal_tools
from jarvis.ui.terminal import confirm_yes_no, print_banner

log = get_logger(__name__)


def build_registry(
    config: JarvisConfig,
    long_term: LongTermMemory | None = None,
    *,
    browser=None,
    rag=None,
    productivity_tools: list | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    enabled = set(config.tools.enabled)
    for tool in build_default_tools():
        if tool.name in enabled:
            registry.register(tool)
    if long_term is not None:
        for tool in build_memory_tools(long_term):
            if tool.name in enabled:
                registry.register(tool)

    roots = resolve_file_roots(config)
    for tool in build_file_tools(roots, max_read_bytes=config.files.max_read_bytes):
        if tool.name in enabled:
            registry.register(tool)

    if config.terminal.enabled:
        for tool in build_terminal_tools(
            cwd=resolve_terminal_cwd(config),
            allowlist=config.terminal.allowlist or None,
            timeout_seconds=config.terminal.timeout_seconds,
        ):
            if tool.name in enabled:
                registry.register(tool)

    if browser is not None:
        for tool in build_browser_tools(browser):
            if tool.name in enabled:
                registry.register(tool)

    if rag is not None:
        from jarvis.tools.rag import build_rag_tools

        for tool in build_rag_tools(rag):
            if tool.name in enabled:
                registry.register(tool)

    if productivity_tools:
        for tool in productivity_tools:
            if tool.name in enabled:
                registry.register(tool)
    return registry


def create_app(
    config: JarvisConfig,
    *,
    confirm=None,
    voice_style: bool = False,
) -> tuple[AgentOrchestrator, OllamaProvider]:
    llm = OllamaProvider(
        host=config.llm.host,
        model=config.llm.model,
        temperature=config.llm.temperature,
    )
    memory = ConversationStore(config.memory.path)
    action_log = ActionLog(config.memory.path)
    embeddings = create_embeddings(
        provider=config.memory.embeddings,
        host=config.llm.host,
        model=config.memory.embedding_model,
    )
    long_term = LongTermMemory(config.memory.path, embeddings)
    permissions = PermissionManager(
        config.permissions,
        confirm=confirm or confirm_yes_no,
        voice_style=voice_style,
    )
    browser = create_browser(headless=config.browser.headless, enabled=config.browser.enabled)
    rag = None
    if config.rag.enabled:
        from jarvis.rag.service import RagService

        rag = RagService(
            config.memory.path,
            embeddings,
            resolve_file_roots(config),
            chunk_size=config.rag.chunk_size,
            chunk_overlap=config.rag.chunk_overlap,
            top_k=config.rag.top_k,
        )
        if config.rag.default_project:
            rag.switch_project(config.rag.default_project)

    productivity_tools = None
    reminder_service = None
    job_runner = None
    if config.productivity.enabled:
        from jarvis.jobs.briefing import BriefingService
        from jarvis.jobs.runner import JobRunner
        from jarvis.productivity.calendar import CalendarService
        from jarvis.productivity.tasks import TaskService
        from jarvis.scheduler.clock import Clock
        from jarvis.scheduler.notifications import create_notifier
        from jarvis.scheduler.service import ReminderService
        from jarvis.scheduler.store import ProductivityStore
        from jarvis.tools.productivity import build_productivity_tools

        clock = Clock(tz_name=config.productivity.timezone)
        notifier = create_notifier(prefer_macos=True)
        store = ProductivityStore(config.memory.path)
        reminder_service = ReminderService(
            store,
            notifier,
            clock,
            poll_seconds=config.productivity.reminder_poll_seconds,
        )
        tasks = TaskService(store, clock)
        calendar = CalendarService(store, clock)
        briefing = BriefingService(
            clock=clock,
            tasks=tasks,
            calendar=calendar,
            reminders=reminder_service,
            project_path=resolve_project_monitor_path(config),
        )
        job_runner = JobRunner(
            config.memory.path,
            clock,
            notifier,
            briefing=briefing,
            poll_seconds=config.proactive.job_poll_seconds,
        )
        if config.proactive.enabled:
            job_runner.register_defaults(
                morning_hour=config.proactive.morning_briefing_hour,
                morning_minute=config.proactive.morning_briefing_minute,
                project_interval_minutes=config.proactive.project_monitor_interval_minutes,
                morning_enabled=config.proactive.morning_briefing_enabled,
                project_enabled=config.proactive.project_monitor_enabled,
            )
        productivity_tools = build_productivity_tools(
            reminders=reminder_service,
            tasks=tasks,
            calendar=calendar,
            briefing=briefing,
            runner=job_runner,
            mcp_enabled=config.proactive.mcp_enabled,
        )

    tools = build_registry(
        config,
        long_term=long_term,
        browser=browser,
        rag=rag,
        productivity_tools=productivity_tools,
    )
    orchestrator = AgentOrchestrator(
        llm=llm,
        tools=tools,
        permissions=permissions,
        memory=memory,
        action_log=action_log,
        long_term=long_term,
        rag=rag,
        max_tool_iterations=config.llm.max_tool_iterations,
        conversation_limit=config.memory.conversation_limit,
        memory_top_k=config.memory.semantic_top_k,
        rag_top_k=config.rag.top_k,
    )
    orchestrator.reminders = reminder_service  # type: ignore[attr-defined]
    orchestrator.jobs = job_runner  # type: ignore[attr-defined]
    return orchestrator, llm


def _start_background_services(orchestrator: AgentOrchestrator, config: JarvisConfig) -> None:
    reminders = getattr(orchestrator, "reminders", None)
    jobs = getattr(orchestrator, "jobs", None)
    if reminders is not None and config.productivity.enabled:
        reminders.start()
    if jobs is not None and config.proactive.enabled:
        jobs.start()


def _stop_background_services(orchestrator: AgentOrchestrator) -> None:
    reminders = getattr(orchestrator, "reminders", None)
    jobs = getattr(orchestrator, "jobs", None)
    if reminders is not None:
        reminders.stop()
    if jobs is not None:
        jobs.stop()


def run_repl(config: JarvisConfig) -> int:
    setup_logging(level=config.logging.level, structured=config.logging.structured)
    orchestrator, llm = create_app(config)

    health = llm.health()
    if not health.ok:
        print_banner(config.llm.model, status="Ollama unavailable")
        print(health.message)
        print("Start Ollama and try again. Core JARVIS stays local — no paid API required.")
        return 1

    _start_background_services(orchestrator, config)
    try:
        print_banner(config.llm.model, status="Ready")
        print("Type a message, or 'exit' / 'quit' to leave. Cost: $0 (local Ollama).")
        print("Tip: python -m jarvis --voice  for spoken mode.")
        if orchestrator.long_term:
            ok, msg = orchestrator.long_term.embeddings.health()
            using_fallback = getattr(orchestrator.long_term.embeddings, "_using_fallback", False)
            if ok and not using_fallback:
                print(f"Memory: long-term + semantic ({msg})")
            else:
                print(
                    f"Memory: long-term on (embeddings fallback — "
                    f"ollama pull {config.memory.embedding_model})"
                )
        if orchestrator.rag:
            print(f"RAG: on (project={orchestrator.rag.active_project()}, top_k={config.rag.top_k})")
        if config.productivity.enabled:
            print("Productivity: reminders + tasks + local calendar")
        if config.proactive.enabled:
            print(
                f"Proactive: briefing @{config.proactive.morning_briefing_hour:02d}:"
                f"{config.proactive.morning_briefing_minute:02d}, "
                f"MCP={'on' if config.proactive.mcp_enabled else 'off'}"
            )
        print()

        while True:
            try:
                user_text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                return 0

            if not user_text:
                continue
            if user_text.lower() in {"exit", "quit", ":q"}:
                print("Goodbye.")
                return 0

            print("Jarvis: ", end="", flush=True)
            try:
                result = orchestrator.handle_user_message(
                    user_text,
                    on_token=lambda token: print(token, end="", flush=True),
                )
            except RuntimeError as exc:
                print(str(exc))
                continue
            except KeyboardInterrupt:
                print("\n(interrupted)")
                continue

            if result.text and not result.text.endswith("\n"):
                print()
            elif not result.text:
                print("(no response)")
            else:
                print()
    finally:
        _stop_background_services(orchestrator)

    return 0


def run_voice(config: JarvisConfig) -> int:
    setup_logging(level=config.logging.level, structured=config.logging.structured)

    probe = OllamaProvider(host=config.llm.host, model=config.llm.model)
    health = probe.health()
    if not health.ok:
        print_banner(config.llm.model, status="Ollama unavailable")
        print(health.message)
        return 1

    print("Loading voice stack (local STT/TTS — still $0)…")
    try:
        from jarvis.audio.microphone import Microphone
        from jarvis.audio.session import VoiceSession
        from jarvis.audio.stt import WhisperCppSTT
        from jarvis.audio.tts import AudioExclusiveTTS, create_tts
        from jarvis.audio.vad import SileroVAD
        from jarvis.audio.wakeword import ActivationMonitor, HotkeyActivator, OpenWakeWordProvider
        from jarvis.permissions.voice_confirm import make_voice_confirm
    except ImportError as exc:
        print(f"Voice dependencies missing: {exc}")
        print('Install with: uv sync --extra voice')
        return 1

    stt = WhisperCppSTT(
        model_name=config.speech.stt_model,
        language=config.speech.language,
        beam_size=config.speech.beam_size,
    )
    tts = create_tts(
        config.speech.tts,
        voice=config.speech.tts_voice,
    )
    vad = SileroVAD(threshold=config.speech.vad_threshold)
    mic = Microphone(sample_rate=config.speech.sample_rate)

    # --- Phase 3: wake word + hotkey (before voice confirm / session so TTS can guard mic) ---
    wake_provider = None
    hotkey = HotkeyActivator(config.wake_word.hotkey)
    if config.wake_word.enabled:
        try:
            wake_provider = OpenWakeWordProvider(
                threshold=config.wake_word.threshold,
                debounce_seconds=config.wake_word.debounce_seconds,
                inference_framework=config.wake_word.inference_framework,
            )
            wake_provider._ensure_model()
        except Exception as exc:  # noqa: BLE001
            print(f"Wake word unavailable ({exc}). Hotkey + Enter still work.")
            wake_provider = None

    monitor = ActivationMonitor(wake_provider, hotkey)
    # Every spoken reply (Yes?, answers, confirms) must release the wake mic first.
    tts = AudioExclusiveTTS(tts, monitor.pause_wake_mic, monitor.resume_wake_mic)

    def listen_for_confirm() -> str:
        monitor.pause_wake_mic()
        try:
            audio = mic.record_until_silence(
                vad,
                max_seconds=6.0,
                silence_seconds=0.8,
                pre_roll_seconds=0.3,
            )
            if audio.samples.size == 0:
                return ""
            return stt.transcribe(audio).text.strip()
        finally:
            monitor.resume_wake_mic()

    voice_confirm = make_voice_confirm(tts, listen_for_confirm)
    orchestrator, _llm = create_app(config, confirm=voice_confirm, voice_style=True)
    _start_background_services(orchestrator, config)

    if config.speech.fresh_session:
        orchestrator.memory.new_conversation()

    session = VoiceSession(
        orchestrator,
        stt=stt,
        tts=tts,
        vad=vad,
        microphone=mic,
        barge_in=config.speech.barge_in,
        silence_seconds=config.speech.silence_seconds,
        max_listen_seconds=config.speech.max_listen_seconds,
        pre_roll_seconds=config.speech.pre_roll_seconds,
    )

    monitor.start()

    print_banner(config.llm.model, status="Voice Ready")
    if wake_provider:
        print("Say “Hey Jarvis” · or hotkey Ctrl+Alt+J · or type / Enter")
    else:
        print("Hotkey Ctrl+Alt+J · or type / Enter to talk")
    print(f"STT: whisper.cpp ({config.speech.stt_model}) · TTS: {config.speech.tts}")
    print("Dangerous actions: voice yes/no. Closing apps: no confirm.")
    print("Note: openWakeWord stock models are CC BY-NC-SA (personal use).")
    print()

    def handle_turn(user_text: str) -> None:
        print(f"You: {user_text}")
        print("Jarvis: ", end="", flush=True)
        try:
            spoken = session.handle_utterance(
                user_text,
                on_token=lambda token: print(token, end="", flush=True),
            )
        except RuntimeError as exc:
            print(str(exc))
            return
        except KeyboardInterrupt:
            session.tts.stop()
            print("\n(interrupted)")
            return

        if spoken and not spoken.endswith("\n"):
            print()
        elif not spoken:
            print("(no response)")
        else:
            print()

    def with_exclusive_audio(fn):
        """Pause wake mic for the whole turn — speaking while it is open ticks (ta-ta-ta)."""
        monitor.pause_wake_mic()
        try:
            return fn()
        finally:
            monitor.resume_wake_mic()

    try:
        while True:
            print("Idle… (Hey Jarvis / Ctrl+Alt+J / type then Enter / 'exit')", flush=True)

            activation = None
            typed: str | None = None
            while True:
                activation = monitor.wait(timeout=0.2)
                if activation:
                    break
                # Non-blocking stdin: type a command or press Enter to push-to-talk
                if select.select([sys.stdin], [], [], 0.0)[0]:
                    typed = sys.stdin.readline().strip()
                    break

            if typed is not None:
                if typed.lower() in {"exit", "quit", ":q"}:
                    print("Goodbye.")
                    return 0
                if typed:

                    def _typed_turn() -> None:
                        handle_turn(typed)

                    with_exclusive_audio(_typed_turn)
                    continue

                def _enter_ptt() -> None:
                    try:
                        user_text = session.listen_once()
                    except Exception as exc:  # noqa: BLE001
                        print(f"Mic/STT error: {exc}")
                        return
                    if not user_text:
                        print("(no speech detected)")
                        return
                    handle_turn(user_text)

                with_exclusive_audio(_enter_ptt)
                continue

            if activation:
                src = activation.source
                score_bit = f" score={activation.score:.2f}" if activation.score is not None else ""
                print(f"[activated: {src}{score_bit}]")

                def _wake_turn() -> None:
                    ack = config.wake_word.acknowledge
                    if ack:
                        print(f"Jarvis: {ack}")
                        session.tts.speak(ack)
                    try:
                        user_text = session.listen_once()
                    except Exception as exc:  # noqa: BLE001
                        print(f"Mic/STT error: {exc}")
                        return
                    if not user_text:
                        print("(no speech detected)")
                        return
                    handle_turn(user_text)

                with_exclusive_audio(_wake_turn)

    except KeyboardInterrupt:
        print("\nGoodbye.")
        return 0
    finally:
        _stop_background_services(orchestrator)
        monitor.stop()
        session.tts.stop()


def run_ui(config: JarvisConfig, *, enable_voice: bool = True) -> int:
    setup_logging(level=config.logging.level, structured=config.logging.structured)
    from jarvis.ui.desktop import run_desktop_ui
    from jarvis.ui.session import DesktopSession

    wake_stop = threading.Event()
    monitor_holder: dict[str, Any] = {"monitor": None, "voice": None}

    orchestrator, llm = create_app(config, voice_style=enable_voice)
    health = llm.health()
    if not health.ok:
        print_banner(config.llm.model, status="Ollama unavailable")
        print(health.message)
        return 1

    if config.speech.fresh_session:
        orchestrator.memory.new_conversation()

    session = DesktopSession(orchestrator, config, voice=None)
    _start_background_services(orchestrator, config)

    def _attach_voice() -> None:
        if not enable_voice:
            return
        try:
            from jarvis.audio.microphone import Microphone
            from jarvis.audio.session import VoiceSession
            from jarvis.audio.stt import WhisperCppSTT
            from jarvis.audio.tts import AudioExclusiveTTS, create_tts
            from jarvis.audio.vad import SileroVAD
            from jarvis.audio.wakeword import ActivationMonitor, HotkeyActivator
        except ImportError as exc:
            print(f"Voice dependencies missing ({exc}). UI text-only.")
            print("Install with: uv sync --extra voice --extra ui")
            session._emit(  # noqa: SLF001
                {
                    "type": "error",
                    "message": "Voice packages missing — install --extra voice.",
                }
            )
            return

        print("Loading voice stack in background (UI is already open)…")
        try:
            stt = WhisperCppSTT(
                model_name=config.speech.stt_model,
                language=config.speech.language,
                beam_size=config.speech.beam_size,
            )
            tts = create_tts(config.speech.tts, voice=config.speech.tts_voice)
            vad = SileroVAD(threshold=config.speech.vad_threshold)
            mic = Microphone(sample_rate=config.speech.sample_rate)

            # Desktop UI: Talk + hotkey only. Continuous openWakeWord holds the mic and
            # races STT on macOS (PortAudio abort → whole Python process dies).
            wake_provider = None
            hotkey = HotkeyActivator(config.wake_word.hotkey)
            monitor = ActivationMonitor(wake_provider, hotkey)
            tts = AudioExclusiveTTS(tts, monitor.pause_wake_mic, monitor.resume_wake_mic)
            voice_session = VoiceSession(
                orchestrator,
                stt=stt,
                tts=tts,
                vad=vad,
                microphone=mic,
                barge_in=config.speech.barge_in,
                silence_seconds=config.speech.silence_seconds,
                max_listen_seconds=config.speech.max_listen_seconds,
                pre_roll_seconds=config.speech.pre_roll_seconds,
            )
            session.set_voice(voice_session)
            session.set_wake_guards(monitor.pause_wake_mic, monitor.resume_wake_mic)
            orchestrator.permissions.voice_style = True
            monitor.start()
            monitor_holder["monitor"] = monitor
            monitor_holder["voice"] = voice_session

            def _wake_loop() -> None:
                while not wake_stop.is_set():
                    activation = monitor.wait(timeout=0.25)
                    if activation is None:
                        continue
                    if session.status != "idle" or getattr(session, "_busy", False):
                        continue
                    ack = config.wake_word.acknowledge
                    if ack:
                        session._emit({"type": "status", "status": "listening"})  # noqa: SLF001
                        try:
                            voice_session.tts.speak(ack)
                        except Exception:  # noqa: BLE001
                            pass
                    session.listen_and_chat()

            threading.Thread(target=_wake_loop, name="jarvis-ui-wake", daemon=True).start()
            snap = session.snapshot()
            # Override hint — wake word intentionally off in UI
            snap_caps = snap["capabilities"]
            session._emit(  # noqa: SLF001
                {
                    "type": "voice_ready",
                    "capabilities": snap_caps,
                    "wake_hint": "Tap Talk or press Ctrl+Alt+J (spoken replies on)",
                }
            )
            print("Voice ready: Talk button · Ctrl+Alt+J (wake-word mic disabled in UI for stability)")
        except Exception as exc:  # noqa: BLE001
            print(f"Voice failed to load: {exc}")
            session._emit({"type": "error", "message": f"Voice failed: {exc}"})  # noqa: SLF001

    if enable_voice:
        threading.Thread(target=_attach_voice, name="jarvis-ui-voice-load", daemon=True).start()

    try:
        print_banner(config.llm.model, status="Desktop UI")
        return run_desktop_ui(
            orchestrator,
            config,
            session=session,
            on_shutdown=lambda: _shutdown_ui_voice(
                monitor_holder["monitor"],
                wake_stop,
                monitor_holder["voice"],
            ),
        )
    finally:
        _stop_background_services(orchestrator)
        _shutdown_ui_voice(monitor_holder["monitor"], wake_stop, monitor_holder["voice"])


def _shutdown_ui_voice(monitor, wake_stop: threading.Event, voice_session) -> None:
    wake_stop.set()
    if monitor is not None:
        try:
            monitor.stop()
        except Exception:  # noqa: BLE001
            pass
    if voice_session is not None:
        try:
            voice_session.tts.stop()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS local assistant")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--voice", action="store_true", help="Enable microphone + TTS mode (terminal)")
    parser.add_argument("--ui", action="store_true", help="Open local desktop UI in the browser")
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="With --ui, disable mic/TTS (text-only shell)",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    config = load_config(args.config)
    if args.ui:
        return run_ui(config, enable_voice=not args.no_voice)
    if args.voice or config.speech.enabled:
        return run_voice(config)
    return run_repl(config)


if __name__ == "__main__":
    sys.exit(main())
