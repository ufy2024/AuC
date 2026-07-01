"""RoleSpec 与 RoleCatalog。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from auc.roles.constants import DEFAULT_ROLE_ID


@dataclass(frozen=True)
class RoleSpec:
    id: str
    label: str
    title: str
    description: str
    capabilities: tuple[str, ...]
    persona: str
    default_work_mode: str = "auto"
    builtin: bool = False
    recommended: bool = False
    role_dir: Path | None = None
    # agency-agents 风格扩展
    division: str = "custom"
    emoji: str = "◆"
    color: str = ""
    vibe: str = ""
    when_to_use: str = ""


@dataclass
class RoleCatalog:
    """系统推荐角色 + 沙盒自定义角色。"""

    roles: dict[str, RoleSpec] = field(default_factory=dict)
    default_role_id: str = DEFAULT_ROLE_ID
    active_role_id: str | None = None

    def resolve(self, role_id: str | None) -> str:
        found = self.try_resolve(role_id)
        if found:
            return found
        if self.active_role_id and self.active_role_id in self.roles:
            return self.active_role_id
        if self.default_role_id in self.roles:
            return self.default_role_id
        return DEFAULT_ROLE_ID

    def try_resolve(self, role_id: str | None) -> str | None:
        if not role_id or not str(role_id).strip():
            return None
        from auc.roles.loader import sanitize_role_id
        from auc.roles.routing import AUTO_ROLE_ID, is_auto_role

        if is_auto_role(role_id):
            return AUTO_ROLE_ID
        try:
            rid = sanitize_role_id(str(role_id))
        except ValueError:
            return None
        return rid if rid in self.roles else None

    def get(self, role_id: str | None) -> RoleSpec:
        from auc.roles.routing import AUTO_ROLE_ID, auto_role_spec, is_auto_role

        if is_auto_role(role_id):
            return auto_role_spec()
        return self.roles[self.resolve(role_id)]

    def list_roles(self) -> list[RoleSpec]:
        from auc.roles.divisions import ROLE_DIVISIONS

        recommended = [
            r for r in self.roles.values() if r.recommended or r.builtin
        ]
        custom = [
            r
            for r in self.roles.values()
            if not r.recommended and not r.builtin
        ]
        order = {d["id"]: d.get("order", 50) for d in ROLE_DIVISIONS.values()}

        def sort_key(r: RoleSpec) -> tuple[int, str, str]:
            return (order.get(r.division, 99), r.division, r.id)

        return [
            *sorted(recommended, key=sort_key),
            *sorted(custom, key=sort_key),
        ]

    def role_ids(self) -> list[str]:
        return [r.id for r in self.list_roles()]
