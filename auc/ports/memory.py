from __future__ import annotations

from typing import Protocol

from auc.context.window import ContextWindow
from auc.messages import ChatMessage
from auc.ports.package import ContextPackage
from auc.ports.rules import ProjectRules
from auc.types import AgentId, RunId


class MemoryPort(Protocol):
    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]: ...

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None: ...


class ContextComposer(Protocol):
    async def compose(
        self,
        window: ContextWindow,
        recall: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        rules: ProjectRules | None = None,
        package: ContextPackage | None = None,
    ) -> list[ChatMessage]: ...


class NoOpMemoryPort:
    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]:
        del query, limit, run_id, agent_id
        return []

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None:
        del items, run_id, agent_id


def format_rules_block(rules: ProjectRules) -> str:
    lines = ["[AU-RULES v1]"]
    if rules.build_commands:
        lines.append("Build: " + " | ".join(rules.build_commands))
    if rules.test_commands:
        lines.append("Test: " + " | ".join(rules.test_commands))
    for note in rules.style_notes:
        lines.append(f"Style: {note}")
    lines.append("[/AU-RULES]")
    return "\n".join(lines)


def format_package_block(package: ContextPackage) -> str:
    parts = [
        f"[CONTEXT-PACKAGE id={package.package_id}]",
        f"Intent: {package.intent_summary}",
    ]
    for snip in package.snippets:
        loc = ""
        if snip.line_range:
            loc = f":{snip.line_range[0]}-{snip.line_range[1]}"
        parts.append(f"--- {snip.path}{loc} ---\n{snip.content}")
    parts.append("[/CONTEXT-PACKAGE]")
    return "\n".join(parts)


class DefaultComposer:
    async def compose(
        self,
        window: ContextWindow,
        recall: list[ChatMessage],
        *,
        system_prompt: str | None = None,
        rules: ProjectRules | None = None,
        package: ContextPackage | None = None,
    ) -> list[ChatMessage]:
        out: list[ChatMessage] = []
        if system_prompt:
            out.append(ChatMessage(role="system", content=system_prompt))
        if rules is not None:
            out.append(
                ChatMessage(role="system", content=format_rules_block(rules))
            )
        if package is not None:
            out.append(
                ChatMessage(
                    role="system",
                    content=format_package_block(package),
                )
            )
        out.extend(recall)
        out.extend(window.view())
        return out


class InMemoryMemoryPort:
    """Simple memory for tests and standalone use."""

    def __init__(self) -> None:
        self._store: list[ChatMessage] = []

    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]:
        del query, run_id, agent_id
        return self._store[-limit:]

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None:
        del run_id, agent_id
        self._store.extend(items)
