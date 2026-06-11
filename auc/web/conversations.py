"""Web 对话记录：持久化、列表、切换续聊。"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auc.messages import ChatMessage, ImageAttachment, ToolCall

_WORK_MODE_PREFIX_RE = re.compile(
    r"^\[工作模式：[^\]]+\]\n.*?\n\n",
    re.DOTALL,
)
_EDITOR_CTX_RE = re.compile(
    r"^\[Web [^\]]+\][^\n]*\n|"
    r"^--- file:[^\n]*\n[\s\S]*?--- end ---\n*",
    re.MULTILINE,
)


@dataclass
class ConversationSummary:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_user_display(content: str) -> str:
    text = _WORK_MODE_PREFIX_RE.sub("", content or "").strip()
    text = _EDITOR_CTX_RE.sub("", text).strip()
    return text


def title_from_messages(messages: list[ChatMessage]) -> str:
    for msg in messages:
        if msg.role != "user":
            continue
        line = _strip_user_display(msg.content).split("\n")[0].strip()
        if line:
            return line[:48] + ("…" if len(line) > 48 else "")
    return "新对话"


def message_to_dict(msg: ChatMessage) -> dict[str, Any]:
    data: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
    if msg.tool_call_id:
        data["tool_call_id"] = msg.tool_call_id
    if msg.name:
        data["name"] = msg.name
    if msg.thinking:
        data["thinking"] = msg.thinking
    if msg.tool_calls:
        data["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.images:
        data["images"] = [
            {
                "mime_type": img.mime_type,
                "data_base64": img.data_base64,
                "name": img.name,
                "source_path": img.source_path,
            }
            for img in msg.images
        ]
    return data


def message_from_dict(data: dict[str, Any]) -> ChatMessage:
    tool_calls = None
    if data.get("tool_calls"):
        tool_calls = [
            ToolCall(
                id=str(tc["id"]),
                name=str(tc["name"]),
                arguments=dict(tc.get("arguments") or {}),
            )
            for tc in data["tool_calls"]
        ]
    images = None
    if data.get("images"):
        images = [
            ImageAttachment(
                mime_type=str(img["mime_type"]),
                data_base64=str(img["data_base64"]),
                name=img.get("name"),
                source_path=img.get("source_path"),
            )
            for img in data["images"]
        ]
    return ChatMessage(
        role=data["role"],
        content=str(data.get("content") or ""),
        tool_call_id=data.get("tool_call_id"),
        name=data.get("name"),
        tool_calls=tool_calls,
        thinking=data.get("thinking"),
        images=images,
    )


def messages_for_ui(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """供前端渲染的对话条目（跳过 system / 空 assistant tool-only）。"""
    items: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            continue
        if msg.role == "user":
            items.append(
                {
                    "role": "user",
                    "content": _strip_user_display(msg.content),
                    "images": message_to_dict(msg).get("images"),
                }
            )
            continue
        if msg.role == "assistant":
            if msg.content and msg.content.strip():
                items.append({"role": "assistant", "content": msg.content})
            continue
        if msg.role == "tool":
            items.append(
                {
                    "role": "tool",
                    "name": msg.name or "tool",
                    "content": msg.content,
                    "is_error": msg.content.startswith("Error") or "error" in msg.content[:80].lower(),
                }
            )
    return items


class ConversationStore:
    def __init__(self, sandbox_root: str) -> None:
        self.root = Path(sandbox_root).resolve() / ".auc" / "conversations"
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"

    def _read_index(self) -> dict[str, Any]:
        if not self._index_path.is_file():
            return {"active_id": None, "conversations": []}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"active_id": None, "conversations": []}

    def _write_index(self, data: dict[str, Any]) -> None:
        self._index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _conv_path(self, conv_id: str) -> Path:
        return self.root / f"{conv_id}.json"

    def exists(self, conv_id: str) -> bool:
        return self._conv_path(conv_id).is_file()

    def get_active_id(self) -> str | None:
        return self._read_index().get("active_id")

    def set_active_id(self, conv_id: str) -> None:
        idx = self._read_index()
        idx["active_id"] = conv_id
        self._write_index(idx)

    def list_summaries(self) -> list[ConversationSummary]:
        idx = self._read_index()
        out: list[ConversationSummary] = []
        for row in idx.get("conversations") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            out.append(
                ConversationSummary(
                    id=str(row["id"]),
                    title=str(row.get("title") or "新对话"),
                    created_at=str(row.get("created_at") or ""),
                    updated_at=str(row.get("updated_at") or ""),
                    message_count=int(row.get("message_count") or 0),
                )
            )
        out.sort(key=lambda c: c.updated_at, reverse=True)
        return out

    def create(self) -> str:
        conv_id = str(uuid.uuid4())
        now = _now_iso()
        payload = {
            "id": conv_id,
            "title": "新对话",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        self._conv_path(conv_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        idx = self._read_index()
        rows = list(idx.get("conversations") or [])
        rows.insert(
            0,
            {
                "id": conv_id,
                "title": "新对话",
                "created_at": now,
                "updated_at": now,
                "message_count": 0,
            },
        )
        idx["conversations"] = rows
        idx["active_id"] = conv_id
        self._write_index(idx)
        return conv_id

    def load_messages(self, conv_id: str) -> list[ChatMessage]:
        path = self._conv_path(conv_id)
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        raw = data.get("messages") or []
        return [message_from_dict(m) for m in raw if isinstance(m, dict)]

    def save_messages(
        self,
        conv_id: str,
        messages: list[ChatMessage],
        *,
        set_active: bool = True,
    ) -> ConversationSummary:
        path = self._conv_path(conv_id)
        now = _now_iso()
        title = title_from_messages(messages)
        created = now
        if path.is_file():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                created = str(old.get("created_at") or now)
            except (json.JSONDecodeError, OSError):
                pass
        payload = {
            "id": conv_id,
            "title": title,
            "created_at": created,
            "updated_at": now,
            "messages": [message_to_dict(m) for m in messages],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = ConversationSummary(
            id=conv_id,
            title=title,
            created_at=created,
            updated_at=now,
            message_count=len([m for m in messages if m.role in ("user", "assistant")]),
        )
        idx = self._read_index()
        rows = [r for r in (idx.get("conversations") or []) if r.get("id") != conv_id]
        rows.insert(0, summary.to_dict())
        idx["conversations"] = rows
        if set_active:
            idx["active_id"] = conv_id
        self._write_index(idx)
        return summary

    def delete(self, conv_id: str) -> None:
        path = self._conv_path(conv_id)
        if path.is_file():
            path.unlink()
        idx = self._read_index()
        rows = [r for r in (idx.get("conversations") or []) if r.get("id") != conv_id]
        idx["conversations"] = rows
        if idx.get("active_id") == conv_id:
            idx["active_id"] = rows[0]["id"] if rows else None
        self._write_index(idx)

    def get_or_create_active(self) -> tuple[str, list[ChatMessage]]:
        active = self.get_active_id()
        if active and self._conv_path(active).is_file():
            return active, self.load_messages(active)
        conv_id = self.create()
        return conv_id, []
