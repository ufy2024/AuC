"""智能路由：把模型名填 ``auto`` 交由网关按请求内容自动选最优模型。

约定（与网关侧实现对齐）：

- 模型名为 ``auto`` 即开启智能路由；不带后缀时使用默认策略 ``cost_optimized``。
- 可用 ``auto:<策略>`` 显式指定侧重：

  | 策略 | 含义 | 适用 |
  |------|------|------|
  | ``cost_optimized`` | 成本优先：能力达标就选最便宜（默认） | 一般任务 |
  | ``balanced`` | 均衡：能力 / 成本 / 延迟兼顾 | 默认折中 |
  | ``quality_first`` | 质量优先：优先选能力最强 | 复杂推理、关键输出 |
  | ``latency_critical`` | 低延迟优先：优先选响应最快 | 交互、补全 |

AuC 不在本地做选型，而是把规范化后的 ``auto:<策略>`` 作为 ``model`` 透传给网关；
网关实际选中的模型从响应体的 ``model`` 字段读回，并在运行时 UI 显示。
"""

from __future__ import annotations

from typing import Any

AUTO_KEYWORD = "auto"
DEFAULT_STRATEGY = "cost_optimized"

# 策略 → (中文标签, 说明)
ROUTING_STRATEGIES: dict[str, tuple[str, str]] = {
    "cost_optimized": ("成本优先", "能力达标就选最便宜"),
    "balanced": ("均衡", "能力 / 成本 / 延迟兼顾"),
    "quality_first": ("质量优先", "优先选能力最强，适合复杂推理、关键输出"),
    "latency_critical": ("低延迟优先", "优先选响应最快"),
}


def is_auto_model(model: str | None) -> bool:
    """模型名是否为智能路由（``auto`` 或 ``auto:<策略>``，大小写/空白不敏感）。"""
    if not model:
        return False
    head = str(model).strip().lower().split(":", 1)[0]
    return head == AUTO_KEYWORD


def parse_auto_model(model: str | None) -> tuple[bool, str]:
    """解析智能路由模型名，返回 ``(是否 auto, 策略)``。

    - ``"auto"`` → ``(True, "cost_optimized")``
    - ``"auto:quality_first"`` → ``(True, "quality_first")``
    - 未知策略回退默认；非 auto → ``(False, "")``
    """
    if not is_auto_model(model):
        return False, ""
    parts = str(model).strip().lower().split(":", 1)
    if len(parts) == 1 or not parts[1].strip():
        return True, DEFAULT_STRATEGY
    strategy = parts[1].strip()
    if strategy not in ROUTING_STRATEGIES:
        return True, DEFAULT_STRATEGY
    return True, strategy


def canonical_auto_model(model: str | None) -> str:
    """规范化为透传给网关的 ``auto:<策略>``；非 auto 原样返回。"""
    is_auto, strategy = parse_auto_model(model)
    if not is_auto:
        return str(model or "")
    return f"{AUTO_KEYWORD}:{strategy}"


def strategy_label(strategy: str) -> str:
    """策略中文标签；未知策略原样返回。"""
    entry = ROUTING_STRATEGIES.get(strategy)
    return entry[0] if entry else strategy


def routing_options() -> list[dict[str, Any]]:
    """供 API / UI 使用的策略清单（含 canonical 模型名与标签、说明）。"""
    return [
        {
            "model": f"{AUTO_KEYWORD}:{key}",
            "strategy": key,
            "label": label,
            "description": desc,
            "default": key == DEFAULT_STRATEGY,
        }
        for key, (label, desc) in ROUTING_STRATEGIES.items()
    ]
