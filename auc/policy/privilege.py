from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from auc.messages import ToolCall, ToolResult
from auc.policy.escalation import EscalationRule, check_escalation
from auc.ports.approval import ApprovalPort, ApprovalRequest
from auc.sandbox import SandboxViolationError, validate_path_argument
from auc.tools.base import Tool, ToolPolicy

if TYPE_CHECKING:
    from auc.loop.base import LoopContext


@dataclass
class PendingApproval:
    request_id: str
    tool_call: ToolCall
    run_id: str


def _write_diff_text(sandbox_root: str | None, arguments: dict[str, Any]) -> str:
    """write_file 审批时生成 unified diff（旧内容 vs 新内容）。"""
    path = arguments.get("path")
    new_content = arguments.get("content")
    if not isinstance(path, str) or not isinstance(new_content, str):
        return ""
    old_lines: list[str] = []
    if sandbox_root:
        try:
            from auc.sandbox import resolve_under_sandbox

            resolved = resolve_under_sandbox(sandbox_root, path)
            if resolved.is_file():
                old_lines = resolved.read_text(encoding="utf-8").splitlines(
                    keepends=True
                )
        except (ValueError, OSError):
            pass
    diff = difflib.unified_diff(
        old_lines,
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


def _build_diff_text(
    sandbox_root: str | None, tool_name: str, arguments: dict[str, Any]
) -> str:
    if tool_name == "write_file":
        return _write_diff_text(sandbox_root, arguments)
    if tool_name == "run_command":
        return str(arguments.get("command") or "")
    if isinstance(arguments.get("path"), str):
        return f"{tool_name}: {arguments['path']}"
    return ""


class ToolPrivilegeGate:
    """智能体工具的唯一裁决入口。

    裁决顺序（ADR-006）：
      escalation 升级判定 → autonomy 会话级收紧 → L3 挂起审批
      → L2 沙盒校验 → 检查点快照（mutates_files）→ tool.invoke
    """

    def __init__(
        self,
        *,
        approval: ApprovalPort | None = None,
        default_diff: str = "",
        escalation_rules: list[EscalationRule] | None = None,
    ) -> None:
        self._approval = approval
        self._default_diff = default_diff
        self._escalation_rules = escalation_rules

    async def check_and_invoke(
        self,
        tool: Tool,
        policy: ToolPolicy,
        arguments: dict[str, Any],
        *,
        ctx: LoopContext,
    ) -> ToolResult | PendingApproval:
        sandbox_root = ctx.project_rules.sandbox_root if ctx.project_rules else None

        # 以注册表 canonical policy 为准（防止 merge 降权绕过 L3）
        try:
            policy = ctx.tools.get_policy(tool.name)
        except KeyError:
            pass

        # 0) pre_tool_use hook（R14）：可拒绝/改写入参
        hooks = getattr(ctx, "hooks", None)
        if hooks is not None and hooks.has("pre_tool_use"):
            decision = await hooks.run_tool_hooks(
                "pre_tool_use",
                tool_name=tool.name,
                privilege=policy.privilege,
                context={
                    "event": "pre_tool_use",
                    "tool": tool.name,
                    "arguments": arguments,
                    "privilege": policy.privilege,
                    "run_id": ctx.run_id,
                    "agent_id": ctx.agent_id,
                },
            )
            if not decision.allow:
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content=f"hook 拒绝（pre_tool_use）：{decision.reason}",
                    is_error=True,
                )
            if isinstance(decision.arguments, dict):
                arguments = decision.arguments

        # 1) escalation：危险命令本次调用按 L3 走审批
        effective_privilege = policy.privilege
        risk_override: str | None = None
        if policy.privilege != "L3":
            rule = check_escalation(tool.name, arguments, self._escalation_rules)
            if rule is not None:
                effective_privilege = "L3"
                risk_override = f"危险操作（{rule.reason}），已升级为 L3 审批"

        # 2) autonomy：会话级收紧判定（仅收紧，不放宽 L3）
        needs_approval = effective_privilege == "L3"
        if (
            needs_approval
            and ctx.autonomy_policy is not None
            and ctx.autonomy_policy.skips_all_approval()
        ):
            needs_approval = False
        if not needs_approval and ctx.autonomy_policy is not None:
            eff_policy = ToolPolicy(
                name=policy.name,
                privilege=effective_privilege,
                sandbox_only=policy.sandbox_only,
                mutates_files=policy.mutates_files,
                mutates_state=policy.mutates_state,
            )
            if ctx.autonomy_policy.requires_approval(eff_policy):
                needs_approval = True
                risk_override = ctx.autonomy_policy.describe(policy)

        # 3) 挂起审批
        if needs_approval:
            if self._approval is None:
                if effective_privilege == "L3":
                    return ToolResult(
                        tool_call_id="",
                        name=tool.name,
                        content="L3 tool requires ApprovalPort",
                        is_error=True,
                    )
                # 自治收紧但无审批通道：按拒绝处理，避免静默放行
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content=f"{risk_override or '需人工确认'}（无可用审批通道）",
                    is_error=True,
                )
            req_id = str(uuid.uuid4())
            tc = ToolCall(id=req_id, name=tool.name, arguments=arguments)
            risk = risk_override or f"L3 工具: {tool.name}"
            if tool.name == "fetch_url" and isinstance(arguments.get("url"), str):
                risk = f"访问外部链接: {arguments['url']}"
            diff_text = (
                _build_diff_text(sandbox_root, tool.name, arguments)
                or self._default_diff
            )
            req = ApprovalRequest(
                request_id=req_id,
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
                tool_name=tool.name,
                arguments=arguments,
                diff_text=diff_text,
                risk_summary=risk,
            )
            await self._approval.request_approval(req)
            ctx.events.emit_typed(
                "approval_required",
                ctx.run_id,
                ctx.agent_id,
                {
                    "request_id": req_id,
                    "tool": tool.name,
                    "arguments": arguments,
                    "risk_summary": risk,
                    "diff_text": diff_text,
                },
            )
            return PendingApproval(request_id=req_id, tool_call=tc, run_id=ctx.run_id)

        # 4) L2 沙盒校验
        if policy.sandbox_only or policy.privilege == "L2":
            try:
                validate_path_argument(sandbox_root, arguments)
            except SandboxViolationError as exc:
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content=str(exc),
                    is_error=True,
                )

        # 5) 检查点快照（写类工具 / shell 命令记录）
        self._snapshot(ctx, policy, arguments, tool_name=tool.name)

        # 6) 调用
        result = await tool.invoke(arguments)
        result.tool_call_id = result.tool_call_id or ""
        return await self._post_tool_use(ctx, tool.name, policy.privilege, arguments, result)

    @staticmethod
    async def _post_tool_use(
        ctx: LoopContext,
        tool_name: str,
        privilege: str,
        arguments: dict[str, Any],
        result: ToolResult,
    ) -> ToolResult:
        """R14 post_tool_use：可改写结果内容。"""
        hooks = getattr(ctx, "hooks", None)
        if hooks is None or not hooks.has("post_tool_use"):
            return result
        decision = await hooks.run_tool_hooks(
            "post_tool_use",
            tool_name=tool_name,
            privilege=privilege,
            context={
                "event": "post_tool_use",
                "tool": tool_name,
                "arguments": arguments,
                "privilege": privilege,
                "result": result.content,
                "is_error": result.is_error,
                "run_id": ctx.run_id,
                "agent_id": ctx.agent_id,
            },
        )
        if decision.content is not None:
            result.content = decision.content
        return result

    @staticmethod
    def _snapshot(
        ctx: LoopContext,
        policy: ToolPolicy,
        arguments: dict[str, Any],
        *,
        tool_name: str,
    ) -> None:
        store = ctx.checkpoints
        if store is None:
            return
        if not (policy.mutates_files or policy.mutates_state):
            return
        try:
            entries = store.snapshot(
                run_id=ctx.run_id,
                step=ctx.step_index,
                tool=tool_name,
                arguments=arguments,
            )
        except OSError:
            return
        if entries:
            ctx.events.emit_typed(
                "checkpoint_created",
                ctx.run_id,
                ctx.agent_id,
                {
                    "step": ctx.step_index,
                    "files": [e.path for e in entries if e.path],
                    "ops": sorted({e.op for e in entries}),
                },
            )

    async def resolve_pending(
        self,
        pending: PendingApproval,
        *,
        ctx: LoopContext,
        tool: Tool,
    ) -> ToolResult:
        if self._approval is None:
            return ToolResult(
                tool_call_id=pending.tool_call.id,
                name=tool.name,
                content="no approval port",
                is_error=True,
            )
        decision = await self._approval.wait_decision(pending.request_id)
        if decision.approved:
            ctx.events.emit_typed(
                "approval_granted",
                ctx.run_id,
                ctx.agent_id,
                {"request_id": pending.request_id},
            )
            try:
                policy = ctx.tools.get_policy(tool.name)
            except KeyError:
                policy = ToolPolicy(name=tool.name, privilege="L3")
            self._snapshot(
                ctx, policy, pending.tool_call.arguments, tool_name=tool.name
            )
            result = await tool.invoke(pending.tool_call.arguments)
            result.tool_call_id = pending.tool_call.id
            return await self._post_tool_use(
                ctx, tool.name, policy.privilege, pending.tool_call.arguments, result
            )
        ctx.events.emit_typed(
            "approval_denied",
            ctx.run_id,
            ctx.agent_id,
            {"request_id": pending.request_id, "reason": decision.reason},
        )
        ctx.cancelled = True
        return ToolResult(
            tool_call_id=pending.tool_call.id,
            name=tool.name,
            content=decision.reason or "denied",
            is_error=True,
        )
