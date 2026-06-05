from auc.model.json_util import safe_parse_tool_input


def test_safe_parse_valid_json() -> None:
    raw = '{"path": "a.py", "content": "print(1)"}'
    assert safe_parse_tool_input(raw)["path"] == "a.py"


def test_safe_parse_write_file_fallback() -> None:
    raw = '{"path": "game/main.py", "content": "line1\\nline2"}'
    data = safe_parse_tool_input(raw, tool_name="write_file")
    assert data["path"] == "game/main.py"
    assert "line1" in data["content"]


def test_unterminated_content_stream() -> None:
    """Simulates Anthropic input_json_delta cut off mid HTML."""
    raw = (
        '{"path": "frontend/index.html", "content": "<!DOCTYPE html>\\n'
        r'<html lang=\"zh-CN\">\n<head>\n<title>仪表盘</title>'
    )
    data = safe_parse_tool_input(raw, tool_name="write_file")
    assert data["path"] == "frontend/index.html"
    assert "<!DOCTYPE html>" in data["content"]
    assert "仪表盘" in data["content"]


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
