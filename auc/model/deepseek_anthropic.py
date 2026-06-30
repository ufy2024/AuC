from __future__ import annotations


def is_deepseek_anthropic_base(base_url: str) -> bool:
    return "deepseek.com" in (base_url or "").lower()


def deepseek_request_extra() -> dict:
    """DeepSeek V4 默认开启 thinking 模式；工具轮次须原样回传 thinking。"""
    return {"thinking": {"type": "enabled"}}


def inject_assistant_thinking_block(
    blocks: list[dict],
    *,
    thinking: str | None,
    has_tool_use: bool,
) -> list[dict]:
    if not has_tool_use:
        return blocks
    if blocks and blocks[0].get("type") == "thinking":
        return blocks
    return [{"type": "thinking", "thinking": thinking or ""}, *blocks]
