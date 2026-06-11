from typing import Literal

AgentId = str
RunId = str

RunStatus = Literal[
    "completed",
    "max_steps",
    "cancelled",
    "error",
    "pending_approval",
    "denied",
]
MessageRole = Literal["system", "user", "assistant", "tool"]
ToolPrivilege = Literal["L1", "L2", "L3"]
AutonomyLevel = Literal["confirm-all", "auto-edit", "full-auto"]
RunEventType = Literal[
    "run_start",
    "step_start",
    "model_delta",
    "tool_start",
    "tool_end",
    "approval_required",
    "approval_granted",
    "approval_denied",
    "step_end",
    "run_end",
    "context_compacted",
    "checkpoint_created",
    "plan_ready",
    "todos_updated",
    "usage_updated",
    "subagent_start",
    "subagent_end",
    "evolution_lesson",
    "skill_promoted",
]
TruncateStrategy = Literal["drop_oldest", "drop_middle", "summarize"]
