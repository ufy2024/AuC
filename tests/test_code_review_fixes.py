"""代码审查修复项回归测试。"""

from __future__ import annotations

import pytest

from auc.checkpoint import CheckpointStore, validate_run_id
from auc.context.pairing import drop_oldest_preserving_pairs, group_boundaries
from auc.context.window import ListContextWindow, TruncatePolicy
from auc.messages import ChatMessage, ToolCall
from auc.policy.escalation import check_escalation, merge_escalation_settings
from auc.tools.registry import DefaultToolRegistry
from auc.tools.base import ToolPolicy
from auc.web.auth import is_public_bind, require_web_token, token_ok
from auc.web.workspace import SandboxViolationError, write_text_file


def test_validate_run_id_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        validate_run_id("../../evil")


def test_invalid_run_id_rejected(tmp_path) -> None:
    store = CheckpointStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.revert_to("../../evil", 0)


def test_checkpoint_revert_skips_escape_path(tmp_path) -> None:
    store = CheckpointStore(str(tmp_path))
    target = tmp_path / "safe.txt"
    target.write_text("ok", encoding="utf-8")
    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "safe.txt"})
    manifest = tmp_path / ".auc" / "checkpoints" / "r1" / "manifest.jsonl"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '{"run_id":"r1","step":1,"tool":"write_file","op":"write","path":"../../../etc/passwd","blob":null,"command":null,"ts":"t"}\n',
        encoding="utf-8",
    )
    report = store.revert_to("r1", 0)
    assert any("跳过非法路径" in w for w in report.warnings)


def test_merge_tool_policy_cannot_downgrade_fetch_url() -> None:
    from auc.tools.base import Tool, ToolResult

    class _FetchTool(Tool):
        name = "fetch_url"
        description = ""
        parameters: dict = {}

        async def invoke(self, arguments: dict) -> ToolResult:
            return ToolResult(tool_call_id="", name=self.name, content="ok")

    reg = DefaultToolRegistry()
    reg.register(_FetchTool(), ToolPolicy(name="fetch_url", privilege="L3"))
    reg.merge_tool_policy({"fetch_url": "L1"})
    assert reg.get_policy("fetch_url").privilege == "L3"


def test_locked_escalation_pattern_cannot_be_neutered() -> None:
    rules = merge_escalation_settings([{"name": "sudo", "pattern": "$^"}])
    rule = check_escalation("run_command", {"command": "sudo apt install x"}, rules)
    assert rule is not None and rule.name == "sudo"


def test_drop_oldest_preserves_tool_pair() -> None:
    msgs = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="u1"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "a"})],
        ),
        ChatMessage(role="tool", content="data", tool_call_id="1", name="read_file"),
        ChatMessage(role="user", content="u2"),
    ]
    trimmed = drop_oldest_preserving_pairs(msgs, 4)
    assert trimmed[0].role == "user"
    assert trimmed[0].content == "u1"
    assert any(m.role == "assistant" and m.tool_calls for m in trimmed)


def test_list_context_window_drop_oldest_safe() -> None:
    win = ListContextWindow()
    for m in [
        ChatMessage(role="user", content="old"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="1", name="t", arguments={})],
        ),
        ChatMessage(role="tool", content="x", tool_call_id="1", name="t"),
        ChatMessage(role="user", content="new"),
    ]:
        win.append(m)
    win.truncate(TruncatePolicy(max_messages=2, strategy="drop_oldest"))
    view = win.view()
    assert len(view) <= 2
    for i, msg in enumerate(view):
        if msg.role == "assistant" and msg.tool_calls:
            assert i + 1 < len(view) and view[i + 1].role == "tool"


def test_workspace_blocks_auc_metadata(tmp_path) -> None:
    with pytest.raises(SandboxViolationError):
        write_text_file(str(tmp_path), ".auc/settings.local.json", "{}")


def test_web_token_required_for_public_bind() -> None:
    assert is_public_bind("0.0.0.0")
    assert not is_public_bind("127.0.0.1")
    with pytest.raises(SystemExit):
        require_web_token("0.0.0.0", None)
    assert require_web_token("127.0.0.1", None) is None


def test_web_token_compare() -> None:
    assert token_ok("secret", "secret")
    assert not token_ok("secret", "wrong")
