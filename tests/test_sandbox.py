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
from auc.sandbox import (
    SandboxViolationError,
    resolve_under_sandbox,
    resolve_workspace_safe,
)
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


def test_resolve_workspace_safe_ok(tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    assert resolve_workspace_safe(str(root), "a.txt") == (root / "a.txt").resolve()


def test_resolve_workspace_safe_rejects_auc(tmp_path) -> None:
    root = tmp_path / "ws"
    (root / ".auc").mkdir(parents=True)
    with pytest.raises(SandboxViolationError):
        resolve_workspace_safe(str(root), ".auc/settings.local.json")
    with pytest.raises(SandboxViolationError):
        resolve_workspace_safe(str(root), ".auc")


def test_resolve_workspace_safe_rejects_symlink_to_auc(tmp_path) -> None:
    """符号链接绕过：evil -> .auc/settings.local.json 必须被拒绝。"""
    root = tmp_path / "ws"
    auc = root / ".auc"
    auc.mkdir(parents=True)
    secret = auc / "settings.local.json"
    secret.write_text('{"api_key": "sk-secret"}', encoding="utf-8")
    link = root / "evil"
    link.symlink_to(secret)
    with pytest.raises(SandboxViolationError):
        resolve_workspace_safe(str(root), "evil")


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


def test_write_file_append_mode(tmp_path) -> None:
    """大文件分段写入：第一段覆盖写，后续 append=true 续写同一文件。"""
    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
    reg = DefaultToolRegistry()
    for t, p in make_file_tools(str(sandbox)):
        reg.register(t, p)
    write = reg.get("write_file")
    assert write is not None
    schema = next(s for s in reg.list_schemas() if s.name == "write_file")
    assert schema.parameters["properties"]["append"]["type"] == "boolean"

    async def _run() -> str:
        await write.invoke({"path": "big.html", "content": "<html>\n"})
        await write.invoke({"path": "big.html", "content": "<body>snake</body>\n", "append": True})
        # 字符串形式的布尔值也应识别
        tr = await write.invoke({"path": "big.html", "content": "</html>\n", "append": "true"})
        return tr.content

    msg = asyncio.run(_run())
    assert "appended" in msg
    text = (sandbox / "big.html").read_text(encoding="utf-8")
    assert text == "<html>\n<body>snake</body>\n</html>\n"


def test_parse_error_marker_becomes_tool_error(tmp_path) -> None:
    """流式参数 JSON 截断：转为工具错误反馈模型，run 不中断且不写文件。"""
    from auc.model.json_util import PARSE_ERROR_KEY

    sandbox = tmp_path / "workspace"
    sandbox.mkdir()
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
                        name="write_file",
                        arguments={PARSE_ERROR_KEY: "write_file 参数 JSON 不完整，请用 append 分段写入"},
                    ),
                ],
            ),
            AssistantMessage(content="收到，改用分段写入", tool_calls=None),
        ],
    )

    async def _run() -> tuple[str, str]:
        window = ListContextWindow()
        window.append(ChatMessage(role="user", content="写贪吃蛇"))
        ctx = LoopContext(
            agent_id="t",
            run_id="r1",
            window=window,
            tools=reg,
            model=model,
            events=EventBus(),
            config=LoopConfig(max_steps=3),
            project_rules=ProjectRules(sandbox_root=str(sandbox)),
            privilege_gate=ToolPrivilegeGate(),
        )
        await AgentLoopRunner().run_until_done(ReActLoop(), ctx)
        tool_msg = next(m.content for m in ctx.window.view() if m.role == "tool")
        final = ctx.window.view()[-1].content
        return tool_msg, final

    tool_msg, final = asyncio.run(_run())
    assert "append" in tool_msg
    assert final == "收到，改用分段写入"
    assert list(sandbox.iterdir()) == []


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
