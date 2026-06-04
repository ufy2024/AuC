from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from auc.messages import ToolCall
from auc.model.client import AssistantMessage, ModelClient, StreamChunk
from auc.tools.base import ToolSchema

OnDelta = Callable[[str], object]


async def stream_to_assistant(
    model: ModelClient,
    messages: list,
    tools: list[ToolSchema] | None,
    *,
    on_delta: OnDelta | None = None,
) -> AssistantMessage:
    """Consume complete_stream; optionally invoke on_delta per text chunk."""
    content_parts: list[str] = []
    tool_acc: dict[int, dict[str, Any]] = {}

    async for chunk in model.complete_stream(messages, tools=tools):
        if chunk.delta_content:
            content_parts.append(chunk.delta_content)
            if on_delta is not None:
                out = on_delta(chunk.delta_content)
                if inspect.isawaitable(out):
                    await out
        if chunk.delta_tool_calls:
            for tc in chunk.delta_tool_calls:
                _merge_tool_call_delta(tool_acc, tc)

    content = "".join(content_parts) or None
    tool_calls = _tool_acc_to_list(tool_acc) if tool_acc else None
    return AssistantMessage(content=content, tool_calls=tool_calls)


def _merge_tool_call_delta(acc: dict[int, dict[str, Any]], tc: ToolCall) -> None:
    """OpenAI streaming may send partial tool calls; merge by index when present in raw."""
    idx = 0
    if tc.id and not any(acc.get(i, {}).get("id") == tc.id for i in acc):
        idx = len(acc)
    entry = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
    if tc.id:
        entry["id"] = tc.id
    if tc.name:
        entry["name"] = tc.name
    if tc.arguments:
        if isinstance(tc.arguments, dict):
            prev = entry.get("_args_dict")
            if prev:
                prev.update(tc.arguments)
                entry["_args_dict"] = prev
            else:
                entry["_args_dict"] = dict(tc.arguments)
        else:
            entry["arguments"] = str(entry.get("arguments", "")) + str(tc.arguments)


def _tool_acc_to_list(acc: dict[int, dict[str, Any]]) -> list[ToolCall]:
    out: list[ToolCall] = []
    for idx in sorted(acc.keys()):
        entry = acc[idx]
        args = entry.get("_args_dict")
        if args is None:
            raw = entry.get("arguments") or "{}"
            args = json.loads(raw) if isinstance(raw, str) and raw else {}
        out.append(
            ToolCall(
                id=str(entry.get("id") or f"call_{idx}"),
                name=str(entry.get("name") or ""),
                arguments=args if isinstance(args, dict) else {},
            )
        )
    return out
