from pathlib import Path

import pytest

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


def test_chat_registers_file_tools(tmp_path, monkeypatch) -> None:
    from auc.cli import _register_chat_tools
    from auc.tools.registry import DefaultToolRegistry

    monkeypatch.chdir(tmp_path)
    reg = DefaultToolRegistry()
    _register_chat_tools(reg, str(tmp_path))
    names = {s.name for s in reg.list_schemas()}
    assert {"read_file", "write_file", "list_dir", "delete_path"} <= names


def test_chat_registers_evolution_tools(tmp_path, monkeypatch) -> None:
    from auc.cli import _chat_memory, _register_chat_tools
    from auc.tools.registry import DefaultToolRegistry

    monkeypatch.chdir(tmp_path)
    reg = DefaultToolRegistry()
    mem = _chat_memory(str(tmp_path), evolve=True)
    _register_chat_tools(reg, str(tmp_path), mem)
    names = {s.name for s in reg.list_schemas()}
    assert "save_lesson" in names
    assert "promote_nugget" in names


def test_cli_config_init_show(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["config", "init"]) == 0
    cfg = Path(tmp_path) / ".Au" / "AuC" / "settings.json"
    assert cfg.is_file()
    assert main(["config", "show"]) == 0


# ── main() 子命令分发与错误路径 ──────────────────────────────


def test_cli_no_subcommand_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_unknown_subcommand_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["no-such-command"])
    assert exc.value.code == 2


def test_cli_extras_lists_install_modes(capsys) -> None:
    assert main(["extras"]) == 0
    out = capsys.readouterr().out
    assert "可选安装模式" in out
    assert "[qq" in out


def test_cli_slice_requires_repo() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["slice", "intent"])
    assert exc.value.code == 2


def test_cli_dispatch_requires_args() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["dispatch", "only-intent", "--repo", "."])
    assert exc.value.code == 2


def test_cli_undo_empty_sandbox_returns_1(tmp_path, capsys) -> None:
    code = main(["undo", "--sandbox", str(tmp_path)])
    assert code == 1
    assert "没有可回滚的检查点" in capsys.readouterr().err


def test_cli_undo_list_and_revert(tmp_path, capsys) -> None:
    from auc.checkpoint import CheckpointStore

    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))
    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "a.txt"})
    target.write_text("v2", encoding="utf-8")

    assert main(["undo", "--sandbox", str(tmp_path), "--list"]) == 0
    out = capsys.readouterr().out
    assert "run: r1" in out
    assert "write_file" in out

    assert main(["undo", "--sandbox", str(tmp_path), "--run", "r1", "--step", "0"]) == 0
    assert target.read_text(encoding="utf-8") == "v1"
    assert "恢复" in capsys.readouterr().out


def test_cli_undo_unknown_run_returns_1(tmp_path, capsys) -> None:
    from auc.checkpoint import CheckpointStore

    (tmp_path / "x.txt").write_text("v", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))
    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "x.txt"})

    code = main(["undo", "--sandbox", str(tmp_path), "--run", "nope"])
    assert code == 1
    assert "没有检查点条目" in capsys.readouterr().err


def test_cli_config_set_and_help(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["config", "init"]) == 0
    assert main(["config", "set", "--model", "gpt-4o"]) == 0
    from auc.config import load_model_config

    cfg_path = Path(tmp_path) / ".Au" / "AuC" / "settings.json"
    assert load_model_config(config_path=str(cfg_path)).model == "gpt-4o"
    with pytest.raises(SystemExit) as exc:
        main(["-h"])
    assert exc.value.code == 0
