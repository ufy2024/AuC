"""R14 Hooks 测试。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
    LoopConfig,
    make_echo_tool,
)
from auc.hooks import HookRunner, HookSpec, load_hooks
from auc.messages import ToolCall
from auc.model import AssistantMessage

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="需要 sh")


def _runner(specs: list[HookSpec], sandbox: str = ".") -> HookRunner:
    hooks: dict[str, list[HookSpec]] = {}
    for s in specs:
        hooks.setdefault(s.event, []).append(s)
    return HookRunner(hooks, sandbox_root=sandbox)


def _pre(runner: HookRunner, *, tool="echo", privilege="L1"):
    return asyncio.run(
        runner.run_tool_hooks(
            "pre_tool_use",
            tool_name=tool,
            privilege=privilege,
            context={"tool": tool, "arguments": {"a": 1}},
        )
    )


def test_allow_exit_zero(tmp_path: Path) -> None:
    runner = _runner([HookSpec("pre_tool_use", "exit 0", "echo")], str(tmp_path))
    d = _pre(runner)
    assert d.allow is True


def test_deny_exit_two_uses_stderr(tmp_path: Path) -> None:
    runner = _runner(
        [HookSpec("pre_tool_use", "echo 不允许 1>&2; exit 2", "echo")], str(tmp_path)
    )
    d = _pre(runner)
    assert d.allow is False
    assert "不允许" in d.reason


def test_matcher_skips_nonmatching(tmp_path: Path) -> None:
    runner = _runner([HookSpec("pre_tool_use", "exit 2", "write_file")], str(tmp_path))
    d = _pre(runner, tool="echo")
    assert d.allow is True  # matcher 不匹配 echo


def test_rewrite_arguments_via_stdout(tmp_path: Path) -> None:
    cmd = "echo '{\"arguments\": {\"city\": \"BJ\"}}'"
    runner = _runner([HookSpec("pre_tool_use", cmd, "echo")], str(tmp_path))
    d = _pre(runner)
    assert d.allow is True
    assert d.arguments == {"city": "BJ"}


def test_stdout_decision_block(tmp_path: Path) -> None:
    cmd = "echo '{\"decision\": \"block\", \"reason\": \"nope\"}'"
    runner = _runner([HookSpec("pre_tool_use", cmd, "echo")], str(tmp_path))
    d = _pre(runner)
    assert d.allow is False
    assert d.reason == "nope"


def test_post_rewrites_content(tmp_path: Path) -> None:
    cmd = "echo '{\"content\": \"REDACTED\"}'"
    runner = _runner([HookSpec("post_tool_use", cmd, "echo")], str(tmp_path))
    d = asyncio.run(
        runner.run_tool_hooks(
            "post_tool_use",
            tool_name="echo",
            privilege="L1",
            context={"result": "secret"},
        )
    )
    assert d.content == "REDACTED"


def test_timeout_l1_allows_l2_denies_l3_allows(tmp_path: Path) -> None:
    spec = HookSpec("pre_tool_use", "sleep 5", "echo", timeout=0.5)
    runner = _runner([spec], str(tmp_path))
    assert _pre(runner, privilege="L1").allow is True
    assert _pre(runner, privilege="L2").allow is False
    assert _pre(runner, privilege="L3").allow is True


def test_nonblocking_error_allows_with_warning(tmp_path: Path) -> None:
    runner = _runner(
        [HookSpec("pre_tool_use", "echo oops 1>&2; exit 1", "echo")], str(tmp_path)
    )
    d = _pre(runner)
    assert d.allow is True
    assert d.warnings


def test_load_hooks_merges_settings_and_trusted_file(tmp_path: Path) -> None:
    auc_dir = tmp_path / ".auc"
    auc_dir.mkdir(parents=True)
    (auc_dir / "hooks.json").write_text(
        json.dumps({"hooks": {"run_start": [{"command": "echo hi"}]}}),
        encoding="utf-8",
    )
    # 沙盒 hooks 文件默认不信任；需显式 opt-in 才合并
    settings = {
        "hooks_trust_sandbox_file": True,
        "hooks": {"pre_tool_use": [{"matcher": "write_file", "command": "exit 0"}]},
    }
    runner = load_hooks(settings, str(tmp_path))
    assert runner is not None
    assert runner.has("pre_tool_use")
    assert runner.has("run_start")


def test_load_hooks_ignores_untrusted_sandbox_file(tmp_path: Path) -> None:
    """安全默认：沙盒 .auc/hooks.json 未显式信任时不加载（防持久化 RCE）。"""
    auc_dir = tmp_path / ".auc"
    auc_dir.mkdir(parents=True)
    (auc_dir / "hooks.json").write_text(
        json.dumps({"hooks": {"run_start": [{"command": "echo hi"}]}}),
        encoding="utf-8",
    )
    # 无 settings 信任标志 → 沙盒 hooks 被忽略 → 无任何 hook → None
    assert load_hooks({}, str(tmp_path)) is None
    # settings.hooks 仍然生效，沙盒 hooks 仍被忽略
    runner = load_hooks(
        {"hooks": {"pre_tool_use": [{"command": "exit 0"}]}}, str(tmp_path)
    )
    assert runner is not None
    assert runner.has("pre_tool_use")
    assert not runner.has("run_start")


def test_load_hooks_none_when_empty(tmp_path: Path) -> None:
    assert load_hooks({}, str(tmp_path)) is None


def test_e2e_pre_hook_blocks_tool(tmp_path: Path) -> None:
    asyncio.run(_e2e_block(tmp_path))


async def _e2e_block(tmp_path: Path) -> None:
    registry = DefaultToolRegistry()
    echo_tool, pol = make_echo_tool()
    registry.register(echo_tool, pol)
    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[ToolCall(id="t1", name="echo", arguments={"city": "北京"})],
            ),
            AssistantMessage(content="完成。", tool_calls=None),
        ]
    )
    hooks = HookRunner(
        {"pre_tool_use": [HookSpec("pre_tool_use", "echo 禁止 1>&2; exit 2", "echo")]},
        sandbox_root=str(tmp_path),
    )
    agent = DefaultAgent(
        AgentConfig(
            agent_id="t",
            model=model,
            tools=registry,
            sandbox_root=str(tmp_path),
            loop_config=LoopConfig(max_steps=5),
            hooks=hooks,
        )
    )
    result = await agent.run("调用 echo")
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert tool_msgs
    assert any("hook 拒绝" in m.content for m in tool_msgs)
