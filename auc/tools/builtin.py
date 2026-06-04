from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from auc.messages import ToolResult
from auc.tools.base import ToolPolicy, tool_from_function


async def echo(**kwargs: Any) -> str:
    """Echo tool arguments as JSON."""
    return json.dumps(kwargs, ensure_ascii=False)


def make_echo_tool() -> tuple[Any, ToolPolicy]:
    return tool_from_function(echo, name="echo", description="Echo arguments", privilege="L1")
