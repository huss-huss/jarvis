"""JARVIS CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from jarvis import __version__
from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.config import JarvisConfig, load_config
from jarvis.llm.ollama import OllamaProvider
from jarvis.logging import get_logger, setup_logging
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system import build_default_tools
from jarvis.ui.terminal import confirm_yes_no, print_banner

log = get_logger(__name__)


def build_registry(config: JarvisConfig) -> ToolRegistry:
    registry = ToolRegistry()
    enabled = set(config.tools.enabled)
    for tool in build_default_tools():
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
    permissions = PermissionManager(
        config.permissions,
        confirm=confirm or confirm_yes_no,
        voice_style=voice_style,
    )
    tools = build_registry(config)
    orchestrator = AgentOrchestrator(
        llm=llm,
        tools=tools,
        permissions=permissions,
        memory=memory,
        action_log=action_log,
        max_tool_iterations=config.llm.max_tool_iterations,
        conversation_limit=config.memory.conversation_limit,
    )
    return orchestrator, llm


def run_repl(config: JarvisConfig) -> int:
    setup_logging(level=config.logging.level, structured=config.logging.structured)
    orchestrator, llm = create_app(config)

    health = llm.health()
    if not health.ok:
        print_banner(config.llm.model, status="Ollama unavailable")
        print(health.message)
        print("Start Ollama and try again. Core JARVIS stays local — no paid API required.")
        return 1

    print_banner(config.llm.model, status="Ready")
    print("Type a message, or 'exit' / 'quit' to leave. Cost: $0 (local Ollama).")
    print("Tip: python -m jarvis --voice  for spoken mode.")
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

    return 0


def run_voice(config: JarvisConfig) -> int:
    setup_logging(level=config.logging.level, structured=config.logging.structured)

    # Health-check LLM before loading heavy audio models
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
        from jarvis.audio.tts import create_tts
        from jarvis.audio.vad import SileroVAD
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
        voice=config.speech.tts_voice if config.speech.tts == "kokoro" else "Samantha",
    )
    vad = SileroVAD(threshold=config.speech.vad_threshold)
    mic = Microphone(sample_rate=config.speech.sample_rate)

    def listen_for_confirm() -> str:
        """Short listen used only for yes/no permission answers."""
        audio = mic.record_until_silence(
            vad,
            max_seconds=6.0,
            silence_seconds=0.8,
            pre_roll_seconds=0.3,
        )
        if audio.samples.size == 0:
            return ""
        return stt.transcribe(audio).text.strip()

    voice_confirm = make_voice_confirm(tts, listen_for_confirm)
    orchestrator, llm = create_app(config, confirm=voice_confirm, voice_style=True)

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

    print_banner(config.llm.model, status="Voice Ready")
    print("Press Enter to talk · type text anytime · 'exit' to quit")
    print(f"STT: whisper.cpp ({config.speech.stt_model}) · TTS: {config.speech.tts}")
    print("Dangerous actions: Jarvis asks by voice (say yes/no). Closing apps: no confirm.")
    print()

    while True:
        try:
            typed = input("You [Enter=mic / or type]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            session.tts.stop()
            return 0

        if typed.lower() in {"exit", "quit", ":q"}:
            print("Goodbye.")
            session.tts.stop()
            return 0

        if typed:
            user_text = typed
        else:
            try:
                user_text = session.listen_once()
            except Exception as exc:  # noqa: BLE001
                print(f"Mic/STT error: {exc}")
                continue
            if not user_text:
                print("(no speech detected)")
                continue
            print(f"You: {user_text}")

        print("Jarvis: ", end="", flush=True)
        try:
            spoken = session.handle_utterance(
                user_text,
                on_token=lambda token: print(token, end="", flush=True),
            )
        except RuntimeError as exc:
            print(str(exc))
            continue
        except KeyboardInterrupt:
            session.tts.stop()
            print("\n(interrupted)")
            continue

        if spoken and not spoken.endswith("\n"):
            print()
        elif not spoken:
            print("(no response)")
        else:
            print()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS local assistant")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--voice", action="store_true", help="Enable microphone + TTS mode")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    config = load_config(args.config)
    if args.voice or config.speech.enabled:
        return run_voice(config)
    return run_repl(config)


if __name__ == "__main__":
    sys.exit(main())
