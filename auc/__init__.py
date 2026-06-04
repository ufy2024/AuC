"""Agents-ufy-Core (AuC): asyncio single-agent framework."""

from auc.agent import AgentConfig, DefaultAgent
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
from auc.sandbox import SandboxViolationError, resolve_under_sandbox
from auc.tools import DefaultToolRegistry, make_echo_tool, register_function_tools, tool

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "AgentConfig",
    "AssistantMessage",
    "AutoApprovePort",
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
    from auc.model.openai import OpenAICompatibleClient

    __all__.append("OpenAICompatibleClient")
except ImportError:  # pragma: no cover
    pass

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
