"""Tests for configuration loading."""

from pathlib import Path

from jarvis.config import load_config


def test_load_default_config(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
assistant:
  name: Jarvis
llm:
  provider: ollama
  host: http://localhost:11434
  model: llama3.1
memory:
  path: data/test.db
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    cfg = load_config(cfg_path)
    assert cfg.assistant.name == "Jarvis"
    assert cfg.llm.model == "llama3.1"
    assert cfg.llm.host == "http://localhost:11434"
    assert cfg.permissions.dangerous_actions == "confirm"


def test_env_overrides_model(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm:\n  model: llama3.1\n", encoding="utf-8")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    cfg = load_config(cfg_path)
    assert cfg.llm.model == "llama3.2"
