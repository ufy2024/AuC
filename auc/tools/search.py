"""R2 代码搜索工具：grep_search（正则内容检索）/ glob_files（文件名定位），均 L1。

纯 Python 基线实现；探测到 ripgrep (`rg`) 时委托加速，输出格式归一。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from auc.tools.base import FunctionTool, ToolPolicy

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".auc"}
)
MAX_FILE_BYTES = 2 * 1024 * 1024
_BINARY_PROBE = 1024


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return b"\x00" in f.read(_BINARY_PROBE)
    except OSError:
        return True


def iter_files(root: Path) -> "list[Path]":
    """递归遍历沙盒，跳过常见噪音目录。"""
    out: list[Path] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_dir(follow_symlinks=False):
                if name not in SKIP_DIRS and not name.startswith(".git"):
                    stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                out.append(Path(entry.path))
    return out


def _grep_python(
    root: Path,
    pattern: re.Pattern[str],
    glob: str | None,
    max_results: int,
    context_lines: int,
) -> tuple[list[str], int, bool]:
    lines_out: list[str] = []
    matched_files = 0
    truncated = False
    for path in sorted(iter_files(root)):
        rel = path.relative_to(root).as_posix()
        if glob and not fnmatch.fnmatch(rel, glob) and not fnmatch.fnmatch(path.name, glob):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES or _is_binary(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_lines = text.splitlines()
        file_hit = False
        for i, line in enumerate(file_lines):
            if not pattern.search(line):
                continue
            file_hit = True
            if context_lines > 0:
                lo = max(0, i - context_lines)
                hi = min(len(file_lines), i + context_lines + 1)
                for j in range(lo, hi):
                    sep = ":" if j == i else "-"
                    lines_out.append(f"{rel}{sep}{j + 1}{sep} {file_lines[j]}")
            else:
                lines_out.append(f"{rel}:{i + 1}: {line}")
            if len(lines_out) >= max_results:
                truncated = True
                break
        if file_hit:
            matched_files += 1
        if truncated:
            break
    return lines_out, matched_files, truncated


def _grep_rg(
    root: Path,
    pattern: str,
    glob: str | None,
    max_results: int,
    context_lines: int,
) -> tuple[list[str], int, bool] | None:
    rg = shutil.which("rg")
    if not rg:
        return None
    cmd = [rg, "--json", "--max-count", str(max_results), pattern]
    if glob:
        cmd[1:1] = ["--glob", glob]
    for d in SKIP_DIRS:
        cmd[1:1] = ["--glob", f"!{d}/**"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True, timeout=30
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode not in (0, 1):  # 2 = 参数/正则错误，回退纯 Python 报错路径
        return None
    lines_out: list[str] = []
    files: set[str] = set()
    truncated = False
    for raw in proc.stdout.splitlines():
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj["data"]
        rel = data["path"]["text"]
        line_no = data["line_number"]
        text = data["lines"]["text"].rstrip("\n")
        files.add(rel)
        lines_out.append(f"{rel}:{line_no}: {text}")
        if len(lines_out) >= max_results:
            truncated = True
            break
    del context_lines  # rg 路径暂不展开上下文行，保持输出归一
    return lines_out, len(files), truncated


def make_search_tools(sandbox_root: str) -> list[tuple[FunctionTool, ToolPolicy]]:
    root = Path(sandbox_root).resolve()

    def _grep_search(
        pattern: str,
        glob: str = "",
        max_results: int = 50,
        context_lines: int = 0,
    ) -> str:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"无效正则: {exc}") from exc
        max_results = min(int(max_results or 50), 200)
        context_lines = max(0, min(int(context_lines or 0), 5))
        result = None
        if context_lines == 0:
            result = _grep_rg(root, pattern, glob or None, max_results, context_lines)
        if result is None:
            result = _grep_python(
                root, compiled, glob or None, max_results, context_lines
            )
        lines, matched_files, truncated = result
        if not lines:
            return "no matches"
        tail = f"\nmatched {matched_files} files" + (" (truncated)" if truncated else "")
        return "\n".join(lines) + tail

    def _glob_files(pattern: str, max_results: int = 200) -> str:
        max_results = min(int(max_results or 200), 1000)
        hits: list[tuple[float, str]] = []
        for path in iter_files(root):
            rel = path.relative_to(root).as_posix()
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                hits.append((mtime, rel))
        hits.sort(key=lambda x: -x[0])
        truncated = len(hits) > max_results
        out = [rel for _, rel in hits[:max_results]]
        if not out:
            return "no files matched"
        return "\n".join(out) + ("\n(truncated)" if truncated else "")

    # path 参数不存在，沙盒由闭包 root 保证；仍标 L1
    grep_tool = FunctionTool(
        _name="grep_search",
        _description=(
            "Search file contents with a regex inside the sandbox. "
            "Returns `path:line: text` lines. Use glob to filter files."
        ),
        _fn=_grep_search,
        _parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式"},
                "glob": {
                    "type": "string",
                    "description": "可选文件过滤，如 '*.py' 或 'src/**/*.ts'",
                },
                "max_results": {"type": "number", "description": "最大匹配行数，默认 50"},
                "context_lines": {
                    "type": "number",
                    "description": "上下文行数（0-5），默认 0",
                },
            },
            "required": ["pattern"],
        },
    )
    glob_tool = FunctionTool(
        _name="glob_files",
        _description=(
            "Find files by glob pattern (e.g. '**/*.py', 'test_*.py'), "
            "sorted by modification time (newest first)."
        ),
        _fn=_glob_files,
        _parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 模式"},
                "max_results": {"type": "number", "description": "最大返回数，默认 200"},
            },
            "required": ["pattern"],
        },
    )
    return [
        (grep_tool, ToolPolicy(name="grep_search", privilege="L1")),
        (glob_tool, ToolPolicy(name="glob_files", privilege="L1")),
    ]
