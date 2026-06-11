from __future__ import annotations

from typing import Any

_MAX_FILE_CHARS = 24_000
_MAX_SELECTION_CHARS = 8_000

_CURRENT_ALIASES = ("@当前文件", "@当前", "@file", "@here")
_SELECTION_ALIASES = ("@选中", "@selection", "@选区")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n... (已截断)"


def format_context_block(ctx: dict[str, Any] | None) -> str:
    """将 Web 编辑器上下文格式化为 Agent 可读块。"""
    if not ctx:
        return ""
    lines: list[str] = []
    active = ctx.get("active_file")
    if active:
        dirty = " (未保存的编辑)" if ctx.get("dirty") else ""
        lines.append(f"[Web 编辑器] 当前文件: {active}{dirty}")
    if ctx.get("preview_url"):
        lines.append(f"[Web 预览] {ctx.get('preview_title') or ''} · {ctx['preview_url']}")
    if ctx.get("project_name"):
        lines.append(f"[Web 项目] {ctx['project_name']} ({ctx.get('project_kind', '')})")

    selection = (ctx.get("selection") or "").strip()
    if selection:
        start = ctx.get("selection_start_line")
        end = ctx.get("selection_end_line")
        loc = f"行 {start}-{end}" if start and end else "选中区域"
        lines.append(f"{loc}:\n```\n{_truncate(selection, _MAX_SELECTION_CHARS)}\n```")

    include_file = ctx.get("include_file", True)
    content = ctx.get("file_content") or ""
    if include_file and active and content.strip() and not selection:
        lines.append(
            f"--- file: {active} ---\n"
            f"{_truncate(content, _MAX_FILE_CHARS)}\n"
            f"--- end ---"
        )
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def merge_message_with_context(message: str, ctx: dict[str, Any] | None) -> tuple[str, list[str]]:
    """合并用户消息与编辑器上下文，解析 @当前文件 / @选中。"""
    notes: list[str] = []
    text = message.strip()
    block = format_context_block(ctx)

    for alias in _CURRENT_ALIASES:
        if alias in text:
            text = text.replace(alias, "").strip()
            if ctx and ctx.get("active_file"):
                notes.append(f"已附带当前文件 {ctx['active_file']}")
            break

    for alias in _SELECTION_ALIASES:
        if alias in text:
            text = text.replace(alias, "").strip()
            if ctx and (ctx.get("selection") or "").strip():
                notes.append("已附带选中代码")
            elif ctx and ctx.get("active_file"):
                notes.append(f"已附带当前文件 {ctx['active_file']}")
            break

    auto = bool(ctx and ctx.get("auto_attach") and ctx.get("active_file"))
    if auto and not block:
        block = format_context_block({**ctx, "include_file": True})

    if block and auto and not any(alias in message for alias in _CURRENT_ALIASES + _SELECTION_ALIASES):
        notes.append(f"自动附带 {ctx.get('active_file')}")

    if not text and block:
        text = (
            "请根据以上当前代码上下文完成我的需求。"
            "先复述需求要点与变更计划，再用 write_file 写入，"
            "收尾对照验收是否满足需求。"
        )
    elif block:
        text = block + text

    return text, notes
