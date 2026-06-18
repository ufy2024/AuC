"""工作区办公文档识别与元数据（PDF / Word / Excel 等）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from auc.sandbox import resolve_under_sandbox

DocType = Literal["pdf", "word", "word_legacy", "excel", "ppt", "unsupported"]

_DOC_EXT: dict[str, DocType] = {
    ".pdf": "pdf",
    ".docx": "word",
    ".doc": "word_legacy",
    ".xlsx": "excel",
    ".xls": "excel",
    ".pptx": "ppt",
    ".ppt": "ppt",
}

_PREVIEWABLE: frozenset[DocType] = frozenset({"pdf", "word", "excel"})


def document_type(path: str) -> DocType | None:
    ext = Path(path).suffix.lower()
    return _DOC_EXT.get(ext)


def is_document_path(path: str) -> bool:
    return document_type(path) is not None


def is_previewable_document(path: str) -> bool:
    kind = document_type(path)
    return kind is not None and kind in _PREVIEWABLE


def read_document_file(sandbox_root: str, rel_path: str) -> dict[str, object]:
    """返回文档元数据；二进制内容由 /preview 或 /api/workspace/file/raw 提供。"""
    kind = document_type(rel_path)
    if kind is None:
        raise ValueError(f"not a document: {rel_path}")
    resolved = resolve_under_sandbox(sandbox_root, rel_path)
    if not resolved.is_file():
        raise FileNotFoundError(rel_path)
    previewable = kind in _PREVIEWABLE
    encoded = quote(rel_path, safe="/")
    return {
        "path": rel_path,
        "kind": "document",
        "doc_type": kind,
        "previewable": previewable,
        "size": resolved.stat().st_size,
        "preview_url": f"/preview/{encoded}" if kind == "pdf" else None,
        "raw_url": f"/api/workspace/file/raw?path={quote(rel_path)}",
        "filename": resolved.name,
    }
