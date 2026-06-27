"""测试夹具：隔离开发机/CI 上真实存在的模型配置环境变量。

`auc.config.load_model_config` 会把 Claude 式 `ANTHROPIC_*`（及 `AUC_*`/`OPENAI_*`/
`DEEPSEEK_*` 等）作为文件配置缺省时的回退来源。若运行环境本身设置了这些变量
（例如 Claude Code 注入的 `ANTHROPIC_MODEL`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`），
配置类测试就会读到真实值而非用例预期，产生假阳性失败。

这里用 autouse fixture 在每个测试前清除这些变量，保证测试相对宿主环境**密闭**；
用例内若需要某变量，仍可通过 `monkeypatch.setenv` 显式设置（在本 fixture 之后生效）。
"""

from __future__ import annotations

import os

import pytest

# 影响 load_model_config 的环境变量前缀与精确键
_ENV_PREFIXES = ("ANTHROPIC_", "OPENAI_", "DEEPSEEK_", "AUC_")
_ENV_KEYS = ("API_TIMEOUT_MS",)


@pytest.fixture(autouse=True)
def _isolate_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(_ENV_PREFIXES) or key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
