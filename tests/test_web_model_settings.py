from __future__ import annotations

import asyncio
import tempfile

from auc.config import load_model_config
from auc.web.model_settings import (
    discover_models_payload,
    save_model_settings,
    settings_local_path,
)


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


def test_discover_models_payload_handles_failure() -> None:
    payload = asyncio.run(
        discover_models_payload(
            provider="openai",
            base_url="",
            api_key="sk-x",
            current_model="m",
        )
    )
    assert payload["ok"] is False
    assert payload["models"] == []
    assert payload["error"]


def test_discover_models_payload_success(monkeypatch) -> None:
    async def fake_discover(**kwargs):
        return ["deepseek-chat", "deepseek-coder"]

    monkeypatch.setattr("auc.model.discovery.discover_models", fake_discover)
    payload = asyncio.run(
        discover_models_payload(
            provider="openai",
            base_url="http://relay/api",
            api_key="sk-x",
            current_model="deepseek-chat",
        )
    )
    assert payload["ok"] is True
    assert payload["models"] == ["deepseek-chat", "deepseek-coder"]
    assert payload["current"] == "deepseek-chat"
