from auc.messages import ChatMessage, ToolCall
from auc.model.anthropic import _sanitize_tool_pairing, _to_anthropic_messages


def test_deepseek_injects_thinking_before_tool_use() -> None:
    msgs = [
        ChatMessage(
            role="assistant",
            content="plan",
            tool_calls=[ToolCall(id="t1", name="write_file", arguments={"path": "a.py"})],
        ),
    ]
    _, api = _to_anthropic_messages(msgs, deepseek=True)
    blocks = api[0]["content"]
    assert blocks[0]["type"] == "thinking"
    assert blocks[1]["type"] == "text"
    assert blocks[2]["type"] == "tool_use"


def test_sanitize_drops_orphan_tool_at_window_start() -> None:
    """孤立 tool_result（无前置 tool_use）必须剔除，否则 API 返回 400。"""
    msgs = [
        ChatMessage(
            role="tool",
            content="orphan",
            tool_call_id="call_01_FBC30IQJ8P1LzkmL5GRV2354",
            name="run_command",
        ),
        ChatMessage(role="user", content="继续"),
    ]
    cleaned = _sanitize_tool_pairing(msgs)
    assert [m.role for m in cleaned] == ["user"]

    _, api = _to_anthropic_messages(msgs, deepseek=True)
    assert api[0]["role"] == "user"
    assert api[0]["content"] != [{"type": "tool_result"}]


def test_sanitize_keeps_paired_assistant_tool_block() -> None:
    msgs = [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="call_01_ABC", name="read_file", arguments={"path": "a.py"}),
            ],
        ),
        ChatMessage(
            role="tool",
            content="ok",
            tool_call_id="call_01_ABC",
            name="read_file",
        ),
        ChatMessage(role="user", content="下一步"),
    ]
    cleaned = _sanitize_tool_pairing(msgs)
    assert len(cleaned) == 3
    _, api = _to_anthropic_messages(cleaned, deepseek=True)
    assert api[0]["content"][-1]["type"] == "tool_use"
    assert api[0]["content"][-1]["id"] == "call_01_ABC"
    assert api[1]["content"][0]["tool_use_id"] == "call_01_ABC"


def test_deepseek_merges_parallel_tool_results() -> None:
    msgs = [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="t1", name="write_file", arguments={}),
                ToolCall(id="t2", name="write_file", arguments={}),
            ],
            thinking="",
        ),
        ChatMessage(role="tool", content="ok1", tool_call_id="t1", name="write_file"),
        ChatMessage(role="tool", content="ok2", tool_call_id="t2", name="write_file"),
    ]
    _, api = _to_anthropic_messages(msgs, deepseek=True)
    assert len(api) == 2
    assert api[1]["role"] == "user"
    assert len(api[1]["content"]) == 2
    assert api[1]["content"][0]["tool_use_id"] == "t1"
    assert api[1]["content"][1]["tool_use_id"] == "t2"
