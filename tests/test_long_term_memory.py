"""Phase 4 long-term / semantic memory tests."""

from __future__ import annotations

from pathlib import Path

from jarvis.memory.long_term import LongTermMemory
from jarvis.rag.embeddings import HashingEmbeddings, cosine_similarity
from jarvis.tools.memory import build_memory_tools
from jarvis.tools.registry import ToolRegistry


def test_fact_survives_reopen(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    emb = HashingEmbeddings()
    mem = LongTermMemory(db, emb)
    fact = mem.remember_fact(
        "The user's test project is called Atlas.",
        key="test_project",
    )
    assert fact.key == "test_project"
    mem.close()

    mem2 = LongTermMemory(db, HashingEmbeddings())
    found = mem2.facts.get_by_key("test_project")
    assert found is not None
    assert "Atlas" in found.content
    hits = mem2.search("What is my test project called?")
    assert hits
    assert any("Atlas" in h.text for h in hits)
    mem2.close()


def test_remember_updates_same_key(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    mem = LongTermMemory(db, HashingEmbeddings())
    mem.remember_fact("Project is Atlas.", key="test_project")
    mem.remember_fact("Project is Borealis.", key="test_project")
    facts = mem.list_facts()
    assert len(facts) == 1
    assert "Borealis" in facts[0].content
    mem.close()


def test_forget_fact(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    mem = LongTermMemory(db, HashingEmbeddings())
    mem.remember_fact("Secret nickname is Chip.", key="nickname")
    assert mem.forget_fact(key="nickname") is not None
    assert mem.facts.get_by_key("nickname") is None
    mem.close()


def test_semantic_ranks_related_fact_higher(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    mem = LongTermMemory(db, HashingEmbeddings())
    mem.remember_fact("The user's test project is called Atlas.", key="test_project")
    mem.remember_fact("Favorite coffee is espresso.", key="coffee")
    hits = mem.search("test project name Atlas")
    assert hits
    assert "Atlas" in hits[0].text
    mem.close()


def test_prompt_block_includes_memories(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    mem = LongTermMemory(db, HashingEmbeddings())
    mem.remember_fact("The user's test project is called Atlas.", key="test_project")
    block = mem.format_for_prompt("what is my test project called?")
    assert "Atlas" in block
    assert "Relevant long-term memories" in block
    mem.close()


def test_memory_tools_roundtrip(tmp_path: Path):
    db = str(tmp_path / "mem.db")
    mem = LongTermMemory(db, HashingEmbeddings())
    registry = ToolRegistry()
    for tool in build_memory_tools(mem):
        registry.register(tool)

    remembered = registry.execute(
        "remember_fact",
        {"content": "The user's test project is called Atlas.", "key": "test_project"},
    )
    assert remembered.success
    recalled = registry.execute("recall_memory", {"query": "test project"})
    assert recalled.success
    assert "Atlas" in recalled.output
    listed = registry.execute("list_memories", {})
    assert listed.success
    assert "Atlas" in listed.output
    mem.close()


def test_cosine_identical_is_one():
    emb = HashingEmbeddings()
    a = emb.embed("atlas project")
    assert cosine_similarity(a, a) > 0.99


def test_orchestrator_injects_memory(tmp_path: Path):
    from collections.abc import Iterator
    from typing import Any

    from jarvis.agent.orchestrator import AgentOrchestrator
    from jarvis.config import PermissionsConfig
    from jarvis.llm.base import ChatChunk, ChatMessage, HealthStatus, LLMProvider
    from jarvis.memory.action_log import ActionLog
    from jarvis.memory.conversation import ConversationStore
    from jarvis.permissions.manager import PermissionManager

    class CaptureLLM(LLMProvider):
        def __init__(self) -> None:
            self.systems: list[str] = []

        def health(self) -> HealthStatus:
            return HealthStatus(ok=True, message="ok")

        def stream_chat(
            self,
            messages: list[ChatMessage],
            tools: list[dict[str, Any]] | None = None,
        ) -> Iterator[ChatChunk]:
            system = next(m.content or "" for m in messages if m.role.value == "system")
            self.systems.append(system)
            yield ChatChunk(content="Your test project is Atlas.", done=True)

    db = str(tmp_path / "mem.db")
    long_term = LongTermMemory(db, HashingEmbeddings())
    long_term.remember_fact("The user's test project is called Atlas.", key="test_project")
    llm = CaptureLLM()
    orch = AgentOrchestrator(
        llm=llm,
        tools=ToolRegistry(),
        permissions=PermissionManager(PermissionsConfig(), confirm=lambda _p: True),
        memory=ConversationStore(db),
        action_log=ActionLog(db),
        long_term=long_term,
    )
    result = orch.handle_user_message("What is my test project called?")
    assert "Atlas" in result.text
    assert any("Atlas" in s for s in llm.systems)
