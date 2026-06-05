from auc.messages import ChatMessage, ToolCall
from auc.model.anthropic import _to_anthropic_messages


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
