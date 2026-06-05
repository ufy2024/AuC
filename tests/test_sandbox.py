import asyncio

import pytest

from auc.context import ListContextWindow
from auc.events import EventBus
from auc.loop.base import AgentLoopRunner, LoopConfig, LoopContext
from auc.loop.react import ReActLoop
from auc.messages import ChatMessage, ToolCall
from auc.model import AssistantMessage, InMemoryModelClient
from auc.policy import ToolPrivilegeGate
from auc.ports.rules import ProjectRules
from auc.sandbox import SandboxViolationError, resolve_under_sandbox
from auc.tools.files import make_file_tools
from auc.tools.registry import DefaultToolRegistry


def test_resolve_under_sandbox_ok(tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    f = root / "a.txt"
    f.write_text("x", encoding="utf-8")
    p = resolve_under_sandbox(str(root), "a.txt")
    assert p == f.resolve()


def test_resolve_under_sandbox_escape(tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(SandboxViolationError):
        resolve_under_sandbox(str(root), str(outside))


def test_l2_tool_blocked_outside_sandbox(tmp_path) -> None:
    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    reg = DefaultToolRegistry()
    for t, p in make_file_tools(str(sandbox)):
        reg.register(t, p)

    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="read_file",
                        arguments={"path": str(outside)},
                    ),
                ],
            ),
        ],
    )

    async def _run() -> str:
        window = ListContextWindow()
        window.append(ChatMessage(role="user", content="read file"))
        ctx = LoopContext(
            agent_id="t",
            run_id="r1",
            window=window,
            tools=reg,
            model=model,
            events=EventBus(),
            config=LoopConfig(max_steps=2),
            project_rules=ProjectRules(sandbox_root=str(sandbox)),
            privilege_gate=ToolPrivilegeGate(),
        )
        await AgentLoopRunner().run_until_done(ReActLoop(), ctx)
        for m in reversed(ctx.window.view()):
            if m.role == "tool":
                return m.content
        return ""

    content = asyncio.run(_run())
    assert "escapes sandbox" in content


def test_delete_path_in_sandbox(tmp_path) -> None:
    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
    target = sandbox / "snake-game"
    target.mkdir()
    (target / "a.txt").write_text("x", encoding="utf-8")

    reg = DefaultToolRegistry()
    for t, p in make_file_tools(str(sandbox)):
        reg.register(t, p)
    delete_tool = reg.get("delete_path")
    assert delete_tool is not None

    async def _run() -> str:
        tr = await delete_tool.invoke({"path": "snake-game"})
        return tr.content

    msg = asyncio.run(_run())
    assert "deleted directory" in msg
    assert not target.exists()
