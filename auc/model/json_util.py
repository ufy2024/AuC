from __future__ import annotations

import json
import re
from typing import Any

# 模型客户端在参数解析失败时注入此键，由循环层转成工具错误反馈（不终止 run）。
PARSE_ERROR_KEY = "__parse_error__"

_WRITE_FILE_TRUNCATED_HINT = (
    "write_file 参数 JSON 不完整（流式输出在 token 上限处被截断），已拒绝写入以避免产生残缺文件。"
    '请分段写入：第一段 {"path":"相对路径","content":"文件前半部分"}；'
    '后续每段加 "append":true 续写剩余内容（{"path":"同一路径","content":"...","append":true}）。'
    "单段建议不超过 150 行。"
)


def safe_parse_tool_input(raw: str, *, tool_name: str | None = None) -> dict[str, Any]:
    """Parse streamed tool JSON; tolerate truncated / reordered keys from LLM streams."""
    text = (raw or "").strip()
    if not text:
        return {}

    # write_file 截断意味着 content 残缺：宁可报错指导分段重写，也不静默写出半个文件。
    is_write = tool_name == "write_file" if tool_name else _looks_like_write_file(text)

    for i, candidate in enumerate(_json_repair_candidates(text)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        # 原文（i==0）允许空对象（无参工具常发 "{}"）；
        # 修复候选要求非空，避免把截断文本错误折叠成空参数。
        if not isinstance(data, dict) or not (data or i == 0):
            continue
        if i > 0 and is_write:
            raise ValueError(_WRITE_FILE_TRUNCATED_HINT)
        return data

    if is_write and _parse_write_file_loose(text):
        raise ValueError(_WRITE_FILE_TRUNCATED_HINT)

    raise ValueError(
        f"invalid tool arguments JSON ({tool_name or 'tool'}): {text[:240]}..."
    )


def _looks_like_write_file(text: str) -> bool:
    return '"content"' in text or '"path"' in text


def _json_repair_candidates(text: str) -> list[str]:
    """Try closing truncated streaming JSON objects with independent suffixes."""
    t = text.rstrip()
    if t.endswith("\\"):
        t = t[:-1]
    out = [text]
    for s in ('"', '"}', '"}}', '"}]}', "}", "}}", "]}"):
        candidate = t + s
        if candidate not in out:
            out.append(candidate)
    return out


def _parse_write_file_loose(text: str) -> dict[str, Any]:
    """提取截断 JSON 中可辨认的 path/content 字段（仅用于判定截断，不用于写入）。"""
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
