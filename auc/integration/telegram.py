from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from auc.integration.im_base import HttpImApprovalPort, make_auc_callback, parse_auc_callback
from auc.integration.im_card import format_approval_card
from auc.ports.approval import ApprovalDecision, ApprovalRequest

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _require_httpx(*modes: str) -> Any:
    if httpx is None:
        from auc.extras import hint_for

        raise ImportError(hint_for(*modes, "llm", "all"))
    return httpx


@dataclass
class ConsoleApprovalPort:
    """Dev fallback: print approval card and read y/n from stdin via executor."""

    async def request_approval(self, req: ApprovalRequest) -> str:
        print(format_approval_card(req))
        return req.request_id

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        del timeout

        def _read() -> bool:
            ans = input("[AuM] Allow L3 action? [y/N]: ").strip().lower()
            return ans in ("y", "yes")

        approved = await asyncio.to_thread(_read)
        return ApprovalDecision(
            approved=approved,
            decided_by="console",
            reason=None if approved else "denied",
        )


@dataclass
class InMemoryCallbackApprovalPort:
    """Tests / automation: pre-register decisions by request_id."""

    _decisions: dict[str, ApprovalDecision] = field(default_factory=dict)
    _pending: dict[str, ApprovalRequest] = field(default_factory=dict)

    def set_decision(self, request_id: str, approved: bool, reason: str | None = None) -> None:
        self._decisions[request_id] = ApprovalDecision(
            approved=approved, decided_by="test", reason=reason
        )

    async def request_approval(self, req: ApprovalRequest) -> str:
        self._pending[req.request_id] = req
        return req.request_id

    async def wait_decision(
        self,
        request_id: str,
        timeout: float = 3600.0,
    ) -> ApprovalDecision:
        del timeout
        if request_id in self._decisions:
            return self._decisions[request_id]
        return ApprovalDecision(approved=False, reason="no decision registered")


@dataclass
class TelegramApprovalPort(HttpImApprovalPort):
    """Send L3 approval card to Telegram; poll callback_query updates."""

    bot_token: str | None = None
    chat_id: str | None = None
    _client: Any = field(default=None, repr=False)
    _offset: int = 0

    def __post_init__(self) -> None:
        _require_httpx("telegram")
        if self.bot_token is None:
            self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if self.chat_id is None:
            self.chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not self.bot_token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def request_approval(self, req: ApprovalRequest) -> str:
        client = self._get_client()
        text = format_approval_card(req)
        if len(text) > 4000:
            text = text[:3990] + "\n..."
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "允许并继续", "callback_data": make_auc_callback("approve", req.request_id)},
                    {"text": "拒绝并中断", "callback_data": make_auc_callback("deny", req.request_id)},
                ]
            ]
        }
        resp = await client.post(
            self._api("sendMessage"),
            json={
                "chat_id": self.chat_id,
                "text": text,
                "reply_markup": keyboard,
            },
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Telegram sendMessage 无效响应: {exc}") from exc
        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram sendMessage 失败: {data.get('description') or data}"
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
        client = self._get_client()
        while time.monotonic() < deadline:
            resp = await client.get(
                self._api("getUpdates"),
                params={"offset": self._offset, "timeout": 10},
            )
            resp.raise_for_status()
            for upd in resp.json().get("result", []):
                self._offset = max(self._offset, int(upd["update_id"]) + 1)
                cb = upd.get("callback_query")
                if not cb:
                    continue
                parsed = parse_auc_callback(cb.get("data", ""))
                if parsed is None:
                    continue
                action, rid = parsed
                if rid != request_id:
                    continue
                decision = self.store_decision(
                    request_id,
                    approved=action == "approve",
                    decided_by=str(cb.get("from", {}).get("id", "telegram")),
                )
                await client.post(
                    self._api("answerCallbackQuery"),
                    json={"callback_query_id": cb["id"]},
                )
                return decision
            await asyncio.sleep(self.poll_interval)

        return ApprovalDecision(approved=False, reason="timeout")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
