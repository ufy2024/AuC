from __future__ import annotations

from typing import TYPE_CHECKING

from auc.config import ModelConfig
from auc.model.client import ModelClient

if TYPE_CHECKING:
    pass


def _is_anthropic_style_base(base_url: str) -> bool:
    """按 base_url 判断应走 Anthropic Messages 协议还是 OpenAI 兼容协议。

    - `api.anthropic.com` 或路径以 `/anthropic` 结尾 → Anthropic 协议
    - 以 `/v1`（OpenAI 兼容）结尾 → OpenAI 协议
    """
    low = (base_url or "").lower().rstrip("/")
    if not low:
        return False
    if "api.anthropic.com" in low:
        return True
    if low.endswith("/anthropic"):
        return True
    return False


def create_model_client(cfg: ModelConfig) -> ModelClient:
    """从合并后的 ModelConfig 构建 ModelClient。

    选型规则（修复 DeepSeek 同名两套不兼容路径）：
    1. provider=anthropic → Anthropic 协议
    2. 否则按 base_url 自动判断：Anthropic 风格端点走 Anthropic 协议，
       其余（含 deepseek 的 `/v1`）走 OpenAI 兼容协议。
    """
    if not cfg.api_key:
        from auc.config import _default_api_key_env

        env_hint = _default_api_key_env(cfg.provider)
        raise ValueError(
            f"api_key not set for provider={cfg.provider}; "
            f"set AUC_API_KEY or {env_hint} or config file api_key"
        )

    from auc.config import _default_base_url
    from auc.model.routing import canonical_auto_model, is_auto_model

    base_url = cfg.base_url or _default_base_url(cfg.provider)
    use_anthropic = cfg.provider == "anthropic" or (
        cfg.provider != "openai" and _is_anthropic_style_base(base_url)
    )

    # 智能路由：把 `auto` 规范化为 `auto:<策略>` 透传给网关由其按请求内容选型。
    model_id = canonical_auto_model(cfg.model) if is_auto_model(cfg.model) else cfg.model

    if use_anthropic:
        from auc.model.anthropic import AnthropicClient

        return AnthropicClient(
            model=model_id,
            api_key=cfg.api_key,
            base_url=cfg.base_url or "https://api.anthropic.com",
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
        )

    from auc.model.openai import OpenAICompatibleClient

    return OpenAICompatibleClient(
        model=model_id,
        api_key=cfg.api_key,
        base_url=base_url,
        timeout=cfg.timeout,
    )


async def aclose_model_client(client: ModelClient) -> None:
    aclose = getattr(client, "aclose", None)
    if aclose is not None:
        await aclose()
