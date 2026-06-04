from auc.model.client import (
    AssistantMessage,
    InMemoryModelClient,
    ModelClient,
    StreamChunk,
)

__all__ = [
    "AssistantMessage",
    "InMemoryModelClient",
    "ModelClient",
    "StreamChunk",
]

try:
    from auc.model.anthropic import AnthropicClient
    from auc.model.factory import create_model_client, aclose_model_client
    from auc.model.openai import OpenAICompatibleClient

    __all__.extend(
        [
            "AnthropicClient",
            "OpenAICompatibleClient",
            "create_model_client",
            "aclose_model_client",
        ]
    )
except ImportError:  # pragma: no cover
    pass
