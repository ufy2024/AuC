"""R26 符号代码索引（基线：零依赖 `ast`，仅 Python）。

为 grep/glob 之上补一层「定义/引用/import 图」索引，解决大仓库「谁定义了 X /
谁引用了 X / 某文件结构」的快速定位。落 `.auc/index/symbols.json`，按 mtime 增量
更新；非 Python 文件不入索引（可后续以 tree-sitter extra 扩展）。

可选语义层（向量检索）默认关闭以守「零硬依赖」；无 embedding 时即本符号索引 + grep。
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auc.tools.search import SKIP_DIRS

_INDEX_VERSION = 1
_MAX_FILE_BYTES = 1_500_000


@dataclass
class Symbol:
    name: str
    kind: str  # function / async_function / class / method
    line: int
    parent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "parent": self.parent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Symbol":
        return cls(
            name=str(d.get("name") or ""),
            kind=str(d.get("kind") or "function"),
            line=int(d.get("line") or 0),
            parent=str(d.get("parent") or ""),
        )


@dataclass
class FileEntry:
    path: str
    mtime: float
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    references: dict[str, list[int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mtime": self.mtime,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": self.imports,
            "references": self.references,
        }

    @classmethod
    def from_dict(cls, path: str, d: dict[str, Any]) -> "FileEntry":
        return cls(
            path=path,
            mtime=float(d.get("mtime") or 0.0),
            symbols=[Symbol.from_dict(s) for s in d.get("symbols") or []],
            imports=[str(x) for x in d.get("imports") or []],
            references={
                str(k): [int(n) for n in v]
                for k, v in (d.get("references") or {}).items()
            },
        )


class _SymbolVisitor(ast.NodeVisitor):
    """收集定义（含类内方法的 parent）、import、名称引用。"""

    def __init__(self) -> None:
        self.symbols: list[Symbol] = []
        self.imports: list[str] = []
        self.references: dict[str, list[int]] = {}
        self._class_stack: list[str] = []

    def _add_ref(self, name: str, line: int) -> None:
        if not name:
            return
        self.references.setdefault(name, [])
        if line not in self.references[name]:
            self.references[name].append(line)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(Symbol(name=node.name, kind="class", line=node.lineno))
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(self, node: ast.AST, is_async: bool) -> None:
        parent = self._class_stack[-1] if self._class_stack else ""
        kind = "method" if parent else ("async_function" if is_async else "function")
        self.symbols.append(
            Symbol(
                name=getattr(node, "name", ""),
                kind=kind,
                line=getattr(node, "lineno", 0),
                parent=parent,
            )
        )
        # 函数体内的嵌套定义不再视为 method（避免 parent 误判）
        saved = self._class_stack
        self._class_stack = []
        self.generic_visit(node)
        self._class_stack = saved

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node, is_async=True)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            self.imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._add_ref(node.id, node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._add_ref(node.attr, node.lineno)
        self.generic_visit(node)


def parse_python_source(source: str) -> tuple[list[Symbol], list[str], dict[str, list[int]]]:
    """解析 Python 源码，返回 (symbols, imports, references)。语法错误时返回空。"""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return [], [], {}
    visitor = _SymbolVisitor()
    visitor.visit(tree)
    return visitor.symbols, visitor.imports, visitor.references


class SymbolIndex:
    """沙盒内 Python 符号索引；mtime 增量更新，持久化到 .auc/index/symbols.json。"""

    def __init__(self, sandbox_root: str) -> None:
        self.root = Path(sandbox_root).resolve()
        self._index_path = self.root / ".auc" / "index" / "symbols.json"
        self.files: dict[str, FileEntry] = {}
        self._loaded = False

    # ── 持久化 ──
    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._index_path.is_file():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if int(data.get("version") or 0) != _INDEX_VERSION:
            return
        for path, entry in (data.get("files") or {}).items():
            if isinstance(entry, dict):
                self.files[path] = FileEntry.from_dict(path, entry)

    def save(self) -> None:
        payload = {
            "version": _INDEX_VERSION,
            "files": {p: e.to_dict() for p, e in self.files.items()},
        }
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._index_path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self._index_path)
        except OSError:
            pass

    # ── 扫描 / 增量构建 ──
    def _extra_exts(self) -> tuple[str, ...]:
        """tree-sitter 可用时额外索引的多语言扩展名（R26 增量）。"""
        try:
            from auc.index_backends import EXT_LANG, treesitter_available

            if treesitter_available():
                return tuple(EXT_LANG.keys())
        except Exception:  # noqa: BLE001
            pass
        return ()

    def _iter_py_files(self) -> list[Path]:
        exts = (".py",) + self._extra_exts()
        out: list[Path] = []
        stack = [self.root]
        while stack:
            cur = stack.pop()
            try:
                entries = list(os.scandir(cur))
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_DIRS and not entry.name.startswith(".git"):
                        stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(exts):
                    out.append(Path(entry.path))
        return out

    def _parse_file(
        self, path: Path, source: str
    ) -> tuple[list[Symbol], list[str], dict[str, list[int]]]:
        """按扩展名选择解析后端：.py 走 ast，其余走 tree-sitter（缺失则空）。"""
        if path.name.endswith(".py"):
            return parse_python_source(source)
        try:
            from auc.index_backends import detect_language, parse_source

            lang = detect_language(path.name)
            if lang is not None:
                result = parse_source(source, lang)
                if result is not None:
                    return result
        except Exception:  # noqa: BLE001 多语言后端失败安全降级
            pass
        return [], [], {}

    def refresh(self) -> dict[str, int]:
        """增量刷新索引；返回 {scanned, updated, removed}。"""
        self.load()
        found = self._iter_py_files()
        found_rel = set()
        updated = 0
        for path in found:
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_size > _MAX_FILE_BYTES:
                continue
            rel = os.path.relpath(path, self.root)
            found_rel.add(rel)
            prev = self.files.get(rel)
            if prev is not None and abs(prev.mtime - st.st_mtime) < 1e-6:
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            symbols, imports, references = self._parse_file(path, source)
            self.files[rel] = FileEntry(
                path=rel,
                mtime=st.st_mtime,
                symbols=symbols,
                imports=imports,
                references=references,
            )
            updated += 1
        removed = 0
        for rel in list(self.files):
            if rel not in found_rel:
                del self.files[rel]
                removed += 1
        if updated or removed:
            self.save()
        return {"scanned": len(found_rel), "updated": updated, "removed": removed}

    # ── 查询 ──
    def find_symbol(self, name: str) -> list[dict[str, Any]]:
        name = (name or "").strip()
        if not name:
            return []
        exact: list[dict[str, Any]] = []
        partial: list[dict[str, Any]] = []
        for entry in self.files.values():
            for sym in entry.symbols:
                if sym.name == name:
                    exact.append({**sym.to_dict(), "path": entry.path})
                elif name.lower() in sym.name.lower():
                    partial.append({**sym.to_dict(), "path": entry.path})
        results = exact or partial
        results.sort(key=lambda r: (r["path"], r["line"]))
        return results

    def find_references(self, name: str) -> list[dict[str, Any]]:
        name = (name or "").strip()
        if not name:
            return []
        out: list[dict[str, Any]] = []
        for entry in self.files.values():
            seen: set[int] = set()
            for sym in entry.symbols:
                if sym.name == name:
                    seen.add(sym.line)
                    out.append({"path": entry.path, "line": sym.line, "kind": "definition"})
            for line in entry.references.get(name, []):
                if line in seen:
                    continue
                out.append({"path": entry.path, "line": line, "kind": "reference"})
        out.sort(key=lambda r: (r["path"], r["line"]))
        return out

    def outline(self, rel_path: str) -> dict[str, Any] | None:
        rel = os.path.relpath(
            (self.root / rel_path).resolve(), self.root
        )
        entry = self.files.get(rel) or self.files.get(rel_path)
        if entry is None:
            return None
        return {
            "path": entry.path,
            "imports": entry.imports,
            "symbols": [s.to_dict() for s in entry.symbols],
        }
