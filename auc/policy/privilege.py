from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from auc.messages import ToolCall, ToolResult
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


class ToolPrivilegeGate:
    def __init__(
        self,
        *,
        approval: ApprovalPort | None = None,
        default_diff: str = "",
    ) -> None:
        self._approval = approval
        self._default_diff = default_diff

    async def check_and_invoke(
        self,
        tool: Tool,
        policy: ToolPolicy,
        arguments: dict[str, Any],
        *,
        ctx: LoopContext,
    ) -> ToolResult | PendingApproval:
        if policy.privilege == "L3":
            if self._approval is None:
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content="L3 tool requires ApprovalPort",
                    is_error=True,
                )
            req_id = str(uuid.uuid4())
            tc = ToolCall(id=req_id, name=tool.name, arguments=arguments)
            req = ApprovalRequest(
                request_id=req_id,
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
                tool_name=tool.name,
                arguments=arguments,
                diff_text=self._default_diff,
                risk_summary=f"L3 tool invocation: {tool.name}",
            )
            await self._approval.request_approval(req)
            ctx.events.emit_typed(
                "approval_required",
                ctx.run_id,
                ctx.agent_id,
                {"request_id": req_id, "tool": tool.name},
            )
            return PendingApproval(request_id=req_id, tool_call=tc, run_id=ctx.run_id)

        if policy.sandbox_only or policy.privilege == "L2":
            root = ctx.project_rules.sandbox_root if ctx.project_rules else None
            try:
                validate_path_argument(root, arguments)
            except SandboxViolationError as exc:
                return ToolResult(
                    tool_call_id="",
                    name=tool.name,
                    content=str(exc),
                    is_error=True,
                )

        result = await tool.invoke(arguments)
        result.tool_call_id = result.tool_call_id or ""
        return result

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
            result = await tool.invoke(pending.tool_call.arguments)
            result.tool_call_id = pending.tool_call.id
            return result
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
