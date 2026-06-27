"""R27 多轮专项审查纯逻辑测试。"""

from __future__ import annotations

from auc.review import (
    REVIEW_PASSES,
    Finding,
    ReviewResult,
    build_pass_prompt,
    findings_to_todos,
    parse_review_findings,
    render_review_report,
    sort_findings,
)

_CORRECTNESS = REVIEW_PASSES[0]

_SAMPLE = """分析如下。

```json auc-review
{"findings": [
  {"severity": "high", "location": "a.py:10", "issue": "空指针", "suggestion": "加判空"},
  {"severity": "low", "location": "a.py:20", "issue": "命名不清", "suggestion": "改名"}
]}
```
"""


def test_parse_findings_ok() -> None:
    findings = parse_review_findings(_SAMPLE, _CORRECTNESS)
    assert len(findings) == 2
    assert findings[0].severity == "high"
    assert findings[0].location == "a.py:10"
    assert findings[0].pass_id == "correctness"


def test_parse_findings_no_block() -> None:
    assert parse_review_findings("没有结构化块", _CORRECTNESS) == []


def test_parse_findings_invalid_json() -> None:
    bad = "```json auc-review\n{not json}\n```"
    assert parse_review_findings(bad, _CORRECTNESS) == []


def test_parse_findings_empty_list() -> None:
    empty = '```json auc-review\n{"findings": []}\n```'
    assert parse_review_findings(empty, _CORRECTNESS) == []


def test_parse_findings_skips_missing_issue() -> None:
    block = (
        '```json auc-review\n'
        '{"findings": [{"severity": "high", "location": "x", "suggestion": "y"}]}\n'
        '```'
    )
    assert parse_review_findings(block, _CORRECTNESS) == []


def test_invalid_severity_falls_back_to_low() -> None:
    block = (
        '```json auc-review\n'
        '{"findings": [{"severity": "critical", "issue": "x"}]}\n'
        '```'
    )
    findings = parse_review_findings(block, _CORRECTNESS)
    assert findings[0].severity == "low"


def test_sort_by_severity() -> None:
    findings = [
        Finding("low", "", "l", "", "p", "P"),
        Finding("high", "", "h", "", "p", "P"),
        Finding("medium", "", "m", "", "p", "P"),
    ]
    ordered = sort_findings(findings)
    assert [f.severity for f in ordered] == ["high", "medium", "low"]


def test_findings_to_todos() -> None:
    findings = [Finding("high", "a.py:1", "bug", "fix", "correctness", "正确性")]
    todos = findings_to_todos(findings)
    assert todos[0]["id"] == "review-1"
    assert todos[0]["status"] == "pending"
    assert "bug" in todos[0]["content"]


def test_render_report_with_and_without_findings() -> None:
    empty = render_review_report(ReviewResult(target="x", passes_run=["正确性"]))
    assert "未发现明显问题" in empty

    res = ReviewResult(
        target="a.py",
        passes_run=["正确性"],
        findings=[Finding("high", "a.py:1", "bug", "fix", "correctness", "正确性")],
    )
    report = render_review_report(res)
    assert "代码审查报告：a.py" in report
    assert "高危 1" in report
    assert "bug" in report


def test_build_pass_prompt_includes_focus_and_diff() -> None:
    prompt = build_pass_prompt(_CORRECTNESS, "a.py", diff_text="@@ -1 +1 @@\n-x\n+y")
    assert "正确性" in prompt
    assert "auc-review" in prompt
    assert "```diff" in prompt
    assert "+y" in prompt


def test_build_pass_prompt_without_diff_mentions_read_tools() -> None:
    prompt = build_pass_prompt(_CORRECTNESS, "a.py")
    assert "read_file" in prompt
