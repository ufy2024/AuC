from pathlib import Path

from auc.cli import main


def test_cli_slice() -> None:
    import os

    repo = os.path.join(os.path.dirname(__file__), "fixtures", "sample_repo")
    code = main(["slice", "stop_loss", "--repo", repo])
    assert code == 0


def test_cli_run_scripted() -> None:
    code = main(["run", "hello", "--reply", "ok"])
    assert code == 0


def test_cli_chat_message_optional() -> None:
    import pytest

    from auc.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["chat", "-h"])
    assert exc.value.code == 0


def test_cli_config_init_show(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["config", "init"]) == 0
    cfg = Path(tmp_path) / ".Au" / "AuC" / "settings.json"
    assert cfg.is_file()
    assert main(["config", "show"]) == 0
