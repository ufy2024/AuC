"""R28 任务回执测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
    LoopConfig,
)
from auc.messages import ChatMessage, ToolCall
from auc.model import AssistantMessage
from auc.receipt import (
    CommandRecord,
    ReceiptStore,
    RunReceipt,
    collect_receipt,
    finalize_receipt,
    render_receipt_md,
)
from auc.tools.shell import make_shell_tool
from auc.usage import UsageTracker


def _shell_result(exit_code: int, timed_out: bool = False) -> str:
    return json.dumps(
        {
            "exit_code": exit_code,
            "stdout": "out",
            "stderr": "",
            "timed_out": timed_out,
        }
    )


def _stub_ctx(tmp: Path, messages: list[ChatMessage], *, checkpoints=None):
    tracker = UsageTracker(model="gpt-4o-mini")
    return SimpleNamespace(
        run_id="run-1",
        agent_id="chat:default",
        window=SimpleNamespace(view=lambda: messages),
        checkpoints=checkpoints,
        usage_tracker=tracker,
        todos=[{"id": "a", "content": "do x", "status": "completed"}],
        error=None,
        project_rules=SimpleNamespace(sandbox_root=str(tmp)),
        config=SimpleNamespace(write_receipt=True),
    )


def test_command_record_ok() -> None:
    assert CommandRecord("pytest", exit_code=0).ok is True
    assert CommandRecord("pytest", exit_code=1).ok is False
    assert CommandRecord("sleep 5", timed_out=True).ok is False
    assert CommandRecord("git status", exit_code=None).ok is True


def test_collect_commands_and_verifications(tmp_path: Path) -> None:
    messages = [
        ChatMessage(role="user", content="修复并跑测试"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="t1", name="run_command", arguments={"command": "ls"}),
                ToolCall(
                    id="t2", name="run_command", arguments={"command": "python -m pytest"}
                ),
            ],
        ),
        ChatMessage(role="tool", content=_shell_result(0), name="run_command", tool_call_id="t1"),
        ChatMessage(role="tool", content=_shell_result(1), name="run_command", tool_call_id="t2"),
    ]
    receipt = collect_receipt(_stub_ctx(tmp_path, messages), "completed")
    assert receipt.goal == "修复并跑测试"
    assert [c.command for c in receipt.commands] == ["ls", "python -m pytest"]
    assert receipt.commands[0].ok is True
    assert receipt.commands[1].ok is False
    # 只有 pytest 命中验证集
    assert len(receipt.verifications) == 1
    assert receipt.verifications[0].command == "python -m pytest"


def test_collect_changed_files_from_checkpoints(tmp_path: Path) -> None:
    from auc.checkpoint import CheckpointStore

    store = CheckpointStore(str(tmp_path))
    (tmp_path / "x.py").write_text("old", encoding="utf-8")
    store.snapshot(run_id="run-1", step=0, tool="write_file", arguments={"path": "x.py"})
    store.snapshot(
        run_id="run-1", step=1, tool="run_command", arguments={"command": "echo hi"}
    )
    ctx = _stub_ctx(tmp_path, [ChatMessage(role="user", content="x")], checkpoints=store)
    receipt = collect_receipt(ctx, "completed")
    assert [c.path for c in receipt.changed_files] == ["x.py"]
    assert receipt.changed_files[0].op == "write"


def test_render_receipt_md_sections() -> None:
    receipt = RunReceipt(
        run_id="r1",
        agent_id="chat:default",
        status="completed",
        goal="做点事",
        commands=[CommandRecord("pytest", exit_code=0)],
        verifications=[CommandRecord("pytest", exit_code=0)],
        usage={"calls": 2, "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost_usd": 0.0, "model": "m"},
    )
    md = render_receipt_md(receipt)
    assert "# 任务回执 · r1" in md
    assert "## 目标" in md
    assert "## 命令转录" in md
    assert "## 验证" in md
    assert "## 用量" in md


def test_receipt_store_write_and_read(tmp_path: Path) -> None:
    receipt = RunReceipt(run_id="run-1", agent_id="a", status="completed", goal="g")
    store = ReceiptStore(str(tmp_path))
    path = store.write(receipt)
    assert Path(path).is_file()
    assert Path(path).with_suffix(".json").is_file()
    assert store.list_runs() == ["run-1"]
    md = store.read_markdown("run-1")
    assert md is not None and "run-1" in md


def test_finalize_skips_empty_receipt(tmp_path: Path) -> None:
    ctx = _stub_ctx(tmp_path, [ChatMessage(role="user", content="hi")])
    assert finalize_receipt(ctx, "completed") is None
    assert not (tmp_path / ".auc" / "receipts").exists()


def test_finalize_writes_when_commands_present(tmp_path: Path) -> None:
    messages = [
        ChatMessage(role="user", content="hi"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="t1", name="run_command", arguments={"command": "ls"})],
        ),
        ChatMessage(role="tool", content=_shell_result(0), name="run_command", tool_call_id="t1"),
    ]
    ctx = _stub_ctx(tmp_path, messages)
    path = finalize_receipt(ctx, "completed")
    assert path is not None and Path(path).is_file()


def test_end_to_end_receipt_event_and_file(tmp_path: Path) -> None:
    asyncio.run(_e2e(tmp_path))


async def _e2e(tmp_path: Path) -> None:
    registry = DefaultToolRegistry()
    shell_tool, pol = make_shell_tool(str(tmp_path))
    registry.register(shell_tool, pol)
    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="t1", name="run_command", arguments={"command": "echo hi"}),
                ],
            ),
            AssistantMessage(content="完成。", tool_calls=None),
        ]
    )
    agent = DefaultAgent(
        AgentConfig(
            agent_id="test",
            model=model,
            tools=registry,
            sandbox_root=str(tmp_path),
            loop_config=LoopConfig(max_steps=5),
            autonomy="full-auto",
        )
    )
    types: list[str] = []
    async for ev in agent.run_stream("跑个命令"):
        types.append(ev.type)
    assert "receipt_ready" in types
    receipts = ReceiptStore(str(tmp_path)).list_runs()
    assert receipts
    md = ReceiptStore(str(tmp_path)).read_markdown(receipts[0])
    assert "echo hi" in md
