"""将对话中定义的角色写入沙盒 `.auc/roles/<id>/`。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from auc.roles.constants import ROLE_META_FILE, ROLE_PROMPT_FILE
from auc.roles.loader import (
    _ensure_sandbox_in_persona,
    sanitize_role_id,
    set_active_role,
    sandbox_role_dir,
)


def _parse_capabilities(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()]
    return [c.strip() for c in str(raw).split(",") if c.strip()]


def _init_evolution_files(role_dir: Path) -> None:
    evo = role_dir / "evolution.yaml"
    if not evo.is_file():
        evo.write_text("version: 1\nepisodes: []\n", encoding="utf-8")
    nug = role_dir / "nuggets.yaml"
    if not nug.is_file():
        nug.write_text("version: 1\nnuggets: []\n", encoding="utf-8")


def write_role_definition(
    sandbox: str | Path,
    *,
    role_id: str,
    label: str,
    persona: str,
    title: str | None = None,
    description: str | None = None,
    capabilities: str | list[str] | None = None,
    default_work_mode: str = "auto",
    activate: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """在沙盒创建或更新自定义角色目录。"""
    rid = sanitize_role_id(role_id)
    label = (label or rid).strip()
    if not label:
        raise ValueError("label required")
    persona_text = _ensure_sandbox_in_persona(persona.strip())
    if not persona_text:
        raise ValueError("persona required")

    role_dir = sandbox_role_dir(sandbox, rid)
    meta_path = role_dir / ROLE_META_FILE
    prompt_path = role_dir / ROLE_PROMPT_FILE
    if meta_path.is_file() and not overwrite:
        raise FileExistsError(f"role already exists: {rid}")

    role_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": rid,
        "label": label,
        "title": (title or label).strip(),
        "description": (description or "").strip(),
        "capabilities": _parse_capabilities(capabilities),
        "default_work_mode": (default_work_mode or "auto").strip() or "auto",
        "builtin": False,
        "recommended": False,
    }
    meta_path.write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    prompt_path.write_text(persona_text + "\n", encoding="utf-8")
    _init_evolution_files(role_dir)

    if activate:
        set_active_role(sandbox, rid)

    return {
        "role_id": rid,
        "label": label,
        "activated": activate,
        "path": str(role_dir.resolve()),
    }


def update_role_definition(
    sandbox: str | Path,
    role_id: str,
    *,
    label: str | None = None,
    persona: str | None = None,
    title: str | None = None,
    description: str | None = None,
    capabilities: str | list[str] | None = None,
    default_work_mode: str | None = None,
    activate: bool = False,
) -> dict[str, Any]:
    rid = sanitize_role_id(role_id)
    role_dir = sandbox_role_dir(sandbox, rid)
    meta_path = role_dir / ROLE_META_FILE
    if not meta_path.is_file():
        raise FileNotFoundError(f"custom role not found in sandbox: {rid}")

    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    if not isinstance(meta, dict):
        meta = {}
    if label is not None:
        meta["label"] = label.strip()
    if title is not None:
        meta["title"] = title.strip()
    if description is not None:
        meta["description"] = description.strip()
    if capabilities is not None:
        meta["capabilities"] = _parse_capabilities(capabilities)
    if default_work_mode is not None:
        meta["default_work_mode"] = default_work_mode.strip() or "auto"

    meta_path.write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    if persona is not None:
        text = _ensure_sandbox_in_persona(persona.strip())
        (role_dir / ROLE_PROMPT_FILE).write_text(text + "\n", encoding="utf-8")

    _init_evolution_files(role_dir)
    if activate:
        set_active_role(sandbox, rid)

    return {
        "role_id": rid,
        "label": str(meta.get("label") or rid),
        "activated": activate,
        "path": str(role_dir.resolve()),
        "updated": True,
    }
