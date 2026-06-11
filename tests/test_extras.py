from pathlib import Path

import tomllib

from auc.extras import INSTALL_MODES, hint_for


def test_install_modes_documented() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    for key in ("llm", "cli", "web", "telegram", "qq", "chat", "all", "dev"):
        assert key in extras
        assert key in INSTALL_MODES


def test_all_is_superset_of_modes() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    all_set = set(extras["all"])
    for mode in ("llm", "cli", "web", "telegram", "qq"):
        for pkg in extras[mode]:
            assert pkg in all_set or pkg.split("[")[0] in {
                p.split("[")[0] for p in all_set
            }


def test_hint_for() -> None:
    msg = hint_for("web", "all")
    assert "[web,all]" in msg or "web" in msg
    assert "pip install" in msg
