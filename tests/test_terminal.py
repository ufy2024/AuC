from auc.terminal import display_width, draw_panel, log_time_prefix, pad_to, strip_ansi, truncate_to


def test_display_width_cjk() -> None:
    assert display_width("中文") == 4
    assert display_width("abc") == 3


def test_pad_to() -> None:
    assert display_width(pad_to("hi", 6)) == 6


def test_truncate_path() -> None:
    long = "/" + "a" * 60
    out = truncate_to(long, 20)
    assert display_width(strip_ansi(out)) <= 20


def test_draw_panel_runs(capsys) -> None:
    draw_panel(title="test", rows=["a", "b"])
    out = capsys.readouterr().out
    assert "╭" in out
    assert "╰" in out


def test_log_time_prefix_format() -> None:
    plain = strip_ansi(log_time_prefix(1704067200.123))
    assert plain.startswith("[") and "] " in plain
    assert "." in plain  # 毫秒分隔
    assert ":" in plain
