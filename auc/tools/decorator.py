from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from auc.tools.base import ToolPolicy, tool_from_function
from auc.types import ToolPrivilege

F = TypeVar("F", bound=Callable[..., Any])


def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    privilege: ToolPrivilege = "L2",
) -> Callable[[F], F]:
    """将函数标记为 AuC 工具（附加元数据供注册表使用）。"""

    def decorator(fn: F) -> F:
        fn._auc_tool_meta = {  # type: ignore[attr-defined]
            "name": name,
            "description": description,
            "privilege": privilege,
        }
        return fn

    return decorator


def register_function_tools(registry: Any, *fns: Callable[..., Any]) -> None:
    from auc.tools.registry import DefaultToolRegistry

    if not isinstance(registry, DefaultToolRegistry):
        raise TypeError("registry must be DefaultToolRegistry")
    for fn in fns:
        meta = getattr(fn, "_auc_tool_meta", {})
        ft, pol = tool_from_function(
            fn,
            name=meta.get("name"),
            description=meta.get("description"),
            privilege=meta.get("privilege", "L2"),
        )
        registry.register(ft, pol)
