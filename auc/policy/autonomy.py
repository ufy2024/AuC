"""R6 会话级自治级别：confirm-all / auto-edit / full-auto。

裁决矩阵（L3 行硬编码，任何级别都不可放宽）：

| 级别        | L1   | L2(mutates_files) | L2(mutates_state) | L3   |
|-------------|------|-------------------|-------------------|------|
| confirm-all | 放行 | 挂起审批(携 diff) | 挂起审批          | 挂起 |
| auto-edit   | 放行 | 放行+检查点       | 挂起审批          | 挂起 |
| full-auto   | 放行 | 放行+检查点       | 放行+检查点       | 挂起 |
"""

from __future__ import annotations

from dataclasses import dataclass

from auc.tools.base import ToolPolicy
from auc.types import AutonomyLevel

AUTONOMY_LEVELS: tuple[AutonomyLevel, ...] = ("confirm-all", "auto-edit", "full-auto")
DEFAULT_AUTONOMY: AutonomyLevel = "auto-edit"


def normalize_autonomy(value: str | None) -> AutonomyLevel:
    v = (value or "").strip().lower()
    if v in AUTONOMY_LEVELS:
        return v  # type: ignore[return-value]
    return DEFAULT_AUTONOMY


@dataclass
class AutonomyPolicy:
    level: AutonomyLevel = DEFAULT_AUTONOMY

    def requires_approval(self, policy: ToolPolicy) -> bool:
        if policy.privilege == "L3":
            return True  # 硬规则，永不放宽
        if policy.privilege == "L1":
            return False
        # L2：
        if self.level == "confirm-all":
            return policy.mutates_files or policy.mutates_state
        if self.level == "auto-edit":
            return policy.mutates_state
        return False  # full-auto：L2 均放行

    def describe(self, policy: ToolPolicy) -> str:
        if policy.mutates_files:
            kind = "写文件"
        elif policy.mutates_state:
            kind = "改变系统状态"
        else:
            kind = policy.privilege
        return f"自治级别 {self.level}：{kind} 操作需确认"
