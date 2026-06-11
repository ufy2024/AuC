from __future__ import annotations

import asyncio

from auc.loop.base import (
    AgentLoop,
    LoopContext,
    LoopStepResult,
    _assistant_chat_message,
    _last_user_content,
    _tool_chat_message,
    default_compose,
)
from auc.messages import ToolResult
from auc.model.client import AssistantMessage
from auc.model.json_util import PARSE_ERROR_KEY
from auc.model.streaming import stream_to_assistant
from auc.plan import parse_plan_block
from auc.policy.privilege import PendingApproval, ToolPrivilegeGate


class ReActLoop:
    async def step(self, ctx: LoopContext) -> LoopStepResult:
        if ctx.compactor is not None:
            try:
                await ctx.compactor.maybe_compact(ctx.window, ctx)
            except Exception:  # noqa: BLE001 压缩失败不致命，下步重试
                pass

        recall: list = []
        if ctx.memory is not None:
            query = _last_user_content(ctx.window)
            recall = await ctx.memory.recall(
                query,
                limit=10,
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
            )

        messages = await default_compose(ctx, recall)
        schemas = ctx.tools.list_schemas()

        async def _on_delta(text: str) -> None:
            ctx.events.emit_typed(
                "model_delta",
                ctx.run_id,
                ctx.agent_id,
                {"delta": text},
            )

        assistant = await stream_to_assistant(
            ctx.model,
            messages,
            schemas or None,
            on_delta=_on_delta,
        )

        if assistant.tool_calls:
            ctx.events.emit_typed(
                "model_delta",
                ctx.run_id,
                ctx.agent_id,
                {
                    "tool_calls": [
                        {"name": tc.name, "id": tc.id}
                        for tc in assistant.tool_calls
                    ],
                },
            )

        tool_results: list[ToolResult] = []
        gate = ctx.privilege_gate or ToolPrivilegeGate(approval=ctx.approval)

        if assistant.tool_calls:
            ctx.window.append(_assistant_chat_message(assistant))
            if ctx.config.parallel_tool_calls:
                tool_results = await self._invoke_all(ctx, assistant, gate)
            else:
                for tc in assistant.tool_calls:
                    tr = await self._invoke_one(ctx, tc.id, tc.name, tc.arguments, gate)
                    tool_results.append(tr)
            for tr in tool_results:
                ctx.window.append(_tool_chat_message(tr))
        elif assistant.content:
            ctx.window.append(_assistant_chat_message(assistant))

        if ctx.memory and ctx.config.remember_each_step:
            await ctx.memory.remember(
                ctx.window.view(),
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
            )

        done = not assistant.tool_calls and bool(assistant.content)
        if done:
            plan = parse_plan_block(assistant.content)
            if plan is not None:
                ctx.events.emit_typed(
                    "plan_ready",
                    ctx.run_id,
                    ctx.agent_id,
                    {"plan": plan, "schema_version": 2},
                )
        return LoopStepResult(
            assistant_message=assistant,
            tool_results=tool_results,
            step_index=ctx.step_index,
            done=done,
        )

    async def _invoke_all(
        self,
        ctx: LoopContext,
        assistant: AssistantMessage,
        gate: ToolPrivilegeGate,
    ) -> list[ToolResult]:
        assert assistant.tool_calls
        tasks = [
            self._invoke_one(ctx, tc.id, tc.name, tc.arguments, gate)
            for tc in assistant.tool_calls
        ]
        return list(await asyncio.gather(*tasks))

    async def _invoke_one(
        self,
        ctx: LoopContext,
        tool_call_id: str,
        name: str,
        arguments: dict,
        gate: ToolPrivilegeGate,
    ) -> ToolResult:
        ctx.events.emit_typed(
            "tool_start",
            ctx.run_id,
            ctx.agent_id,
            {"tool": name, "arguments": arguments},
        )
        if PARSE_ERROR_KEY in arguments:
            # 流式参数 JSON 截断/损坏：以工具错误反馈模型，run 继续
            tr = ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=str(arguments[PARSE_ERROR_KEY]),
                is_error=True,
            )
            ctx.events.emit_typed(
                "tool_end",
                ctx.run_id,
                ctx.agent_id,
                {"tool": name, "is_error": True, "summary": tr.content[:120]},
            )
            return tr
        tool = ctx.tools.get(name)
        if tool is None:
            tr = ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"unknown tool: {name}",
                is_error=True,
            )
        else:
            policy = ctx.tools.get_policy(name)
            if ctx.project_rules and name in ctx.project_rules.tool_policy:
                policy.privilege = ctx.project_rules.tool_policy[name]
            outcome = await gate.check_and_invoke(
                tool, policy, arguments, ctx=ctx
            )
            if isinstance(outcome, PendingApproval):
                tr = await gate.resolve_pending(outcome, ctx=ctx, tool=tool)
            else:
                tr = outcome
            tr.tool_call_id = tool_call_id
            tr.name = name

        summary = (tr.content or "").replace("\n", " ").strip()
        if len(summary) > 120:
            summary = summary[:117] + "..."
        ctx.events.emit_typed(
            "tool_end",
            ctx.run_id,
            ctx.agent_id,
            {
                "tool": name,
                "is_error": tr.is_error,
                "summary": summary,
            },
        )
        return tr

    def should_continue(self, ctx: LoopContext, last: LoopStepResult) -> bool:
        if ctx.cancelled:
            return False
        if last.done:
            return False
        if ctx.step_index >= ctx.config.max_steps:
            return False
        return True
