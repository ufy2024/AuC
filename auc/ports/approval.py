from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from auc.types import AgentId, RunId


@dataclass
class ApprovalRequest:
    request_id: str
    run_id: RunId
    agent_id: AgentId
    tool_name: str
    arguments: dict[str, object]
    diff_text: str
    risk_summary: str


@dataclass
class ApprovalDecision:
    approved: bool
    decided_by: str | None = None
    reason: str | None = None


class ApprovalPort(Protocol):
    async def request_approval(self, req: ApprovalRequest) -> str: ...

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision: ...


class AutoApprovePort:
    """测试/开发用端口：立即批准 L3 操作。"""

    def __init__(self, *, approved: bool = True, decided_by: str = "auto") -> None:
        self._approved = approved
        self._decided_by = decided_by
        self._pending: dict[str, ApprovalRequest] = {}

    async def request_approval(self, req: ApprovalRequest) -> str:
        rid = req.request_id or str(uuid.uuid4())
        self._pending[rid] = req
        return rid

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        del timeout
        if request_id not in self._pending:
            return ApprovalDecision(approved=False, reason="unknown request")
        return ApprovalDecision(
            approved=self._approved,
            decided_by=self._decided_by,
        )


class DenyApprovalPort(AutoApprovePort):
    def __init__(self) -> None:
        super().__init__(approved=False, decided_by="deny")

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        del timeout
        return ApprovalDecision(approved=False, decided_by="deny", reason="denied")
