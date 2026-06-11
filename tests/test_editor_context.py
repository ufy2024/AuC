from auc.web.editor_context import format_context_block, merge_message_with_context


def test_format_context_with_file() -> None:
    block = format_context_block({
        "active_file": "game.js",
        "file_content": "const x = 1;",
        "include_file": True,
    })
    assert "game.js" in block
    assert "const x = 1" in block


def test_merge_auto_attach() -> None:
    msg, notes = merge_message_with_context(
        "加个暂停按钮",
        {
            "auto_attach": True,
            "active_file": "index.html",
            "file_content": "<html></html>",
        },
    )
    assert "index.html" in msg
    assert "暂停" in msg
    assert notes


def test_merge_at_current_file() -> None:
    msg, notes = merge_message_with_context(
        "优化 @当前文件",
        {"active_file": "a.py", "file_content": "print(1)"},
    )
    assert "a.py" in msg
    assert any("当前文件" in n for n in notes)


def test_merge_selection() -> None:
    msg, _ = merge_message_with_context(
        "重构 @选中",
        {
            "active_file": "a.py",
            "selection": "def foo(): pass",
            "selection_start_line": 1,
            "selection_end_line": 1,
        },
    )
    assert "def foo" in msg
