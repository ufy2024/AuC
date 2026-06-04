"""Agents-ufy-Core (AuC): asyncio single-agent framework."""

from auc.agent import AgentConfig, DefaultAgent
from auc.context import ListContextWindow
from auc.events import EventBus, RunEvent
from auc.loop import AgentLoopRunner, LoopConfig, ReActLoop
from auc.messages import ChatMessage, RunRequest, RunResult, ToolCall, ToolResult
from auc.model import AssistantMessage, InMemoryModelClient
from auc.ports import (
    AutoApprovePort,
    ContextPackage,
    CodeSnippet,
    DefaultComposer,
    DenyApprovalPort,
    FileRulesPort,
    InMemoryMemoryPort,
    NoOpMemoryPort,
    SlicerPolicy,
)
from auc.policy import ToolPrivilegeGate
from auc.tools import DefaultToolRegistry, make_echo_tool, tool, register_function_tools

__version__ = "0.1.0"

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
    "SlicerPolicy",
    "ToolCall",
    "ToolPrivilegeGate",
    "ToolResult",
    "make_echo_tool",
    "register_function_tools",
    "tool",
]
