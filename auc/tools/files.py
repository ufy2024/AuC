from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from auc.sandbox import (
    DEFAULT_MAX_READ_BYTES,
    assert_not_hardlink_escape,
    assert_within_size_limit,
    resolve_under_sandbox,
)
from auc.tools.base import ToolPolicy, tool_from_function

_MAX_WRITE_BYTES = 5_000_000


def make_file_tools(
    sandbox_root: str,
) -> list[tuple[Any, ToolPolicy]]:
    """Sandbox filesystem tools (read / write / list / delete under sandbox_root)."""
    root = Path(sandbox_root).resolve()

    def _read(path: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        assert_not_hardlink_escape(resolved, sandbox_root)
        assert_within_size_limit(resolved, DEFAULT_MAX_READ_BYTES)
        return resolved.read_text(encoding="utf-8")

    def _write(path: str, content: str, append: bool = False) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
            raise ValueError(
                f"content too large: exceeds {_MAX_WRITE_BYTES} bytes; write in chunks"
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # 模型可能以字符串形式传布尔值
        if isinstance(append, str):
            append = append.strip().lower() in ("true", "1", "yes")
        if append:
            with resolved.open("a", encoding="utf-8") as f:
                f.write(content)
            total = resolved.stat().st_size
            return f"appended {len(content)} chars to {resolved} (file now {total} bytes)"
        resolved.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {resolved}"

    def _list_dir(path: str = ".") -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        if not resolved.is_dir():
            return f"not a directory: {resolved}"
        lines = []
        for p in sorted(resolved.iterdir()):
            tag = "dir" if p.is_dir() else "file"
            rel = p.relative_to(root)
            lines.append(f"{tag}\t{rel}")
        return "\n".join(lines) if lines else "(empty)"

    def _delete(path: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        if resolved == root:
            raise ValueError("cannot delete sandbox root")
        if not resolved.exists():
            return f"not found: {resolved}"
        if resolved.is_dir():
            shutil.rmtree(resolved)
            return f"deleted directory {resolved.relative_to(root)}"
        resolved.unlink()
        return f"deleted file {resolved.relative_to(root)}"

    def _l2_policy(tool: Any, pol: ToolPolicy) -> ToolPolicy:
        pol.sandbox_only = True
        return pol

    specs = [
        tool_from_function(
            _read,
            name="read_file",
            description="Read UTF-8 text file under sandbox",
            privilege="L1",
        ),
        tool_from_function(
            _write,
            name="write_file",
            description=(
                "Write UTF-8 file under sandbox. Args: path, content, append (optional bool). "
                "Include path before content. For large files (>150 lines) write in chunks: "
                "first call overwrites, following calls pass append=true to continue the same file."
            ),
            privilege="L2",
            mutates_files=True,
        ),
        tool_from_function(
            _list_dir,
            name="list_dir",
            description="List files and subdirectories under a sandbox path (default .)",
            privilege="L1",
        ),
        tool_from_function(
            _delete,
            name="delete_path",
            description=(
                "Delete a file or directory tree under sandbox (e.g. snake-game). "
                "Cannot delete sandbox root."
            ),
            privilege="L2",
            mutates_files=True,
        ),
    ]
    return [(t, _l2_policy(t, p)) for t, p in specs]
