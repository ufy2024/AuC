"""R14 生命周期 Hooks：配置驱动的外部命令钩子（Claude Code 式 exit-code 协议）。

事件：`pre_tool_use`（可拒绝/改参）、`post_tool_use`（可改写结果）、`run_start`、
`run_end`、`pre_compact`。配置来源：`settings.json.hooks` 与沙盒 `.auc/hooks.json`
合并。

协议（对齐 Claude Code）：
  - hook 进程 stdin 收 JSON 事件上下文；
  - exit 0 放行；exit 2 拒绝（stderr 作为原因）；其他非零=非阻断错误（放行+警告）；
  - stdout 若为 JSON：`{"arguments": {...}}` 改写入参（pre）、`{"content": "..."}`
    改写结果（post）、`{"decision": "block", "reason": "..."}` 显式拒绝。
  - 超时 10s：L1 读超时→放行+警告；L2 写超时→拒绝；L3 永不因 hook 超时被放行
    （超时即回退到正常审批链，不授予通过）。

守恒：纯标准库，零新增依赖；hook 失败绝不影响框架自身的 `.auc/` 写入。
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HOOK_EVENTS = (
    "pre_tool_use",
    "post_tool_use",
    "run_start",
    "run_end",
    "pre_compact",
)
_DEFAULT_TIMEOUT = 10.0


@dataclass
class HookSpec:
    event: str
    command: str
    matcher: str = "*"  # 工具名 glob；多个用 "|" 分隔；仅 *_tool_use 事件生效
    timeout: float = _DEFAULT_TIMEOUT


@dataclass
class HookDecision:
    allow: bool = True
    reason: str = ""
    arguments: dict[str, Any] | None = None  # pre_tool_use 改写后的入参
    content: str | None = None  # post_tool_use 改写后的结果
    warnings: list[str] = field(default_factory=list)


def _matches(matcher: str, tool_name: str) -> bool:
    matcher = (matcher or "").strip()
    if not matcher or matcher == "*":
        return True
    return any(
        fnmatch.fnmatch(tool_name, part.strip())
        for part in matcher.split("|")
        if part.strip()
    )


def _parse_specs(raw: Any) -> dict[str, list[HookSpec]]:
    out: dict[str, list[HookSpec]] = {}
    if not isinstance(raw, dict):
        return out
    for event, items in raw.items():
        if event not in HOOK_EVENTS or not isinstance(items, list):
            continue
        specs: list[HookSpec] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            command = str(item.get("command") or "").strip()
            if not command:
                continue
            try:
                timeout = float(item.get("timeout") or _DEFAULT_TIMEOUT)
            except (TypeError, ValueError):
                timeout = _DEFAULT_TIMEOUT
            specs.append(
                HookSpec(
                    event=event,
                    command=command,
                    matcher=str(item.get("matcher") or "*"),
                    timeout=max(0.5, min(timeout, 120.0)),
                )
            )
        if specs:
            out[event] = specs
    return out


def _merge(*configs: dict[str, list[HookSpec]]) -> dict[str, list[HookSpec]]:
    merged: dict[str, list[HookSpec]] = {}
    for cfg in configs:
        for event, specs in cfg.items():
            merged.setdefault(event, []).extend(specs)
    return merged


class HookRunner:
    def __init__(
        self, hooks: dict[str, list[HookSpec]], sandbox_root: str | None = None
    ) -> None:
        self._hooks = hooks
        self._sandbox = sandbox_root

    def has(self, event: str) -> bool:
        return bool(self._hooks.get(event))

    def specs_for(self, event: str, tool_name: str | None = None) -> list[HookSpec]:
        specs = self._hooks.get(event) or []
        if tool_name is None:
            return list(specs)
        return [s for s in specs if _matches(s.matcher, tool_name)]

    async def _exec(self, spec: HookSpec, context: dict[str, Any]) -> tuple[int | None, str, str]:
        """执行单个 hook；返回 (exit_code|None=超时, stdout, stderr)。"""
        try:
            proc = await asyncio.create_subprocess_shell(
                spec.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._sandbox or None,
                env=os.environ.copy(),
            )
        except OSError as exc:
            return 1, "", f"hook 启动失败: {exc}"
        payload = json.dumps(context, ensure_ascii=False).encode("utf-8")
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(payload), timeout=spec.timeout
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 进程可能已退出或无权限终止
                pass
            return None, "", f"hook 超时（>{spec.timeout:g}s）"
        return (
            proc.returncode,
            (out_b or b"").decode("utf-8", errors="replace").strip(),
            (err_b or b"").decode("utf-8", errors="replace").strip(),
        )

    @staticmethod
    def _apply_stdout(stdout: str, decision: HookDecision, *, is_pre: bool) -> bool:
        """解析 hook stdout JSON 改写 decision；返回是否被显式拒绝。"""
        if not stdout:
            return False
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        if str(data.get("decision") or "").lower() in ("block", "deny"):
            decision.allow = False
            decision.reason = str(data.get("reason") or "hook 拒绝")
            return True
        if is_pre and isinstance(data.get("arguments"), dict):
            decision.arguments = data["arguments"]
        if not is_pre and isinstance(data.get("content"), str):
            decision.content = data["content"]
        return False

    async def run_tool_hooks(
        self,
        event: str,
        *,
        tool_name: str,
        privilege: str,
        context: dict[str, Any],
    ) -> HookDecision:
        decision = HookDecision()
        specs = self.specs_for(event, tool_name)
        if not specs:
            return decision
        is_pre = event == "pre_tool_use"
        ctx = dict(context)
        for spec in specs:
            code, stdout, stderr = await self._exec(spec, ctx)
            if code is None:  # 超时
                if privilege == "L1":
                    decision.warnings.append(stderr or "hook 超时（L1 放行）")
                    continue
                if privilege == "L2":
                    decision.allow = False
                    decision.reason = stderr or "hook 超时（L2 拒绝）"
                    return decision
                # L3：超时不授予通过，交回正常审批链
                decision.warnings.append(stderr or "hook 超时（L3 回退审批）")
                continue
            if code == 2:
                decision.allow = False
                decision.reason = stderr or "hook 拒绝（exit 2）"
                return decision
            if code != 0:
                decision.warnings.append(stderr or f"hook 非阻断错误（exit {code}）")
                continue
            blocked = self._apply_stdout(stdout, decision, is_pre=is_pre)
            if blocked:
                return decision
            if is_pre and decision.arguments is not None:
                ctx["arguments"] = decision.arguments
        return decision

    async def run_lifecycle(self, event: str, context: dict[str, Any]) -> list[str]:
        """run_start/run_end/pre_compact：尽力执行，仅收集警告，不阻断。"""
        warnings: list[str] = []
        for spec in self.specs_for(event):
            code, _stdout, stderr = await self._exec(spec, context)
            if code not in (0, None) and stderr:
                warnings.append(stderr)
        return warnings


def load_hooks(
    settings: dict[str, Any] | None, sandbox_root: str | None
) -> HookRunner | None:
    """合并 settings.hooks 与沙盒 .auc/hooks.json；无配置返回 None。"""
    from_settings = _parse_specs((settings or {}).get("hooks"))
    from_file: dict[str, list[HookSpec]] = {}
    if sandbox_root:
        path = Path(sandbox_root) / ".auc" / "hooks.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                from_file = _parse_specs(
                    data.get("hooks") if isinstance(data, dict) and "hooks" in data else data
                )
            except (json.JSONDecodeError, OSError):
                from_file = {}
    merged = _merge(from_settings, from_file)
    if not merged:
        return None
    return HookRunner(merged, sandbox_root=sandbox_root)
