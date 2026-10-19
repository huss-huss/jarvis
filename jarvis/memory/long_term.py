"""Long-term memory facade: facts + episodic + semantic retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.memory.database import connect, init_db
from jarvis.memory.episodic import Episode, EpisodicStore
from jarvis.memory.facts import Fact, FactStore
from jarvis.memory.semantic import SemanticIndex
from jarvis.rag.embeddings import EmbeddingProvider


@dataclass
class MemoryHit:
    kind: str  # fact | episode
    id: int
    text: str
    score: float
    key: str | None = None


class LongTermMemory:
    def __init__(self, db_path: str, embeddings: EmbeddingProvider) -> None:
        self.db_path = db_path
        self.embeddings = embeddings
        self._conn = connect(db_path)
        init_db(self._conn)
        self.facts = FactStore(db_path, conn=self._conn)
        self.episodes = EpisodicStore(db_path, conn=self._conn)
        self.semantic = SemanticIndex(db_path, embeddings, conn=self._conn)

    def remember_fact(
        self,
        content: str,
        *,
        key: str | None = None,
        category: str = "general",
        source: str = "user",
    ) -> Fact:
        fact = self.facts.remember(content, key=key, category=category, source=source)
        self.semantic.upsert("fact", fact.id, _fact_index_text(fact))
        self.episodes.add(
            f"Remembered: {fact.content}",
            details=f"key={fact.key}" if fact.key else None,
            kind="memory",
        )
        return fact

    def forget_fact(self, *, fact_id: int | None = None, key: str | None = None) -> Fact | None:
        fact = self.facts.forget(fact_id=fact_id, key=key)
        if fact:
            self.semantic.delete("fact", fact.id)
            self.episodes.add(
                f"Forgot: {fact.content}",
                details=f"key={fact.key}" if fact.key else None,
                kind="memory",
            )
        return fact

    def list_facts(self, *, limit: int = 50) -> list[Fact]:
        return self.facts.list_facts(limit=limit)

    def add_episode(self, summary: str, *, details: str | None = None, kind: str = "event") -> Episode:
        episode = self.episodes.add(summary, details=details, kind=kind)
        self.semantic.upsert("episode", episode.id, episode.summary)
        return episode

    def search(self, query: str, *, top_k: int = 5) -> list[MemoryHit]:
        """Hybrid semantic + keyword recall for agent context and tools."""
        hits: dict[tuple[str, int], MemoryHit] = {}

        for owner_type, owner_id, score in self.semantic.search(query, top_k=top_k * 2):
            hit = self._hydrate(owner_type, owner_id, score)
            if hit:
                hits[(hit.kind, hit.id)] = hit

        for fact in self.facts.keyword_search(query, limit=top_k):
            key = ("fact", fact.id)
            bonus = 0.35
            if key in hits:
                hits[key].score = max(hits[key].score, hits[key].score * 0.5 + bonus + 0.2)
            else:
                hits[key] = MemoryHit(
                    kind="fact",
                    id=fact.id,
                    text=fact.content,
                    score=bonus,
                    key=fact.key,
                )

        ranked = sorted(hits.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k]

    def format_for_prompt(self, query: str, *, top_k: int = 5) -> str:
        results = self.search(query, top_k=top_k)
        if not results:
            return ""
        lines = ["Relevant long-term memories (use if helpful; do not invent extras):"]
        for hit in results:
            label = f"[{hit.kind}"
            if hit.key:
                label += f":{hit.key}"
            label += "]"
            lines.append(f"- {label} {hit.text}")
        return "\n".join(lines)

    def _hydrate(self, owner_type: str, owner_id: int, score: float) -> MemoryHit | None:
        if owner_type == "fact":
            fact = self.facts.get(owner_id)
            if not fact:
                return None
            return MemoryHit(
                kind="fact",
                id=fact.id,
                text=fact.content,
                score=score,
                key=fact.key,
            )
        if owner_type == "episode":
            episode = self.episodes.get(owner_id)
            if not episode:
                return None
            return MemoryHit(
                kind="episode",
                id=episode.id,
                text=episode.summary,
                score=score,
            )
        return None

    def close(self) -> None:
        self._conn.close()


def _fact_index_text(fact: Fact) -> str:
    if fact.key:
        return f"{fact.key}: {fact.content}"
    return fact.content
