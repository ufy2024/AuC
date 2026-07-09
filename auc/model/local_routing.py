"""本地智能路由：当网关不支持 ``auto`` 虚拟模型时，由 AuC 在本地按策略选型。

许多「中转」并未实现网关侧智能路由（填 ``auto`` 会报模型不存在）。此时 AuC
拉取网关的可用模型列表，按所选策略（成本 / 均衡 / 质量 / 低延迟）从中挑出一个
**真实模型** 顶替 ``auto``。

选型完全基于模型 ID 的启发式推断（无法依赖网关返回的能力/价格元数据，标准
``/models`` 接口通常只给 id），对每个模型估算三维分值：

- ``capability`` 能力：旗舰/大参数/推理模型高，mini/lite/小参数低；
- ``cheapness`` 便宜度：mini/flash/haiku 等高，opus/max/pro/reasoner 低；
- ``speed`` 速度：mini/flash/turbo 高，reasoner/o1/opus/thinking 低。

再按策略加权求总分，取最高者；非对话类模型（embedding/rerank/tts/image…）
会被排除。纯函数、可单测，不触发任何网络请求。
"""

from __future__ import annotations

import re

from auc.model.routing import DEFAULT_STRATEGY, ROUTING_STRATEGIES

# 非对话模型：不应被 auto 路由选中（auto 面向 chat/completions）。
_NON_CHAT = re.compile(
    r"(embed|rerank|reranker|whisper|(^|[-/])tts|text-to-speech|speech|audio|voice|"
    r"realtime|dall-?e|gpt-image|(^|[-/])image|midjourney|flux|stable-?diffusion|sdxl|"
    r"(^|[-/])sd3|(^|[-/])sd-|kolors|imagen|recraft|ideogram|seedream|jimeng|cogview|"
    r"(^|[-/])video|\bsora\b|\bveo\b|kling|seedance|hailuo|runway|moderation|guard|"
    r"(^|[-/])bge-|(^|[-/])gte-|(^|[-/])m3e|ocr)",
    re.IGNORECASE,
)

# 高能力关键字（旗舰 / 大参数 / 推理）。
_HIGH_CAP = re.compile(
    r"(opus|sonnet|gpt-4\.5|gpt-4\.1|gpt-4o(?!-mini)|(^|[-/])gpt-4(?!o-mini)|"
    r"(^|[-/])o1(?!-mini)|(^|[-/])o3|(^|[-/])o4|reasoner|deepseek-r|"
    r"max\b|-max|ultra|(^|[-/])pro\b|-pro|grok-[2-9]|405b|70b|72b|magnum|"
    r"gemini-(1\.5-pro|2\.0|2\.5|exp)|qwen.*(max|plus)|command-r-plus)",
    re.IGNORECASE,
)

# 低能力 / 轻量关键字。
_LOW_CAP = re.compile(
    r"(mini|nano|tiny|small|lite|haiku|flash|instant|micro|(^|[-/])air|"
    r"gpt-3\.5|1\.5b|(^|[-/])2b|(^|[-/])3b|(^|[-/])7b|(^|[-/])8b|(^|[-/])9b)",
    re.IGNORECASE,
)

# 便宜 / 快关键字。
_LIGHT = re.compile(
    r"(mini|nano|tiny|small|lite|haiku|flash|instant|turbo|micro|(^|[-/])air|free|"
    r"(^|[-/])7b|(^|[-/])8b|1\.5b|(^|[-/])2b|(^|[-/])3b)",
    re.IGNORECASE,
)

# 贵 / 慢关键字。
_HEAVY = re.compile(
    r"(opus|gpt-4\.5|(^|[-/])gpt-4(?!o-mini)|gpt-4o(?!-mini)|ultra|max\b|-max|"
    r"(^|[-/])pro\b|-pro|(^|[-/])o1(?!-mini)|(^|[-/])o3|reasoner|thinking|"
    r"405b|70b|72b)",
    re.IGNORECASE,
)


def is_chat_model(model_id: str) -> bool:
    """是否为可用于对话补全的模型（排除向量/重排/语音/图像/视频等）。"""
    return not _NON_CHAT.search(model_id or "")


def _capability(model_id: str) -> float:
    s = model_id or ""
    if _HIGH_CAP.search(s) and not _LOW_CAP.search(s):
        return 0.9
    if _LOW_CAP.search(s):
        # mini / haiku / flash 等：能力达标可用，但低于旗舰。
        return 0.45
    return 0.6


def _cheapness(model_id: str) -> float:
    s = model_id or ""
    if _LIGHT.search(s):
        return 0.9
    if _HEAVY.search(s):
        return 0.25
    return 0.6


def _speed(model_id: str) -> float:
    s = model_id or ""
    if _LIGHT.search(s):
        return 0.9
    if _HEAVY.search(s):
        return 0.3
    return 0.6


# 策略 → (cap, cheap, speed) 权重。
_STRATEGY_WEIGHTS: dict[str, tuple[float, float, float]] = {
    "cost_optimized": (0.35, 0.65, 0.0),
    "balanced": (0.34, 0.33, 0.33),
    "quality_first": (0.8, 0.1, 0.1),
    "latency_critical": (0.2, 0.1, 0.7),
}


def score_model(model_id: str, strategy: str) -> float:
    """按策略对单个模型打分（越大越优）。未知策略回退默认。"""
    weights = _STRATEGY_WEIGHTS.get(strategy) or _STRATEGY_WEIGHTS[DEFAULT_STRATEGY]
    wc, wch, wsp = weights
    cap = _capability(model_id)
    score = wc * cap + wch * _cheapness(model_id) + wsp * _speed(model_id)
    # cost_optimized：能力作门槛，过低（玩具模型）才惩罚，避免选到不可用的小模型。
    if strategy == "cost_optimized" and cap < 0.3:
        score *= 0.5
    return score


def rank_models(models: list[str], strategy: str = DEFAULT_STRATEGY) -> list[str]:
    """按策略对候选模型降序排列；同分保持原始顺序。"""
    candidates = [m for m in models if m and isinstance(m, str)]
    if not candidates:
        return []
    if strategy not in ROUTING_STRATEGIES:
        strategy = DEFAULT_STRATEGY
    chat = [m for m in candidates if is_chat_model(m)]
    pool = chat or candidates
    scored = sorted(
        ((score_model(m, strategy), idx, m) for idx, m in enumerate(pool)),
        key=lambda t: (-t[0], t[1]),
    )
    return [m for _, _, m in scored]


def select_model(models: list[str], strategy: str = DEFAULT_STRATEGY) -> str | None:
    """从候选模型中按策略选一个真实模型；无可用对话模型时返回 ``None``。"""
    ranked = rank_models(models, strategy)
    return ranked[0] if ranked else None
