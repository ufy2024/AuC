"""Web 技能选择设置（读写沙盒 .auc/skills/settings.json）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auc.skills import AUTO_SKILL_MODE, SkillPrefs, slugify


def skill_settings_path(sandbox_root: str) -> Path:
    return Path(sandbox_root).resolve() / ".auc" / "skills" / "settings.json"


def load_skill_prefs(sandbox_root: str) -> SkillPrefs:
    path = skill_settings_path(sandbox_root)
    if not path.is_file():
        return SkillPrefs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return SkillPrefs()
    if not isinstance(data, dict):
        return SkillPrefs()
    mode = str(data.get("mode") or AUTO_SKILL_MODE)
    pinned_raw = data.get("pinned") or []
    pinned = [slugify(str(x)) for x in pinned_raw if str(x).strip()]
    return SkillPrefs(mode="manual" if mode == "manual" else "auto", pinned=pinned).normalized()


def save_skill_prefs(sandbox_root: str, prefs: SkillPrefs) -> Path:
    path = skill_settings_path(sandbox_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    p = prefs.normalized()
    data = {"mode": p.mode, "pinned": p.pinned}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def skill_settings_payload(sandbox_root: str, *, locale: str = "zh") -> dict[str, Any]:
    prefs = load_skill_prefs(sandbox_root)
    zh = not locale.lower().startswith("en")
    return {
        "mode": prefs.mode,
        "pinned": prefs.pinned,
        "modes": [
            {
                "id": "auto",
                "label": "智能选择" if zh else "Auto",
                "hint": "按消息触发词与当前角色自动匹配技能" if zh else "Match skills by triggers and active role",
            },
            {
                "id": "manual",
                "label": "手动选择" if zh else "Manual",
                "hint": "仅使用你在技能广场勾选的技能" if zh else "Use only skills pinned in Skill Plaza",
            },
        ],
    }
