from auc.terminal import display_width, draw_panel, pad_to, strip_ansi, truncate_to


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
