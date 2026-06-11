from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from auc.integration.nuggets import AuNugget, NuggetsStore
from auc.messages import ChatMessage
from auc.ports.memory import MemoryPort
from auc.types import AgentId, RunId


def evolution_paths(sandbox_root: str) -> tuple[Path, Path]:
    """Return (nuggets_yaml, evolution_yaml) under sandbox .auc/."""
    root = Path(sandbox_root).resolve()
    auc_dir = root / ".auc"
    nuggets = auc_dir / "au-nuggets.yaml"
    if not nuggets.is_file():
        alt = root / "au-nuggets.yaml"
        if alt.is_file():
            nuggets = alt
    evolution = auc_dir / "evolution.yaml"
    return nuggets, evolution


@dataclass
class Episode:
    id: str
    tags: list[str]
    lesson: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvolutionStore:
    """Persist episodic lessons and nuggets in the sandbox (agent evolution)."""

    path: Path
    episodes: list[Episode] = field(default_factory=list)
    version: int = 1

    @classmethod
    def load(cls, path: Path) -> EvolutionStore:
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            store = cls(path=path)
            store.save()
            return store
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        eps: list[Episode] = []
        for item in data.get("episodes") or []:
            eps.append(
                Episode(
                    id=str(item.get("id", "")),
                    tags=list(item.get("tags") or []),
                    lesson=str(item.get("lesson", "")),
                    created_at=str(item.get("created_at", "")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return cls(
            path=path,
            episodes=eps,
            version=int(data.get("version", 1)),
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "episodes": [
                {
                    "id": e.id,
                    "tags": e.tags,
                    "lesson": e.lesson,
                    "created_at": e.created_at,
                    "metadata": e.metadata,
                }
                for e in self.episodes
            ],
        }
        self.path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def recall_episodes(self, query: str, limit: int = 5) -> list[Episode]:
        q = query.lower()
        scored: list[tuple[float, Episode]] = []
        for ep in self.episodes:
            score = 0.0
            for tag in ep.tags:
                if tag.lower() in q:
                    score += 2.0
            if any(w in ep.lesson.lower() for w in q.split() if len(w) > 2):
                score += 1.0
            if score > 0:
                scored.append((score, ep))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def add_episode(
        self,
        *,
        tags: list[str],
        lesson: str,
        metadata: dict[str, Any] | None = None,
    ) -> Episode:
        ep_id = f"ep-{len(self.episodes) + 1:04d}"
        ep = Episode(
            id=ep_id,
            tags=[t.strip() for t in tags if t.strip()],
            lesson=lesson.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        self.episodes.append(ep)
        if len(self.episodes) > 200:
            self.episodes = self.episodes[-200:]
        self.save()
        return ep

    def promote_nugget(
        self,
        nuggets_path: Path,
        *,
        nugget_id: str,
        tags: list[str],
        content: str,
    ) -> AuNugget:
        store = (
            NuggetsStore.from_yaml(nuggets_path)
            if nuggets_path.is_file()
            else NuggetsStore()
        )
        nugget = AuNugget(
            id=nugget_id,
            tags=tags,
            content=content,
            metadata={"promoted_at": datetime.now(timezone.utc).isoformat()},
        )
        store.nuggets = [n for n in store.nuggets if n.id != nugget_id]
        store.nuggets.append(nugget)
        store.save_yaml(nuggets_path)
        return nugget


def _tags_from_text(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z_\-\u4e00-\u9fff]{2,}", text.lower())
    return list(dict.fromkeys(words[:8]))


def _distill_lesson(messages: list[ChatMessage]) -> tuple[list[str], str] | None:
    users = [
        m.content
        for m in messages
        if m.role == "user" and m.content and not m.tool_call_id
    ]
    assistants = [m.content for m in messages if m.role == "assistant" and m.content]
    if not users:
        return None
    tools_used = [m.name for m in messages if m.role == "tool" and m.name]
    tags = _tags_from_text(users[-1])
    if tools_used:
        tags.extend(_tags_from_text(" ".join(tools_used)))
    tags = list(dict.fromkeys(tags))[:12]
    answer = assistants[-1][:800] if assistants else "(tool-only turn)"
    lesson = f"用户: {users[-1][:300]}\n结果: {answer}"
    if tools_used:
        lesson += f"\n工具: {', '.join(dict.fromkeys(tools_used))}"
    return tags, lesson


class EvolutionMemoryPort:
    """Recall nuggets + episodic lessons; remember successful runs into evolution.yaml."""

    def __init__(
        self,
        *,
        sandbox_root: str,
        nuggets_path: Path | None = None,
        evolution_path: Path | None = None,
    ) -> None:
        self._sandbox = sandbox_root
        n_path, e_path = evolution_paths(sandbox_root)
        self._nuggets_path = nuggets_path or n_path
        self._evolution = EvolutionStore.load(evolution_path or e_path)
        self._nuggets = (
            NuggetsStore.from_yaml(self._nuggets_path)
            if self._nuggets_path.is_file()
            else NuggetsStore()
        )

    @property
    def evolution_store(self) -> EvolutionStore:
        return self._evolution

    @property
    def nuggets_store(self) -> NuggetsStore:
        return self._nuggets

    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]:
        del run_id, agent_id
        msgs: list[ChatMessage] = []
        for n in self._nuggets.recall_by_query(query, limit=3):
            msgs.append(
                ChatMessage(
                    role="system",
                    content=f"[进化·金块 {n.id}] {n.content}",
                )
            )
        for ep in self._evolution.recall_episodes(query, limit=3):
            tag_s = ", ".join(ep.tags) if ep.tags else "general"
            msgs.append(
                ChatMessage(
                    role="system",
                    content=f"[进化·经验 {ep.id} · {tag_s}] {ep.lesson}",
                )
            )
        return msgs[:limit]

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None:
        del run_id, agent_id
        distilled = _distill_lesson(items)
        if not distilled:
            return
        tags, lesson = distilled
        self._evolution.add_episode(tags=tags, lesson=lesson, metadata={"sandbox": self._sandbox})

    def save_lesson(self, tags: str, lesson: str) -> str:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        ep = self._evolution.add_episode(tags=tag_list, lesson=lesson)
        return f"saved episode {ep.id}"

    def promote_nugget(self, nugget_id: str, tags: str, content: str) -> str:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        n = self._evolution.promote_nugget(
            self._nuggets_path,
            nugget_id=nugget_id,
            tags=tag_list,
            content=content,
        )
        self._nuggets = NuggetsStore.from_yaml(self._nuggets_path)
        return f"promoted nugget {n.id} -> {self._nuggets_path}"


def make_evolution_tools(
    memory: EvolutionMemoryPort,
) -> list[tuple[Any, Any]]:
    from auc.tools.base import ToolPolicy, tool_from_function

    def _save_lesson(tags: str, lesson: str) -> str:
        return memory.save_lesson(tags, lesson)

    def _promote_nugget(nugget_id: str, tags: str, content: str) -> str:
        return memory.promote_nugget(nugget_id, tags, content)

    specs = [
        tool_from_function(
            _save_lesson,
            name="save_lesson",
            description=(
                "固化一条可复用的经验教训到沙盒进化库（跨会话召回）。"
                "tags 为逗号分隔关键词，lesson 为简短可执行说明。"
            ),
            privilege="L2",
        ),
        tool_from_function(
            _promote_nugget,
            name="promote_nugget",
            description=(
                "将验证成功的经验提升为 Au-Nugget 金块技能（写入 .auc/au-nuggets.yaml）。"
                "参数: nugget_id, tags, content"
            ),
            privilege="L2",
        ),
    ]
    out = [(t, p) for t, p in specs]
    return out
