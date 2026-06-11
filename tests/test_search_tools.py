import asyncio

from auc.tools.search import make_search_tools


def _setup(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def main():\n    return 'needle'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "util.py").write_text(
        "VALUE = 1\n# needle in comment\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("docs needle\n", encoding="utf-8")
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config.py").write_text("needle\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"needle\x00binary")


def _tools(tmp_path):
    pairs = make_search_tools(str(tmp_path))
    return {t.name: t for t, _ in pairs}, {t.name: p for t, p in pairs}


def test_grep_hits_and_skips(tmp_path) -> None:
    _setup(tmp_path)
    tools, policies = _tools(tmp_path)
    tr = asyncio.run(tools["grep_search"].invoke({"pattern": "needle"}))
    assert not tr.is_error
    assert "src/app.py:2:" in tr.content
    assert ".git" not in tr.content
    assert "blob.bin" not in tr.content
    assert policies["grep_search"].privilege == "L1"


def test_grep_glob_filter(tmp_path) -> None:
    _setup(tmp_path)
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(
        tools["grep_search"].invoke({"pattern": "needle", "glob": "*.md"})
    )
    assert "README.md" in tr.content
    assert "app.py" not in tr.content


def test_grep_max_results_truncated(tmp_path) -> None:
    big = "\n".join(f"line needle {i}" for i in range(100))
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(
        tools["grep_search"].invoke({"pattern": "needle", "max_results": 5})
    )
    assert "(truncated)" in tr.content
    assert tr.content.count("big.txt") == 5


def test_grep_invalid_regex(tmp_path) -> None:
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(tools["grep_search"].invoke({"pattern": "[unclosed"}))
    assert tr.is_error
    assert "无效正则" in tr.content


def test_grep_no_match(tmp_path) -> None:
    _setup(tmp_path)
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(tools["grep_search"].invoke({"pattern": "zzz_not_there"}))
    assert tr.content == "no matches"


def test_glob_files_sorted_by_mtime(tmp_path) -> None:
    import os
    import time

    _setup(tmp_path)
    old = tmp_path / "src" / "app.py"
    new = tmp_path / "src" / "util.py"
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(new, (now, now))
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(tools["glob_files"].invoke({"pattern": "*.py"}))
    lines = tr.content.splitlines()
    assert lines.index("src/util.py") < lines.index("src/app.py")


def test_glob_no_match(tmp_path) -> None:
    _setup(tmp_path)
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(tools["glob_files"].invoke({"pattern": "*.rs"}))
    assert tr.content == "no files matched"


def test_glob_relative_path_pattern(tmp_path) -> None:
    _setup(tmp_path)
    tools, _ = _tools(tmp_path)
    tr = asyncio.run(tools["glob_files"].invoke({"pattern": "src/*.py"}))
    assert "src/app.py" in tr.content
    assert "README.md" not in tr.content
