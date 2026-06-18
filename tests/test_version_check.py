from __future__ import annotations

import auc.version_check as vc


def test_parse_version() -> None:
    assert vc.parse_version("0.2.9") == (0, 2, 9)
    assert vc.parse_version("v1.10.3") == (1, 10, 3)


def test_is_newer() -> None:
    assert vc.is_newer("0.3.0", "0.2.9")
    assert not vc.is_newer("0.2.8", "0.2.9")
    assert not vc.is_newer("0.2.9", "0.2.9")


def test_release_info_update_available(monkeypatch) -> None:
    monkeypatch.setattr(vc, "__version__", "0.1.0")
    monkeypatch.setattr(vc, "fetch_latest_version", lambda **kwargs: "0.2.9")
    info = vc.release_info()
    assert info["current_version"] == "0.1.0"
    assert info["latest_version"] == "0.2.9"
    assert info["update_available"] is True
    assert info["install_cmd"] == "pip install -U ufy-auc -i https://pypi.org/simple/"


def test_release_info_force_refresh(monkeypatch) -> None:
    calls: list[bool] = []

    def _fetch(**kwargs: object) -> str:
        calls.append(bool(kwargs.get("force")))
        return "0.2.10"

    monkeypatch.setattr(vc, "__version__", "0.2.9")
    monkeypatch.setattr(vc, "fetch_latest_version", _fetch)
    vc.release_info(force=True)
    assert calls == [True]


def test_release_info_up_to_date(monkeypatch) -> None:
    monkeypatch.setattr(vc, "__version__", "0.2.9")
    monkeypatch.setattr(vc, "fetch_latest_version", lambda **kwargs: "0.2.9")
    info = vc.release_info()
    assert info["update_available"] is False
