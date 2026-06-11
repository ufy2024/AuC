"""M1 集成：写文件 → 跑测试失败 → 修复 → 复跑通过（InMemoryModelClient 脚本化）。"""

import asyncio
import json

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.checkpoint import CheckpointStore
from auc.messages import RunRequest, ToolCall
from auc.model import AssistantMessage
from auc.tools.files import make_file_tools
from auc.tools.shell import make_shell_tool

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
# -B 禁用字节码缓存：两次写发生在同一秒内，秒级 mtime 会让 __pycache__ 误判为新
CHECK = 'python3 -B -c "import mod; assert mod.add(1, 2) == 3"'


def _tc(i: int, name: str, args: dict) -> AssistantMessage:
    return AssistantMessage(
        content=None, tool_calls=[ToolCall(id=f"t{i}", name=name, arguments=args)]
    )


def test_edit_test_fix_loop(tmp_path) -> None:
    asyncio.run(_test_edit_test_fix_loop(tmp_path))


async def _test_edit_test_fix_loop(tmp_path) -> None:
    model = InMemoryModelClient(
        responses=[
            _tc(1, "write_file", {"path": "mod.py", "content": BUGGY}),
            _tc(2, "run_command", {"command": CHECK}),
            _tc(3, "write_file", {"path": "mod.py", "content": FIXED}),
            _tc(4, "run_command", {"command": CHECK}),
            AssistantMessage(content="已修复并通过测试", tool_calls=None),
        ]
    )
    registry = DefaultToolRegistry()
    for tool, pol in make_file_tools(str(tmp_path)):
        registry.register(tool, pol)
    shell_tool, shell_pol = make_shell_tool(str(tmp_path))
    registry.register(shell_tool, shell_pol)

    agent = DefaultAgent(
        AgentConfig(
            agent_id="m1",
            model=model,
            tools=registry,
            sandbox_root=str(tmp_path),
        )
    )
    events = []
    result = None
    async for ev in agent.run_stream(
        RunRequest(
            input="实现 add 并保证测试通过",
            metadata={"autonomy": "full-auto"},  # shell 免确认（安全命令）
        )
    ):
        events.append(ev)
    result = agent.last_run_result

    assert result is not None and result.status == "completed"
    assert (tmp_path / "mod.py").read_text(encoding="utf-8") == FIXED

    # 第一次 run_command 失败（is_error），第二次成功
    tool_ends = [e for e in events if e.type == "tool_end" and e.payload["tool"] == "run_command"]
    assert len(tool_ends) == 2
    assert tool_ends[0].payload["is_error"] is True
    assert tool_ends[1].payload["is_error"] is False

    # 检查点：两次 write + 两次 shell 记录
    store = CheckpointStore(str(tmp_path))
    entries = store.list_entries(result.run_id)
    ops = [e.op for e in entries]
    assert ops.count("write") == 2
    assert ops.count("shell") == 2
    assert any(e.type == "checkpoint_created" for e in events)

    # 回滚到起点：mod.py（新建文件）被删除
    store.revert_to(result.run_id, 0)
    assert not (tmp_path / "mod.py").exists()
