from __future__ import annotations

from typing import TYPE_CHECKING

from auc.config import ModelConfig
from auc.model.client import ModelClient

if TYPE_CHECKING:
    pass


def create_model_client(cfg: ModelConfig) -> ModelClient:
    """Build ModelClient from merged ModelConfig."""
    if not cfg.api_key:
        env_hint = (
            "ANTHROPIC_API_KEY"
            if cfg.provider == "anthropic"
            else "OPENAI_API_KEY"
        )
        raise ValueError(
            f"api_key not set for provider={cfg.provider}; "
            f"set AUC_API_KEY or {env_hint} or config file api_key"
        )

    if cfg.provider == "anthropic":
        from auc.model.anthropic import AnthropicClient

        return AnthropicClient(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url or "https://api.anthropic.com",
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout,
        )

    from auc.model.openai import OpenAICompatibleClient

    return OpenAICompatibleClient(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url or "https://api.openai.com/v1",
        timeout=cfg.timeout,
    )


async def aclose_model_client(client: ModelClient) -> None:
    aclose = getattr(client, "aclose", None)
    if aclose is not None:
        await aclose()
