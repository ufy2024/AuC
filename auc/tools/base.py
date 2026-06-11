from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from auc.messages import ToolResult
from auc.types import ToolPrivilege


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolPolicy:
    name: str
    privilege: ToolPrivilege
    sandbox_only: bool = False
    mutates_files: bool = False  # R4：写文件类工具，触发检查点快照
    mutates_state: bool = False  # R6：改系统状态（shell/git 等），受自治级别管控


class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult: ...


@dataclass
class FunctionTool:
    _name: str
    _description: str
    _fn: Callable[..., Any]
    _parameters: dict[str, Any]

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = self._fn(**arguments)
            if inspect.isawaitable(result):
                result = await result
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=content,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=str(exc),
                is_error=True,
            )


def _json_schema_from_fn(fn: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        if isinstance(param.default, bool) or param.annotation in (bool, "bool"):
            ptype = "boolean"
        elif isinstance(param.default, int) or param.annotation in (int, "int"):
            ptype = "integer"
        else:
            ptype = "string"
        props[pname] = {"type": ptype, "description": pname}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


def tool_from_function(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    privilege: ToolPrivilege = "L2",
    mutates_files: bool = False,
    mutates_state: bool = False,
) -> tuple[FunctionTool, ToolPolicy]:
    tname = name or fn.__name__
    desc = description or (fn.__doc__ or "").strip() or tname
    ft = FunctionTool(
        _name=tname,
        _description=desc,
        _fn=fn,
        _parameters=_json_schema_from_fn(fn),
    )
    pol = ToolPolicy(
        name=tname,
        privilege=privilege,
        sandbox_only=privilege == "L2",
        mutates_files=mutates_files,
        mutates_state=mutates_state,
    )
    return ft, pol
