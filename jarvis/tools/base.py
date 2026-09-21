"""Tool interfaces and permission levels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    SAFE = "safe"
    MODIFICATION = "modification"
    DANGEROUS = "dangerous"


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def for_llm(self) -> str:
        if self.success:
            return self.output
        return f"Error: {self.error or self.output}"


class Tool(ABC):
    name: str
    description: str
    permission: PermissionLevel
    parameters: dict[str, Any]

    def schema(self) -> dict[str, Any]:
        """Ollama / OpenAI-style tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError
