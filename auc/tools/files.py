from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from auc.sandbox import resolve_under_sandbox
from auc.tools.base import ToolPolicy, tool_from_function


def make_file_tools(
    sandbox_root: str,
) -> list[tuple[Any, ToolPolicy]]:
    """Sandbox filesystem tools (read / write / list / delete under sandbox_root)."""
    root = Path(sandbox_root).resolve()

    def _read(path: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        return resolved.read_text(encoding="utf-8")

    def _write(path: str, content: str) -> str:
        resolved = resolve_under_sandbox(sandbox_root, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
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
                "Write UTF-8 file under sandbox. Args: path, content (JSON). "
                "Include path before content; split large files across calls."
            ),
            privilege="L2",
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
        ),
    ]
    return [(t, _l2_policy(t, p)) for t, p in specs]
