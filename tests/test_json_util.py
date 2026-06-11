import pytest

from auc.model.json_util import safe_parse_tool_input


def test_safe_parse_valid_json() -> None:
    raw = '{"path": "a.py", "content": "print(1)"}'
    assert safe_parse_tool_input(raw)["path"] == "a.py"


def test_safe_parse_write_file_fallback() -> None:
    raw = '{"path": "game/main.py", "content": "line1\\nline2"}'
    data = safe_parse_tool_input(raw, tool_name="write_file")
    assert data["path"] == "game/main.py"
    assert "line1" in data["content"]


def test_unterminated_content_stream_rejected_with_append_hint() -> None:
    """content 中途截断：拒绝写入残缺文件，错误信息指导 append 分段续写。"""
    raw = (
        '{"path": "frontend/index.html", "content": "<!DOCTYPE html>\\n'
        r'<html lang=\"zh-CN\">\n<head>\n<title>仪表盘</title>'
    )
    with pytest.raises(ValueError, match="append"):
        safe_parse_tool_input(raw, tool_name="write_file")


def test_truncated_before_path_rejected_with_append_hint() -> None:
    """截断发生在 path 之前（content 键序在前）：同样指导分段续写。"""
    raw = '{"content": "<!DOCTYPE html><script>const x = '
    with pytest.raises(ValueError, match="append"):
        safe_parse_tool_input(raw, tool_name="write_file")


def test_truncated_non_write_tool_repaired() -> None:
    """非 write_file 工具的轻度截断（缺收尾引号/括号）仍可修复。"""
    data = safe_parse_tool_input('{"path": "a.py"', tool_name="read_file")
    assert data == {"path": "a.py"}
    data = safe_parse_tool_input('{"pattern": "needle', tool_name="grep_search")
    assert data == {"pattern": "needle"}


def test_content_only_with_path_later_in_buffer() -> None:
    raw = '{"content": "hello", "path": "b.txt"}'
    data = safe_parse_tool_input(raw, tool_name="write_file")
    assert data["path"] == "b.txt"
    assert data["content"] == "hello"


def test_reordered_path_after_long_content() -> None:
    html = "<div>" + "x" * 500 + "</div>"
    raw = '{"content": "' + html.replace('"', '\\"') + '", "path": "out.html"}'
    data = safe_parse_tool_input(raw, tool_name="write_file")
    assert data["path"] == "out.html"
    assert len(data["content"]) > 400
