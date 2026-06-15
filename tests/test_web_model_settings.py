from __future__ import annotations

import tempfile

from auc.config import load_model_config
from auc.web.model_settings import save_model_settings, settings_local_path


def test_save_model_settings_writes_local_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg, path = save_model_settings(
            tmp,
            provider="openai",
            model="gpt-test",
            base_url="http://example/api",
            api_key="sk-abc12345",
            scope="project_local",
            repo_root=tmp,
        )
        assert path == settings_local_path(tmp)
        assert path.is_file()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-test"
        assert cfg.api_key == "sk-abc12345"
        reloaded = load_model_config(repo_root=tmp)
        assert reloaded.model == "gpt-test"


def test_save_model_settings_project_scope(tmp_path) -> None:
    from auc.config import project_settings_path

    sandbox = str(tmp_path)
    _, path = save_model_settings(
        sandbox,
        provider="openai",
        model="team-model",
        base_url="http://example/api",
        api_key="sk-team",
        scope="project",
        repo_root=sandbox,
    )
    assert path == project_settings_path(sandbox)
    assert path.is_file()
