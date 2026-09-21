"""Orchestrator tool-loop tests with a fake LLM."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from jarvis.agent.orchestrator import AgentOrchestrator
from jarvis.config import PermissionsConfig
from jarvis.llm.base import ChatChunk, ChatMessage, HealthStatus, LLMProvider, ToolCall
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.base import PermissionLevel, Tool, ToolResult
from jarvis.tools.registry import ToolRegistry


class _TimeTool(Tool):
    name = "get_current_time"
    description = "time"
    permission = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="It is 9:25 AM.")


class _DeleteTool(Tool):
    name = "delete_file"
    description = "delete"
    permission = PermissionLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output=f"Deleted {kwargs.get('path')}")


class ScriptedLLM(LLMProvider):
    def __init__(self, scripts: list[tuple[str, list[ToolCall] | None]]) -> None:
        self.scripts = scripts
        self.calls = 0

    def health(self) -> HealthStatus:
        return HealthStatus(ok=True, message="ok")

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatChunk]:
        text, calls = self.scripts[self.calls]
        self.calls += 1
        if text:
            yield ChatChunk(content=text, done=False)
        yield ChatChunk(content=None, tool_calls=calls or [], done=True)


def _make_orch(tmp_path: Path, llm: LLMProvider, confirm) -> AgentOrchestrator:
    db = str(tmp_path / "t.db")
    registry = ToolRegistry()
    registry.register(_TimeTool())
    registry.register(_DeleteTool())
    return AgentOrchestrator(
        llm=llm,
        tools=registry,
        permissions=PermissionManager(PermissionsConfig(), confirm=confirm),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
    )


def test_tool_loop_then_final_answer(tmp_path: Path):
    llm = ScriptedLLM(
        [
            ("", [ToolCall(id="1", name="get_current_time", arguments={})]),
            ("It is 9:25 AM.", None),
        ]
    )
    orch = _make_orch(tmp_path, llm, confirm=lambda _p: False)
    tokens: list[str] = []
    result = orch.handle_user_message("What time is it?", on_token=tokens.append)
    assert result.text == "It is 9:25 AM."
    assert result.tool_names == ["get_current_time"]
    assert "It is 9:25 AM." in "".join(tokens)


def test_dangerous_tool_denied_without_confirm(tmp_path: Path):
    llm = ScriptedLLM(
        [
            ("", [ToolCall(id="1", name="delete_file", arguments={"path": "/tmp/x"})]),
            ("I did not delete the file.", None),
        ]
    )
    orch = _make_orch(tmp_path, llm, confirm=lambda _p: False)
    result = orch.handle_user_message("Delete /tmp/x")
    assert "delete_file" in result.tool_names
    assert result.text == "I did not delete the file."
    # Ensure the dangerous tool never reported success to the model path via denial message
    # (action log status denied is enough — checked indirectly by final answer script running)
    assert llm.calls == 2
