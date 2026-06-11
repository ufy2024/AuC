"""大仓库搜索性能基准（需求 NFR：10 万行仓库 grep/glob < 1s，CI 放宽至 5s）。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from auc.tools.search import make_search_tools

# 1000 文件 × 100 行 = 10 万行
_N_FILES = 1000
_LINES_PER_FILE = 100
_TIME_BUDGET_SEC = 5.0


@pytest.fixture(scope="module")
def big_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("bigrepo")
    line = "def func_{i}_{j}():  # placeholder logic\n    return {j}\n"
    for i in range(_N_FILES):
        sub = root / f"pkg{i % 20}"
        sub.mkdir(exist_ok=True)
        body = "".join(
            line.format(i=i, j=j) for j in range(_LINES_PER_FILE // 2)
        )
        if i == _N_FILES - 7:
            body += "TARGET_NEEDLE = 'unique'\n"
        (sub / f"mod_{i:04d}.py").write_text(body, encoding="utf-8")
    # 噪声目录应被跳过
    nm = root / "node_modules" / "dep"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("TARGET_NEEDLE\n" * 100, encoding="utf-8")
    return root


def _tools(root: Path) -> dict:
    return {t.name: t for t, _ in make_search_tools(str(root))}


def test_grep_large_repo_within_budget(big_repo: Path) -> None:
    tools = _tools(big_repo)
    t0 = time.monotonic()
    tr = asyncio.run(tools["grep_search"].invoke({"pattern": r"TARGET_NEEDLE\b"}))
    elapsed = time.monotonic() - t0
    assert not tr.is_error
    assert "TARGET_NEEDLE" in tr.content
    assert "node_modules" not in tr.content
    assert elapsed < _TIME_BUDGET_SEC, f"grep 超时: {elapsed:.2f}s"


def test_grep_no_match_scans_fast(big_repo: Path) -> None:
    tools = _tools(big_repo)
    t0 = time.monotonic()
    tr = asyncio.run(tools["grep_search"].invoke({"pattern": "absolutely_no_such_token_xyz"}))
    elapsed = time.monotonic() - t0
    assert not tr.is_error
    assert elapsed < _TIME_BUDGET_SEC, f"全仓扫描超时: {elapsed:.2f}s"


def test_grep_max_results_caps_output(big_repo: Path) -> None:
    tools = _tools(big_repo)
    tr = asyncio.run(
        tools["grep_search"].invoke({"pattern": r"def func_", "max_results": 10})
    )
    assert not tr.is_error
    hits = [ln for ln in tr.content.splitlines() if ":" in ln and "def func_" in ln]
    assert len(hits) <= 10


def test_glob_large_repo_within_budget(big_repo: Path) -> None:
    tools = _tools(big_repo)
    t0 = time.monotonic()
    tr = asyncio.run(tools["glob_files"].invoke({"pattern": "**/mod_0042.py"}))
    elapsed = time.monotonic() - t0
    assert not tr.is_error
    assert "mod_0042.py" in tr.content
    assert elapsed < _TIME_BUDGET_SEC, f"glob 超时: {elapsed:.2f}s"
