"""assistant(tool_calls) 与 tool 结果的消息配对边界。"""

from __future__ import annotations

from auc.messages import ChatMessage


def group_boundaries(messages: list[ChatMessage]) -> list[int]:
    """返回安全分割点索引：在这些下标处切分不会拆散 tool 调用组。"""
    boundaries: list[int] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if msg.role == "assistant" and msg.tool_calls:
            j = i + 1
            while j < n and messages[j].role == "tool":
                j += 1
            i = j
        else:
            i += 1
        boundaries.append(i)
    return boundaries


def drop_oldest_preserving_pairs(
    messages: list[ChatMessage],
    max_messages: int,
) -> list[ChatMessage]:
    """从头部丢弃最旧消息，但不拆散 assistant+tool 组。"""
    if max_messages <= 0 or len(messages) <= max_messages:
        return messages
    excess = len(messages) - max_messages
    boundaries = group_boundaries(messages)
    cut = excess
    for b in boundaries:
        if b >= excess:
            cut = b
            break
    else:
        cut = boundaries[-1] if boundaries else excess
    if cut <= 0:
        cut = excess
    return messages[cut:]
