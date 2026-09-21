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
    tts: Literal["kokoro", "macos_say"] = "kokoro"
    tts_voice: str = "af_heart"
    barge_in: bool = True
    sample_rate: int = 16000
    silence_seconds: float = 1.2
    max_listen_seconds: float = 25.0
    vad_threshold: float = 0.4
    pre_roll_seconds: float = 0.5
    beam_size: int = 5
    fresh_session: bool = True


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
        ]
    )


class JarvisConfig(BaseModel):
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)


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
