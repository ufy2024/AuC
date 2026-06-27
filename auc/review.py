"""R27 多轮专项审查：固定 pass 序列 + 结构化 findings 协议。

复用计划模式的「围栏块」思路（```json auc-review```）。核心逻辑（pass 定义、
prompt 构造、findings 解析、报告渲染、转 Todo）皆为纯函数，便于测试；与模型/
Agent 的编排在 CLI 驱动层完成。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_REVIEW_FENCE_RE = re.compile(
    r"```json\s+auc-review\s*\n(?P<body>.*?)```",
    re.DOTALL,
)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_ICON = {"high": "●", "medium": "◐", "low": "○"}


@dataclass(frozen=True)
class ReviewPass:
    id: str
    label: str
    focus: str


# 固定 pass 序列：正确性 → 安全 → 性能 → 风格/可维护（对标 Claude /ultrareview）
REVIEW_PASSES: list[ReviewPass] = [
    ReviewPass(
        "correctness",
        "正确性",
        "逻辑错误、边界条件、空值/异常处理、资源泄漏、并发竞争、错误的算法或数据结构、对契约的违反。",
    ),
    ReviewPass(
        "security",
        "安全",
        "注入（SQL/命令/路径穿越）、越权、密钥/凭据泄漏、不安全反序列化、SSRF、缺失输入校验、危险默认值。",
    ),
    ReviewPass(
        "performance",
        "性能",
        "不必要的复杂度、N+1 查询、重复计算、阻塞 IO、可缓存项、内存放大、热点路径上的低效写法。",
    ),
    ReviewPass(
        "maintainability",
        "风格/可维护",
        "命名、重复代码、过长函数、缺少测试、可读性、注释/文档缺口、不一致的风格。",
    ),
]


@dataclass
class Finding:
    severity: str
    location: str
    issue: str
    suggestion: str
    pass_id: str = ""
    pass_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "location": self.location,
            "issue": self.issue,
            "suggestion": self.suggestion,
            "pass_id": self.pass_id,
            "pass_label": self.pass_label,
        }


@dataclass
class ReviewResult:
    target: str
    findings: list[Finding] = field(default_factory=list)
    passes_run: list[str] = field(default_factory=list)


def _review_output_spec() -> str:
    return (
        "充分阅读相关代码后，在回复末尾输出结构化结果，必须用如下围栏块"
        "（语言标注 `json auc-review`，严格合法 JSON）：\n\n"
        "```json auc-review\n"
        "{\n"
        '  "findings": [\n'
        '    {"severity": "high|medium|low", "location": "文件:行号",'
        ' "issue": "问题描述", "suggestion": "可执行的修改建议"}\n'
        "  ]\n"
        "}\n"
        "```\n"
        "若本维度没有问题，输出 `{\"findings\": []}`。"
    )


def build_pass_prompt(
    pass_spec: ReviewPass,
    target_desc: str,
    *,
    diff_text: str | None = None,
) -> str:
    """构造单个 pass 的审查指令。"""
    lines = [
        f"[审查 pass：{pass_spec.label}]",
        f"本轮只关注「{pass_spec.label}」维度：{pass_spec.focus}",
        "",
        f"审查对象：{target_desc}",
    ]
    if diff_text:
        lines.append("")
        lines.append("以下为待审查的改动 diff：")
        lines.append("```diff")
        lines.append(diff_text.rstrip())
        lines.append("```")
    else:
        lines.append(
            "用 read_file / grep_search 阅读相关代码取证，定位到具体文件与行号。"
        )
    lines.append("")
    lines.append("仅报告该维度的真实问题，不要泛泛而谈，不要直接改文件。")
    lines.append("")
    lines.append(_review_output_spec())
    return "\n".join(lines)


def parse_review_findings(text: str | None, pass_spec: ReviewPass) -> list[Finding]:
    """从 assistant 文本提取 auc-review 围栏块；解析失败返回空列表。"""
    if not text:
        return []
    m = _REVIEW_FENCE_RE.search(text)
    if m is None:
        return []
    try:
        data = json.loads(m.group("body"))
    except json.JSONDecodeError:
        return []
    raw = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[Finding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "low").strip().lower()
        if severity not in SEVERITY_ORDER:
            severity = "low"
        issue = str(item.get("issue") or "").strip()
        if not issue:
            continue
        out.append(
            Finding(
                severity=severity,
                location=str(item.get("location") or "").strip(),
                issue=issue,
                suggestion=str(item.get("suggestion") or "").strip(),
                pass_id=pass_spec.id,
                pass_label=pass_spec.label,
            )
        )
    return out


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (
            SEVERITY_ORDER.get(f.severity, 9),
            f.pass_id,
            f.location,
        ),
    )


def findings_to_todos(findings: list[Finding]) -> list[dict[str, str]]:
    """把审查问题转为 R10 任务清单条目（供一键转 Todo）。"""
    todos: list[dict[str, str]] = []
    for i, f in enumerate(sort_findings(findings), start=1):
        loc = f" [{f.location}]" if f.location else ""
        todos.append(
            {
                "id": f"review-{i}",
                "content": f"({f.severity}/{f.pass_label}){loc} {f.issue}",
                "status": "pending",
            }
        )
    return todos


def render_review_report(result: ReviewResult) -> str:
    """渲染 Markdown 审查报告。"""
    findings = sort_findings(result.findings)
    counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    lines = [
        f"# 代码审查报告：{result.target}",
        "",
        f"- 审查维度：{', '.join(result.passes_run)}",
        f"- 问题统计：高危 {counts['high']} · 中 {counts['medium']} · 低 {counts['low']}"
        f"（共 {len(findings)}）",
        "",
    ]
    if not findings:
        lines.append("未发现明显问题。✅")
        return "\n".join(lines)
    for f in findings:
        icon = SEVERITY_ICON.get(f.severity, "○")
        loc = f" `{f.location}`" if f.location else ""
        lines.append(f"## {icon} [{f.severity}] {f.pass_label}{loc}")
        lines.append(f"- 问题：{f.issue}")
        if f.suggestion:
            lines.append(f"- 建议：{f.suggestion}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
