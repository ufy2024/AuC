"""Web UI 外链授权（L3 ApprovalPort）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from auc.ports.approval import ApprovalDecision, ApprovalPort, ApprovalRequest


@dataclass
class WebApprovalPort:
    """挂起 L3 工具调用，等待前端 /api/chat/approve 批复。"""

    _pending: dict[str, ApprovalRequest] = field(default_factory=dict)
    _events: dict[str, asyncio.Event] = field(default_factory=dict)
    _decisions: dict[str, ApprovalDecision] = field(default_factory=dict)

    async def request_approval(self, req: ApprovalRequest) -> str:
        rid = req.request_id
        self._pending[rid] = req
        self._events[rid] = asyncio.Event()
        return rid

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        if request_id in self._decisions:
            self._consume(request_id)
            return self._decisions[request_id]
        event = self._events.get(request_id)
        if event is None:
            return ApprovalDecision(approved=False, reason="unknown request")
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            # 超时不清理：保留记录，允许迟到决策被登记后再消费
            return ApprovalDecision(approved=False, reason="授权超时")
        self._consume(request_id)
        return self._decisions.get(
            request_id,
            ApprovalDecision(approved=False, reason="no decision"),
        )

    def _consume(self, request_id: str) -> None:
        """决策已消费：移出挂起列表（决议保留作迟到查询缓存）。"""
        self._pending.pop(request_id, None)
        self._events.pop(request_id, None)

    def decide(self, request_id: str, *, approved: bool, reason: str | None = None) -> bool:
        if request_id not in self._pending:
            return False
        self._decisions[request_id] = ApprovalDecision(
            approved=approved,
            decided_by="web",
            reason=reason,
        )
        event = self._events.get(request_id)
        if event:
            event.set()
        return True

    def get_pending(self, request_id: str) -> ApprovalRequest | None:
        return self._pending.get(request_id)

    def list_pending(self) -> list[dict[str, object]]:
        """所有未决授权请求（供前端找回丢失/被覆盖的授权卡片）。"""
        out: list[dict[str, object]] = []
        for rid in list(self._pending):
            if rid in self._decisions:
                continue
            payload = self.pending_payload(rid)
            if payload is not None:
                out.append(payload)
        return out

    def pending_payload(self, request_id: str) -> dict[str, object] | None:
        req = self._pending.get(request_id)
        if req is None:
            return None
        return {
            "request_id": req.request_id,
            "tool": req.tool_name,
            "arguments": req.arguments,
            "risk_summary": req.risk_summary,
            "run_id": req.run_id,
        }
