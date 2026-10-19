"""Configuration loading for JARVIS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantConfig(BaseModel):
    name: str = "Jarvis"


class LLMConfig(BaseModel):
    provider: Literal["ollama"] = "ollama"
    host: str = "http://localhost:11434"
    model: str = "llama3.1"
    temperature: float = 0.3
    max_tool_iterations: int = 8


class MemoryConfig(BaseModel):
    provider: Literal["sqlite"] = "sqlite"
    path: str = "data/jarvis.db"
    conversation_limit: int = 40
    embeddings: Literal["ollama", "hashing"] = "ollama"
    embedding_model: str = "nomic-embed-text"
    semantic_top_k: int = 5


class PermissionsConfig(BaseModel):
    modification_actions: Literal["confirm", "allow"] = "confirm"
    dangerous_actions: Literal["confirm"] = "confirm"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    structured: bool = True


class SpeechConfig(BaseModel):
    enabled: bool = False
    stt: Literal["whisper_cpp"] = "whisper_cpp"
    stt_model: str = "small"
    language: str = "en"
    tts: Literal["kokoro", "macos_say"] = "macos_say"
    tts_voice: str = "Samantha"
    barge_in: bool = True
    sample_rate: int = 16000
    silence_seconds: float = 1.2
    max_listen_seconds: float = 25.0
    vad_threshold: float = 0.4
    pre_roll_seconds: float = 0.5
    beam_size: int = 5
    fresh_session: bool = True


class WakeWordConfig(BaseModel):
    enabled: bool = True
    phrase: str = "hey_jarvis"
    backend: Literal["openwakeword"] = "openwakeword"
    threshold: float = 0.5
    inference_framework: Literal["onnx"] = "onnx"
    debounce_seconds: float = 2.0
    hotkey: str = "<ctrl>+<alt>+j"
    acknowledge: str = "Yes?"


class ToolsConfig(BaseModel):
    enabled: list[str] = Field(
        default_factory=lambda: [
            "get_current_time",
            "get_system_information",
            "get_battery_status",
            "get_running_apps",
            "open_application",
            "close_application",
            "get_clipboard",
            "set_clipboard",
            "remember_fact",
            "recall_memory",
            "forget_fact",
            "list_memories",
            "list_files",
            "find_file",
            "read_file",
            "create_file",
            "move_file",
            "copy_file",
            "search_files",
            "summarize_file",
            "delete_file",
            "run_command",
            "open_browser",
            "navigate_browser",
            "get_page_text",
            "click_browser",
            "type_browser",
            "close_browser",
            "ingest_document",
            "ingest_folder",
            "search_docs",
            "list_ingested",
            "switch_project",
            "list_projects",
            "create_reminder",
            "list_reminders",
            "cancel_reminder",
            "create_task",
            "list_tasks",
            "complete_task",
            "add_calendar_event",
            "list_calendar",
            "get_briefing",
            "list_jobs",
            "run_job",
            "set_job_enabled",
            "mcp_status",
        ]
    )


class FilesConfig(BaseModel):
    roots: list[str] = Field(
        default_factory=lambda: [
            ".",
            "~/Desktop",
            "~/Documents",
            "~/Downloads",
            "~/Desktop/Work",
        ]
    )
    max_read_bytes: int = 200_000


class TerminalConfig(BaseModel):
    enabled: bool = True
    cwd: str = "~"
    timeout_seconds: float = 30.0
    allowlist: list[str] = Field(default_factory=list)  # empty → built-in default


class BrowserConfig(BaseModel):
    enabled: bool = True
    headless: bool = True


class RagConfig(BaseModel):
    enabled: bool = True
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 5
    default_project: str = "jarvis"


class ProductivityConfig(BaseModel):
    enabled: bool = True
    timezone: str = "local"
    reminder_poll_seconds: float = 2.0


class ProactiveConfig(BaseModel):
    enabled: bool = True
    morning_briefing_enabled: bool = True
    morning_briefing_hour: int = 8
    morning_briefing_minute: int = 0
    project_monitor_enabled: bool = True
    project_monitor_path: str = "."
    project_monitor_interval_minutes: int = 60
    job_poll_seconds: float = 5.0
    mcp_enabled: bool = False


class UiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8742
    open_browser: bool = True


class JarvisConfig(BaseModel):
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    files: FilesConfig = Field(default_factory=FilesConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    productivity: ProductivityConfig = Field(default_factory=ProductivityConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    ui: UiConfig = Field(default_factory=UiConfig)


class EnvOverrides(BaseSettings):
    """Environment overrides (never point at paid cloud by default)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_host: str | None = None
    ollama_model: str | None = None
    jarvis_config: str | None = None
    jarvis_log_level: str | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def load_config(config_path: str | Path | None = None) -> JarvisConfig:
    """Load config.yaml and apply env overrides."""
    env = EnvOverrides()
    root = _project_root()

    path = Path(config_path or env.jarvis_config or os.environ.get("JARVIS_CONFIG", "config.yaml"))
    if not path.is_absolute():
        path = root / path

    cfg = JarvisConfig.model_validate(_load_yaml(path))

    if env.ollama_host:
        cfg.llm.host = env.ollama_host
    if env.ollama_model:
        cfg.llm.model = env.ollama_model
    if env.jarvis_log_level:
        cfg.logging.level = env.jarvis_log_level

    # Resolve DB path relative to project root when not absolute
    mem_path = Path(cfg.memory.path)
    if not mem_path.is_absolute():
        cfg.memory.path = str(root / mem_path)

    return cfg


def resolve_file_roots(config: JarvisConfig, project_root: Path | None = None) -> list[Path]:
    from jarvis.tools.paths import expand_root

    root = project_root or _project_root()
    return [expand_root(item, project_root=root) for item in config.files.roots]


def resolve_terminal_cwd(config: JarvisConfig, project_root: Path | None = None) -> Path:
    from jarvis.tools.paths import expand_root

    root = project_root or _project_root()
    return expand_root(config.terminal.cwd, project_root=root)


def resolve_project_monitor_path(config: JarvisConfig, project_root: Path | None = None) -> Path:
    from jarvis.tools.paths import expand_root

    root = project_root or _project_root()
    return expand_root(config.proactive.project_monitor_path, project_root=root)
