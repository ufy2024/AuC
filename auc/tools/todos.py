"""R10：任务清单工具 `update_todos`。

模型用它维护一份会话内的结构化任务清单，便于在多步任务中规划与展示进度。
工具本身只读写 `LoopContext.todos` 并 emit `todos_updated` 事件，不触碰文件/系统状态。
"""

from __future__ import annotations

import json
from typing import Any

from auc.run_context import current_loop_context
from auc.tools.base import FunctionTool, ToolPolicy

VALID_STATUS = ("pending", "in_progress", "completed", "cancelled")

_TODOS_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "description": "任务清单。默认整体替换旧清单（除非 merge=true）。",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "任务稳定标识"},
                    "content": {"type": "string", "description": "任务描述"},
                    "status": {
                        "type": "string",
                        "enum": list(VALID_STATUS),
                        "description": "pending / in_progress / completed / cancelled",
                    },
                },
                "required": ["id", "content", "status"],
            },
        },
        "merge": {
            "type": "boolean",
            "description": "true 则按 id 合并到现有清单；false（默认）整体替换。",
        },
    },
    "required": ["todos"],
}


def _normalize_todos(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise ValueError("todos must be a list of {id, content, status}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"todos[{i}] must be an object")
        tid = str(item.get("id") or "").strip() or f"todo-{i + 1}"
        content = str(item.get("content") or "").strip()
        if not content:
            raise ValueError(f"todos[{i}].content is required")
        status = str(item.get("status") or "pending").strip()
        if status not in VALID_STATUS:
            raise ValueError(
                f"todos[{i}].status must be one of {', '.join(VALID_STATUS)}"
            )
        if tid in seen:
            raise ValueError(f"duplicate todo id: {tid}")
        seen.add(tid)
        out.append({"id": tid, "content": content, "status": status})
    return out


def update_todos(todos: Any, merge: bool = False) -> str:
    """创建或更新当前任务清单（结构化 todo），用于多步任务的规划与进度展示。"""
    incoming = _normalize_todos(todos)
    ctx = current_loop_context.get()
    if merge and ctx is not None and ctx.todos:
        by_id = {t["id"]: dict(t) for t in ctx.todos if isinstance(t, dict) and t.get("id")}
        for t in incoming:
            by_id[t["id"]] = t
        result = list(by_id.values())
    else:
        result = incoming

    if ctx is not None:
        ctx.todos = result
        ctx.events.emit_typed(
            "todos_updated",
            ctx.run_id,
            ctx.agent_id,
            {"todos": result},
        )

    done = sum(1 for t in result if t["status"] == "completed")
    return json.dumps(
        {"ok": True, "total": len(result), "completed": done, "todos": result},
        ensure_ascii=False,
    )


def make_todos_tool() -> tuple[FunctionTool, ToolPolicy]:
    tool = FunctionTool(
        _name="update_todos",
        _description=(
            "维护一份结构化任务清单，用于规划并展示多步任务的进度。"
            "传入完整 todos 列表（每项含 id/content/status）；默认整体替换，"
            "merge=true 时按 id 增量更新。status ∈ {pending, in_progress, completed, cancelled}。"
            "建议复杂任务（3+ 步）开始时建清单，并在每步完成后及时更新状态。"
        ),
        _fn=update_todos,
        _parameters=_TODOS_PARAMETERS,
    )
    policy = ToolPolicy(name="update_todos", privilege="L1")
    return tool, policy
