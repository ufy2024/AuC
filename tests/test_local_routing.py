"""本地智能路由选型的单元测试。"""

from __future__ import annotations

from auc.model.local_routing import is_chat_model, score_model, select_model


def test_excludes_non_chat_models() -> None:
    assert is_chat_model("deepseek-chat")
    assert is_chat_model("gpt-4o")
    assert not is_chat_model("text-embedding-3-large")
    assert not is_chat_model("bge-reranker-v2")
    assert not is_chat_model("whisper-1")
    assert not is_chat_model("dall-e-3")
    assert not is_chat_model("stable-diffusion-xl")


def test_quality_first_prefers_flagship() -> None:
    models = ["gpt-4o-mini", "gpt-4o", "claude-3-haiku", "claude-3-opus"]
    chosen = select_model(models, "quality_first")
    assert chosen in ("gpt-4o", "claude-3-opus")
    assert score_model("claude-3-opus", "quality_first") > score_model(
        "claude-3-haiku", "quality_first"
    )


def test_cost_optimized_prefers_cheap_but_capable() -> None:
    models = ["gpt-4o", "gpt-4o-mini", "claude-3-opus"]
    chosen = select_model(models, "cost_optimized")
    assert chosen == "gpt-4o-mini"


def test_latency_critical_prefers_fast() -> None:
    models = ["o1", "gpt-4o-mini", "claude-3-opus"]
    chosen = select_model(models, "latency_critical")
    assert chosen == "gpt-4o-mini"


def test_balanced_returns_some_chat_model() -> None:
    models = ["text-embedding-3-small", "deepseek-chat", "deepseek-reasoner"]
    chosen = select_model(models, "balanced")
    assert chosen in ("deepseek-chat", "deepseek-reasoner")
    assert chosen != "text-embedding-3-small"


def test_unknown_strategy_falls_back_to_default() -> None:
    models = ["gpt-4o", "gpt-4o-mini"]
    # cost_optimized 默认 → 偏向便宜的 mini
    assert select_model(models, "no-such-strategy") == "gpt-4o-mini"


def test_empty_and_only_non_chat() -> None:
    assert select_model([], "balanced") is None
    # 仅有非对话模型时，兜底仍返回一个（不至于无法路由）
    only_embed = ["text-embedding-3-large", "bge-m3"]
    assert select_model(only_embed, "balanced") in only_embed


def test_stable_order_on_tie() -> None:
    # 两个等价模型，取靠前者（稳定）
    models = ["model-a", "model-b"]
    assert select_model(models, "balanced") == "model-a"
