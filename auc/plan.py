"""R5 计划模式：```json auc-plan``` 围栏块协议的解析与渲染。"""

from __future__ import annotations

import json
import re
from typing import Any

READONLY_TOOL_NAMES = frozenset(
    {"read_file", "list_dir", "grep_search", "glob_files", "fetch_url"}
)

_PLAN_FENCE_RE = re.compile(
    r"```json\s+auc-plan\s*\n(?P<body>.*?)```",
    re.DOTALL,
)

PLAN_MODE_PROMPT = """\
- **只读探索**：你处于计划模式，只能使用只读工具（read_file/list_dir/grep_search/glob_files/fetch_url），禁止任何写操作。
- **产出计划**：充分探索后，在回复末尾输出结构化计划，必须使用如下围栏块（语言标注为 `json auc-plan`，严格合法 JSON）：

```json auc-plan
{
  "goal": "一句话目标",
  "steps": [{"n": 1, "title": "步骤标题", "detail": "做什么、怎么验证", "files": ["涉及文件"]}],
  "files": ["全部涉及文件"],
  "risks": ["风险与注意事项"],
  "estimate": "约 N 步"
}
```

- **等待批准**：输出计划后结束本轮；用户批准后才会进入执行。"""


def parse_plan_block(text: str | None) -> dict[str, Any] | None:
    """从 assistant 文本中提取 auc-plan 围栏块；解析失败返回 None（降级为普通文本）。"""
    if not text:
        return None
    m = _PLAN_FENCE_RE.search(text)
    if m is None:
        return None
    try:
        plan = json.loads(m.group("body"))
    except json.JSONDecodeError:
        return None
    if not isinstance(plan, dict) or "goal" not in plan or "steps" not in plan:
        return None
    return plan


def render_plan_context(plan: dict[str, Any]) -> str:
    """把已批准计划渲染为 system 块文本，供执行 Run 注入。"""
    lines = ["[已批准计划]", f"目标: {plan.get('goal', '')}"]
    for step in plan.get("steps") or []:
        if isinstance(step, dict):
            n = step.get("n", "?")
            title = step.get("title", "")
            detail = step.get("detail", "")
            lines.append(f"{n}. {title} — {detail}")
    files = plan.get("files") or []
    if files:
        lines.append("涉及文件: " + ", ".join(str(f) for f in files))
    risks = plan.get("risks") or []
    if risks:
        lines.append("风险: " + "; ".join(str(r) for r in risks))
    lines.append("请严格按计划执行，偏离时说明原因。")
    return "\n".join(lines)
