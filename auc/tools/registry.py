from __future__ import annotations

from dataclasses import dataclass, field

from auc.tools.base import Tool, ToolPolicy, ToolSchema
from auc.types import ToolPrivilege


@dataclass
class DefaultToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)
    _policies: dict[str, ToolPolicy] = field(default_factory=dict)

    def register(self, tool: Tool, policy: ToolPolicy | None = None) -> None:
        pol = policy or ToolPolicy(
            name=tool.name,
            privilege="L2",
            sandbox_only=True,
        )
        self._tools[tool.name] = tool
        self._policies[tool.name] = pol

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_policy(self, name: str) -> ToolPolicy:
        if name not in self._policies:
            raise KeyError(f"unknown tool: {name}")
        return self._policies[name]

    def list_schemas(self) -> list[ToolSchema]:
        return [
            ToolSchema(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
            )
            for t in self._tools.values()
        ]

    def merge_tool_policy(self, overrides: dict[str, ToolPrivilege]) -> None:
        for name, priv in overrides.items():
            if name in self._policies:
                self._policies[name] = ToolPolicy(
                    name=name,
                    privilege=priv,
                    sandbox_only=priv == "L2",
                )
