from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from auc.messages import ChatMessage
from auc.ports.memory import MemoryPort
from auc.types import AgentId, RunId


@dataclass
class AuNugget:
    id: str
    tags: list[str]
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NuggetsStore:
    nuggets: list[AuNugget] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> NuggetsStore:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        items = data.get("nuggets", data) if isinstance(data, dict) else data
        nuggets: list[AuNugget] = []
        for item in items or []:
            nuggets.append(
                AuNugget(
                    id=str(item["id"]),
                    tags=list(item.get("tags", [])),
                    content=str(item.get("content", "")),
                    metadata=dict(item.get("metadata", {})),
                )
            )
        return cls(nuggets=nuggets)

    def recall_by_query(self, query: str, limit: int = 5) -> list[AuNugget]:
        q = query.lower()
        scored: list[tuple[float, AuNugget]] = []
        for n in self.nuggets:
            score = 0.0
            for tag in n.tags:
                if tag.lower() in q:
                    score += 2.0
            if any(word in n.content.lower() for word in q.split() if len(word) > 3):
                score += 1.0
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:limit]]

    def save_yaml(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "nuggets": [
                {
                    "id": n.id,
                    "tags": n.tags,
                    "content": n.content,
                    "metadata": n.metadata,
                }
                for n in self.nuggets
            ]
        }
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


class NuggetsMemoryPort:
    """MemoryPort：召回时注入 Au-Nuggets（AuM 进化层）。"""

    def __init__(
        self,
        base: MemoryPort | None = None,
        store: NuggetsStore | None = None,
    ) -> None:
        self._base = base
        self._store = store or NuggetsStore()

    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        for n in self._store.recall_by_query(query, limit=min(5, limit)):
            msgs.append(
                ChatMessage(
                    role="system",
                    content=f"[AU-NUGGET {n.id}] {n.content}",
                )
            )
        if self._base is not None:
            base_limit = max(0, limit - len(msgs))
            msgs.extend(
                await self._base.recall(
                    query, limit=base_limit, run_id=run_id, agent_id=agent_id
                )
            )
        return msgs

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None:
        if self._base is not None:
            await self._base.remember(
                items, run_id=run_id, agent_id=agent_id
            )
