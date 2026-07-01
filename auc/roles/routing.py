"""基于角色元数据的通用 auto 路由（适配 agency-agents 大规模角色库）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auc.roles.catalog import RoleCatalog, RoleSpec

AUTO_ROLE_ID = "auto"
AUTO_DIVISION = "__auto__"

# 保留少量高优先级别名 → 角色 id（覆盖元数据匹配）
_ROLE_ALIASES: dict[str, str] = {
    "代码审查": "engineering-code-reviewer",
    "code review": "engineering-code-reviewer",
    "审查": "engineering-code-reviewer",
    "review": "engineering-code-reviewer",
    "写代码": "coder",
    "修 bug": "coder",
    "实现": "coder",
    "架构": "engineering-software-architect",
    "architecture": "engineering-software-architect",
    "后端": "engineering-backend-architect",
    "backend": "engineering-backend-architect",
    "前端": "engineering-frontend-developer",
    "frontend": "engineering-frontend-developer",
    "运维": "engineering-devops-automator",
    "devops": "engineering-devops-automator",
    "教学": "education",
    "解释": "education",
}


def is_auto_role(role_id: str | None) -> bool:
    return str(role_id or "").strip().lower() == AUTO_ROLE_ID


def auto_role_spec() -> RoleSpec:
    from auc.roles.catalog import RoleSpec

    return RoleSpec(
        id=AUTO_ROLE_ID,
        label="智能选择",
        title="按任务自动匹配角色",
        description="根据你的问题内容自动选用全部角色库中最合适的专家",
        capabilities=("自动路由",),
        persona="",
        default_work_mode="auto",
        builtin=True,
        recommended=True,
        division=AUTO_DIVISION,
        emoji="✨",
        vibe="按任务内容自动匹配专家",
        when_to_use="不确定选哪个角色、希望系统自动匹配时",
    )


def _tokens(text: str) -> list[str]:
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9-]{2,}", text.lower())
    return parts


def _score_role(spec: RoleSpec, message: str) -> float:
    msg = message.lower()
    score = 0.0
    hay = " ".join(
        [
            spec.id,
            spec.label,
            spec.title,
            spec.description,
            spec.vibe,
            spec.when_to_use,
            spec.division,
            " ".join(spec.capabilities),
        ]
    ).lower()
    for tok in _tokens(msg):
        if len(tok) < 2:
            continue
        if tok in hay:
            score += 1.5 if tok in spec.id else 1.0
    for alias, rid in _ROLE_ALIASES.items():
        if alias in msg and spec.id == rid:
            score += 3.0
    return score


def route_role(message: str, catalog: RoleCatalog) -> str:
    text = (message or "").strip()
    if not text:
        return catalog.default_role_id

    candidates = [r for r in catalog.list_roles() if r.id != AUTO_ROLE_ID]
    if not candidates:
        return catalog.default_role_id

    scored = [(spec, _score_role(spec, text)) for spec in candidates]
    scored.sort(key=lambda x: (-x[1], x[0].id))
    best_score = scored[0][1]
    if best_score <= 0:
        return catalog.default_role_id
    top = [spec for spec, s in scored if s == best_score]
    return sorted(top, key=lambda r: r.id)[0].id


def format_auto_role_note(resolved_id: str, *, catalog: RoleCatalog) -> str:
    spec = catalog.get(resolved_id)
    return f"› 角色：智能选择 → {spec.label}（{spec.title}）"
