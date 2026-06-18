"""Agents-ufy-Core (AuC): asyncio single-agent framework."""

from auc.agent import AgentConfig, DefaultAgent
from auc.checkpoint import CheckpointStore
from auc.config import (
    ModelConfig,
    default_config_path,
    discover_config_path,
    load_model_config,
    user_config_dir,
)
from auc.context import ListContextWindow
from auc.events import EventBus, RunEvent
from auc.loop import AgentLoopRunner, LoopConfig, ReActLoop
from auc.messages import ChatMessage, RunRequest, RunResult, ToolCall, ToolResult
from auc.model import AssistantMessage, InMemoryModelClient
from auc.ports import (
    AutoApprovePort,
    CodeSnippet,
    ContextPackage,
    DefaultComposer,
    DenyApprovalPort,
    FileRulesPort,
    InMemoryMemoryPort,
    NoOpMemoryPort,
    SlicerPolicy,
)
from auc.policy import ToolPrivilegeGate
from auc.policy.autonomy import AutonomyPolicy
from auc.sandbox import SandboxViolationError, resolve_under_sandbox
from auc.tools import DefaultToolRegistry, make_echo_tool, register_function_tools, tool

__version__ = "0.2.12"

__all__ = [
    "__version__",
    "AgentConfig",
    "AssistantMessage",
    "AutoApprovePort",
    "AutonomyPolicy",
    "CheckpointStore",
    "ChatMessage",
    "CodeSnippet",
    "ContextPackage",
    "DefaultAgent",
    "DefaultComposer",
    "DefaultToolRegistry",
    "DenyApprovalPort",
    "EventBus",
    "FileRulesPort",
    "InMemoryMemoryPort",
    "InMemoryModelClient",
    "ListContextWindow",
    "LoopConfig",
    "NoOpMemoryPort",
    "ReActLoop",
    "RunEvent",
    "RunRequest",
    "RunResult",
    "SandboxViolationError",
    "SlicerPolicy",
    "ToolCall",
    "ToolPrivilegeGate",
    "ToolResult",
    "make_echo_tool",
    "register_function_tools",
    "resolve_under_sandbox",
    "tool",
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
            "ModelConfig",
            "load_model_config",
            "discover_config_path",
            "user_config_dir",
            "default_config_path",
        ]
    )
except ImportError:  # pragma: no cover
    __all__.extend(
        [
            "ModelConfig",
            "load_model_config",
            "discover_config_path",
            "user_config_dir",
            "default_config_path",
        ]
    )

try:
    from auc.integration import (
        AuMStack,
        MetaDispatcher,
        NuggetsStore,
        SemanticSlicer,
        SpecialistRegistry,
        SpecialistSpec,
        ConsoleApprovalPort,
        TelegramApprovalPort,
    )

    __all__.extend(
        [
            "AuMStack",
            "MetaDispatcher",
            "NuggetsStore",
            "SemanticSlicer",
            "SpecialistRegistry",
            "SpecialistSpec",
            "ConsoleApprovalPort",
            "TelegramApprovalPort",
        ]
    )
except ImportError:  # pragma: no cover
    pass
