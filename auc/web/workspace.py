from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import base64

from auc.multimodal import is_image_path, load_image_from_path
from auc.web.documents import is_document_path, read_document_file
from auc.web.preview import is_html_path, media_type_for
from auc.sandbox import (
    SandboxViolationError,
    resolve_under_sandbox,
    resolve_workspace_safe,
)


def resolve_workspace_path(sandbox_root: str, rel_path: str) -> Path:
    """解析工作区相对路径：沙盒约束 + 拒绝 `.auc/` 框架元数据（含符号链接绕过）。"""
    return resolve_workspace_safe(sandbox_root, rel_path)

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
    resolved = resolve_workspace_safe(sandbox_root, subpath)
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
    resolve_workspace_safe(sandbox_root, rel_path)
    img = load_image_from_path(sandbox_root, rel_path)
    return {
        "path": rel_path,
        "kind": "image",
        "mime_type": img.mime_type,
        "data_base64": img.data_base64,
        "size": len(base64.b64decode(img.data_base64)),
    }


def read_text_file(sandbox_root: str, rel_path: str) -> dict[str, object]:
    resolved = resolve_workspace_path(sandbox_root, rel_path)
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
    resolved = resolve_workspace_path(sandbox_root, rel_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return {"path": rel_path, "size": len(content.encode("utf-8"))}


def delete_path(sandbox_root: str, rel_path: str) -> dict[str, object]:
    root = Path(sandbox_root).resolve()
    resolved = resolve_workspace_safe(sandbox_root, rel_path)
    if resolved == root:
        raise ValueError("cannot delete sandbox root")
    if not resolved.exists():
        raise FileNotFoundError(rel_path)
    kind = "dir" if resolved.is_dir() else "file"
    rel = str(resolved.relative_to(root))
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    return {"path": rel, "type": kind, "deleted": True}


def rename_path(sandbox_root: str, rel_path: str, new_path: str) -> dict[str, object]:
    root = Path(sandbox_root).resolve()
    src = resolve_workspace_safe(sandbox_root, rel_path)
    dst = resolve_workspace_safe(sandbox_root, new_path)
    if src == root:
        raise ValueError("cannot rename sandbox root")
    if not src.exists():
        raise FileNotFoundError(rel_path)
    if dst.exists():
        raise FileExistsError(new_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    rel = str(dst.relative_to(root))
    entry_type: EntryType = "dir" if dst.is_dir() else "file"
    return {"path": rel, "type": entry_type, "from": rel_path}


def create_directory(sandbox_root: str, rel_path: str) -> dict[str, object]:
    resolved = resolve_workspace_safe(sandbox_root, rel_path)
    if resolved.exists():
        raise FileExistsError(rel_path)
    resolved.mkdir(parents=True, exist_ok=False)
    rel = str(resolved.relative_to(Path(sandbox_root).resolve()))
    return {"path": rel, "type": "dir"}


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
                "is_document": e.type == "file" and is_document_path(e.path),
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
    "delete_path",
    "rename_path",
    "create_directory",
    "short_display_path",
    "tree_to_dict",
]
