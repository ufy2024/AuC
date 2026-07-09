"""Web 授权模式设置（读写 settings.json）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auc.config import load_merged_settings, load_raw_config_file
from auc.policy.autonomy import (
    ApprovalPrefs,
    approval_mode_spec,
    approval_modes_payload,
    auto_approve_permitted,
    normalize_approval_mode,
    resolve_approval_prefs,
)
from auc.web.model_settings import Scope, settings_path_for_scope


def approval_settings_payload(
    sandbox_root: str,
    *,
    bind_host: str | None = None,
    locale: str = "zh",
    scope: Scope | None = None,
) -> dict[str, Any]:
    settings, _ = load_merged_settings(None, Path(sandbox_root))
    prefs = resolve_approval_prefs(settings, bind_host=bind_host)
    spec = approval_mode_spec(prefs.mode_id)
    return {
        "mode": prefs.mode_id,
        "autonomy": prefs.autonomy,
        "auto_approve": prefs.auto_approve,
        "auto_approve_available": auto_approve_permitted(bind_host),
        "label": spec.label_en if locale.lower().startswith("en") else spec.label_zh,
        "hint": spec.hint_en if locale.lower().startswith("en") else spec.hint_zh,
        "modes": approval_modes_payload(locale=locale),
        "active_scope": scope or "project_local",
    }


def save_approval_settings(
    sandbox_root: str,
    *,
    mode_id: str,
    scope: Scope = "project_local",
    bind_host: str | None = None,
) -> tuple[ApprovalPrefs, Path]:
    spec = approval_mode_spec(mode_id)
    if spec.auto_approve and not auto_approve_permitted(bind_host):
        raise ValueError("「全部通过」仅允许在本地绑定 (127.0.0.1 / localhost) 下启用")

    path = settings_path_for_scope(scope, sandbox_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data = load_raw_config_file(path)
        if not isinstance(data, dict):
            data = {}
    else:
        data = {}

    data["autonomy"] = spec.autonomy
    approval = data.get("approval")
    if not isinstance(approval, dict):
        approval = {}
    approval["mode"] = normalize_approval_mode(mode_id)
    approval["auto_approve"] = spec.auto_approve
    data["approval"] = approval

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prefs = resolve_approval_prefs(data, bind_host=bind_host)
    return prefs, path
