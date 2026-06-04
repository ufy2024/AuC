from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any
from auc.ports.approval import ApprovalDecision, ApprovalPort, ApprovalRequest

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _require_httpx() -> Any:
    if httpx is None:
        raise ImportError("Install httpx: pip install 'auc[openai]'")
    return httpx


@dataclass
class ConsoleApprovalPort:
    """Dev fallback: print approval card and read y/n from stdin via executor."""

    async def request_approval(self, req: ApprovalRequest) -> str:
        card = _format_card(req)
        print(card)
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
class TelegramApprovalPort:
    """Send L3 approval card to Telegram; poll callback_query updates."""

    bot_token: str | None = None
    chat_id: str | None = None
    poll_interval: float = 2.0
    _client: Any = field(default=None, repr=False)
    _decisions: dict[str, ApprovalDecision] = field(default_factory=dict)
    _request_by_callback: dict[str, str] = field(default_factory=dict)
    _offset: int = 0

    def __post_init__(self) -> None:
        _require_httpx()
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
        text = _format_card(req)
        if len(text) > 4000:
            text = text[:3990] + "\n..."
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "允许并继续", "callback_data": f"auc:approve:{req.request_id}"},
                    {"text": "拒绝并中断", "callback_data": f"auc:deny:{req.request_id}"},
                ]
            ]
        }
        await client.post(
            self._api("sendMessage"),
            json={
                "chat_id": self.chat_id,
                "text": text,
                "reply_markup": keyboard,
            },
        )
        self._request_by_callback[f"auc:approve:{req.request_id}"] = req.request_id
        self._request_by_callback[f"auc:deny:{req.request_id}"] = req.request_id
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
                data = cb.get("data", "")
                if not data.startswith("auc:"):
                    continue
                parts = data.split(":", 2)
                if len(parts) != 3:
                    continue
                action, rid = parts[1], parts[2]
                if rid != request_id:
                    continue
                approved = action == "approve"
                decision = ApprovalDecision(
                    approved=approved,
                    decided_by=str(cb.get("from", {}).get("id", "telegram")),
                    reason=None if approved else "denied",
                )
                self._decisions[request_id] = decision
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


def _format_card(req: ApprovalRequest) -> str:
    diff = req.diff_text or "(no diff)"
    if len(diff) > 1500:
        diff = diff[:1500] + "\n..."
    return (
        "⚠️ AuM 风险提示\n"
        f"Agent `{req.agent_id}` 请求 L3 工具: `{req.tool_name}`\n"
        f"Run: `{req.run_id}`\n"
        f"参数: `{json.dumps(req.arguments, ensure_ascii=False)[:500]}`\n"
        f"--- Diff ---\n{diff}"
    )
