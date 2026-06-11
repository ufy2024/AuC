"""裁决链集成：escalation → autonomy → 审批 → 检查点 → invoke（ADR-006）。"""

import asyncio

from auc.checkpoint import CheckpointStore
from auc.context.window import ListContextWindow
from auc.events.bus import EventBus
from auc.loop.base import LoopConfig, LoopContext
from auc.policy.autonomy import AutonomyPolicy
from auc.policy.privilege import PendingApproval, ToolPrivilegeGate
from auc.ports.approval import ApprovalRequest, AutoApprovePort
from auc.ports.rules import ProjectRules
from auc.tools.files import make_file_tools
from auc.tools.registry import DefaultToolRegistry
from auc.tools.shell import make_shell_tool


class RecordingApprovalPort(AutoApprovePort):
    def __init__(self, *, approved: bool = True) -> None:
        super().__init__(approved=approved)
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, req: ApprovalRequest) -> str:
        self.requests.append(req)
        return await super().request_approval(req)


def _build(tmp_path, *, autonomy: str, approval=None):
    registry = DefaultToolRegistry()
    for tool, pol in make_file_tools(str(tmp_path)):
        registry.register(tool, pol)
    shell_tool, shell_pol = make_shell_tool(str(tmp_path))
    registry.register(shell_tool, shell_pol)
    ctx = LoopContext(
        agent_id="a",
        run_id="r1",
        window=ListContextWindow(),
        tools=registry,
        model=None,  # type: ignore[arg-type]
        events=EventBus(),
        config=LoopConfig(),
        project_rules=ProjectRules(sandbox_root=str(tmp_path)),
        autonomy_policy=AutonomyPolicy(level=autonomy),  # type: ignore[arg-type]
        checkpoints=CheckpointStore(str(tmp_path)),
    )
    gate = ToolPrivilegeGate(approval=approval)
    return registry, ctx, gate


def test_escalation_dangerous_command_pending(tmp_path) -> None:
    asyncio.run(_test_escalation_pending(tmp_path))


async def _test_escalation_pending(tmp_path) -> None:
    approval = RecordingApprovalPort()
    registry, ctx, gate = _build(tmp_path, autonomy="full-auto", approval=approval)
    tool = registry.get("run_command")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("run_command"),
        {"command": "sudo rm -rf /"},
        ctx=ctx,
    )
    assert isinstance(outcome, PendingApproval)
    assert "升级为 L3" in approval.requests[0].risk_summary


def test_full_auto_safe_shell_passes(tmp_path) -> None:
    asyncio.run(_test_full_auto_shell(tmp_path))


async def _test_full_auto_shell(tmp_path) -> None:
    registry, ctx, gate = _build(tmp_path, autonomy="full-auto")
    tool = registry.get("run_command")
    outcome = await gate.check_and_invoke(
        tool, registry.get_policy("run_command"), {"command": "echo ok"}, ctx=ctx
    )
    assert not isinstance(outcome, PendingApproval)
    assert "ok" in outcome.content
    # shell 步在检查点 manifest 留痕
    entries = ctx.checkpoints.list_entries("r1")
    assert entries and entries[0].op == "shell"


def test_auto_edit_shell_requires_approval(tmp_path) -> None:
    asyncio.run(_test_auto_edit_shell(tmp_path))


async def _test_auto_edit_shell(tmp_path) -> None:
    approval = RecordingApprovalPort()
    registry, ctx, gate = _build(tmp_path, autonomy="auto-edit", approval=approval)
    tool = registry.get("run_command")
    outcome = await gate.check_and_invoke(
        tool, registry.get_policy("run_command"), {"command": "pytest -q"}, ctx=ctx
    )
    assert isinstance(outcome, PendingApproval)
    # 审批后正常执行
    tr = await gate.resolve_pending(outcome, ctx=ctx, tool=tool)
    assert "pytest" in approval.requests[0].diff_text


def test_auto_edit_write_passes_with_checkpoint(tmp_path) -> None:
    asyncio.run(_test_auto_edit_write(tmp_path))


async def _test_auto_edit_write(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    registry, ctx, gate = _build(tmp_path, autonomy="auto-edit")
    events = []
    ctx.events.subscribe(events.append)
    tool = registry.get("write_file")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("write_file"),
        {"path": "a.txt", "content": "new"},
        ctx=ctx,
    )
    assert not isinstance(outcome, PendingApproval)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"
    assert any(e.type == "checkpoint_created" for e in events)
    # 回滚可恢复
    ctx.checkpoints.revert_to("r1", 0)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old"


def test_confirm_all_write_pending_with_diff(tmp_path) -> None:
    asyncio.run(_test_confirm_all_write(tmp_path))


async def _test_confirm_all_write(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("line1\n", encoding="utf-8")
    approval = RecordingApprovalPort()
    registry, ctx, gate = _build(tmp_path, autonomy="confirm-all", approval=approval)
    tool = registry.get("write_file")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("write_file"),
        {"path": "a.txt", "content": "line1\nline2\n"},
        ctx=ctx,
    )
    assert isinstance(outcome, PendingApproval)
    diff = approval.requests[0].diff_text
    assert "+line2" in diff and "a/a.txt" in diff
    # 批准后落盘 + 检查点
    tr = await gate.resolve_pending(outcome, ctx=ctx, tool=tool)
    assert not tr.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "line1\nline2\n"
    assert ctx.checkpoints.list_entries("r1")


def test_confirm_all_denied_no_write(tmp_path) -> None:
    asyncio.run(_test_confirm_all_denied(tmp_path))


async def _test_confirm_all_denied(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("keep", encoding="utf-8")
    approval = RecordingApprovalPort(approved=False)
    registry, ctx, gate = _build(tmp_path, autonomy="confirm-all", approval=approval)
    tool = registry.get("write_file")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("write_file"),
        {"path": "a.txt", "content": "overwrite"},
        ctx=ctx,
    )
    assert isinstance(outcome, PendingApproval)
    tr = await gate.resolve_pending(outcome, ctx=ctx, tool=tool)
    assert tr.is_error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "keep"


def test_dot_auc_write_protected(tmp_path) -> None:
    asyncio.run(_test_dot_auc_protected(tmp_path))


async def _test_dot_auc_protected(tmp_path) -> None:
    approval = RecordingApprovalPort()
    registry, ctx, gate = _build(tmp_path, autonomy="full-auto", approval=approval)
    tool = registry.get("write_file")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("write_file"),
        {"path": ".auc/evolution.yaml", "content": "hacked"},
        ctx=ctx,
    )
    assert isinstance(outcome, PendingApproval)


def test_tightening_without_approval_port_denies(tmp_path) -> None:
    asyncio.run(_test_no_port_denies(tmp_path))


async def _test_no_port_denies(tmp_path) -> None:
    registry, ctx, gate = _build(tmp_path, autonomy="confirm-all", approval=None)
    tool = registry.get("write_file")
    outcome = await gate.check_and_invoke(
        tool,
        registry.get_policy("write_file"),
        {"path": "x.txt", "content": "y"},
        ctx=ctx,
    )
    assert not isinstance(outcome, PendingApproval)
    assert outcome.is_error
    assert not (tmp_path / "x.txt").exists()
