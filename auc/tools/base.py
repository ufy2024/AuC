from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from auc.messages import ToolResult
from auc.types import ToolPrivilege

logger = logging.getLogger("auc.tools")


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

    def _validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        """对照函数签名校验参数：拒绝未知键、报告缺失必填项。返回错误信息或 None。"""
        sig = inspect.signature(self._fn)
        params = {
            n: p
            for n, p in sig.parameters.items()
            if n not in ("self", "cls")
        }
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if not accepts_kwargs:
            unknown = [k for k in arguments if k not in params]
            if unknown:
                return f"unexpected argument(s): {', '.join(sorted(unknown))}"
        missing = [
            n
            for n, p in params.items()
            if p.default is inspect.Parameter.empty
            and p.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and n not in arguments
        ]
        if missing:
            return f"missing required argument(s): {', '.join(missing)}"
        return None

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        if not isinstance(arguments, dict):
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content="arguments must be a JSON object",
                is_error=True,
            )
        schema_err = self._validate_arguments(arguments)
        if schema_err is not None:
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=schema_err,
                is_error=True,
            )
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
        except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
            # 预期内的用户/环境错误：原文反馈，便于模型自纠
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=str(exc),
                is_error=True,
            )
        except Exception:  # noqa: BLE001 非预期错误：记录完整栈，对模型泛化
            logger.exception("tool %s raised an unexpected error", self._name)
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=f"internal error in tool {self._name}",
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
