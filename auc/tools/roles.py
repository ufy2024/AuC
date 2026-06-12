"""对话定义 / 切换角色工具。"""

from __future__ import annotations

import json
from typing import Any

from auc.roles import load_role_catalog, parse_role_from_agent_id, set_active_role
from auc.roles.writer import update_role_definition, write_role_definition
from auc.run_context import current_agent_id
from auc.tools.base import ToolPolicy, tool_from_function


def _current_role_id(sandbox: str, explicit: str | None = None) -> str:
    if explicit and str(explicit).strip():
        return load_role_catalog(sandbox=sandbox).resolve(str(explicit))
    aid = current_agent_id.get()
    parsed = parse_role_from_agent_id(aid)
    if parsed:
        return load_role_catalog(sandbox=sandbox).resolve(parsed)
    return load_role_catalog(sandbox=sandbox).default_role_id


def make_role_tools(sandbox: str) -> list[tuple[Any, ToolPolicy]]:
    def define_role(
        role_id: str,
        label: str,
        persona: str,
        title: str = "",
        description: str = "",
        capabilities: str = "",
        default_work_mode: str = "auto",
        activate: bool = True,
    ) -> str:
        """根据对话内容在沙盒创建自定义角色并可选设为当前角色。"""
        result = write_role_definition(
            sandbox,
            role_id=role_id,
            label=label,
            persona=persona,
            title=title or None,
            description=description or None,
            capabilities=capabilities or None,
            default_work_mode=default_work_mode,
            activate=activate,
            overwrite=False,
        )
        return json.dumps(result, ensure_ascii=False)

    def update_role(
        role_id: str = "",
        persona: str = "",
        label: str = "",
        title: str = "",
        description: str = "",
        capabilities: str = "",
        default_work_mode: str = "",
        activate: bool = False,
    ) -> str:
        """更新沙盒内已有自定义角色的 prompt 或元数据。"""
        rid = _current_role_id(sandbox, role_id or None)
        result = update_role_definition(
            sandbox,
            rid,
            label=label or None,
            persona=persona or None,
            title=title or None,
            description=description or None,
            capabilities=capabilities or None,
            default_work_mode=default_work_mode or None,
            activate=activate,
        )
        return json.dumps(result, ensure_ascii=False)

    def switch_role(role_id: str) -> str:
        """切换当前活跃角色（写入 .auc/roles/active）。"""
        catalog = load_role_catalog(sandbox=sandbox)
        rid = catalog.resolve(role_id)
        set_active_role(sandbox, rid)
        spec = catalog.get(rid)
        return json.dumps(
            {
                "role_id": rid,
                "label": spec.label,
                "activated": True,
            },
            ensure_ascii=False,
        )

    return [
        tool_from_function(
            define_role,
            name="define_role",
            description=(
                "在沙盒 .auc/roles/<role_id>/ 创建自定义角色（role.yaml + prompt.md），"
                "并初始化该角色的 evolution.yaml / nuggets.yaml。"
                "与用户澄清定位与能力后调用；role_id 为小写英文 slug（如 stock-analyst）。"
                "persona 为完整系统人格说明（Markdown）；activate=true 时设为当前角色。"
            ),
            privilege="L2",
            mutates_files=True,
        ),
        tool_from_function(
            update_role,
            name="update_role",
            description=(
                "更新沙盒内自定义角色的 prompt.md 或 role.yaml 元数据。"
                "role_id 留空则更新当前角色；仅更新传入的非空字段。"
            ),
            privilege="L2",
            mutates_files=True,
        ),
        tool_from_function(
            switch_role,
            name="switch_role",
            description="切换到已有角色（写入 .auc/roles/active），不改变 prompt 文件。",
            privilege="L1",
        ),
    ]
