"""HTTP 型 IM 二次授权基类（Telegram / QQ 继承）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from auc.ports.approval import ApprovalDecision

CALLBACK_PREFIX = "auc:"


def parse_auc_callback(data: str) -> tuple[str, str] | None:
    """解析 ``auc:approve:<request_id>`` / ``auc:deny:<request_id>``。"""
    if not data.startswith(CALLBACK_PREFIX):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    action, request_id = parts[1], parts[2]
    if action not in ("approve", "deny") or not request_id:
        return None
    return action, request_id


def make_auc_callback(action: str, request_id: str) -> str:
    return f"{CALLBACK_PREFIX}{action}:{request_id}"


@dataclass
class HttpImApprovalPort:
    """Telegram / QQ 等 HTTP 轮询或 Webhook 型 ``ApprovalPort`` 的共用状态与工具。"""

    poll_interval: float = 2.0
    _decisions: dict[str, ApprovalDecision] = field(default_factory=dict)

    def store_decision(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str | None = None,
    ) -> ApprovalDecision:
        decision = ApprovalDecision(
            approved=approved,
            decided_by=decided_by,
            reason=None if approved else (reason or "denied"),
        )
        self._decisions[request_id] = decision
        return decision
