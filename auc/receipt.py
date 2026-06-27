"""R28 任务回执 / Replay：Run 结束沉淀可追溯产物。

Run 结束时由框架汇总 `RunReceipt`（目标 → 改动文件 + diff 摘要 → 命令转录 →
测试/验证结果 → 用量），渲染为 Markdown 落 `.auc/receipts/<run_id>.md`，可直接贴入
PR/审阅。数据全部复用既有设施：检查点 manifest（改动文件/命令）、窗口工具结果
（命令退出码）、`UsageTracker`（R11 用量），不引入新依赖。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auc.checkpoint import validate_run_id

if TYPE_CHECKING:
    from auc.loop.base import LoopContext

# 识别「验证类」命令（测试 / 类型检查 / lint / 构建），用于回执的验证小节。
_VERIFY_RE = re.compile(
    r"\b("
    r"pytest|unittest|tox|nox|"
    r"(npm|yarn|pnpm)\s+(run\s+)?(test|lint|build|typecheck)|"
    r"go\s+test|cargo\s+(test|build|clippy)|mvn\s+test|gradle\s+test|"
    r"make\s+(test|check|lint)|"
    r"ruff|mypy|pyright|eslint|tsc|jest|vitest"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class FileChange:
    path: str
    op: str  # write / delete

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileChange":
        return cls(path=str(d.get("path") or ""), op=str(d.get("op") or "write"))


@dataclass
class CommandRecord:
    command: str
    exit_code: int | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and (self.exit_code is None or self.exit_code == 0)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CommandRecord":
        ec = d.get("exit_code")
        return cls(
            command=str(d.get("command") or ""),
            exit_code=int(ec) if isinstance(ec, (int, float)) else None,
            timed_out=bool(d.get("timed_out")),
        )


@dataclass
class RunReceipt:
    run_id: str
    agent_id: str
    status: str
    goal: str = ""
    changed_files: list[FileChange] = field(default_factory=list)
    commands: list[CommandRecord] = field(default_factory=list)
    verifications: list[CommandRecord] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.changed_files or self.commands)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "goal": self.goal,
            "changed_files": [asdict(c) for c in self.changed_files],
            "commands": [asdict(c) for c in self.commands],
            "verifications": [asdict(c) for c in self.verifications],
            "todos": self.todos,
            "usage": self.usage,
            "error": self.error,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunReceipt":
        return cls(
            run_id=str(d.get("run_id") or ""),
            agent_id=str(d.get("agent_id") or ""),
            status=str(d.get("status") or ""),
            goal=str(d.get("goal") or ""),
            changed_files=[FileChange.from_dict(x) for x in d.get("changed_files") or []],
            commands=[CommandRecord.from_dict(x) for x in d.get("commands") or []],
            verifications=[CommandRecord.from_dict(x) for x in d.get("verifications") or []],
            todos=list(d.get("todos") or []),
            usage=d.get("usage"),
            error=d.get("error"),
            created_at=str(d.get("created_at") or ""),
        )


def _parse_shell_result(content: str) -> tuple[int | None, bool]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None, False
    if not isinstance(data, dict):
        return None, False
    exit_code = data.get("exit_code")
    return (
        int(exit_code) if isinstance(exit_code, (int, float)) else None,
        bool(data.get("timed_out")),
    )


def _first_goal(messages: list[Any]) -> str:
    for msg in messages:
        if getattr(msg, "role", "") == "user":
            return (getattr(msg, "content", "") or "").strip()
    return ""


def _collect_commands(messages: list[Any]) -> list[CommandRecord]:
    """从窗口配对 run_command 的命令文本与执行退出码（按时间序）。"""
    call_cmd: dict[str, str] = {}
    for msg in messages:
        if getattr(msg, "role", "") == "assistant" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.name == "run_command":
                    call_cmd[tc.id] = str((tc.arguments or {}).get("command") or "")
    out: list[CommandRecord] = []
    for msg in messages:
        if getattr(msg, "role", "") == "tool" and getattr(msg, "name", "") == "run_command":
            cmd = call_cmd.get(getattr(msg, "tool_call_id", "") or "", "")
            if not cmd.strip():
                continue
            exit_code, timed_out = _parse_shell_result(getattr(msg, "content", "") or "")
            out.append(CommandRecord(command=cmd, exit_code=exit_code, timed_out=timed_out))
    return out


def _collect_changed_files(ctx: "LoopContext") -> list[FileChange]:
    store = getattr(ctx, "checkpoints", None)
    if store is None:
        return []
    try:
        entries = store.list_entries(ctx.run_id)
    except Exception:  # noqa: BLE001 回执不应让 Run 结束崩溃
        return []
    ordered: dict[str, str] = {}
    for entry in entries:
        if entry.op in ("write", "delete") and entry.path:
            ordered[entry.path] = entry.op
    return [FileChange(path=p, op=op) for p, op in sorted(ordered.items())]


def collect_receipt(ctx: "LoopContext", status: str) -> RunReceipt:
    """从 LoopContext 汇总一次 Run 的回执（纯读，不触发副作用）。"""
    messages = ctx.window.view()
    commands = _collect_commands(messages)
    usage = None
    tracker = getattr(ctx, "usage_tracker", None)
    if tracker is not None and hasattr(tracker, "snapshot"):
        try:
            usage = tracker.snapshot()
        except Exception:  # noqa: BLE001
            usage = None
    return RunReceipt(
        run_id=str(ctx.run_id),
        agent_id=str(ctx.agent_id),
        status=status,
        goal=_first_goal(messages),
        changed_files=_collect_changed_files(ctx),
        commands=commands,
        verifications=[c for c in commands if _VERIFY_RE.search(c.command)],
        todos=list(getattr(ctx, "todos", []) or []),
        usage=usage,
        error=getattr(ctx, "error", None),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


_STATUS_ICON = {
    "completed": "✅",
    "error": "❌",
    "cancelled": "⏹️",
    "denied": "🚫",
    "max_steps": "⏱️",
}


def render_receipt_md(receipt: RunReceipt) -> str:
    icon = _STATUS_ICON.get(receipt.status, "•")
    lines: list[str] = [
        f"# 任务回执 · {receipt.run_id}",
        "",
        f"- 状态：{icon} `{receipt.status}`",
        f"- 智能体：`{receipt.agent_id}`",
        f"- 时间：{receipt.created_at}",
    ]
    if receipt.error:
        lines.append(f"- 错误：{receipt.error}")
    lines.append("")

    lines.append("## 目标")
    lines.append(receipt.goal or "_（无）_")
    lines.append("")

    lines.append(f"## 改动文件（{len(receipt.changed_files)}）")
    if receipt.changed_files:
        for ch in receipt.changed_files:
            tag = "删除" if ch.op == "delete" else "写入"
            lines.append(f"- `{ch.path}` — {tag}")
    else:
        lines.append("_无文件改动_")
    lines.append("")

    lines.append(f"## 命令转录（{len(receipt.commands)}）")
    if receipt.commands:
        for c in receipt.commands:
            mark = "✓" if c.ok else ("⏱" if c.timed_out else "✗")
            code = "timeout" if c.timed_out else (
                "?" if c.exit_code is None else str(c.exit_code)
            )
            lines.append(f"- {mark} `{c.command}`  (exit={code})")
    else:
        lines.append("_未执行命令_")
    lines.append("")

    if receipt.verifications:
        passed = sum(1 for c in receipt.verifications if c.ok)
        lines.append(f"## 验证（{passed}/{len(receipt.verifications)} 通过）")
        for c in receipt.verifications:
            mark = "✓" if c.ok else "✗"
            lines.append(f"- {mark} `{c.command}`")
        lines.append("")

    if receipt.todos:
        done = sum(1 for t in receipt.todos if str(t.get("status")) == "completed")
        lines.append(f"## 任务清单（{done}/{len(receipt.todos)} 完成）")
        for t in receipt.todos:
            st = str(t.get("status") or "pending")
            box = {"completed": "x", "in_progress": "~", "cancelled": "-"}.get(st, " ")
            lines.append(f"- [{box}] {t.get('content') or t.get('id') or ''}")
        lines.append("")

    if receipt.usage:
        u = receipt.usage
        lines.append("## 用量")
        lines.append(
            f"- 调用 {u.get('calls', 0)} 次 · "
            f"prompt {u.get('prompt_tokens', 0)} / completion "
            f"{u.get('completion_tokens', 0)} / total {u.get('total_tokens', 0)} tokens"
        )
        cost = u.get("cost_usd") or 0
        if cost:
            lines.append(f"- 估算成本：${cost:.4f}（模型 `{u.get('model', '')}`）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_receipt_block(receipt: RunReceipt, *, output: str = "") -> str:
    """R13：返回给父 Run 的精简回执块（paths/commands/tests）。"""
    lines = [f"[子智能体回执] status={receipt.status}"]
    if output.strip():
        snippet = output.strip()
        lines.append(f"结果：{snippet[:600]}")
    if receipt.changed_files:
        paths = ", ".join(c.path for c in receipt.changed_files[:20])
        more = "" if len(receipt.changed_files) <= 20 else f" …(+{len(receipt.changed_files) - 20})"
        lines.append(f"改动文件（{len(receipt.changed_files)}）：{paths}{more}")
    if receipt.commands:
        cmds = " | ".join(c.command for c in receipt.commands[:10])
        lines.append(f"命令（{len(receipt.commands)}）：{cmds}")
    if receipt.verifications:
        passed = sum(1 for c in receipt.verifications if c.ok)
        lines.append(f"验证：{passed}/{len(receipt.verifications)} 通过")
    if receipt.error:
        lines.append(f"错误：{receipt.error}")
    return "\n".join(lines)


class ReceiptStore:
    """回执持久化到 `.auc/receipts/<run_id>.md`（同名 .json 存结构化数据）。"""

    def __init__(self, sandbox_root: str) -> None:
        self._root = Path(sandbox_root).resolve()
        self._base = self._root / ".auc" / "receipts"

    def path_for(self, run_id: str) -> Path:
        return self._base / f"{validate_run_id(run_id)}.md"

    def write(self, receipt: RunReceipt) -> str:
        self._base.mkdir(parents=True, exist_ok=True)
        md_path = self.path_for(receipt.run_id)
        md_path.write_text(render_receipt_md(receipt), encoding="utf-8")
        json_path = md_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(md_path)

    def list_runs(self) -> list[str]:
        if not self._base.exists():
            return []
        files = [p for p in self._base.glob("*.md")]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in files]

    def read_markdown(self, run_id: str) -> str | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def read(self, run_id: str) -> RunReceipt | None:
        json_path = self.path_for(run_id).with_suffix(".json")
        if not json_path.is_file():
            return None
        try:
            return RunReceipt.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return None


def finalize_receipt(ctx: "LoopContext", status: str) -> str | None:
    """Run 结束钩子：汇总并落盘回执，返回 Markdown 路径（无沙盒/空回执则返回 None）。"""
    sandbox = None
    rules = getattr(ctx, "project_rules", None)
    if rules is not None:
        sandbox = getattr(rules, "sandbox_root", None)
    if not sandbox:
        return None
    try:
        receipt = collect_receipt(ctx, status)
        if receipt.is_empty:
            return None
        return ReceiptStore(str(sandbox)).write(receipt)
    except Exception:  # noqa: BLE001 回执失败绝不影响 Run 结果
        return None
