"""R26 符号索引与工具测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from auc.code_index import SymbolIndex, parse_python_source
from auc.tools.index_tools import make_index_tools


SAMPLE = '''\
import os
from collections import OrderedDict


class Greeter:
    def hello(self, name):
        return greet(name)


def greet(name):
    return f"hi {name}"


def main():
    g = Greeter()
    return g.hello("x")
'''


def test_parse_python_source_symbols_imports_refs() -> None:
    symbols, imports, refs = parse_python_source(SAMPLE)
    by_name = {s.name: s for s in symbols}
    assert by_name["Greeter"].kind == "class"
    assert by_name["hello"].kind == "method"
    assert by_name["hello"].parent == "Greeter"
    assert by_name["greet"].kind == "function"
    assert "os" in imports
    assert "collections.OrderedDict" in imports
    assert "greet" in refs  # 被 hello 与 main 引用


def test_parse_syntax_error_is_safe() -> None:
    symbols, imports, refs = parse_python_source("def (:::")
    assert symbols == [] and imports == [] and refs == {}


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_index_refresh_query_and_persistence(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", SAMPLE)
    idx = SymbolIndex(str(tmp_path))
    stats = idx.refresh()
    assert stats["updated"] == 1

    defs = idx.find_symbol("greet")
    assert len(defs) == 1
    assert defs[0]["path"] == "pkg/mod.py"
    assert defs[0]["kind"] == "function"

    refs = idx.find_references("greet")
    assert len(refs) >= 2  # 定义行 + 调用行

    outline = idx.outline("pkg/mod.py")
    assert outline is not None
    assert "os" in outline["imports"]
    assert any(s["name"] == "Greeter" for s in outline["symbols"])

    # 持久化文件存在，新实例可加载且无改动时不重建
    assert (tmp_path / ".auc" / "index" / "symbols.json").is_file()
    idx2 = SymbolIndex(str(tmp_path))
    stats2 = idx2.refresh()
    assert stats2["updated"] == 0
    assert idx2.find_symbol("Greeter")


def test_index_incremental_add_and_remove(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def alpha():\n    return 1\n")
    idx = SymbolIndex(str(tmp_path))
    idx.refresh()
    assert idx.find_symbol("alpha")

    # 新增文件 -> 增量收录
    _write(tmp_path, "b.py", "def beta():\n    return alpha()\n")
    stats = idx.refresh()
    assert stats["updated"] == 1
    assert idx.find_symbol("beta")
    assert idx.find_references("alpha")  # b.py 引用了 alpha

    # 删除文件 -> 从索引剔除
    (tmp_path / "a.py").unlink()
    stats = idx.refresh()
    assert stats["removed"] == 1
    assert idx.find_symbol("alpha") == []


def test_index_skips_noise_dirs(tmp_path: Path) -> None:
    _write(tmp_path, "real.py", "def keep():\n    return 1\n")
    _write(tmp_path, "node_modules/x.py", "def junk():\n    return 1\n")
    _write(tmp_path, ".git/y.py", "def junk2():\n    return 1\n")
    idx = SymbolIndex(str(tmp_path))
    idx.refresh()
    assert idx.find_symbol("keep")
    assert idx.find_symbol("junk") == []
    assert idx.find_symbol("junk2") == []


def _call(tool, **kwargs) -> dict:
    result = asyncio.run(tool.invoke(kwargs))
    return json.loads(result.content)


def _tool(tools, name):
    for t, _ in tools:
        if t.name == name:
            return t
    raise AssertionError(f"missing tool: {name}")


def test_index_tools_roundtrip(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", SAMPLE)
    tools = make_index_tools(str(tmp_path))
    find_symbol = _tool(tools, "find_symbol")
    find_references = _tool(tools, "find_references")
    outline = _tool(tools, "outline")

    data = _call(find_symbol, name="greet")
    assert data["count"] == 1
    assert data["results"][0]["path"] == "pkg/mod.py"

    data = _call(find_references, symbol="greet")
    assert data["count"] >= 2

    data = _call(outline, path="pkg/mod.py")
    assert any(s["name"] == "Greeter" for s in data["symbols"])

    data = _call(outline, path="nope.py")
    assert "error" in data


def test_index_tools_are_l1(tmp_path: Path) -> None:
    tools = make_index_tools(str(tmp_path))
    for _, pol in tools:
        assert pol.privilege == "L1"
        assert pol.mutates_files is False
        assert pol.mutates_state is False
