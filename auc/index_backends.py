"""R26 增量：多语言符号索引后端（tree-sitter，可选 extra `index`）。

基线 `code_index.py` 仅用标准库 `ast` 索引 Python。本模块在其上补一层**可选**的
tree-sitter 后端，支持 JS/TS/Go/Rust/Java/C/C++/Ruby 等：

- 惰性导入 `tree_sitter_language_pack`（或旧版 `tree_sitter_languages`）；**未安装即整体降级**
  （`treesitter_available()` 返回 False，解析函数返回 None），调用方退回「仅 Python + grep」。
- 通过「定义节点类型表」+ 子节点 `name` 提取符号，标识符节点作引用，import 语句按语言粗取。

零硬依赖：不装 extra 时本模块全部 no-op，绝不影响核心。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# 扩展名 → tree-sitter 语言名
EXT_LANG: dict[str, str] = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
}

# 各语言「定义」节点类型 → 归一化 kind
_DEF_NODES: dict[str, dict[str, str]] = {
    "javascript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "generator_function_declaration": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "method_definition": "method",
        "method_signature": "method",
        "class_declaration": "class",
        "interface_declaration": "class",
        "enum_declaration": "class",
    },
    "tsx": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "interface_declaration": "class",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "class",
        "enum_item": "class",
        "trait_item": "class",
        "impl_item": "class",
    },
    "java": {
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "class",
        "enum_declaration": "class",
        "constructor_declaration": "method",
    },
    "c": {
        "function_definition": "function",
        "struct_specifier": "class",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "class",
    },
    "ruby": {
        "method": "method",
        "class": "class",
        "module": "class",
        "singleton_method": "method",
    },
}

_IMPORT_NODES = {
    "import_statement",
    "import_declaration",
    "import_spec",
    "use_declaration",
    "preproc_include",
    "call",  # ruby require（粗略，按文本过滤）
}


def detect_language(path: str) -> str | None:
    """按扩展名识别 tree-sitter 语言；Python 与未知返回 None（交给 ast/降级）。"""
    p = path.lower()
    for ext, lang in EXT_LANG.items():
        if p.endswith(ext):
            return lang
    return None


@lru_cache(maxsize=1)
def _loader() -> Any:
    """返回 (get_parser) 可调用；不可用返回 None。结果缓存避免重复探测。"""
    try:
        from tree_sitter_language_pack import get_parser  # type: ignore

        return get_parser
    except Exception:  # noqa: BLE001
        pass
    try:
        from tree_sitter_languages import get_parser  # type: ignore

        return get_parser
    except Exception:  # noqa: BLE001
        return None


def treesitter_available() -> bool:
    return _loader() is not None


@lru_cache(maxsize=32)
def _parser_for(lang: str) -> Any:
    get_parser = _loader()
    if get_parser is None:
        return None
    try:
        return get_parser(lang)
    except Exception:  # noqa: BLE001 语言语法未打包
        return None


def _node_name(node: Any, source: bytes) -> str:
    """取定义节点的名字：优先 name 字段，回退首个 identifier 子节点。"""
    try:
        named = node.child_by_field_name("name")
        if named is not None:
            return source[named.start_byte : named.end_byte].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    try:
        for child in node.children:
            if "identifier" in child.type:
                return source[child.start_byte : child.end_byte].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    return ""


def parse_source(source: str, lang: str) -> tuple[list[Any], list[str], dict[str, list[int]]] | None:
    """用 tree-sitter 解析；返回 (Symbol 列表, imports, references)。

    不可用 / 语言不支持 / 解析异常 → 返回 None（调用方据此降级）。
    Symbol 用 `code_index.Symbol`，避免重复定义。
    """
    def_table = _DEF_NODES.get(lang)
    if def_table is None:
        return None
    parser = _parser_for(lang)
    if parser is None:
        return None
    try:
        from auc.code_index import Symbol

        data = source.encode("utf-8", "replace")
        tree = parser.parse(data)
    except Exception:  # noqa: BLE001
        return None

    symbols: list[Any] = []
    imports: list[str] = []
    references: dict[str, list[int]] = {}

    def _add_ref(name: str, line: int) -> None:
        if not name:
            return
        references.setdefault(name, [])
        if line not in references[name]:
            references[name].append(line)

    def _walk(node: Any, class_parent: str) -> None:
        ntype = node.type
        next_parent = class_parent
        if ntype in def_table:
            kind = def_table[ntype]
            name = _node_name(node, data)
            if name:
                line = node.start_point[0] + 1
                parent = class_parent if kind == "method" else ""
                symbols.append(Symbol(name=name, kind=kind, line=line, parent=parent))
                if kind == "class":
                    next_parent = name
        elif ntype in _IMPORT_NODES:
            txt = data[node.start_byte : node.end_byte].decode("utf-8", "replace")
            imports.append(txt.strip().splitlines()[0][:200] if txt.strip() else "")
        elif ntype == "identifier" or ntype.endswith("type_identifier"):
            name = data[node.start_byte : node.end_byte].decode("utf-8", "replace")
            _add_ref(name, node.start_point[0] + 1)
        for child in getattr(node, "children", []) or []:
            _walk(child, next_parent)

    try:
        _walk(tree.root_node, "")
    except RecursionError:
        return None
    imports = [i for i in imports if i]
    return symbols, imports, references
