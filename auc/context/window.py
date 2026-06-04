from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from auc.messages import ChatMessage
from auc.types import TruncateStrategy


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
        if policy.max_messages is None:
            return
        excess = len(self._messages) - policy.max_messages
        if excess <= 0:
            return
        if policy.strategy == "drop_oldest":
            self._messages = self._messages[excess:]
        elif policy.strategy == "drop_middle" and len(self._messages) > 2:
            keep_head = policy.max_messages // 2
            keep_tail = policy.max_messages - keep_head
            self._messages = (
                self._messages[:keep_head] + self._messages[-keep_tail:]
            )
        else:
            self._messages = self._messages[-policy.max_messages :]

    def clear(self) -> None:
        self._messages.clear()
