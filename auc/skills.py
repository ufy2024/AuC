"""R21 技能固化 + R15 Skills 机制：SKILL.md 技能库与晋升流水线。

技能 = 可移植「操作手册」（与 Nuggets 经验互补）。格式对齐社区 `SKILL.md`（YAML
frontmatter：`name/description/triggers` + 正文步骤）。两段式晋升：
- 高频命中经验（R23 度量满足阈值）起草为草案，落 `.auc/skills/_drafts/<name>/SKILL.md`；
- **生效需 L3 人审**（CLI `auc skills promote` 由操作者批准）→ 移入 `.auc/skills/<name>/`；
- 注入：按用户消息与 `triggers` 匹配（英文用词边界、中文用子串），命中则注入技能正文（单次≤2，防膨胀）。

手工放置的 `SKILL.md`（`source: manual`）同样被加载/匹配（R15）。零新增依赖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from auc.messages import ChatMessage

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)

SkillMode = Literal["auto", "manual"]
AUTO_SKILL_MODE: SkillMode = "auto"


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:48] or "skill"


def trigger_matches_message(trigger: str, message: str) -> bool:
    """触发词匹配：中文子串；英文/数字用词边界，避免 ``net`` 命中 ``kubernetes``。"""
    t = (trigger or "").strip().lower()
    msg = (message or "").lower()
    if not t or not msg:
        return False
    if re.search(r"[\u4e00-\u9fff]", t):
        return t in msg
    return bool(re.search(rf"(?<![a-z0-9-]){re.escape(t)}(?![a-z0-9-])", msg))


def bundled_skills_root() -> Path:
    return Path(__file__).resolve().parent / "skill_library" / "bundled"


def iter_bundled_skill_files(root: Path | None = None) -> list[Path]:
    """递归发现 ``bundled/`` 下所有 ``SKILL.md``（含 anbeime 等子目录）。"""
    base = root or bundled_skills_root()
    if not base.is_dir():
        return []
    skip_parts = frozenset({"_drafts", "__MACOSX", ".git"})
    out: list[Path] = []
    for p in sorted(base.rglob("SKILL.md")):
        if any(part in skip_parts for part in p.parts):
            continue
        if p.name.startswith("._"):
            continue
        out.append(p)
    return out


@dataclass
class SkillPrefs:
    """技能选择偏好：自动按触发词匹配，或手动固定若干技能。"""

    mode: SkillMode = AUTO_SKILL_MODE
    pinned: list[str] = field(default_factory=list)

    def normalized(self) -> SkillPrefs:
        mode: SkillMode = "manual" if self.mode == "manual" else "auto"
        pinned = [slugify(n) for n in self.pinned if str(n).strip()]
        return SkillPrefs(mode=mode, pinned=list(dict.fromkeys(pinned)))


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: str = ""
    draft: bool = False
    source: str = "manual"  # manual | promoted | bundled
    promoted_from: str = ""
    roles: list[str] = field(default_factory=list)
    division: str = "custom"
    builtin: bool = False
    source_url: str = ""
    emoji: str = "⚡"

    def render_md(self) -> str:
        front: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "source": self.source,
        }
        if self.roles:
            front["roles"] = self.roles
        if self.division:
            front["division"] = self.division
        if self.builtin:
            front["builtin"] = True
        if self.source_url:
            front["source_url"] = self.source_url
        if self.emoji:
            front["emoji"] = self.emoji
        if self.promoted_from:
            front["promoted_from"] = self.promoted_from
        fm = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{fm}\n---\n{self.body.rstrip()}\n"

    def inject_block(self) -> str:
        return f"[SKILL: {self.name}]\n{self.body.strip()}\n[/SKILL]"


def _parse_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


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
    triggers = _parse_str_list(front.get("triggers"))
    roles = _parse_str_list(front.get("roles"))
    return Skill(
        name=str(front["name"]),
        description=str(front.get("description") or ""),
        triggers=triggers,
        body=m.group(2).strip(),
        path=path,
        draft=draft,
        source=str(front.get("source") or "manual"),
        promoted_from=str(front.get("promoted_from") or ""),
        roles=roles,
        division=str(front.get("division") or "custom"),
        builtin=bool(front.get("builtin")),
        source_url=str(front.get("source_url") or ""),
        emoji=str(front.get("emoji") or "⚡"),
    )


def skill_matches_role(skill: Skill, role_id: str | None) -> bool:
    """技能是否适用于当前角色（无 roles 限制 = 全角色可用）。"""
    if not skill.roles:
        return True
    if not role_id:
        return True
    rid = slugify(role_id)
    return rid in {slugify(r) for r in skill.roles}


def skills_payload(skills: list[Skill], *, active_role: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sk in skills:
        item: dict[str, Any] = {
            "name": sk.name,
            "description": sk.description,
            "triggers": sk.triggers,
            "roles": sk.roles,
            "division": sk.division,
            "builtin": sk.builtin,
            "draft": sk.draft,
            "source": sk.source,
            "source_url": sk.source_url,
            "emoji": sk.emoji,
            "for_role": skill_matches_role(sk, active_role),
        }
        out.append(item)
    return out


class SkillStore:
    """技能库：内置 `skill_library/bundled/` + 沙盒 `.auc/skills/<name>/SKILL.md`。"""

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

    def _load_bundled(self) -> list[Skill]:
        root = bundled_skills_root()
        skills: list[Skill] = []
        for f in iter_bundled_skill_files(root):
            sk = parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=False)
            if sk:
                sk.builtin = True
                if not sk.source or sk.source == "manual":
                    sk.source = "bundled"
                skills.append(sk)
        return skills

    def list(
        self,
        *,
        include_drafts: bool = False,
        role_id: str | None = None,
        division: str | None = None,
    ) -> list[Skill]:
        by_name: dict[str, Skill] = {}
        for sk in self._load_bundled():
            by_name[sk.name] = sk
        for f in self._iter_dirs(self._base):
            sk = parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=False)
            if sk:
                by_name[sk.name] = sk
        skills = list(by_name.values())
        if include_drafts:
            for f in self._iter_dirs(self.drafts_dir):
                sk = parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=True)
                if sk and sk.name not in by_name:
                    skills.append(sk)
        if role_id:
            skills = [s for s in skills if skill_matches_role(s, role_id)]
        if division and division != "all":
            skills = [s for s in skills if s.division == division]
        skills.sort(key=lambda s: (not s.builtin, s.name))
        return skills

    def get(self, name: str, *, draft: bool = False) -> Skill | None:
        if draft:
            f = self._skill_file(name, draft=True)
            if f.is_file():
                return parse_skill_md(f.read_text(encoding="utf-8"), path=str(f), draft=True)
            return None
        for sk in self.list():
            if sk.name == name or slugify(sk.name) == slugify(name):
                return sk
        return None

    def match(
        self,
        message: str,
        *,
        limit: int = 2,
        role_id: str | None = None,
    ) -> list[Skill]:
        msg = (message or "").lower()
        scored: list[tuple[int, Skill]] = []
        for sk in self.list(role_id=role_id):
            hits = sum(1 for t in sk.triggers if trigger_matches_message(t, msg))
            if hits > 0:
                scored.append((hits, sk))
        scored.sort(key=lambda x: (-x[0], x[1].name))
        return [s for _, s in scored[:limit]]

    def resolve(
        self,
        message: str,
        *,
        role_id: str | None = None,
        prefs: SkillPrefs | None = None,
        limit: int = 2,
    ) -> list[Skill]:
        """按偏好解析应注入的技能列表。"""
        p = (prefs or SkillPrefs()).normalized()
        if p.mode == "manual":
            out: list[Skill] = []
            for name in p.pinned:
                sk = self.get(name)
                if sk and skill_matches_role(sk, role_id):
                    out.append(sk)
                if len(out) >= limit:
                    break
            return out
        return self.match(message, limit=limit, role_id=role_id)

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


def matched_skill_messages(
    store: SkillStore,
    query: str,
    *,
    limit: int = 2,
    role_id: str | None = None,
    prefs: SkillPrefs | None = None,
) -> list[ChatMessage]:
    """把命中技能渲染为可注入的 system 消息（供 recall/compose 注入）。"""
    out: list[ChatMessage] = []
    for sk in store.resolve(query, role_id=role_id, prefs=prefs, limit=limit):
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
