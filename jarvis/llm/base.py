"""LLM provider interfaces and message types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None

    def to_ollama(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_name is not None:
            msg["name"] = self.tool_name
        return msg


@dataclass
class ChatChunk:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False


@dataclass
class HealthStatus:
    ok: bool
    message: str


class LLMProvider(ABC):
    """Internal interface — agent depends on this, not Ollama directly."""

    @abstractmethod
    def health(self) -> HealthStatus:
        raise NotImplementedError

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatChunk]:
        raise NotImplementedError

    async def astream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ChatChunk]:
        for chunk in self.stream_chat(messages, tools):
            yield chunk
