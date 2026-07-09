"""智能体角色：每角色一个目录（role.yaml + prompt.md + 进化文件）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auc.roles.catalog import RoleCatalog, RoleSpec
from auc.roles.constants import (
    ACTIVE_ROLE_FILE,
    CHAT_SHARED_TOOLS,
    DEFAULT_ROLE_ID,
    ROLE_TAG_PREFIX,
    render_sandbox_template,
)
from auc.roles.loader import (
    active_role_path,
    legacy_roles_yaml_path,
    load_legacy_roles_yaml,
    load_role_catalog,
    load_roles_from_directory,
    load_roles_yaml,
    matches_role,
    package_roles_root,
    parse_role_from_agent_id,
    read_active_role,
    role_from_folder,
    role_tag,
    roles_yaml_path,
    sandbox_role_dir,
    sandbox_roles_root,
    sanitize_role_id,
    set_active_role,
)
from auc.work_mode import WORK_MODE_OVERVIEW, build_full_system_prompt

# 兼容：从包内目录加载的内置角色 id 集合
BUILTIN_ROLES: dict[str, RoleSpec] = load_roles_from_directory(
    package_roles_root() / "core", builtin=True, recommended=True
)

_default_catalog: RoleCatalog | None = None


def _builtin_catalog() -> RoleCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = RoleCatalog(roles=dict(BUILTIN_ROLES))
    return _default_catalog


def normalize_role_id(
    role_id: str | None,
    *,
    catalog: RoleCatalog | None = None,
) -> str:
    return (catalog or _builtin_catalog()).resolve(role_id)


def get_role(role_id: str | None, *, catalog: RoleCatalog | None = None) -> RoleSpec:
    return (catalog or _builtin_catalog()).get(role_id)


def list_roles(*, catalog: RoleCatalog | None = None) -> list[RoleSpec]:
    return (catalog or _builtin_catalog()).list_roles()


def build_role_system_prompt(
    sandbox: str,
    role_id: str | None = None,
    *,
    include_work_mode: bool = True,
    extra: str | None = None,
    catalog: RoleCatalog | None = None,
) -> str:
    cat = catalog or _builtin_catalog()
    spec = cat.get(role_id)
    base = render_sandbox_template(spec.persona, sandbox) + "\n\n" + CHAT_SHARED_TOOLS
    return build_full_system_prompt(
        sandbox,
        base=base,
        include_work_mode=include_work_mode,
        extra=extra,
    )


def format_role_note(role_id: str | None, *, catalog: RoleCatalog | None = None) -> str:
    from auc.roles.routing import is_auto_role

    cat = catalog or _builtin_catalog()
    if is_auto_role(role_id):
        return "› 角色：智能选择（按任务自动匹配）"
    spec = get_role(role_id, catalog=cat)
    return f"› 角色：{spec.label}（{spec.title}）"


def _role_item_payload(r: RoleSpec, *, active: bool = False, auto: bool = False) -> dict[str, object]:
    return {
        "id": r.id,
        "label": r.label,
        "title": r.title,
        "description": r.description,
        "capabilities": list(r.capabilities),
        "default_work_mode": r.default_work_mode,
        "builtin": r.builtin,
        "recommended": r.recommended,
        "active": active,
        "auto": auto,
        "division": r.division,
        "emoji": r.emoji,
        "color": r.color,
        "vibe": r.vibe,
        "when_to_use": r.when_to_use,
    }


def roles_payload(*, catalog: RoleCatalog | None = None) -> list[dict[str, object]]:
    from auc.roles.routing import auto_role_spec

    cat = catalog or _builtin_catalog()
    active = cat.active_role_id or cat.default_role_id
    auto = auto_role_spec()
    items: list[dict[str, object]] = [
        _role_item_payload(auto, active=False, auto=True),
    ]
    for r in cat.list_roles():
        items.append(_role_item_payload(r, active=r.id == active, auto=False))
    return items


def divisions_payload(*, catalog: RoleCatalog | None = None) -> list[dict[str, object]]:
    from auc.roles.divisions import divisions_payload as _divisions_payload

    extra: list[str] = []
    if catalog:
        extra = sorted({r.division for r in catalog.roles.values() if r.division})
    return _divisions_payload(extra_ids=extra)


def role_evolution_paths(sandbox: str | Path, role_id: str) -> tuple[Path, Path]:
    """返回角色目录下的 (nuggets.yaml, evolution.yaml)，必要时创建目录。"""
    role_dir = sandbox_role_dir(sandbox, role_id)
    role_dir.mkdir(parents=True, exist_ok=True)
    return role_dir / "nuggets.yaml", role_dir / "evolution.yaml"


__all__ = [
    "ACTIVE_ROLE_FILE",
    "BUILTIN_ROLES",
    "CHAT_SHARED_TOOLS",
    "DEFAULT_ROLE_ID",
    "ROLE_TAG_PREFIX",
    "RoleCatalog",
    "RoleSpec",
    "active_role_path",
    "build_role_system_prompt",
    "format_role_note",
    "get_role",
    "legacy_roles_yaml_path",
    "list_roles",
    "load_role_catalog",
    "load_roles_yaml",
    "matches_role",
    "normalize_role_id",
    "package_roles_root",
    "parse_role_from_agent_id",
    "read_active_role",
    "role_evolution_paths",
    "role_from_folder",
    "role_tag",
    "roles_payload",
    "divisions_payload",
    "roles_yaml_path",
    "sandbox_role_dir",
    "sandbox_roles_root",
    "sanitize_role_id",
    "set_active_role",
]
