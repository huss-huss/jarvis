"""Tests for tool registry."""

from jarvis.tools.base import PermissionLevel, Tool, ToolResult
from jarvis.tools.registry import ToolRegistry


class _EchoTool(Tool):
    name = "echo"
    description = "Echo text"
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, **kwargs):
        return ToolResult(success=True, output=str(kwargs.get("text", "")))


def test_registry_register_and_schema():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    assert registry.get("echo") is not None
    schemas = registry.schemas()
    assert schemas[0]["function"]["name"] == "echo"


def test_registry_unknown_tool():
    registry = ToolRegistry()
    result = registry.execute("missing", {})
    assert result.success is False
    assert "Unknown tool" in (result.error or "")


def test_registry_execute():
    registry = ToolRegistry()
    registry.register(_EchoTool())
    result = registry.execute("echo", {"text": "hi"})
    assert result.success is True
    assert result.output == "hi"
