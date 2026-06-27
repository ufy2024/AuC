from __future__ import annotations

import json

import pytest

from auc.cli import main
from auc.evaluation import (
    DEFAULT_EVAL_DIR,
    EvalCase,
    SuiteReport,
    load_cases,
    render_report,
    run_case,
    run_suite,
)


def test_load_builtin_cases():
    cases = load_cases()
    ids = {c.id for c in cases}
    assert "fix-add" in ids
    assert len(cases) >= 5  # 至少 5 个确定性用例


def test_case_from_dict_requires_id():
    with pytest.raises(ValueError):
        EvalCase.from_dict({"name": "no id"})


@pytest.mark.asyncio
async def test_run_case_pass(tmp_path):
    case = EvalCase(
        id="t-write",
        instruction="write a file",
        script=[
            {"tool": "write_file", "args": {"path": "x.txt", "content": "hi\n"}},
            {"say": "done"},
        ],
        checks=[
            {"status": "completed"},
            {"file": "x.txt", "contains": "hi"},
        ],
    )
    res = await run_case(case, workdir=tmp_path / "wd")
    assert res.passed is True
    assert res.status == "completed"
    assert (tmp_path / "wd" / "x.txt").read_text() == "hi\n"


@pytest.mark.asyncio
async def test_run_case_check_failure(tmp_path):
    case = EvalCase(
        id="t-fail",
        instruction="noop",
        script=[{"say": "nothing"}],
        checks=[{"file": "missing.txt", "contains": "x"}],
    )
    res = await run_case(case, workdir=tmp_path / "wd2")
    assert res.passed is False
    assert res.failed_checks


@pytest.mark.asyncio
async def test_run_case_shell_and_run_check(tmp_path):
    case = EvalCase(
        id="t-shell",
        instruction="shell",
        script=[
            {"tool": "run_command", "args": {"command": 'printf abc > f.txt'}},
            {"say": "ok"},
        ],
        checks=[
            {"run": "test -f f.txt", "exit": 0},
            {"file": "f.txt", "contains": "abc"},
        ],
    )
    res = await run_case(case, workdir=tmp_path / "wd3")
    assert res.passed is True


@pytest.mark.asyncio
async def test_run_suite_builtin_all_pass():
    report = await run_suite()
    assert report.total >= 5
    assert report.pass_rate == 1.0, render_report(report)


@pytest.mark.asyncio
async def test_run_suite_only_filter():
    report = await run_suite(only=["fix-add"])
    assert report.total == 1
    assert report.results[0].case_id == "fix-add"


def test_render_report_lists_failures():
    from auc.evaluation import CheckResult, EvalResult

    report = SuiteReport(
        results=[
            EvalResult("ok", passed=True, status="completed"),
            EvalResult(
                "bad",
                passed=False,
                status="completed",
                checks=[CheckResult(False, "file x", "missing")],
            ),
        ]
    )
    text = render_report(report)
    assert "1/2 通过" in text
    assert "[FAIL] bad" in text
    assert "file x" in text


def test_cli_eval_run_default(capsys):
    code = main(["eval", "run"])
    assert code == 0
    assert "通过率 100%" in capsys.readouterr().out


def test_cli_eval_run_json(capsys):
    code = main(["eval", "run", "--json", "--case", "fix-add"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"] == 1
    assert data["passed"] == 1


def test_default_eval_dir_exists():
    assert DEFAULT_EVAL_DIR.exists()
