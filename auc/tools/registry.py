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

    def filtered_view(self, allowed: set[str] | frozenset[str]) -> "DefaultToolRegistry":
        """返回仅含 allowed 工具的浅包装视图（不复制工具实例）。

        计划模式（R5）用于收窄为只读工具集；对动态注册（MCP 等）同样生效，
        因为视图按名单白名单过滤而非黑名单。
        """
        view = DefaultToolRegistry()
        for name, tool in self._tools.items():
            if name in allowed:
                view._tools[name] = tool
                view._policies[name] = self._policies[name]
        return view

    def merge_tool_policy(self, overrides: dict[str, ToolPrivilege]) -> None:
        for name, priv in overrides.items():
            if name in self._policies:
                old = self._policies[name]
                self._policies[name] = ToolPolicy(
                    name=name,
                    privilege=priv,
                    sandbox_only=priv == "L2",
                    mutates_files=old.mutates_files,
                    mutates_state=old.mutates_state,
                )
