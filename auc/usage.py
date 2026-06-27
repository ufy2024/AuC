"""R11 用量与预算：价格表 + 累计追踪 + token 预算上限。

设计取舍：
  - 价格表为「USD / 每百万 token」，按模型名前缀匹配；无表项时成本记 0（不臆造）。
  - 每次模型调用都按全量 prompt 计费，故累计成本按调用求和（贴近真实账单）；
    同时保留 last_prompt_tokens 以反映当前上下文规模。
  - 预算 `max_total_tokens` 为软上限：累计 total 超限即停止本 Run（不再发起新步）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auc.model.client import TokenUsage

# (input_per_1M, output_per_1M) USD —— 2026 主流模型粗略价目，可被设置覆盖。
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
}
DEFAULT_PRICE: tuple[float, float] = (0.0, 0.0)


def price_for(model: str) -> tuple[float, float]:
    """按模型名解析单价；精确命中优先，否则取最长前缀匹配的表项。"""
    name = (model or "").strip().lower()
    if not name:
        return DEFAULT_PRICE
    if name in MODEL_PRICES:
        return MODEL_PRICES[name]
    best: tuple[str, tuple[float, float]] | None = None
    for key, price in MODEL_PRICES.items():
        if key in name and (best is None or len(key) > len(best[0])):
            best = (key, price)
    return best[1] if best else DEFAULT_PRICE


@dataclass
class UsageTracker:
    model: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    last_prompt_tokens: int = 0

    def add(self, usage: TokenUsage | None) -> bool:
        """累加一次调用的用量，返回是否实际累加（usage 为空则跳过）。"""
        if usage is None:
            return False
        self.calls += 1
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens or (
            usage.prompt_tokens + usage.completion_tokens
        )
        self.last_prompt_tokens = usage.prompt_tokens
        pin, pout = price_for(self.model)
        self.cost_usd += (
            usage.prompt_tokens / 1_000_000 * pin
            + usage.completion_tokens / 1_000_000 * pout
        )
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "last_prompt_tokens": self.last_prompt_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }
