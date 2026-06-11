"""tools/decorator：@tool 元数据与注册边缘路径。"""

from __future__ import annotations

import asyncio

import pytest

from auc.tools.decorator import register_function_tools, tool
from auc.tools.registry import DefaultToolRegistry


def test_tool_decorator_attaches_metadata() -> None:
    @tool(name="custom_name", description="自定义描述", privilege="L3")
    def my_fn(x: str) -> str:
        return x

    meta = my_fn._auc_tool_meta  # noqa: SLF001
    assert meta == {
        "name": "custom_name",
        "description": "自定义描述",
        "privilege": "L3",
    }
    # 装饰器不改变函数本身
    assert my_fn("a") == "a"


def test_register_function_tools_with_and_without_decorator() -> None:
    registry = DefaultToolRegistry()

    @tool(name="greet", privilege="L1")
    def hello(name: str) -> str:
        """打招呼。"""
        return f"hi {name}"

    def plain(value: str) -> str:
        """未装饰的普通函数。"""
        return value.upper()

    register_function_tools(registry, hello, plain)

    t = registry.get("greet")
    assert registry.get_policy("greet").privilege == "L1"
    res = asyncio.run(t.invoke({"name": "张三"}))
    assert res.content == "hi 张三"

    # 未装饰函数：函数名作工具名、docstring 作描述、默认 L2
    t2 = registry.get("plain")
    assert "未装饰" in t2.description
    assert registry.get_policy("plain").privilege == "L2"
    res2 = asyncio.run(t2.invoke({"value": "ab"}))
    assert res2.content == "AB"


def test_register_function_tools_rejects_wrong_registry() -> None:
    def fn() -> str:
        return "x"

    with pytest.raises(TypeError, match="DefaultToolRegistry"):
        register_function_tools(object(), fn)
