from auc.cli import main


def test_cli_slice() -> None:
    import os

    repo = os.path.join(os.path.dirname(__file__), "fixtures", "sample_repo")
    code = main(["slice", "stop_loss", "--repo", repo])
    assert code == 0


def test_cli_run_scripted() -> None:
    code = main(["run", "hello", "--reply", "ok"])
    assert code == 0
