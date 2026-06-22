"""内置工具权限下限：项目配置 merge 时不可降级。"""

from __future__ import annotations

from auc.types import ToolPrivilege

_PRIV_ORDER: dict[ToolPrivilege, int] = {"L1": 1, "L2": 2, "L3": 3}

# 内置高危工具最低权限（与注册默认值一致，不可被 .aurules 降权）
MIN_TOOL_PRIVILEGE: dict[str, ToolPrivilege] = {
    "fetch_url": "L3",
    "run_command": "L2",
    "write_file": "L2",
    "delete_path": "L2",
    "delete_file": "L2",
}


def max_privilege(a: ToolPrivilege, b: ToolPrivilege) -> ToolPrivilege:
    return a if _PRIV_ORDER[a] >= _PRIV_ORDER[b] else b


def floor_privilege(tool_name: str, requested: ToolPrivilege) -> ToolPrivilege:
    floor = MIN_TOOL_PRIVILEGE.get(tool_name, "L1")
    return max_privilege(requested, floor)
