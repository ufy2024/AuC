from __future__ import annotations

import pytest

from auc.web import upgrade as up


def test_infer_pip_install_spec_web(monkeypatch) -> None:
    def _spec(name: str):
        return name == "fastapi" or name == "httpx"

    monkeypatch.setattr(up.importlib.util, "find_spec", _spec)
    assert up.infer_pip_install_spec() == "ufy-auc[web]"


def test_run_pip_upgrade_success(monkeypatch) -> None:
    class R:
        returncode = 0
        stdout = "Successfully installed ufy-auc-0.2.12"
        stderr = ""

    monkeypatch.setattr(up, "infer_pip_install_spec", lambda: "ufy-auc[web]")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: R())
    versions = iter(["0.2.11", "0.2.12"])
    monkeypatch.setattr(up, "_installed_distribution_version", lambda: next(versions, "0.2.12"))
    monkeypatch.setattr(up, "fetch_latest_version", lambda **kwargs: "0.2.12")

    result = up.run_pip_upgrade()
    assert result["ok"] is True
    assert result["installed_version"] == "0.2.12"
    assert result["restart_required"] is True


def test_run_pip_upgrade_retries_official_pypi_on_stale_mirror(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = (
                "Requirement already satisfied: ufy-auc[web] (0.2.11)"
                if "--index-url" not in cmd
                else "Successfully installed ufy-auc-0.2.12"
            )
            stderr = ""

        return R()

    versions = iter(["0.2.11", "0.2.11", "0.2.12"])
    monkeypatch.setattr(up, "infer_pip_install_spec", lambda: "ufy-auc[web]")
    monkeypatch.setattr("subprocess.run", _run)
    monkeypatch.setattr(up, "_installed_distribution_version", lambda: next(versions, "0.2.12"))
    monkeypatch.setattr(up, "fetch_latest_version", lambda **kwargs: "0.2.12")

    result = up.run_pip_upgrade()
    assert result["ok"] is True
    assert len(calls) == 2
    assert "--index-url" in calls[1]
    assert "pypi.org" in calls[1][calls[1].index("--index-url") + 1]


@pytest.mark.asyncio
async def test_upgrade_package_skips_when_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(
        up,
        "release_info",
        lambda **kwargs: {"update_available": False, "current_version": "0.2.10"},
    )
    result = await up.upgrade_package()
    assert result["skipped"] is True
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_upgrade_package_runs_pip(monkeypatch) -> None:
    monkeypatch.setattr(
        up,
        "release_info",
        lambda **kwargs: {
            "update_available": True,
            "current_version": "0.2.9",
            "latest_version": "0.2.10",
        },
    )
    monkeypatch.setattr(
        up,
        "run_pip_upgrade",
        lambda **kwargs: {"ok": True, "installed_version": "0.2.10", "message": "done"},
    )
    result = await up.upgrade_package()
    assert result["ok"] is True
    assert result["installed_version"] == "0.2.10"
