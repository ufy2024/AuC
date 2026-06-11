from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auc.messages import ChatMessage, ImageAttachment
from auc.sandbox import resolve_under_sandbox

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024

_AT_FILE_RE = re.compile(r"@([^\s@]+)")


@dataclass
class PreparedUserInput:
    text: str
    notes: list[str]
    images: list[ImageAttachment]


def is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTS


def mime_for_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def load_image_from_path(sandbox_root: str, rel_path: str) -> ImageAttachment:
    resolved = resolve_under_sandbox(sandbox_root, rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(rel_path)
    if not is_image_path(rel_path):
        raise ValueError(f"not an image: {rel_path}")
    data = resolved.read_bytes()
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError(f"image too large (max {_MAX_IMAGE_BYTES // (1024*1024)}MB): {rel_path}")
    mime = mime_for_path(rel_path)
    return ImageAttachment(
        mime_type=mime,
        data_base64=base64.b64encode(data).decode("ascii"),
        name=resolved.name,
        source_path=rel_path,
    )


def image_from_payload(data: dict[str, Any]) -> ImageAttachment:
    mime = str(data.get("mime_type") or data.get("mimeType") or "image/png")
    b64 = str(data.get("data_base64") or data.get("dataBase64") or "")
    if not b64:
        raise ValueError("image data_base64 required")
    raw = base64.b64decode(b64, validate=True)
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    return ImageAttachment(
        mime_type=mime,
        data_base64=b64,
        name=data.get("name"),
        source_path=data.get("source_path"),
    )


def prepare_user_input(
    text: str,
    sandbox: str,
    *,
    extra_images: list[ImageAttachment] | None = None,
) -> PreparedUserInput:
    """解析 @path：文本文件嵌入内容，图片作为多模态附件。"""
    from auc.terminal import dim, green, red, yellow

    root = Path(sandbox).resolve()
    notes: list[str] = []
    images: list[ImageAttachment] = list(extra_images or [])

    def _repl(match: re.Match[str]) -> str:
        rel = match.group(1).rstrip("/")
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            notes.append(red(f"越界路径 {rel}"))
            return match.group(0)
        if is_image_path(rel):
            try:
                img = load_image_from_path(sandbox, rel)
                images.append(img)
                notes.append(green(f"🖼 @{rel}") + dim(f" · {img.mime_type}"))
            except (OSError, ValueError) as exc:
                notes.append(red(f"无法加载图片 @{rel}: {exc}"))
            return ""
        if not path.is_file():
            notes.append(yellow(f"找不到 @{rel}"))
            return match.group(0)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(red(f"无法读取 @{rel}: {exc}"))
            return match.group(0)
        lines = content.count("\n") + 1
        notes.append(dim(f"📎 @{rel} ({lines} 行)"))
        return f"\n\n--- file: {rel} ---\n{content}\n--- end ---\n\n"

    expanded = _AT_FILE_RE.sub(_repl, text)
    expanded = re.sub(r"\n{3,}", "\n\n", expanded).strip()
    if not expanded and images:
        expanded = "请分析以上图片。"
    return PreparedUserInput(text=expanded, notes=notes, images=images)


def build_user_message(prepared: PreparedUserInput) -> ChatMessage:
    return ChatMessage(
        role="user",
        content=prepared.text,
        images=prepared.images or None,
    )


def openai_message_content(msg: ChatMessage) -> str | list[dict[str, Any]]:
    if msg.role != "user" or not msg.images:
        return msg.content
    parts: list[dict[str, Any]] = []
    if msg.content.strip():
        parts.append({"type": "text", "text": msg.content})
    for img in msg.images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.mime_type};base64,{img.data_base64}",
                },
            }
        )
    return parts or msg.content


def strip_images_for_memory(messages: list[ChatMessage]) -> list[ChatMessage]:
    """进化记忆不落盘 base64 图片。"""
    out: list[ChatMessage] = []
    for m in messages:
        if m.images:
            note = f"[image x{len(m.images)}]"
            content = f"{m.content}\n{note}".strip() if m.content else note
            out.append(
                ChatMessage(
                    role=m.role,
                    content=content,
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                    tool_calls=m.tool_calls,
                    thinking=m.thinking,
                )
            )
        else:
            out.append(m)
    return out


def anthropic_user_content(msg: ChatMessage) -> str | list[dict[str, Any]]:
    if msg.role != "user" or not msg.images:
        return msg.content
    blocks: list[dict[str, Any]] = []
    if msg.content.strip():
        blocks.append({"type": "text", "text": msg.content})
    for img in msg.images:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": img.data_base64,
                },
            }
        )
    return blocks or msg.content
