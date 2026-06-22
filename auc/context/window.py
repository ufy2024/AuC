from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from auc.context.pairing import drop_oldest_preserving_pairs, group_boundaries
from auc.messages import ChatMessage
from auc.types import TruncateStrategy


def _estimate_message_tokens(msg: ChatMessage) -> int:
    tokens = len(msg.content or "") // 3
    if msg.thinking:
        tokens += len(msg.thinking) // 3
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tokens += len(str(tc.arguments)) // 3 + 8
    return tokens + 4


@dataclass
class TruncatePolicy:
    max_messages: int | None = None
    max_tokens: int | None = None
    strategy: TruncateStrategy = "drop_oldest"


class ContextWindow(Protocol):
    def append(self, message: ChatMessage) -> None: ...
    def view(self) -> list[ChatMessage]: ...
    def truncate(self, policy: TruncatePolicy) -> None: ...
    def clear(self) -> None: ...


@dataclass
class ListContextWindow:
    _messages: list[ChatMessage]

    def __init__(self) -> None:
        self._messages = []

    def append(self, message: ChatMessage) -> None:
        self._messages.append(message)

    def view(self) -> list[ChatMessage]:
        return list(self._messages)

    def truncate(self, policy: TruncatePolicy) -> None:
        if policy.max_messages is not None:
            self._truncate_by_messages(policy)
        if policy.max_tokens is not None:
            self._truncate_by_tokens(policy.max_tokens)

    def _truncate_by_messages(self, policy: TruncatePolicy) -> None:
        if policy.max_messages is None:
            return
        excess = len(self._messages) - policy.max_messages
        if excess <= 0:
            return
        if policy.strategy == "drop_middle" and len(self._messages) > 2:
            keep_head = policy.max_messages // 2
            keep_tail = policy.max_messages - keep_head
            self._messages = (
                self._messages[:keep_head] + self._messages[-keep_tail:]
            )
        else:
            # drop_oldest 与 summarize（窗口层无模型，按组安全丢弃旧消息；
            # 真正的摘要由 SummarizingCompactor 负责）均保护 tool 组配对
            self._messages = drop_oldest_preserving_pairs(
                self._messages, policy.max_messages
            )

    def _truncate_by_tokens(self, max_tokens: int) -> None:
        """按估算 token 预算从最旧的安全组边界丢弃消息。"""
        if max_tokens <= 0:
            return

        def total() -> int:
            return sum(_estimate_message_tokens(m) for m in self._messages)

        if total() <= max_tokens:
            return
        while total() > max_tokens and len(self._messages) > 1:
            boundaries = [b for b in group_boundaries(self._messages) if b > 0]
            cut = boundaries[0] if boundaries else 1
            if cut >= len(self._messages):
                cut = 1
            self._messages = self._messages[cut:]

    def clear(self) -> None:
        self._messages.clear()
