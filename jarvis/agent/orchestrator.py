"""Agent orchestrator — text turn loop with tools and permissions."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.agent.prompts import SYSTEM_PROMPT
from jarvis.llm.base import ChatMessage, LLMProvider, Role, ToolCall
from jarvis.logging import get_logger
from jarvis.memory.action_log import ActionLog
from jarvis.memory.conversation import ConversationStore
from jarvis.permissions.manager import PermissionManager
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)

TokenCallback = Callable[[str], None]

_TEXT_TOOL_RE = re.compile(
    r"\{[^{}]*\"name\"\s*:\s*\"([^\"]+)\"[^{}]*\"parameters\"\s*:\s*(\{[^{}]*\})[^{}]*\}",
    re.DOTALL,
)


@dataclass
class TurnResult:
    text: str
    tool_names: list[str] = field(default_factory=list)


def _normalize_tool_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = dict(arguments or {})
    if name in {"open_application", "close_application"}:
        if "application_name" not in args:
            for key in ("name", "app", "application", "app_name"):
                if key in args and args[key]:
                    args["application_name"] = args[key]
                    break
    return args


def _parse_text_tool_calls(text: str) -> list[ToolCall]:
    """Fallback when the model dumps a tool call as JSON text instead of API tool_calls."""
    calls: list[ToolCall] = []
    for match in _TEXT_TOOL_RE.finditer(text or ""):
        tool_name = match.group(1)
        try:
            params = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if not isinstance(params, dict):
            continue
        calls.append(
            ToolCall(
                id=f"text_{uuid.uuid4().hex[:10]}",
                name=tool_name,
                arguments=_normalize_tool_arguments(tool_name, params),
            )
        )
    return calls


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        permissions: PermissionManager,
        memory: ConversationStore,
        action_log: ActionLog,
        *,
        max_tool_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
        conversation_limit: int = 40,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
        self.action_log = action_log
        self.max_tool_iterations = max_tool_iterations
        self.system_prompt = system_prompt
        self.conversation_limit = conversation_limit

    def handle_user_message(
        self,
        user_text: str,
        *,
        on_token: TokenCallback | None = None,
    ) -> TurnResult:
        self.memory.add_message(Role.USER, user_text)

        messages = self._build_messages()
        tool_schemas = self.tools.schemas() or None
        used_tools: list[str] = []
        final_text = ""

        for iteration in range(self.max_tool_iterations):
            log.info("llm_turn", iteration=iteration + 1)
            assistant_text, tool_calls = self._stream_assistant(
                messages,
                tools=tool_schemas,
                on_token=on_token,
            )

            if not tool_calls and assistant_text:
                tool_calls = _parse_text_tool_calls(assistant_text)
                if tool_calls:
                    assistant_text = _TEXT_TOOL_RE.sub("", assistant_text).strip()

            if tool_calls:
                self.memory.add_message(
                    Role.ASSISTANT,
                    assistant_text or None,
                )
                messages.append(
                    ChatMessage(
                        role=Role.ASSISTANT,
                        content=assistant_text or None,
                        tool_calls=tool_calls,
                    )
                )

                for call in tool_calls:
                    call.arguments = _normalize_tool_arguments(call.name, call.arguments)
                    result_text = self._run_tool(call, user_request=user_text)
                    used_tools.append(call.name)
                    messages.append(
                        ChatMessage(
                            role=Role.TOOL,
                            content=result_text,
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )
                continue

            final_text = assistant_text
            if not final_text and not tool_calls:
                final_text = "Yes? How can I help?"
            if final_text:
                self.memory.add_message(Role.ASSISTANT, final_text)
                if on_token and not assistant_text:
                    on_token(final_text)
            break
        else:
            final_text = "I reached my tool-iteration limit before finishing. Please try again."
            self.memory.add_message(Role.ASSISTANT, final_text)
            if on_token and final_text:
                on_token(final_text)

        return TurnResult(text=final_text, tool_names=used_tools)

    def _build_messages(self) -> list[ChatMessage]:
        history = self.memory.recent_messages(limit=self.conversation_limit)
        messages = [ChatMessage(role=Role.SYSTEM, content=self.system_prompt)]
        for msg in history:
            if msg.role is Role.SYSTEM:
                continue
            messages.append(msg)
        return messages

    def _stream_assistant(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None,
        on_token: TokenCallback | None,
    ) -> tuple[str, list[ToolCall]]:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for chunk in self.llm.stream_chat(messages, tools=tools):
            if chunk.content:
                content_parts.append(chunk.content)
                if on_token:
                    on_token(chunk.content)
            if chunk.tool_calls:
                tool_calls = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=_normalize_tool_arguments(tc.name, tc.arguments),
                    )
                    for tc in chunk.tool_calls
                ]

        return "".join(content_parts).strip(), tool_calls

    def _run_tool(self, call: ToolCall, *, user_request: str) -> str:
        tool = self.tools.get(call.name)
        if tool is None:
            msg = f"Unknown tool: {call.name}"
            self.action_log.record(
                tool=call.name,
                parameters=call.arguments,
                result=msg,
                status="error",
                user_request=user_request,
            )
            return msg

        decision = self.permissions.authorize(tool, call.arguments)
        if not decision.allowed:
            msg = f"Permission denied for tool `{call.name}` ({decision.reason})."
            self.action_log.record(
                tool=call.name,
                parameters=call.arguments,
                result=msg,
                status="denied",
                confirmation=decision.reason,
                user_request=user_request,
            )
            log.warning("tool_denied", tool=call.name, reason=decision.reason)
            return msg

        result = self.tools.execute(call.name, call.arguments)
        status = "success" if result.success else "error"
        self.action_log.record(
            tool=call.name,
            parameters=call.arguments,
            result=result.for_llm(),
            status=status,
            confirmation=decision.reason,
            user_request=user_request,
        )
        log.info(
            "tool_executed",
            tool=call.name,
            status=status,
            permission=tool.permission.value,
        )
        return result.for_llm()
