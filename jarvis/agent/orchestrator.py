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
from jarvis.memory.long_term import LongTermMemory
from jarvis.permissions.manager import PermissionManager
from jarvis.rag.service import RagService
from jarvis.tools.registry import ToolRegistry

log = get_logger(__name__)

TokenCallback = Callable[[str], None]
EventCallback = Callable[[str, dict[str, Any]], None]

_TEXT_TOOL_RE = re.compile(
    r"\{[^{}]*\"name\"\s*:\s*\"([^\"]+)\"[^{}]*\"parameters\"\s*:\s*(\{[^{}]*\})[^{}]*\}",
    re.DOTALL,
)
_FUNC_TOOL_RE = re.compile(
    r"\{[^{}]*\"(?:type)\"\s*:\s*\"function\"[^{}]*\"name\"\s*:\s*\"([^\"]+)\"[^{}]*"
    r"\"parameters\"\s*:\s*(\{[^{}]*\})[^{}]*\}",
    re.DOTALL,
)
# Malformed dumps like: "parameters{"type":"string","value":"ps -ef"}
# (missing quote/colon after parameters — common llama glitch)
_LOOSE_TOOL_RE = re.compile(
    r'"name"\s*:\s*"([^"]+)"\s*,\s*"parameters"?\s*\{([^}]*)\}',
    re.DOTALL,
)
_TOOLISH_START = re.compile(r'^\s*\{\s*"(?:type|name|function)"')


def _looks_like_tool_dump(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned.startswith("{"):
        return False
    return bool(
        _TOOLISH_START.match(cleaned)
        or '"parameters"' in cleaned
        or '"type":"function"' in cleaned.replace(" ", "")
    )


def _args_from_loose_params(blob: str) -> dict[str, Any]:
    """Best-effort parse of broken parameter blobs from llama tool dumps."""
    args: dict[str, Any] = {}
    # {"type":"string","value":"ps -ef"} or command=...
    value_m = re.search(r'"value"\s*:\s*"([^"]*)"', blob)
    if value_m:
        args["command"] = value_m.group(1)
        return args
    cmd_m = re.search(r'"(?:command|cmd|query|path|message|title)"\s*:\s*"([^"]*)"', blob)
    if cmd_m:
        key = re.search(r'"(command|cmd|query|path|message|title)"', blob)
        args[(key.group(1) if key else "command").replace("cmd", "command")] = cmd_m.group(1)
        return args
    # bare shell-ish string
    bare = re.search(r'"([^"]+)"', blob)
    if bare:
        args["command"] = bare.group(1)
    return args


def _normalize_tool_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = dict(arguments or {})
    # Flatten {"type":"string","value":"..."} style mistakes
    if "value" in args and len(args) <= 3 and "command" not in args:
        if name == "run_command":
            args["command"] = args.pop("value")
        elif name in {"open_application", "close_application"}:
            args["application_name"] = args.pop("value")
    if name == "run_command" and "cmd" in args and "command" not in args:
        args["command"] = args.pop("cmd")
    if name in {"open_application", "close_application"}:
        if "application_name" not in args:
            for key in ("name", "app", "application", "app_name"):
                if key in args and args[key]:
                    args["application_name"] = args[key]
                    break
    if name == "remember_fact":
        if "content" not in args:
            for key in ("fact", "text", "memory", "value"):
                if key in args and args[key]:
                    args["content"] = args[key]
                    break
        if "key" not in args:
            for key in ("name", "fact_key", "id"):
                if key in args and args[key] and key != "id":
                    args["key"] = args[key]
                    break
    if name == "recall_memory":
        if "query" not in args:
            for key in ("q", "search", "text", "question"):
                if key in args and args[key]:
                    args["query"] = args[key]
                    break
    if name == "forget_fact":
        if "key" not in args and "fact_id" not in args:
            for key in ("name", "fact_key", "id"):
                if key in args and args[key] is not None:
                    if key == "id":
                        args["fact_id"] = args[key]
                    else:
                        args["key"] = args[key]
                    break
    if name in {"ingest_document", "ingest_folder"}:
        if "path" not in args:
            for key in ("file", "filepath", "folder", "directory"):
                if key in args and args[key]:
                    args["path"] = args[key]
                    break
    if name == "search_docs":
        if "query" not in args:
            for key in ("q", "search", "text", "question"):
                if key in args and args[key]:
                    args["query"] = args[key]
                    break
    if name == "switch_project":
        if "project" not in args:
            for key in ("name", "context", "project_name"):
                if key in args and args[key]:
                    args["project"] = args[key]
                    break
    return args


def _parse_text_tool_calls(text: str) -> list[ToolCall]:
    """Fallback when the model dumps a tool call as JSON text instead of API tool_calls."""
    calls: list[ToolCall] = []
    seen: set[str] = set()

    def _add(tool_name: str, params: dict[str, Any]) -> None:
        key = f"{tool_name}:{json.dumps(params, sort_keys=True)}"
        if key in seen:
            return
        seen.add(key)
        calls.append(
            ToolCall(
                id=f"text_{uuid.uuid4().hex[:10]}",
                name=tool_name,
                arguments=_normalize_tool_arguments(tool_name, params),
            )
        )

    for match in _TEXT_TOOL_RE.finditer(text or ""):
        try:
            params = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(params, dict):
            _add(match.group(1), params)

    for match in _FUNC_TOOL_RE.finditer(text or ""):
        try:
            params = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(params, dict):
            _add(match.group(1), params)

    for match in _LOOSE_TOOL_RE.finditer(text or ""):
        _add(match.group(1), _args_from_loose_params(match.group(2)))

    # Whole-message JSON object
    raw = (text or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("function")
            if isinstance(name, dict):
                name = name.get("name")
            params = obj.get("parameters") or obj.get("arguments") or obj.get("args") or {}
            if isinstance(name, str) and isinstance(params, dict):
                _add(name, params)

    # Prefer dedicated tools over shell guesses
    remapped: list[ToolCall] = []
    for call in calls:
        cmd = str(call.arguments.get("command") or "").lower()
        if call.name == "run_command" and (
            cmd.startswith("ps ") or "ps -" in cmd or cmd in {"ps", "ps aux", "ps -ef"}
        ):
            remapped.append(
                ToolCall(
                    id=call.id,
                    name="get_running_apps",
                    arguments={},
                )
            )
        else:
            remapped.append(call)
    return remapped


@dataclass
class TurnResult:
    text: str
    tool_names: list[str] = field(default_factory=list)


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        permissions: PermissionManager,
        memory: ConversationStore,
        action_log: ActionLog,
        *,
        long_term: LongTermMemory | None = None,
        rag: RagService | None = None,
        max_tool_iterations: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
        conversation_limit: int = 40,
        memory_top_k: int = 5,
        rag_top_k: int = 5,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
        self.action_log = action_log
        self.long_term = long_term
        self.rag = rag
        self.max_tool_iterations = max_tool_iterations
        self.system_prompt = system_prompt
        self.conversation_limit = conversation_limit
        self.memory_top_k = memory_top_k
        self.rag_top_k = rag_top_k

    def handle_user_message(
        self,
        user_text: str,
        *,
        on_token: TokenCallback | None = None,
        on_event: EventCallback | None = None,
    ) -> TurnResult:
        def emit(kind: str, payload: dict[str, Any] | None = None) -> None:
            if on_event:
                on_event(kind, payload or {})

        self.memory.add_message(Role.USER, user_text)
        emit("status", {"status": "thinking"})

        messages = self._build_messages(user_query=user_text)
        tool_schemas = self.tools.schemas() or None
        used_tools: list[str] = []
        final_text = ""

        for iteration in range(self.max_tool_iterations):
            log.info("llm_turn", iteration=iteration + 1)
            emit("status", {"status": "thinking"})
            assistant_text, tool_calls = self._stream_assistant(
                messages,
                tools=tool_schemas,
                on_token=on_token,
            )

            if not tool_calls and assistant_text:
                tool_calls = _parse_text_tool_calls(assistant_text)
                if tool_calls:
                    # Clear any streamed tool-JSON from the UI bubble
                    emit("assistant_reset", {})
                    assistant_text = ""

            if tool_calls:
                # Clear any streamed tool-JSON from the UI bubble
                emit("assistant_reset", {})
                messages.append(
                    ChatMessage(
                        role=Role.ASSISTANT,
                        content=None,
                        tool_calls=tool_calls,
                    )
                )

                for call in tool_calls:
                    call.arguments = _normalize_tool_arguments(call.name, call.arguments)
                    result_text = self._run_tool(
                        call,
                        user_request=user_text,
                        on_event=on_event,
                    )
                    used_tools.append(call.name)
                    # Persist a short trail so the next turn still has context
                    self.memory.add_message(
                        Role.ASSISTANT,
                        f"[tool {call.name}] {result_text[:800]}",
                        tool_name=call.name,
                    )
                    messages.append(
                        ChatMessage(
                            role=Role.TOOL,
                            content=result_text,
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )
                continue

            # If the model dumped broken tool JSON we couldn't parse, don't show/save it
            if assistant_text and _looks_like_tool_dump(assistant_text) and not tool_calls:
                emit("assistant_reset", {})
                final_text = (
                    "I tried to use a tool but the call was malformed. "
                    "Please ask again — for open apps, I'll use get_running_apps."
                )
                self.memory.add_message(Role.ASSISTANT, final_text)
                if on_token:
                    on_token(final_text)
                break

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

        emit("status", {"status": "idle"})
        return TurnResult(text=final_text, tool_names=used_tools)

    def _build_messages(self, *, user_query: str | None = None) -> list[ChatMessage]:
        history = self.memory.recent_messages(limit=self.conversation_limit)
        system = self.system_prompt
        extras: list[str] = []
        if self.long_term and user_query:
            block = self.long_term.format_for_prompt(user_query, top_k=self.memory_top_k)
            if block:
                extras.append(block)
        if self.rag and user_query and _looks_like_knowledge_query(user_query):
            try:
                rag_block = self.rag.retriever.format_for_prompt(user_query, top_k=self.rag_top_k)
            except Exception as exc:  # noqa: BLE001
                log.warning("rag_prompt_inject_failed", error=str(exc))
                rag_block = ""
            if rag_block:
                extras.append(rag_block)
        if extras:
            system = self.system_prompt + "\n\n" + "\n\n".join(extras)
        messages = [ChatMessage(role=Role.SYSTEM, content=system)]
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
        # Hold back early tokens that look like tool JSON so the UI doesn't flash garbage
        holdback = True
        released = False

        for chunk in self.llm.stream_chat(messages, tools=tools):
            if chunk.content:
                content_parts.append(chunk.content)
                so_far = "".join(content_parts)
                if holdback and not released:
                    if _looks_like_tool_dump(so_far) or so_far.lstrip().startswith("{"):
                        # keep buffering — may be a tool dump
                        if len(so_far) > 400 and not _looks_like_tool_dump(so_far):
                            released = True
                            if on_token:
                                on_token(so_far)
                        continue
                    released = True
                    if on_token:
                        on_token(so_far)
                elif on_token and released:
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

        text = "".join(content_parts).strip()
        # If we held back a normal reply that never looked like tools, flush it
        if on_token and holdback and not released and text and not tool_calls and not _looks_like_tool_dump(text):
            on_token(text)
        return text, tool_calls

    def _run_tool(
        self,
        call: ToolCall,
        *,
        user_request: str,
        on_event: EventCallback | None = None,
    ) -> str:
        def emit(kind: str, payload: dict[str, Any] | None = None) -> None:
            if on_event:
                on_event(kind, payload or {})

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
            emit("tool", {"name": call.name, "phase": "error", "detail": msg})
            return msg

        emit(
            "status",
            {"status": "executing"},
        )
        emit(
            "tool",
            {
                "name": call.name,
                "phase": "start",
                "arguments": call.arguments,
                "permission": tool.permission.value,
            },
        )

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
            emit("tool", {"name": call.name, "phase": "denied", "detail": decision.reason})
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
        emit(
            "tool",
            {
                "name": call.name,
                "phase": status,
                "detail": (result.for_llm() or "")[:500],
            },
        )
        return result.for_llm()


def _looks_like_knowledge_query(text: str) -> bool:
    """Avoid RAG on every greeting; prefer question / doc-ish asks."""
    lowered = text.lower().strip()
    if len(lowered) < 12:
        return False
    greetings = {"hi", "hey", "hello", "thanks", "thank you", "ok", "okay", "bye", "goodbye"}
    if lowered.rstrip(".!") in greetings:
        return False
    cues = (
        "?",
        "what ",
        "where ",
        "how ",
        "why ",
        "who ",
        "which ",
        "document",
        "requirements",
        "readme",
        "according to",
        "in the ",
        "client",
        "spec",
        "project",
    )
    return any(c in lowered for c in cues)
