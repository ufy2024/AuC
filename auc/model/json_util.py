from __future__ import annotations

import json
import re
from typing import Any


def safe_parse_tool_input(raw: str, *, tool_name: str | None = None) -> dict[str, Any]:
    """Parse streamed tool JSON; tolerate truncated / reordered keys from LLM streams."""
    text = (raw or "").strip()
    if not text:
        return {}

    for candidate in _json_repair_candidates(text):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and data:
                return data
        except json.JSONDecodeError:
            continue

    if tool_name == "write_file" or _looks_like_write_file(text):
        repaired = _parse_write_file_loose(text)
        if repaired.get("path") and "content" in repaired:
            return repaired
        if "content" in repaired and not repaired.get("path"):
            raise ValueError(
                "write_file 缺少 path 字段；流式 JSON 被截断时请拆成多个较小文件，"
                '参数格式: {"path":"相对路径","content":"文件内容"}'
            )

    raise ValueError(
        f"invalid tool arguments JSON ({tool_name or 'tool'}): {text[:240]}..."
    )


def _looks_like_write_file(text: str) -> bool:
    return '"content"' in text or '"path"' in text


def _json_repair_candidates(text: str) -> list[str]:
    """Try progressive closing of truncated streaming JSON objects."""
    out = [text]
    t = text.rstrip()
    if t.endswith("\\"):
        t = t[:-1]
    suffixes = ['"', '"}', '"}', '"}', '}']
    built = t
    for s in suffixes:
        built = built + s
        if built not in out:
            out.append(built)
    return out


def _parse_write_file_loose(text: str) -> dict[str, Any]:
    path = _extract_json_string_field(text, "path")
    content = _extract_json_string_field(text, "content", allow_unterminated=True)
    out: dict[str, Any] = {}
    if path:
        out["path"] = path
    if content is not None:
        out["content"] = content
    return out


def _extract_json_string_field(
    text: str,
    key: str,
    *,
    allow_unterminated: bool = False,
) -> str | None:
    pattern = rf'"{re.escape(key)}"\s*:\s*"'
    m = re.search(pattern, text)
    if not m:
        return None
    quote_start = m.end() - 1
    value, end = _decode_json_string(text, quote_start)
    if value or (allow_unterminated and end > quote_start + 1):
        return value
    return None


def _decode_json_string(s: str, start: int) -> tuple[str, int]:
    """Decode JSON string at s[start]=='\"'; unterminated strings read to EOF."""
    if start >= len(s) or s[start] != '"':
        return "", start
    i = start + 1
    chars: list[str] = []
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
            chars.append(escapes.get(n, n))
            i += 2
            continue
        if c == '"':
            return "".join(chars), i + 1
        chars.append(c)
        i += 1
    return "".join(chars), i
