"""R28 `auc receipt` CLI 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auc.cli import main
from auc.receipt import ReceiptStore, RunReceipt


def _seed(tmp: Path) -> None:
    ReceiptStore(str(tmp)).write(
        RunReceipt(run_id="run-1", agent_id="a", status="completed", goal="目标X")
    )


def test_receipt_show_latest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    code = main(["receipt", "--sandbox", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "任务回执 · run-1" in out
    assert "目标X" in out


def test_receipt_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(tmp_path)
    code = main(["receipt", "--sandbox", str(tmp_path), "--list"])
    assert code == 0
    assert "run-1" in capsys.readouterr().out


def test_receipt_empty_returns_1(tmp_path: Path) -> None:
    assert main(["receipt", "--sandbox", str(tmp_path)]) == 1
