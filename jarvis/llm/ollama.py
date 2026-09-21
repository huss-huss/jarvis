"""Ollama LLM provider adapter."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import ollama

from jarvis.llm.base import (
    ChatChunk,
    ChatMessage,
    HealthStatus,
    LLMProvider,
    ToolCall,
)
from jarvis.logging import get_logger

log = get_logger(__name__)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {"value": raw}


def _extract_tool_calls(message: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    raw_calls = getattr(message, "tool_calls", None) or []
    for call in raw_calls:
        function = getattr(call, "function", None)
        if function is None and isinstance(call, dict):
            function = call.get("function", call)
        if function is None:
            continue

        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        if isinstance(function, dict):
            name = function.get("name", name)
            arguments = function.get("arguments", arguments)

        call_id = getattr(call, "id", None)
        if call_id is None and isinstance(call, dict):
            call_id = call.get("id")
        if not call_id:
            call_id = f"call_{uuid.uuid4().hex[:12]}"

        if not name:
            continue
        calls.append(ToolCall(id=str(call_id), name=str(name), arguments=_parse_arguments(arguments)))
    return calls


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3.1",
        temperature: float = 0.3,
    ) -> None:
        self.host = host
        self.model = model
        self.temperature = temperature
        self._client = ollama.Client(host=host)

    def health(self) -> HealthStatus:
        try:
            self._client.list()
            return HealthStatus(ok=True, message=f"Ollama reachable at {self.host}")
        except Exception as exc:  # noqa: BLE001 — surface any connection failure
            return HealthStatus(
                ok=False,
                message=f"I couldn't connect to Ollama at {self.host}. It may not be running. ({exc})",
            )

    def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatChunk]:
        payload = [m.to_ollama() for m in messages]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        if tools:
            kwargs["tools"] = tools

        log.debug("ollama_stream_start", model=self.model, message_count=len(payload), tool_count=len(tools or []))

        try:
            stream = self._client.chat(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.error("ollama_stream_error", error=str(exc))
            raise RuntimeError(
                f"I couldn't connect to Ollama at {self.host}. It may not be running."
            ) from exc

        accumulated_calls: dict[str, ToolCall] = {}
        for part in stream:
            message = getattr(part, "message", None)
            if message is None and isinstance(part, dict):
                message = part.get("message", {})

            content = None
            if message is not None:
                content = getattr(message, "content", None)
                if content is None and isinstance(message, dict):
                    content = message.get("content")

            new_calls = _extract_tool_calls(message) if message is not None else []
            for call in new_calls:
                # Prefer latest arguments for the same id/name during streaming
                key = call.id or call.name
                accumulated_calls[key] = call

            done = bool(getattr(part, "done", False))
            if isinstance(part, dict):
                done = bool(part.get("done", done))

            yield ChatChunk(
                content=content or None,
                tool_calls=list(accumulated_calls.values()),
                done=done,
            )
