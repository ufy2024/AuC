from __future__ import annotations

from auc import index_backends as ib


def test_detect_language():
    assert ib.detect_language("a.ts") == "typescript"
    assert ib.detect_language("a.tsx") == "tsx"
    assert ib.detect_language("main.go") == "go"
    assert ib.detect_language("lib.rs") == "rust"
    assert ib.detect_language("X.java") == "java"
    assert ib.detect_language("m.rb") == "ruby"
    # Python 与未知交回 ast/降级
    assert ib.detect_language("x.py") is None
    assert ib.detect_language("README.md") is None


def test_def_tables_cover_declared_langs():
    # 每个扩展名映射到的语言都应有定义节点表
    for lang in set(ib.EXT_LANG.values()):
        assert lang in ib._DEF_NODES


def test_parse_source_unsupported_lang_returns_none():
    assert ib.parse_source("x", "cobol") is None


def test_parse_source_degrades_without_treesitter(monkeypatch):
    # 强制后端不可用 → parse_source 返回 None（调用方降级）
    ib._loader.cache_clear()
    ib._parser_for.cache_clear()
    monkeypatch.setattr(ib, "_loader", lambda: None)
    assert ib.treesitter_available() is False
    assert ib.parse_source("function f(){}", "javascript") is None


def test_symbolindex_degrades_to_python_only(tmp_path, monkeypatch):
    # tree-sitter 不可用时，SymbolIndex 仅索引 .py，多语言文件被忽略
    from auc.code_index import SymbolIndex

    monkeypatch.setattr(ib, "treesitter_available", lambda: False)
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("function bar() {}\n", encoding="utf-8")
    idx = SymbolIndex(str(tmp_path))
    idx.refresh()
    assert idx.find_symbol("foo")
    # ts 文件未被索引
    assert idx.find_symbol("bar") == []


def test_symbolindex_parse_file_dispatch(tmp_path, monkeypatch):
    # 当后端声称可用但 parse 返回 None 时，_parse_file 安全返回空
    from auc.code_index import SymbolIndex

    monkeypatch.setattr(ib, "detect_language", lambda name: "javascript")
    monkeypatch.setattr(ib, "parse_source", lambda src, lang: None)
    idx = SymbolIndex(str(tmp_path))
    syms, imports, refs = idx._parse_file(tmp_path / "x.js", "function f(){}")
    assert syms == [] and imports == [] and refs == {}
