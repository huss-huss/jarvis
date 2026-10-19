"""Memory tools — remember / recall / forget (Phase 4)."""

from __future__ import annotations

from typing import Any

from jarvis.memory.long_term import LongTermMemory
from jarvis.tools.base import PermissionLevel, Tool, ToolResult


class RememberFactTool(Tool):
    name = "remember_fact"
    description = (
        "Store a durable personal fact the user asked you to remember "
        "(survives restarts). Use a short snake_case key when possible "
        "(e.g. test_project)."
    )
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact to remember, written as a clear sentence.",
            },
            "key": {
                "type": "string",
                "description": "Optional stable key, e.g. test_project, preferred_name.",
            },
            "category": {
                "type": "string",
                "description": "Optional category (general, project, preference, people).",
            },
        },
        "required": ["content"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self.memory = memory

    def execute(self, **kwargs: Any) -> ToolResult:
        content = str(kwargs.get("content") or "").strip()
        if not content:
            return ToolResult(success=False, output="", error="content is required")
        key = kwargs.get("key")
        category = str(kwargs.get("category") or "general")
        fact = self.memory.remember_fact(
            content,
            key=str(key) if key else None,
            category=category,
            source="user",
        )
        key_bit = f" (key={fact.key})" if fact.key else ""
        return ToolResult(
            success=True,
            output=f"Remembered{key_bit}: {fact.content}",
            data={"id": fact.id, "key": fact.key, "content": fact.content},
        )


class RecallMemoryTool(Tool):
    name = "recall_memory"
    description = (
        "Search long-term memories (facts + notable events) by meaning or keywords. "
        "Use when the user asks what you remember or about stored personal details."
    )
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look up, e.g. 'test project name'.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 5).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self.memory = memory

    def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, output="", error="query is required")
        limit = int(kwargs.get("limit") or 5)
        hits = self.memory.search(query, top_k=max(1, min(limit, 20)))
        if not hits:
            return ToolResult(success=True, output="No matching memories found.")
        lines = []
        for hit in hits:
            label = hit.key or hit.kind
            lines.append(f"- ({label}, score={hit.score:.2f}) {hit.text}")
        return ToolResult(success=True, output="Memories:\n" + "\n".join(lines))


class ForgetFactTool(Tool):
    name = "forget_fact"
    description = (
        "Delete a stored fact by key or id when the user asks to forget something."
    )
    permission = PermissionLevel.MODIFICATION
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Fact key to forget."},
            "fact_id": {"type": "integer", "description": "Fact id to forget."},
        },
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self.memory = memory

    def execute(self, **kwargs: Any) -> ToolResult:
        key = kwargs.get("key")
        fact_id = kwargs.get("fact_id")
        if key is None and fact_id is None:
            return ToolResult(success=False, output="", error="Provide key or fact_id")
        fact = self.memory.forget_fact(
            fact_id=int(fact_id) if fact_id is not None else None,
            key=str(key) if key else None,
        )
        if fact is None:
            return ToolResult(success=False, output="", error="Fact not found")
        return ToolResult(success=True, output=f"Forgot: {fact.content}")


class ListMemoriesTool(Tool):
    name = "list_memories"
    description = "List stored long-term facts (most recently updated first)."
    permission = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max facts to list (default 20)."},
        },
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self.memory = memory

    def execute(self, **kwargs: Any) -> ToolResult:
        limit = int(kwargs.get("limit") or 20)
        facts = self.memory.list_facts(limit=max(1, min(limit, 100)))
        if not facts:
            return ToolResult(success=True, output="No long-term facts stored yet.")
        lines = []
        for fact in facts:
            key_bit = f"[{fact.key}] " if fact.key else ""
            lines.append(f"- {key_bit}{fact.content}")
        return ToolResult(success=True, output="Stored facts:\n" + "\n".join(lines))


def build_memory_tools(memory: LongTermMemory) -> list[Tool]:
    return [
        RememberFactTool(memory),
        RecallMemoryTool(memory),
        ForgetFactTool(memory),
        ListMemoriesTool(memory),
    ]
