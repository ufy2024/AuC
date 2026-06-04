import json
import os
from pathlib import Path

from auc.config import (
    default_config_path,
    discover_config_path,
    load_merged_settings,
    load_model_config,
    migrate_yaml_to_json,
    user_config_dir,
)
from auc.model.anthropic import AnthropicClient
from auc.model.factory import create_model_client
from auc.model.openai import OpenAICompatibleClient


def test_user_config_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert user_config_dir() == tmp_path / ".Au" / "AuC"
    assert default_config_path() == tmp_path / ".Au" / "AuC" / "settings.json"


def test_load_from_settings_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = user_config_dir()
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "settings.json"
    cfg_file.write_text(
        json.dumps(
            {
                "model": {
                    "provider": "anthropic",
                    "id": "claude-test",
                    "apiKey": "${MY_KEY}",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_KEY", "secret-key")
    cfg = load_model_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-test"
    assert cfg.api_key == "secret-key"
    assert cfg.config_path == str(cfg_file)


def test_legacy_yaml_still_loads(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = user_config_dir()
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "provider: openai\nmodel: gpt-legacy\napi_key: k\n",
        encoding="utf-8",
    )
    cfg = load_model_config()
    assert cfg.model == "gpt-legacy"


def test_project_settings_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    udir = user_config_dir()
    udir.mkdir(parents=True)
    (udir / "settings.json").write_text(
        json.dumps({"model": {"provider": "openai", "id": "user-model"}}),
        encoding="utf-8",
    )
    proj = tmp_path / "repo"
    auc_dir = proj / ".auc"
    auc_dir.mkdir(parents=True)
    (auc_dir / "settings.json").write_text(
        json.dumps({"model": {"id": "project-model"}}),
        encoding="utf-8",
    )
    cfg = load_model_config(repo_root=str(proj))
    assert cfg.model == "project-model"


def test_cli_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "custom.json"
    cfg_file.write_text(
        json.dumps({"model": {"provider": "openai", "id": "gpt-old"}}),
        encoding="utf-8",
    )
    cfg = load_model_config(
        config_path=str(cfg_file),
        provider="anthropic",
        model="claude-new",
        api_key="k",
    )
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-new"


def test_env_auc_config(monkeypatch, tmp_path) -> None:
    f = tmp_path / "via-env.json"
    f.write_text(
        json.dumps({"model": {"provider": "openai", "id": "from-env-file"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUC_CONFIG", str(f))
    cfg = load_model_config()
    assert cfg.model == "from-env-file"


def test_env_model_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(
        json.dumps({"model": {"provider": "openai", "id": "gpt-old"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUC_CONFIG", str(cfg_file))
    monkeypatch.setenv("AUC_MODEL", "from-env")
    cfg = load_model_config()
    assert cfg.model == "from-env"


def test_create_openai_client(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cfg = load_model_config(provider="openai", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, OpenAICompatibleClient)


def test_create_anthropic_client(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cfg = load_model_config(provider="anthropic", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, AnthropicClient)


def test_deepseek_defaults(monkeypatch) -> None:
    from auc.config import _default_base_url, _default_model, normalize_provider

    assert normalize_provider("deepseek") == "deepseek"
    assert _default_base_url("deepseek") == "https://api.deepseek.com"
    assert _default_model("deepseek") == "deepseek-chat"


def test_create_deepseek_client(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    cfg = load_model_config(provider="deepseek", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.deepseek.com"
    assert cfg.model == "deepseek-chat"


def test_config_init_deepseek_template() -> None:
    from auc.config import config_template_for_provider

    data = json.loads(config_template_for_provider("deepseek"))
    assert data["configName"] == "DeepSeek V4"
    assert data["configId"] == "deepseek-v4-anthropic"
    assert "env" in data
    assert data["env"]["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert "${DEEPSEEK_API_KEY}" in data["env"]["ANTHROPIC_AUTH_TOKEN"]


def test_env_block_claude_style(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    cfg_dir = user_config_dir()
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "settings.json").write_text(
        json.dumps(
            {
                "configName": "DS Gateway",
                "configId": "ds-gw",
                "description": "test",
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "${DEEPSEEK_API_KEY}",
                    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                    "ANTHROPIC_MODEL": "deepseek-chat",
                    "API_TIMEOUT_MS": "300000",
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_model_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "deepseek-chat"
    assert cfg.api_key == "sk-test"
    assert cfg.base_url == "https://api.deepseek.com/anthropic"
    assert cfg.timeout == 300.0
    assert cfg.config_name == "DS Gateway"
    assert cfg.config_id == "ds-gw"


def test_api_timeout_ms_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    udir = user_config_dir()
    udir.mkdir(parents=True)
    (udir / "settings.json").write_text(
        json.dumps({"env": {"API_TIMEOUT_MS": "60000", "OPENAI_API_KEY": "k"}}),
        encoding="utf-8",
    )
    cfg = load_model_config()
    assert cfg.timeout == 60.0


def test_migrate_yaml_to_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    udir = user_config_dir()
    udir.mkdir(parents=True)
    (udir / "config.yaml").write_text(
        "provider: deepseek\nmodel: deepseek-chat\napi_key: ${DEEPSEEK_API_KEY}\n",
        encoding="utf-8",
    )
    out = migrate_yaml_to_json()
    assert out == udir / "settings.json"
    assert (udir / "settings.json").is_file()
    cfg = load_model_config()
    assert cfg.provider == "deepseek"
    assert discover_config_path() == udir / "settings.json"


def test_load_merged_settings_layers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    udir = user_config_dir()
    udir.mkdir(parents=True)
    (udir / "settings.json").write_text('{"model":{"id":"a"}}', encoding="utf-8")
    proj = tmp_path / "p"
    (proj / ".auc").mkdir(parents=True)
    (proj / ".auc" / "settings.local.json").write_text(
        '{"model":{"id":"b"}}', encoding="utf-8"
    )
    merged, _ = load_merged_settings(repo_root=proj)
    assert merged["model"]["id"] == "b"
