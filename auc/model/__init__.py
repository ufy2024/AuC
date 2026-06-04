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
    from auc.model.openai import OpenAICompatibleClient

    __all__.append("OpenAICompatibleClient")
except ImportError:  # pragma: no cover
    pass
