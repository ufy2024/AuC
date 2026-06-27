"""Web uvicorn 日志配置。"""

from __future__ import annotations

import pytest

pytest.importorskip("uvicorn")

from auc.web.log_config import uvicorn_log_config


def test_uvicorn_log_config_includes_asctime() -> None:
    cfg = uvicorn_log_config()
    for name in ("default", "access"):
        fmt = cfg["formatters"][name]["fmt"]
        assert "%(asctime)s" in fmt
        assert "%(msecs)03d" in fmt
        assert cfg["formatters"][name]["datefmt"] == "%Y-%m-%d %H:%M:%S"
