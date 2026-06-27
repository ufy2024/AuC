from __future__ import annotations

"""可选安装模式（对应 pyproject.toml optional-dependencies）。"""

from typing import Final

# 模式说明（与 pyproject [project.optional-dependencies] 同步）
INSTALL_MODES: Final[dict[str, str]] = {
    "llm": "大模型 API 调用（OpenAI / Anthropic / DeepSeek，需 httpx）",
    "cli": "终端增强交互（历史、补全、多行，需 prompt-toolkit）",
    "web": "Web UI（Code + Chat 双模式，含 FastAPI + uvicorn + httpx）",
    "telegram": "Telegram 二次授权（需 httpx）",
    "qq": "QQ 二次授权（OneBot 11 / 官方机器人，需 httpx）",
    "mcp": "MCP 客户端（接入外部 stdio/HTTP MCP server，需官方 mcp SDK）",
    "index": "多语言符号索引（tree-sitter）+ 向量语义层（sentence-transformers）",
    "chat": "终端对话完整体验（llm + cli）",
    "openai": "同 llm（兼容旧名）",
    "all": "全部可选组件",
    "dev": "开发依赖（pytest + 全部组件）",
}

INSTALL_EXAMPLES: Final[list[str]] = [
    "pip install -e .              # 仅核心框架",
    "pip install -e '.[llm]'       # 调用大模型",
    "pip install -e '.[chat]'        # 终端对话（推荐日常）",
    "pip install -e '.[web]'         # 网页版",
    "pip install -e '.[all]'         # 所有组件",
    "pip install -e '.[dev]'         # 开发与测试",
]


def hint_for(*modes: str) -> str:
    tags = ",".join(modes)
    return f"请安装可选组件: pip install -e '.[{tags}]' 或 pip install -e '.[all]'"
