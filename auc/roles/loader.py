"""从目录 / 遗留 YAML 加载角色；管理沙盒当前角色标识。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from auc.roles.catalog import RoleCatalog, RoleSpec
from auc.roles.constants import (
    ACTIVE_ROLE_FILE,
    DEFAULT_ROLE_ID,
    LEGACY_ROLES_YAML,
    ROLE_META_FILE,
    ROLE_PROMPT_FILE,
    ROLE_TAG_PREFIX,
)

ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SKIP_DIR_NAMES = frozenset({"__pycache__", "__init__.py"})


def package_roles_root() -> Path:
    return Path(__file__).resolve().parent


def sandbox_roles_root(sandbox: str | Path) -> Path:
    return Path(sandbox).resolve() / ".auc" / "roles"


def sandbox_role_dir(sandbox: str | Path, role_id: str) -> Path:
    return sandbox_roles_root(sandbox) / sanitize_role_id(role_id)


def legacy_roles_yaml_path(sandbox: str | Path) -> Path:
    return Path(sandbox).resolve() / ".auc" / LEGACY_ROLES_YAML


def active_role_path(sandbox: str | Path) -> Path:
    return sandbox_roles_root(sandbox) / ACTIVE_ROLE_FILE


def sanitize_role_id(raw: str) -> str:
    rid = raw.strip().lower().replace(" ", "-").replace("_", "-")
    while "--" in rid:
        rid = rid.replace("--", "-")
    rid = rid.strip("-")
    if not rid or not ROLE_ID_RE.match(rid):
        raise ValueError(f"invalid role id: {raw!r}")
    return rid


def role_tag(role_id: str) -> str:
    return f"{ROLE_TAG_PREFIX}{role_id}"


def parse_role_from_agent_id(agent_id: str | None) -> str | None:
    if agent_id and agent_id.startswith("chat:"):
        slug = agent_id.split(":", 1)[1].strip().lower()
        try:
            return sanitize_role_id(slug)
        except ValueError:
            return slug or None
    return None


def matches_role(
    *,
    role_id: str,
    tags: list[str],
    metadata: dict | None = None,
) -> bool:
    tag = role_tag(role_id)
    if tag in tags:
        return True
    meta = metadata or {}
    if meta.get("role_id") == role_id:
        return True
    has_role = any(t.startswith(ROLE_TAG_PREFIX) for t in tags) or meta.get("role_id")
    return not has_role


def read_active_role(sandbox: str | Path | None) -> str | None:
    if not sandbox:
        return None
    path = active_role_path(sandbox)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        return sanitize_role_id(raw)
    except ValueError:
        return None


def set_active_role(sandbox: str | Path, role_id: str) -> None:
    rid = sanitize_role_id(role_id)
    root = sandbox_roles_root(sandbox)
    root.mkdir(parents=True, exist_ok=True)
    active_role_path(sandbox).write_text(rid + "\n", encoding="utf-8")


def _ensure_sandbox_in_persona(persona: str) -> str:
    text = persona.rstrip()
    if "{sandbox}" not in text:
        text += "\n工作区根目录（沙盒）为：{sandbox}"
    return text


def _read_prompt(role_dir: Path) -> str:
    for name in (ROLE_PROMPT_FILE, "persona.md", "prompt.txt", "persona.txt"):
        path = role_dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def _read_role_meta(role_dir: Path) -> dict[str, Any]:
    path = role_dir / ROLE_META_FILE
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def role_from_folder(
    role_dir: Path,
    *,
    builtin: bool = False,
    recommended: bool = False,
    division_hint: str | None = None,
) -> RoleSpec | None:
    if not role_dir.is_dir() or role_dir.name in _SKIP_DIR_NAMES:
        return None
    try:
        rid = sanitize_role_id(role_dir.name)
    except ValueError:
        return None
    meta = _read_role_meta(role_dir)
    persona = _read_prompt(role_dir)
    if not persona:
        persona = str(meta.get("persona") or meta.get("system") or "").strip()
    if not persona:
        label = str(meta.get("label") or rid)
        persona = f"你是 **{label}**。\n工作区根目录（沙盒）为：{{sandbox}}"
    else:
        persona = _ensure_sandbox_in_persona(persona)
    caps = meta.get("capabilities") or []
    if isinstance(caps, str):
        caps = [c.strip() for c in caps.split(",") if c.strip()]
    from auc.roles.divisions import normalize_division

    division = normalize_division(
        str(meta.get("division") or division_hint or "custom")
    )
    return RoleSpec(
        id=rid,
        label=str(meta.get("label") or meta.get("name") or rid),
        title=str(meta.get("title") or meta.get("label") or meta.get("name") or rid),
        description=str(meta.get("description") or ""),
        capabilities=tuple(str(c) for c in caps),
        persona=persona,
        default_work_mode=str(meta.get("default_work_mode") or "auto"),
        builtin=builtin or bool(meta.get("builtin")),
        recommended=recommended or bool(meta.get("recommended")),
        role_dir=role_dir.resolve(),
        division=division,
        emoji=str(meta.get("emoji") or "◆"),
        color=str(meta.get("color") or ""),
        vibe=str(meta.get("vibe") or ""),
        when_to_use=str(meta.get("when_to_use") or meta.get("whenToUse") or ""),
    )


def load_roles_from_directory(
    base: Path,
    *,
    builtin: bool = False,
    recommended: bool = False,
    division_hint: str | None = None,
) -> dict[str, RoleSpec]:
    if not base.is_dir():
        return {}
    out: dict[str, RoleSpec] = {}
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name.startswith("_"):
            continue
        if child.name in _SKIP_DIR_NAMES:
            continue
        meta_path = child / ROLE_META_FILE
        if meta_path.is_file():
            spec = role_from_folder(
                child,
                builtin=builtin,
                recommended=recommended,
                division_hint=division_hint,
            )
            if spec is not None:
                out[spec.id] = spec
        else:
            # 细分领域目录（如 engineering/）→ 递归加载其下角色
            out.update(
                load_roles_from_directory(
                    child,
                    builtin=builtin,
                    recommended=recommended,
                    division_hint=child.name,
                )
            )
    return out


def role_from_mapping(role_id: str, data: dict[str, Any], *, builtin: bool = False) -> RoleSpec:
    rid = sanitize_role_id(role_id)
    persona = str(data.get("persona") or data.get("system") or "").strip()
    if not persona:
        label = str(data.get("label") or rid)
        persona = f"你是 **{label}**。\n工作区根目录（沙盒）为：{{sandbox}}"
    else:
        persona = _ensure_sandbox_in_persona(persona)
    caps = data.get("capabilities") or []
    if isinstance(caps, str):
        caps = [c.strip() for c in caps.split(",") if c.strip()]
    from auc.roles.divisions import normalize_division

    division = normalize_division(str(data.get("division") or "custom"))
    return RoleSpec(
        id=rid,
        label=str(data.get("label") or data.get("name") or rid),
        title=str(data.get("title") or data.get("label") or data.get("name") or rid),
        description=str(data.get("description") or ""),
        capabilities=tuple(str(c) for c in caps),
        persona=persona,
        default_work_mode=str(data.get("default_work_mode") or "auto"),
        builtin=builtin,
        recommended=bool(data.get("recommended")),
        role_dir=None,
        division=division,
        emoji=str(data.get("emoji") or "◆"),
        color=str(data.get("color") or ""),
        vibe=str(data.get("vibe") or ""),
        when_to_use=str(data.get("when_to_use") or data.get("whenToUse") or ""),
    )


def parse_roles_mapping(data: dict[str, Any] | None) -> dict[str, RoleSpec]:
    if not data:
        return {}
    items = data.get("roles", data) if isinstance(data, dict) else {}
    if not isinstance(items, dict):
        return {}
    out: dict[str, RoleSpec] = {}
    for key, val in items.items():
        if not isinstance(val, dict):
            continue
        try:
            spec = role_from_mapping(str(key), val)
        except ValueError:
            continue
        out[spec.id] = spec
    return out


def load_legacy_roles_yaml(path: Path) -> dict[str, RoleSpec]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_roles_mapping(data if isinstance(data, dict) else {})


def core_roles_root() -> Path:
    return package_roles_root() / "core"


def load_role_catalog(
    *,
    sandbox: str | Path | None = None,
    settings: dict[str, Any] | None = None,
    locale: str | None = None,
) -> RoleCatalog:
    from auc.roles.agency_loader import agency_bundled_root, load_agency_roles_from_directory

    merged: dict[str, RoleSpec] = load_agency_roles_from_directory(
        agency_bundled_root(locale), builtin=True, recommended=True
    )
    merged.update(
        load_roles_from_directory(
            core_roles_root(), builtin=True, recommended=True
        )
    )
    if settings:
        merged.update(parse_roles_mapping(settings.get("roles")))  # type: ignore[arg-type]
    if sandbox:
        merged.update(
            load_roles_from_directory(
                sandbox_roles_root(sandbox), builtin=False, recommended=False
            )
        )
        merged.update(load_legacy_roles_yaml(legacy_roles_yaml_path(sandbox)))

    default_id = DEFAULT_ROLE_ID
    active_id = read_active_role(sandbox)
    if settings and str(settings.get("role") or "").strip():
        try:
            candidate = sanitize_role_id(str(settings["role"]))
            if candidate in merged:
                default_id = candidate
        except ValueError:
            pass
    if active_id and active_id in merged:
        default_id = active_id

    return RoleCatalog(
        roles=merged,
        default_role_id=default_id,
        active_role_id=active_id,
    )


# 兼容旧测试导出名
roles_yaml_path = legacy_roles_yaml_path
load_roles_yaml = load_legacy_roles_yaml
