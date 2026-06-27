"""Uvicorn 日志配置：访问/错误日志带时间戳。"""

from __future__ import annotations

import copy
from typing import Any


def uvicorn_log_config() -> dict[str, Any]:
    """基于 uvicorn 默认配置，为 access/error 日志加上 ``%(asctime)s``。"""
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    datefmt = "%Y-%m-%d %H:%M:%S"
    for name in ("default", "access"):
        fmt = config["formatters"][name]
        fmt["fmt"] = "%(asctime)s,%(msecs)03d " + str(fmt.get("fmt", ""))
        fmt["datefmt"] = datefmt
    return config
