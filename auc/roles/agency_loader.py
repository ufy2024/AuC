"""从 agency-agents 格式的 Markdown（YAML frontmatter + 正文）加载角色。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from auc.roles.catalog import RoleSpec
from auc.roles.divisions import normalize_division
from auc.roles.loader import ROLE_ID_RE, _ensure_sandbox_in_persona, sanitize_role_id

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SKIP_DIR_NAMES = frozenset({"__pycache__", "__init__.py", ".git"})


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end() :].strip()
    return (meta if isinstance(meta, dict) else {}), body


def _role_id_from_path(path: Path, division_hint: str) -> str:
    stem = path.stem.lower().replace("_", "-")
    # engineering-frontend-developer → 保留完整 slug 避免跨领域冲突
    if not ROLE_ID_RE.match(stem):
        stem = sanitize_role_id(stem.replace(".", "-"))
    return stem


def _first_heading_summary(body: str, fallback: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return re.sub(r"^#+\s*", "", s).strip()
    return fallback


def role_from_agency_markdown(
    path: Path,
    *,
    division_hint: str,
    builtin: bool = True,
    recommended: bool = True,
) -> RoleSpec | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _parse_frontmatter(raw)
    if not body and not meta:
        return None
    try:
        rid = _role_id_from_path(path, division_hint)
    except ValueError:
        return None
    name = str(meta.get("name") or meta.get("label") or rid).strip()
    description = str(meta.get("description") or "").strip()
    persona = _ensure_sandbox_in_persona(body)
    title = _first_heading_summary(body, name)
    vibe = str(meta.get("vibe") or "").strip()
    when_to_use = str(meta.get("when_to_use") or meta.get("whenToUse") or description[:120]).strip()
    return RoleSpec(
        id=rid,
        label=name,
        title=title,
        description=description,
        capabilities=(),
        persona=persona,
        default_work_mode="auto",
        builtin=builtin,
        recommended=recommended,
        role_dir=path.resolve().parent,
        division=normalize_division(division_hint or str(meta.get("division") or "")),
        emoji=str(meta.get("emoji") or "◆"),
        color=str(meta.get("color") or ""),
        vibe=vibe,
        when_to_use=when_to_use,
    )


def load_agency_roles_from_directory(
    base: Path,
    *,
    builtin: bool = True,
    recommended: bool = True,
) -> dict[str, RoleSpec]:
    if not base.is_dir():
        return {}
    out: dict[str, RoleSpec] = {}
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIR_NAMES:
            continue
        division = child.name
        for md in sorted(child.glob("*.md")):
            if md.name.upper() == "README.MD":
                continue
            spec = role_from_agency_markdown(
                md,
                division_hint=division,
                builtin=builtin,
                recommended=recommended,
            )
            if spec is not None:
                out[spec.id] = spec
    return out


def agency_bundled_root(locale: str | None = None) -> Path:
    from auc.roles.agency_sources import ROLE_CATALOG_DIRS, normalize_role_locale
    from auc.roles.loader import package_roles_root

    loc = normalize_role_locale(locale)
    sub = ROLE_CATALOG_DIRS[loc]
    return package_roles_root() / "bundled" / sub
