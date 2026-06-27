"""R21 技能固化 + R15 Skills 机制：SKILL.md 技能库与晋升流水线。

技能 = 可移植「操作手册」（与 Nuggets 经验互补）。格式对齐社区 `SKILL.md`（YAML
frontmatter：`name/description/triggers` + 正文步骤）。两段式晋升：
- 高频命中经验（R23 度量满足阈值）起草为草案，落 `.auc/skills/_drafts/<name>/SKILL.md`；
- **生效需 L3 人审**（CLI `auc skills promote` 由操作者批准）→ 移入 `.auc/skills/<name>/`；
- 注入：按用户消息与 `triggers` 匹配（不区分大小写包含），命中则注入技能正文（单次≤2，防膨胀）。

手工放置的 `SKILL.md`（`source: manual`）同样被加载/匹配（R15）。零新增依赖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from auc.messages import ChatMessage

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:48] or "skill"


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: str = ""
    draft: bool = False
    source: str = "manual"  # manual | promoted
    promoted_from: str = ""

    def render_md(self) -> str:
        front = {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "source": self.source,
        }
        if self.promoted_from:
            front["promoted_from"] = self.promoted_from
        fm = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{fm}\n---\n{self.body.rstrip()}\n"

    def inject_block(self) -> str:
        return f"[SKILL: {self.name}]\n{self.body.strip()}\n[/SKILL]"


def parse_skill_md(text: str, *, path: str = "", draft: bool = False) -> Skill | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        front = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict) or not front.get("name"):
        return None
    triggers = front.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    return Skill(
        name=str(front["name"]),
        description=str(front.get("description") or ""),
        triggers=[str(t) for t in triggers],
        body=m.group(2).strip(),
        path=path,
        draft=draft,
        source=str(front.get("source") or "manual"),
        promoted_from=str(front.get("promoted_from") or ""),
    )


class SkillStore:
    """技能库：`<sandbox>/.auc/skills/<name>/SKILL.md`（草案在 `_drafts/`）。"""

    def __init__(self, sandbox_root: str) -> None:
        self._base = Path(sandbox_root).resolve() / ".auc" / "skills"

    @property
    def base(self) -> Path:
        return self._base

    @property
    def drafts_dir(self) -> Path:
        return self._base / "_drafts"

    def _skill_file(self, name: str, *, draft: bool = False) -> Path:
        root = self.drafts_dir if draft else self._base
        return root / slugify(name) / "SKILL.md"

    def _iter_dirs(self, root: Path) -> list[Path]:
        if not root.exists():
            return []
        return [
            d / "SKILL.md"
            for d in sorted(root.iterdir())
            if d.is_dir() and d.name != "_drafts" and (d / "SKILL.md").is_file()
        ]

    def list(self, *, include_drafts: bool = False) -> list[Skill]:
        skills: list[Skill] = []
        for f in self._iter_dirs(self._base):
            sk = parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=False)
            if sk:
                skills.append(sk)
        if include_drafts:
            for f in self._iter_dirs(self.drafts_dir):
                sk = parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=True)
                if sk:
                    skills.append(sk)
        return skills

    def get(self, name: str, *, draft: bool = False) -> Skill | None:
        f = self._skill_file(name, draft=draft)
        if not f.is_file():
            return None
        return parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=draft)

    def match(self, message: str, *, limit: int = 2) -> list[Skill]:
        msg = (message or "").lower()
        scored: list[tuple[int, Skill]] = []
        for sk in self.list():
            hits = sum(1 for t in sk.triggers if t and t.lower() in msg)
            if hits > 0:
                scored.append((hits, sk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    def write(self, skill: Skill, *, draft: bool = True) -> Path:
        f = self._skill_file(skill.name, draft=draft)
        f.parent.mkdir(parents=True, exist_ok=True)
        skill.draft = draft
        f.write_text(skill.render_md(), encoding="utf-8")
        return f

    def promote(self, name: str) -> Skill | None:
        """草案 → 正式（调用方负责 L3 审批）。"""
        draft = self.get(name, draft=True)
        if draft is None:
            return None
        draft.draft = False
        draft.source = "promoted"
        active_path = self.write(draft, draft=False)
        # 移除草案
        self.remove(name, draft=True)
        return parse_skill_md(
            active_path.read_text(encoding="utf-8"), path=str(active_path), draft=False
        )

    def remove(self, name: str, *, draft: bool = False) -> bool:
        f = self._skill_file(name, draft=draft)
        if not f.is_file():
            return False
        try:
            f.unlink()
            parent = f.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
            return True
        except OSError:
            return False

    def draft_from_episode(
        self,
        *,
        episode_id: str,
        goal: str,
        tags: list[str],
        lesson: str,
        commands: list[str] | None = None,
    ) -> Skill:
        """R21：把高频命中经验起草为技能草案（启发式，无模型）。"""
        name = slugify(goal or episode_id)
        steps = []
        for i, c in enumerate(commands or [], start=1):
            steps.append(f"{i}. 执行：`{c}`")
        if not steps:
            steps.append("1. 参考以下经验执行并自行校验。")
        body = (
            "# 触发条件\n"
            f"{', '.join(tags) or goal}\n\n"
            "# 操作步骤\n" + "\n".join(steps) + "\n\n"
            "# 经验依据\n" + lesson.strip()
        )
        skill = Skill(
            name=name,
            description=(goal or lesson)[:120],
            triggers=list(dict.fromkeys([t for t in tags if len(t) >= 2]))[:8],
            body=body,
            source="promoted",
            promoted_from=episode_id,
        )
        self.write(skill, draft=True)
        return skill


def matched_skill_messages(store: SkillStore, query: str, *, limit: int = 2) -> list[ChatMessage]:
    """把命中技能渲染为可注入的 system 消息（供 recall/compose 注入）。"""
    out: list[ChatMessage] = []
    for sk in store.match(query, limit=limit):
        out.append(ChatMessage(role="system", content=f"[技能·{sk.name}] {sk.inject_block()}"))
    return out


# ── R21 晋升判定（输入来自 R23 度量）──
def should_promote(*, recall_count: int, adopted_count: int) -> bool:
    if recall_count < 3:
        return False
    return adopted_count / recall_count >= 0.5 if recall_count else False


def promotion_candidates(metrics: Any) -> list[str]:
    """从 EvolutionMetrics 找出满足晋升阈值的经验 id。"""
    out: list[str] = []
    for entry_id, stat in getattr(metrics, "stats", {}).items():
        if should_promote(
            recall_count=stat.recall_count, adopted_count=stat.adopted_count
        ):
            out.append(entry_id)
    return out
