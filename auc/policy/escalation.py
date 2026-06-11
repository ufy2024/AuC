"""R1 危险命令升级规则：命中即把本次调用按 L3 走审批（不改工具静态注册级别）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EscalationRule:
    name: str
    pattern: str  # 对 run_command 的 command 文本做 re.search
    reason: str


DEFAULT_ESCALATIONS: list[EscalationRule] = [
    EscalationRule("rm-rf", r"\brm\s+(-[a-zA-Z]*[rf]){1,2}", "递归删除"),
    EscalationRule("git-push", r"\bgit\s+push\b", "推送远端"),
    EscalationRule("sudo", r"\bsudo\b|\bsu\s", "提权"),
    EscalationRule("pipe-sh", r"(curl|wget)[^|]*\|\s*(ba)?sh", "下载执行"),
    EscalationRule("dd-mkfs", r"\b(dd|mkfs|fdisk)\b", "磁盘破坏"),
    EscalationRule("dot-auc", r"\.auc/", "写框架元数据"),
    EscalationRule("chmod-x", r"\bchmod\s+[0-7]*7[0-7]*\s", "危险权限"),
]

# 安全底线：这些内置规则不可被用户配置关闭
LOCKED_RULES = frozenset({"sudo", "pipe-sh", "dot-auc"})

# 命令文本可能出现的参数键（run_command 用 command；git 类工具留扩展）
_COMMAND_KEYS = ("command",)


def check_escalation(
    tool_name: str,
    arguments: dict[str, Any],
    rules: list[EscalationRule] | None = None,
) -> EscalationRule | None:
    """返回首条命中的升级规则；未命中返回 None。

    仅对带命令文本的工具生效（run_command 等）；其中 dot-auc 规则同时
    检查文件类工具的 path 参数，防智能体直写 `.auc/`。
    """
    active = DEFAULT_ESCALATIONS if rules is None else rules
    texts: list[str] = []
    for key in _COMMAND_KEYS:
        val = arguments.get(key)
        if isinstance(val, str):
            texts.append(val)
    path_val = arguments.get("path")
    has_path = isinstance(path_val, str)

    for rule in active:
        compiled = re.compile(rule.pattern)
        for text in texts:
            if compiled.search(text):
                return rule
        if rule.name == "dot-auc" and has_path and compiled.search(path_val):
            return rule
    return None


def merge_escalation_settings(
    overrides: list[dict[str, Any]] | None,
) -> list[EscalationRule]:
    """合并 settings.json["escalations"]：按 name 覆盖 pattern/reason，
    `enabled: false` 关闭（LOCKED_RULES 除外）；未知 name 视为新增规则。"""
    rules = {r.name: r for r in DEFAULT_ESCALATIONS}
    for item in overrides or []:
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        if item.get("enabled") is False:
            if name not in LOCKED_RULES:
                rules.pop(name, None)
            continue
        base = rules.get(name)
        rules[name] = EscalationRule(
            name=name,
            pattern=str(item.get("pattern") or (base.pattern if base else "")),
            reason=str(item.get("reason") or (base.reason if base else name)),
        )
    return [r for r in rules.values() if r.pattern]
