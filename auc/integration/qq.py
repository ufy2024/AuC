"""QQ 机器人 L3 二次授权（继承 ``HttpImApprovalPort``，与 Telegram 同语义）。"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from auc.integration.im_base import HttpImApprovalPort, make_auc_callback, parse_auc_callback
from auc.integration.im_card import format_approval_card
from auc.ports.approval import ApprovalDecision, ApprovalRequest

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

QQBackend = Literal["onebot11", "official"]


def _require_httpx() -> Any:
    if httpx is None:
        from auc.extras import hint_for

        raise ImportError(hint_for("qq", "telegram", "llm", "all"))
    return httpx


# 进程内回调队列：OneBot 反向 HTTP / QQ 官方 Webhook 写入（见 docs/详细设计.md §12）
_interaction_store: dict[str, ApprovalDecision] = {}


def register_qq_callback(data: str, *, decided_by: str = "qq") -> ApprovalDecision | None:
    """供 Webhook 路由调用：解析 ``auc:approve|deny:<request_id>`` 并登记决策。"""
    parsed = parse_auc_callback(data)
    if parsed is None:
        return None
    action, request_id = parsed
    approved = action == "approve"
    decision = ApprovalDecision(
        approved=approved,
        decided_by=decided_by,
        reason=None if approved else "denied",
    )
    _interaction_store[request_id] = decision
    return decision


@dataclass
class QQApprovalPort(HttpImApprovalPort):
    """QQ L3 二次授权：默认 OneBot 11 HTTP 发消息 + 进程内回调队列。

    - **onebot11**（默认）：``QQ_ONEBOT_HTTP_URL`` + ``QQ_TARGET_USER_ID`` 或 ``QQ_TARGET_GROUP_ID``
    - **official**：QQ 官方机器人开放平台（Webhook 模式，见详细设计）
    """

    backend: QQBackend = "onebot11"
    onebot_http_url: str | None = None
    target_user_id: int | None = None
    target_group_id: int | None = None
    app_id: str | None = None
    client_secret: str | None = None
    _client: Any = field(default=None, repr=False)

    @classmethod
    def from_settings(cls, settings: dict[str, Any] | None = None) -> "QQApprovalPort":
        """从 settings.json 的 ``qq`` 段构造（缺省字段回退环境变量，见 __post_init__）。"""
        qq = (settings or {}).get("qq") or {}
        return cls(
            backend=qq.get("backend") or "onebot11",
            onebot_http_url=qq.get("onebot_http_url"),
            target_user_id=int(qq["target_user_id"]) if qq.get("target_user_id") else None,
            target_group_id=int(qq["target_group_id"]) if qq.get("target_group_id") else None,
            app_id=qq.get("app_id"),
            client_secret=qq.get("client_secret"),
        )

    def __post_init__(self) -> None:
        _require_httpx()
        if self.backend == "onebot11":
            if self.onebot_http_url is None:
                self.onebot_http_url = os.environ.get("QQ_ONEBOT_HTTP_URL", "").rstrip("/")
            if self.target_user_id is None and os.environ.get("QQ_TARGET_USER_ID"):
                self.target_user_id = int(os.environ["QQ_TARGET_USER_ID"])
            if self.target_group_id is None and os.environ.get("QQ_TARGET_GROUP_ID"):
                self.target_group_id = int(os.environ["QQ_TARGET_GROUP_ID"])
            if not self.onebot_http_url:
                raise ValueError("QQ_ONEBOT_HTTP_URL required for onebot11 backend")
            if self.target_user_id is None and self.target_group_id is None:
                raise ValueError("QQ_TARGET_USER_ID or QQ_TARGET_GROUP_ID required")
        else:
            if self.app_id is None:
                self.app_id = os.environ.get("QQ_APP_ID")
            if self.client_secret is None:
                self.client_secret = os.environ.get("QQ_CLIENT_SECRET")
            if not self.app_id or not self.client_secret:
                raise ValueError("QQ_APP_ID and QQ_CLIENT_SECRET required for official backend")

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _send_onebot_card(self, req: ApprovalRequest, text: str) -> None:
        client = self._get_client()
        buttons = [
            [
                {
                    "text": "允许并继续",
                    "data": make_auc_callback("approve", req.request_id),
                    "enter": True,
                    "style": 1,
                },
                {
                    "text": "拒绝并中断",
                    "data": make_auc_callback("deny", req.request_id),
                    "enter": True,
                    "style": 4,
                },
            ]
        ]
        if self.target_group_id is not None:
            action = "send_group_msg"
            params: dict[str, Any] = {
                "group_id": self.target_group_id,
                "message": text,
                "buttons": buttons,
            }
        else:
            action = "send_private_msg"
            params = {
                "user_id": self.target_user_id,
                "message": text,
                "buttons": buttons,
            }
        resp = await client.post(
            f"{self.onebot_http_url}/{action}",
            json=params,
        )
        resp.raise_for_status()

    async def request_approval(self, req: ApprovalRequest) -> str:
        text = format_approval_card(req)
        if len(text) > 4000:
            text = text[:3990] + "\n..."
        if self.backend == "onebot11":
            await self._send_onebot_card(req, text)
        else:
            raise NotImplementedError(
                "QQ official backend: use Webhook + register_qq_callback; see docs/详细设计.md §12"
            )
        return req.request_id

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        if request_id in self._decisions:
            return self._decisions[request_id]

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if request_id in _interaction_store:
                decision = _interaction_store.pop(request_id)
                self._decisions[request_id] = decision
                return decision
            await asyncio.sleep(self.poll_interval)

        return ApprovalDecision(approved=False, reason="timeout")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
