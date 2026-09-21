"""Conversation memory tests."""

from pathlib import Path

from jarvis.llm.base import Role
from jarvis.memory.conversation import ConversationStore


def test_conversation_roundtrip(tmp_path: Path):
    db = tmp_path / "jarvis.db"
    store = ConversationStore(str(db))
    store.add_message(Role.USER, "Hello")
    store.add_message(Role.ASSISTANT, "Hi there")

    store2 = ConversationStore(str(db))
    messages = store2.recent_messages()
    assert [(m.role, m.content) for m in messages] == [
        (Role.USER, "Hello"),
        (Role.ASSISTANT, "Hi there"),
    ]
