from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import base64

from auc.multimodal import is_image_path, load_image_from_path
from auc.web.preview import is_html_path
from auc.sandbox import SandboxViolationError, resolve_under_sandbox

EntryType = Literal["file", "dir"]


@dataclass
class WorkspaceEntry:
    name: str
    path: str
    type: EntryType
    size: int | None = None


@dataclass
class WorkspaceTree:
    path: str
    entries: list[WorkspaceEntry]


def list_tree(sandbox_root: str, subpath: str = ".") -> WorkspaceTree:
    resolved = resolve_under_sandbox(sandbox_root, subpath)
    if not resolved.is_dir():
        raise FileNotFoundError(f"not a directory: {subpath}")
    entries: list[WorkspaceEntry] = []
    for item in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith("."):
            continue
        rel = str(item.relative_to(Path(sandbox_root).resolve()))
        if item.is_dir():
            entries.append(WorkspaceEntry(name=item.name, path=rel, type="dir"))
        else:
            try:
                size = item.stat().st_size
            except OSError:
                size = None
            entries.append(WorkspaceEntry(name=item.name, path=rel, type="file", size=size))
    rel_path = "."
    if subpath not in (".", ""):
        rel_path = str(resolve_under_sandbox(sandbox_root, subpath).relative_to(
            Path(sandbox_root).resolve()
        ))
    return WorkspaceTree(path=rel_path, entries=entries)


def read_image_file(sandbox_root: str, rel_path: str) -> dict[str, object]:
    img = load_image_from_path(sandbox_root, rel_path)
    return {
        "path": rel_path,
        "kind": "image",
        "mime_type": img.mime_type,
        "data_base64": img.data_base64,
        "size": len(base64.b64decode(img.data_base64)),
    }


def read_text_file(sandbox_root: str, rel_path: str) -> dict[str, object]:
    resolved = resolve_under_sandbox(sandbox_root, rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(rel_path)
    content = resolved.read_text(encoding="utf-8", errors="replace")
    return {
        "path": rel_path,
        "kind": "text",
        "content": content,
        "size": resolved.stat().st_size,
    }


def write_text_file(sandbox_root: str, rel_path: str, content: str) -> dict[str, object]:
    resolved = resolve_under_sandbox(sandbox_root, rel_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return {"path": rel_path, "size": len(content.encode("utf-8"))}


def short_display_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return "~" + path[len(home) :]
    return path


def tree_to_dict(tree: WorkspaceTree) -> dict[str, object]:
    return {
        "path": tree.path,
        "entries": [
            {
                "name": e.name,
                "path": e.path,
                "type": e.type,
                "size": e.size,
                "is_image": e.type == "file" and is_image_path(e.path),
                "is_html": e.type == "file" and is_html_path(e.path),
            }
            for e in tree.entries
        ],
    }


__all__ = [
    "SandboxViolationError",
    "list_tree",
    "read_image_file",
    "read_text_file",
    "write_text_file",
    "short_display_path",
    "tree_to_dict",
]
