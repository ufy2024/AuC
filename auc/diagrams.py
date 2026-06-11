"""Mermaid 图表语法修复（本地启发式 + 智能体）。"""

from __future__ import annotations

import re

from auc.messages import ChatMessage

DIAGRAM_FIX_SYSTEM = """\
你是 Mermaid 语法专家。用户会提供渲染失败的 Mermaid 源码与错误信息。
请只输出一个修正后的 ```mermaid ... ``` 代码块，不要任何解释或多余文字。

常见规则：
- subgraph 标题含中文、空格、冒号、标点时必须加双引号：subgraph "第一阶段：基础"
- 节点标签含 emoji、中文、/、括号、空格时用双引号：A["标签内容"]
- gantt：title / section / 任务名含冒号（:或：）、+、/、→、#、; 或非 ASCII 时用双引号包裹
- gantt 示例："ML入门→XGBoost" :b3, after b2, 3w；title "AI + 量化：1 年路线"
- 保持原有节点 ID、连线与 subgraph 结构，只修语法
- 使用 flowchart TD/LR 等标准关键字
"""

_GANTT_CONFIG_PREFIXES = (
    "title ",
    "section ",
    "dateformat",
    "axisformat",
    "excludes",
    "includes",
    "todaymarker",
    "tickinterval",
    "weekday",
    "weekend",
    "topaxis",
)
_GANTT_SPECIAL_RE = re.compile(r"[:：;#+→/\\]|[^\x00-\x7f]")

_SUBGRAPH_RE = re.compile(r"^(\s*subgraph\s+)(.+)$", re.MULTILINE)
_NODE_LABEL_RE = re.compile(r"(\b[\w][\w-]*\s*)\[([^\]\"]+)\]")
_SPECIAL_LABEL_RE = re.compile(
    r"[\u4e00-\u9fff：:（）()/\s🎯]|[^\x00-\x7f]"
)
_MERMAID_FENCE_RE = re.compile(r"```mermaid\s*\n([\s\S]*?)\n```", re.IGNORECASE)


def _needs_gantt_quote(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        return False
    return bool(_GANTT_SPECIAL_RE.search(t))


def _quote_gantt_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _is_gantt_config_line(stripped: str) -> bool:
    lower = stripped.lower()
    if lower.startswith("%%"):
        return True
    return any(lower.startswith(p) for p in _GANTT_CONFIG_PREFIXES)


def try_local_gantt_fix(code: str) -> str:
    """启发式修复 gantt 标题/分区/任务名中的特殊字符。"""
    if not re.match(r"^\s*gantt\b", code, re.IGNORECASE):
        return code
    out: list[str] = []
    for line in code.splitlines():
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        lower = stripped.lower()

        if lower.startswith("title "):
            title = stripped[6:].strip()
            if _needs_gantt_quote(title):
                out.append(f'{indent}title "{_quote_gantt_text(title)}"')
            else:
                out.append(line)
            continue

        if lower.startswith("section "):
            name = stripped[8:].strip()
            if _needs_gantt_quote(name):
                out.append(f'{indent}section "{_quote_gantt_text(name)}"')
            else:
                out.append(line)
            continue

        if lower.startswith("axisformat"):
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                fmt = parts[1].strip()
                if not (
                    (fmt.startswith('"') and fmt.endswith('"'))
                    or (fmt.startswith("'") and fmt.endswith("'"))
                ):
                    out.append(f'{indent}axisFormat "{_quote_gantt_text(fmt)}"')
                    continue

        if stripped and not _is_gantt_config_line(stripped) and ":" in stripped:
            m = re.match(r"^(\s*)(.+?)\s+:(.+)$", line)
            if m:
                name = m.group(2).strip()
                meta = m.group(3)
                if _needs_gantt_quote(name):
                    out.append(f'{indent}"{_quote_gantt_text(name)}" :{meta}')
                    continue

        out.append(line)
    return "\n".join(out)


def try_local_mermaid_fix(code: str) -> str:
    """启发式修复常见 Mermaid 词法错误（中文 subgraph、特殊节点标签、gantt 等）。"""
    if re.match(r"^\s*gantt\b", code, re.IGNORECASE):
        fixed = try_local_gantt_fix(code)
        if fixed != code:
            return fixed
    fixed = code

    def _quote_subgraph(match: re.Match[str]) -> str:
        prefix, title = match.group(1), match.group(2).strip()
        if title.startswith('"') and title.endswith('"'):
            return match.group(0)
        if _SPECIAL_LABEL_RE.search(title):
            return f'{prefix}"{title}"'
        return match.group(0)

    fixed = _SUBGRAPH_RE.sub(_quote_subgraph, fixed)

    def _quote_node(match: re.Match[str]) -> str:
        node_id, label = match.group(1), match.group(2).strip()
        if _SPECIAL_LABEL_RE.search(label):
            escaped = label.replace('"', '\\"')
            return f'{node_id}["{escaped}"]'
        return match.group(0)

    fixed = _NODE_LABEL_RE.sub(_quote_node, fixed)
    return fixed


def extract_mermaid_codeblock(text: str) -> str | None:
    """从模型回复中提取 mermaid 代码块。"""
    m = _MERMAID_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    if stripped and not stripped.startswith("```"):
        return stripped
    return None


async def fix_mermaid_diagram(
    model: object,
    code: str,
    error: str,
    *,
    force_agent: bool = False,
) -> tuple[str, str]:
    """
    修复 Mermaid 源码。返回 (fixed_code, method)。
    method: local | agent | none
    """
    if not force_agent:
        local = try_local_mermaid_fix(code)
        if local != code:
            return local, "local"

    complete = getattr(model, "complete", None)
    if not callable(complete):
        return code, "none"

    user = (
        f"渲染错误：{error or '未知'}\n\n"
        f"```mermaid\n{code}\n```\n\n"
        "请输出修正后的完整 mermaid 代码块。"
    )
    messages = [
        ChatMessage(role="system", content=DIAGRAM_FIX_SYSTEM),
        ChatMessage(role="user", content=user),
    ]
    msg = await complete(messages, tools=[])
    extracted = extract_mermaid_codeblock(msg.content or "")
    if extracted and extracted.strip() != code.strip():
        return extracted.strip(), "agent"
    local = try_local_mermaid_fix(code)
    if local != code:
        return local, "local"
    return code, "none"
