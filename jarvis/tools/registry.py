"""Tool registry."""

from __future__ import annotations

from typing import Any

from jarvis.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
        try:
            return tool.execute(**(arguments or {}))
        except TypeError as exc:
            return ToolResult(success=False, output="", error=f"Invalid arguments for {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output="", error=str(exc))
