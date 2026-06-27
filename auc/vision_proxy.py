"""文本模型不支持图片时，经可选视觉模型将图片转写为文字描述。"""

from __future__ import annotations

import os
from typing import Any

from auc.config import (
    ModelConfig,
    _default_api_key_env,
    _default_base_url,
    _resolve_tree,
    normalize_provider,
)
from auc.messages import ChatMessage, ImageAttachment
from auc.model.factory import aclose_model_client, create_model_client

_VISION_MODEL_HINTS = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-turbo",
    "vision",
    "-vl",
    "claude-3",
    "claude-sonnet",
    "claude-opus",
    "gemini",
)


def model_supports_vision(cfg: ModelConfig) -> bool:
    """主模型是否原生支持图片输入。"""
    base = (cfg.base_url or _default_base_url(cfg.provider)).lower()
    if "deepseek.com" in base:
        return False
    if cfg.provider == "deepseek":
        return False
    if cfg.provider == "anthropic":
        return True
    # OpenAI 兼容网关：默认可传图（具体能力由上游决定）
    model = cfg.model.lower()
    if any(h in model for h in _VISION_MODEL_HINTS):
        return True
    # 未识别的 openai 兼容模型名仍尝试原生传图，避免误走代理
    return cfg.provider == "openai"


def _api_key_from_block(block: dict[str, Any], provider: str) -> str | None:
    raw = block.get("api_key") or block.get("apiKey")
    if isinstance(raw, str) and raw.strip():
        resolved = _resolve_tree(raw)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
    env_name = block.get("api_key_env") or block.get("apiKeyEnv")
    if isinstance(env_name, str) and env_name.strip():
        val = os.environ.get(env_name.strip())
        if val:
            return val
    return os.environ.get(_default_api_key_env(normalize_provider(provider)))


def resolve_vision_config(
    settings: dict[str, Any] | None,
    main_cfg: ModelConfig,
) -> ModelConfig | None:
    """解析视觉代理配置；主模型已支持视觉时返回 None。"""
    if model_supports_vision(main_cfg):
        return None

    block = (settings or {}).get("vision")
    if block is False:
        return None
    if isinstance(block, dict) and block.get("enabled") is False:
        return None

    provider = normalize_provider(
        str(
            (block or {}).get("provider")
            or os.environ.get("AUC_VISION_PROVIDER")
            or "openai"
        )
    )
    model = str(
        (block or {}).get("model")
        or os.environ.get("AUC_VISION_MODEL")
        or ("gpt-4o-mini" if provider == "openai" else "claude-sonnet-4-20250514")
    )
    api_key = None
    base_url = None
    if isinstance(block, dict):
        api_key = _api_key_from_block(block, provider)
        base_url = block.get("base_url") or block.get("baseUrl")
    if not api_key:
        api_key = os.environ.get(_default_api_key_env(provider))
    if not api_key:
        return None

    timeout = 120.0
    if isinstance(block, dict) and block.get("timeout"):
        try:
            timeout = float(block["timeout"])
        except (TypeError, ValueError):
            pass

    return ModelConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=str(base_url) if base_url else _default_base_url(provider),
        timeout=timeout,
    )


async def transcribe_images(
    images: list[ImageAttachment],
    vision_cfg: ModelConfig,
) -> str:
    if not images:
        return ""
    client = create_model_client(vision_cfg)
    try:
        prompt = (
            "请详细描述以下图片中的可见内容（文字、界面元素、图表、报错信息等）。"
            "若有多张图，按顺序分别描述。只输出客观描述，不要提问。"
        )
        msg = ChatMessage(role="user", content=prompt, images=images)
        result = await client.complete([msg])
        return (result.content or "").strip()
    finally:
        await aclose_model_client(client)


async def prepare_images_for_model(
    text: str,
    images: list[ImageAttachment],
    main_cfg: ModelConfig,
    settings: dict[str, Any] | None = None,
) -> tuple[str, list[ImageAttachment], list[str]]:
    """为不支持视觉的主模型准备输入：尝试视觉代理转写，否则剥离图片并提示。"""
    if not images:
        return text, images, []

    if model_supports_vision(main_cfg):
        return text, images, []

    notes: list[str] = []
    vision_cfg = resolve_vision_config(settings, main_cfg)
    if vision_cfg is not None:
        try:
            desc = await transcribe_images(images, vision_cfg)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"视觉代理失败: {exc}")
            desc = ""
        if desc:
            header = f"--- 图片内容（经 {vision_cfg.model} 转写）---"
            block = f"\n\n{header}\n{desc}\n--- end ---\n"
            merged = f"{text}{block}".strip() if text.strip() else desc
            notes.append(
                f"已通过视觉模型 {vision_cfg.provider}/{vision_cfg.model} "
                f"转写 {len(images)} 张图片"
            )
            return merged, [], notes
        notes.append("视觉代理未返回描述，图片已忽略")
        fallback = text or "（用户附带了图片，但无法解析内容）"
        return fallback, [], notes

    notes.append(
        "当前主模型不支持图片输入（DeepSeek API 官方仅文本）。"
        "请在 settings.json 配置 vision 段，或设置 OPENAI_API_KEY + "
        "AUC_VISION_MODEL 启用视觉代理。"
    )
    fallback = text or "（用户附带了图片，但当前模型无法处理）"
    return fallback, [], notes
