from __future__ import annotations

from typing import Any

from auc.sandbox import resolve_under_sandbox
from auc.tools.base import ToolPolicy, tool_from_function


def make_file_tools(
    sandbox_root: str,
) -> list[tuple[Any, ToolPolicy]]:
    """Register read/write tools bound to a sandbox root."""

    def _read(path: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        return resolved.read_text(encoding="utf-8")

    def _write(path: str, content: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {resolved}"

    r, rp = tool_from_function(
        _read, name="read_file", description="Read UTF-8 file in sandbox", privilege="L1"
    )
    w, wp = tool_from_function(
        _write,
        name="write_file",
        description="Write UTF-8 file in sandbox",
        privilege="L2",
    )
    wp.sandbox_only = True
    return [(r, rp), (w, wp)]
