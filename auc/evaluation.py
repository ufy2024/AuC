"""R19 评测基线（Evaluation Harness）：确定性回归集，护航提示词/循环改动防退化。

任务即 YAML 用例（初始文件树 + 指令 + 脚本化模型回放 + 校验断言）。`auc eval run` 以
`InMemoryModelClient` 确定性回放（离线、无 API），在临时沙盒内建立初始文件树、跑 Run、
再执行校验（文件内容 / 存在性 / 验证命令退出码 / Run 状态）。CI 阈值：确定性集应 100%
通过。同时为 R22 提示自优化提供反馈来源。零新增依赖（PyYAML 已是核心依赖）。

用例 YAML 结构::

    id: fix-add
    name: 写文件→测试失败→修复→通过
    instruction: 实现 add 并保证测试通过
    autonomy: full-auto
    tags: [files, shell]
    files:
      mod.py: "def add(a, b):\\n    return a - b\\n"
    script:
      - tool: write_file
        args: {path: mod.py, content: "def add(a, b):\\n    return a + b\\n"}
      - say: 已修复
    checks:
      - status: completed
      - file: mod.py
        contains: "a + b"
      - run: 'python3 -c "import mod; assert mod.add(1,2)==3"'
        exit: 0
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.messages import RunRequest, ToolCall
from auc.model import AssistantMessage
from auc.tools.files import make_file_tools
from auc.tools.shell import make_shell_tool

DEFAULT_EVAL_DIR = Path(__file__).resolve().parent.parent / "tests" / "eval"


@dataclass
class EvalCase:
    id: str
    name: str = ""
    instruction: str = ""
    files: dict[str, str] = field(default_factory=dict)
    script: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    autonomy: str = "full-auto"
    tags: list[str] = field(default_factory=list)
    source: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str = "") -> "EvalCase":
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError(f"无效用例（缺少 id）：{source or data}")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name") or data["id"]),
            instruction=str(data.get("instruction") or ""),
            files={str(k): str(v) for k, v in (data.get("files") or {}).items()},
            script=list(data.get("script") or []),
            checks=list(data.get("checks") or []),
            autonomy=str(data.get("autonomy") or "full-auto"),
            tags=[str(t) for t in (data.get("tags") or [])],
            source=source,
        )


@dataclass
class CheckResult:
    ok: bool
    label: str
    detail: str = ""


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    status: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]


@dataclass
class SuiteReport:
    results: list[EvalResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


def load_cases(directory: str | Path | None = None) -> list[EvalCase]:
    base = Path(directory) if directory else DEFAULT_EVAL_DIR
    if not base.exists():
        return []
    cases: list[EvalCase] = []
    for path in sorted(base.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                cases.append(EvalCase.from_dict(item, source=str(path)))
        elif isinstance(data, dict):
            cases.append(EvalCase.from_dict(data, source=str(path)))
    return cases


def _build_responses(script: list[dict[str, Any]]) -> list[AssistantMessage]:
    responses: list[AssistantMessage] = []
    for i, step in enumerate(script, start=1):
        if "tool" in step:
            responses.append(
                AssistantMessage(
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id=f"t{i}",
                            name=str(step["tool"]),
                            arguments=dict(step.get("args") or {}),
                        )
                    ],
                )
            )
        else:
            text = step.get("say") or step.get("text") or step.get("content") or ""
            responses.append(AssistantMessage(content=str(text), tool_calls=None))
    # 兜底收尾，避免脚本最后一步是工具调用时循环无终结文本
    responses.append(AssistantMessage(content="(eval done)", tool_calls=None))
    return responses


def _run_command(command: str, cwd: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "(timeout)"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _eval_checks(case: EvalCase, sandbox: Path, status: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for chk in case.checks:
        if "status" in chk:
            want = str(chk["status"])
            results.append(
                CheckResult(status == want, f"status=={want}", f"实际 {status}")
            )
        elif "file" in chk:
            rel = str(chk["file"])
            fp = sandbox / rel
            if not fp.is_file():
                results.append(CheckResult(False, f"file {rel}", "文件不存在"))
                continue
            text = fp.read_text(encoding="utf-8")
            if "equals" in chk:
                ok = text == str(chk["equals"])
                results.append(CheckResult(ok, f"file {rel} equals", "" if ok else "内容不匹配"))
            elif "contains" in chk:
                needle = str(chk["contains"])
                ok = needle in text
                results.append(
                    CheckResult(ok, f"file {rel} contains", "" if ok else f"未含 {needle!r}")
                )
            else:
                results.append(CheckResult(True, f"file {rel} exists"))
        elif "missing" in chk:
            rel = str(chk["missing"])
            ok = not (sandbox / rel).exists()
            results.append(CheckResult(ok, f"missing {rel}", "" if ok else "文件仍存在"))
        elif "run" in chk:
            cmd = str(chk["run"])
            want = int(chk.get("exit", 0))
            code, out = _run_command(cmd, str(sandbox))
            ok = code == want
            detail = "" if ok else f"退出码 {code}（期望 {want}）"
            if ok and "contains" in chk:
                needle = str(chk["contains"])
                if needle not in out:
                    ok = False
                    detail = f"输出未含 {needle!r}"
            results.append(CheckResult(ok, f"run `{cmd[:40]}`", detail))
        else:
            results.append(CheckResult(False, "unknown-check", str(chk)))
    return results


async def run_case(case: EvalCase, *, workdir: str | Path | None = None) -> EvalResult:
    """在临时（或指定）沙盒内回放用例并校验。"""
    tmp_ctx = None
    if workdir is None:
        tmp_ctx = tempfile.TemporaryDirectory()
        sandbox = Path(tmp_ctx.name)
    else:
        sandbox = Path(workdir)
        sandbox.mkdir(parents=True, exist_ok=True)
    try:
        for rel, content in case.files.items():
            fp = sandbox / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")

        model = InMemoryModelClient(responses=_build_responses(case.script))
        registry = DefaultToolRegistry()
        for tool, pol in make_file_tools(str(sandbox)):
            registry.register(tool, pol)
        shell_tool, shell_pol = make_shell_tool(str(sandbox))
        registry.register(shell_tool, shell_pol)

        agent = DefaultAgent(
            AgentConfig(
                agent_id=f"eval-{case.id}",
                model=model,
                tools=registry,
                sandbox_root=str(sandbox),
            )
        )
        try:
            async for _ in agent.run_stream(
                RunRequest(
                    input=case.instruction or "(eval)",
                    metadata={"autonomy": case.autonomy},
                )
            ):
                pass
        except Exception as exc:  # noqa: BLE001
            return EvalResult(case.id, passed=False, status="error", error=str(exc))

        result = agent.last_run_result
        status = result.status if result is not None else "unknown"
        checks = _eval_checks(case, sandbox, status)
        passed = all(c.ok for c in checks) if checks else status == "completed"
        return EvalResult(case.id, passed=passed, status=status, checks=checks)
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


async def run_suite(
    directory: str | Path | None = None, *, only: list[str] | None = None
) -> SuiteReport:
    cases = load_cases(directory)
    if only:
        wanted = set(only)
        cases = [c for c in cases if c.id in wanted]
    report = SuiteReport()
    for case in cases:
        report.results.append(await run_case(case))
    return report


def render_report(report: SuiteReport) -> str:
    lines = [
        f"评测基线：{report.passed}/{report.total} 通过"
        f"（通过率 {report.pass_rate * 100:.0f}%）",
        "",
    ]
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"[{mark}] {r.case_id}  (status={r.status})")
        if not r.passed:
            if r.error:
                lines.append(f"       error: {r.error}")
            for c in r.failed_checks:
                lines.append(f"       ✗ {c.label}: {c.detail}")
    return "\n".join(lines)
