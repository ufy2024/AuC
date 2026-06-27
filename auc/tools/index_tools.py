"""R26 符号索引工具：find_symbol / find_references / outline（均 L1 只读）。"""

from __future__ import annotations

import json
from typing import Any

from auc.code_index import SymbolIndex
from auc.tools.base import ToolPolicy, tool_from_function

_RESULT_LIMIT = 200


def make_index_tools(sandbox: str) -> list[tuple[Any, ToolPolicy]]:
    index = SymbolIndex(sandbox)

    def _refresh() -> None:
        try:
            index.refresh()
        except Exception:  # noqa: BLE001 索引失败不应让工具崩溃
            pass

    def find_symbol(name: str) -> str:
        """按名称查符号定义（函数/类/方法），返回路径与行号。"""
        _refresh()
        results = index.find_symbol(name)
        return json.dumps(
            {"name": name, "count": len(results), "results": results[:_RESULT_LIMIT]},
            ensure_ascii=False,
        )

    def find_references(symbol: str) -> str:
        """查某名称在仓库中被引用的位置（路径:行号）。"""
        _refresh()
        results = index.find_references(symbol)
        return json.dumps(
            {
                "symbol": symbol,
                "count": len(results),
                "results": results[:_RESULT_LIMIT],
            },
            ensure_ascii=False,
        )

    def outline(path: str) -> str:
        """列出某 Python 文件的 import 与符号大纲（类/函数/方法）。"""
        _refresh()
        result = index.outline(path)
        if result is None:
            return json.dumps(
                {"path": path, "error": "文件未在索引中（非 .py 或不存在）"},
                ensure_ascii=False,
            )
        return json.dumps(result, ensure_ascii=False)

    tools: list[tuple[Any, ToolPolicy]] = [
        tool_from_function(
            find_symbol,
            name="find_symbol",
            description=(
                "按名称查找符号定义（函数/类/方法）在仓库中的位置。"
                "精确匹配优先，无精确命中时回退包含匹配。大仓库定位定义首选。"
            ),
            privilege="L1",
        ),
        tool_from_function(
            find_references,
            name="find_references",
            description=(
                "查找某名称（函数/类/方法/属性）在仓库中被引用的位置（路径:行号），"
                "用于「谁调用了 X」。基于 Python AST，精确到名称。"
            ),
            privilege="L1",
        ),
        tool_from_function(
            outline,
            name="outline",
            description="列出某 Python 文件的 import 与符号大纲（类/函数/方法及行号）。",
            privilege="L1",
        ),
    ]

    # R26 增量：向量语义层可用时追加「语义找符号」工具（extra `index`，缺失不挂载）
    try:
        from auc.index_vector import VectorIndex, available

        if available():
            vindex = VectorIndex(sandbox)

            def semantic_search(query: str) -> str:
                """按语义（而非字面）查找最相关的符号定义。"""
                _refresh()
                try:
                    vindex.build(index)
                    results = vindex.search(query, k=8)
                except Exception:  # noqa: BLE001
                    results = []
                return json.dumps(
                    {"query": query, "count": len(results), "results": results},
                    ensure_ascii=False,
                )

            tools.append(
                tool_from_function(
                    semantic_search,
                    name="semantic_search",
                    description=(
                        "按语义查找最相关的符号定义（向量召回），适合「描述功能找实现」。"
                        "需可选 extra `index`；不可用时本工具不挂载。"
                    ),
                    privilege="L1",
                )
            )
    except Exception:  # noqa: BLE001 向量层不可用即跳过
        pass

    return tools
