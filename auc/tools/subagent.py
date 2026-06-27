"""R13 子智能体工具：`spawn_subagent(task, kind)`。

在当前 Run 内派生一个**一层嵌套**的子智能体，拥有独立窗口/预算，运行结束后
返回精简回执块（paths/commands/tests，复用 R28）。子 Run 经检查点/回执沉淀，可
单独 `auc undo` / `auc receipt` 追溯。父 Run 上 emit `subagent_start`/`subagent_end`。

约束：
  - 仅一层嵌套：子智能体注册时不含本工具；运行期再以 `parent_run_id` 兜底拒绝。
  - 子 Run 复用父进程的模型客户端与沙盒，避免连接泄漏与越权。
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from auc.messages import RunRequest
from auc.receipt import ReceiptStore, RunReceipt, render_receipt_block
from auc.run_context import current_loop_context
from auc.tools.base import ToolPolicy, tool_from_function

# kind(role_id) -> 已构建的子智能体（DefaultAgent）。
SubagentBuilder = Callable[[str], Any]


def make_subagent_tool(
    *,
    build_agent: SubagentBuilder,
    sandbox: str,
    allowed_kinds: list[str],
    default_kind: str,
) -> tuple[Any, ToolPolicy]:
    kinds = [k for k in allowed_kinds if k]
    kinds_text = ", ".join(kinds) if kinds else default_kind

    async def spawn_subagent(task: str, kind: str = "") -> str:
        task = (task or "").strip()
        if not task:
            raise ValueError("task 不能为空")
        ctx = current_loop_context.get()
        if ctx is not None and getattr(ctx, "parent_run_id", None):
            raise ValueError("子智能体不可再派生子智能体（仅支持一层嵌套）")

        rid = (kind or "").strip() or default_kind
        if kinds and rid not in kinds:
            raise ValueError(f"未知 kind={rid!r}；可选：{kinds_text}")

        child_run_id = f"sub-{uuid.uuid4().hex[:12]}"
        parent_run_id = str(ctx.run_id) if ctx is not None else child_run_id
        if ctx is not None:
            ctx.events.emit_typed(
                "subagent_start",
                ctx.run_id,
                ctx.agent_id,
                {"child_run_id": child_run_id, "kind": rid, "task": task[:200]},
            )

        child = build_agent(rid)
        request = RunRequest(
            input=task,
            run_id=child_run_id,
            metadata={
                "parent_run_id": parent_run_id,
                "role_id": rid,
                "autonomy": "full-auto",
            },
        )
        result = await child.run(request)

        receipt = ReceiptStore(sandbox).read(child_run_id) or RunReceipt(
            run_id=child_run_id,
            agent_id=f"chat:{rid}",
            status=result.status,
            error=result.error,
        )
        block = render_receipt_block(receipt, output=result.output or "")

        if ctx is not None:
            ctx.events.emit_typed(
                "subagent_end",
                ctx.run_id,
                ctx.agent_id,
                {
                    "child_run_id": child_run_id,
                    "kind": rid,
                    "status": result.status,
                    "changed_files": [c.path for c in receipt.changed_files],
                    "commands": len(receipt.commands),
                },
            )
        return block

    return tool_from_function(
        spawn_subagent,
        name="spawn_subagent",
        description=(
            "派生一个子智能体完成相对独立的子任务（一层嵌套，独立上下文与预算）。"
            f"kind 选择角色：{kinds_text}。返回子 Run 的精简回执（改动文件/命令/验证），"
            "适合并行化或隔离探索；子 Run 可经 auc receipt/undo 追溯。"
        ),
        privilege="L2",
        mutates_files=True,
        mutates_state=True,
    )
