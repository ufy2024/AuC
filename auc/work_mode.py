"""智能体工作模式：多模式注册、自动识别、手动指定。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from auc.plan import PLAN_MODE_PROMPT as _PLAN_MODE_RULES

WorkModeId = Literal[
    "implement",
    "explain",
    "diagram",
    "debug",
    "review",
    "explore",
    "clarify",
    "chat",
    "plan",
]
WorkModeChoice = Literal[
    "auto",
    "implement",
    "explain",
    "diagram",
    "debug",
    "review",
    "explore",
    "clarify",
    "chat",
    "plan",
]

AUTO_MODE = "auto"


@dataclass(frozen=True)
class WorkModeSpec:
    id: WorkModeId
    label: str
    description: str
    turn_rules: str
    phases: str
    readonly_tools: bool = False  # R5：True 时 Run 的工具视图收窄为只读集


WORK_MODES: dict[WorkModeId, WorkModeSpec] = {
    "implement": WorkModeSpec(
        id="implement",
        label="实现模式",
        description="改代码、加功能、写文件；理解→计划→执行→验收",
        phases="理解 → 计划 → 执行 → 验收",
        turn_rules="""\
- **理解**：复述需求要点与约束；含糊时先澄清（≤2 问），勿猜测后大改。
- **计划**：列出将读写的文件与每项变更；最小改动；改前必 `read_file`。
- **执行**：用 `write_file` 落盘；禁止只贴代码不保存。
- **验收**：逐条对照需求 `✓/✗`；列出实际修改的文件。""",
    ),
    "explain": WorkModeSpec(
        id="explain",
        label="解答模式",
        description="概念解释、原理说明、技术咨询；紧扣问题、避免跑题",
        phases="理解 → 解答 → 确认",
        turn_rules="""\
- **理解**：用一句话复述用户问的是什么。
- **解答**：针对该问题回答；可举例但不展开无关话题。
- **确认**：结尾说明是否已回答核心问题；若需更多信息，指出缺什么。""",
    ),
    "diagram": WorkModeSpec(
        id="diagram",
        label="图表模式",
        description="流程图、架构图、思维导图等 Mermaid 可视化",
        phases="理解 → 构图 → 校验",
        turn_rules="""\
- **理解**：说明图表要表达的核心信息与受众。
- **构图**：输出规范 Mermaid（subgraph/中文标签加双引号）。
- **校验**：确认是否覆盖用户提到的全部要点；缺项标明。""",
    ),
    "debug": WorkModeSpec(
        id="debug",
        label="调试模式",
        description="排查 Bug、报错、异常行为；证据驱动、最小修复",
        phases="复现 → 定位 → 修复 → 验证",
        turn_rules="""\
- **复现**：复述现象、期望与实际；确认复现条件。
- **定位**：先 `read_file` / `list_dir` 收集证据，再提出根因假设。
- **修复**：最小改动修复；勿顺带重构无关代码。
- **验证**：说明修复点及如何验证；未确认处标明。""",
    ),
    "review": WorkModeSpec(
        id="review",
        label="审查模式",
        description="代码审查、风险与改进建议；默认只读不改",
        phases="阅读 → 评审 → 建议",
        turn_rules="""\
- **阅读**：`read_file` 查看相关代码，理解意图与上下文。
- **评审**：按严重度列出问题（安全/正确性/可维护性/风格）。
- **建议**：给出可操作建议；**未经用户要求不要直接改文件**。""",
    ),
    "explore": WorkModeSpec(
        id="explore",
        label="探索模式",
        description="了解项目结构、模块关系；只读不写",
        phases="扫描 → 归纳 → 指引",
        turn_rules="""\
- **扫描**：`list_dir` / `read_file` 探索结构，勿修改文件。
- **归纳**：说明目录职责、入口、关键依赖与数据流。
- **指引**：若用户下一步要改什么，指出从哪入手。""",
    ),
    "clarify": WorkModeSpec(
        id="clarify",
        label="澄清模式",
        description="需求不清时先对齐目标，再决定是否动手",
        phases="复述 → 澄清 → 待确认",
        turn_rules="""\
- **复述**：你对需求的当前理解（可能不完整）。
- **澄清**：列出 2–4 个关键待确认点（范围、文件、验收标准等）。
- **外链**：若需网页内容，可用 `fetch_url`（需用户授权）；或请用户粘贴正文/保存文件到工作区。
- **待确认**：在用户确认前，不做大规模 `write_file`。""",
    ),
    "chat": WorkModeSpec(
        id="chat",
        label="对话模式",
        description="一般编程相关对话；保持聚焦、礼貌引导",
        phases="理解 → 回应",
        turn_rules="""\
- **理解**：简要复述用户意图。
- **回应**：简洁有用；与编程无关时说明边界并引导回任务。""",
    ),
    "plan": WorkModeSpec(
        id="plan",
        label="计划模式",
        description="只读探索并产出结构化计划，批准后执行",
        phases="探索 → 计划 → 待批准",
        turn_rules=_PLAN_MODE_RULES,
        readonly_tools=True,
    ),
}

WORK_MODE_OVERVIEW = """\
## 工作模式体系

每轮用户消息会带有 `[工作模式：…]` 指令（自动识别或用户下拉指定）。**必须严格遵循该模式的阶段与规则**，防止答非所问、实现与需求不一致。

| 模式 | 适用场景 | 阶段 |
|------|----------|------|
| 实现 | 改代码、加功能、写文件 | 理解→计划→执行→验收 |
| 解答 | 解释概念、技术咨询 | 理解→解答→确认 |
| 图表 | 流程/架构 Mermaid | 理解→构图→校验 |
| 调试 | Bug、报错排查 | 复现→定位→修复→验证 |
| 审查 | 代码评审 | 阅读→评审→建议 |
| 探索 | 了解项目结构 | 扫描→归纳→指引 |
| 澄清 | 需求不明确 | 复述→澄清→待确认 |
| 对话 | 一般交流 | 理解→回应 |
| 计划 | 大改动先出计划再执行（只读） | 探索→计划→待批准 |

回复建议用 Markdown 标出当前模式的关键阶段标题（如 **需求理解**、**计划**、**验收**）。
"""

# 保留兼容旧引用
WORK_MODE_SECTION = WORK_MODE_OVERVIEW

_DEBUG_RE = re.compile(
    r"(报错|错误|异常|崩溃|bug|Bug|失败|不工作|打不开|500|404|"
    r"traceback|stack trace|exception|fix.*error|排查|调试)",
    re.I,
)
_REVIEW_RE = re.compile(
    r"(审查|review|code review|看看代码|检查代码|有没有问题|"
    r"代码质量|评审|review一下)",
    re.I,
)
_EXPLORE_RE = re.compile(
    r"(项目结构|代码结构|有哪些文件|目录结构|了解一下|"
    r"帮我看看|概览|overview|walkthrough|讲讲这个项目)",
    re.I,
)
_IMPLEMENT_RE = re.compile(
    r"(实现|添加|增加|修改|改写|创建|新建|写入|删除|移除|修复|优化|重构|"
    r"帮我|帮忙|做一|做一个|写一个|改一|改成|换成|接入|集成|部署|"
    r"fix|implement|add|create|update|refactor|remove|delete)",
    re.I,
)
_EXPLAIN_RE = re.compile(
    r"(什么是|是什么|为什么|怎样|如何理解|解释一下|什么意思|区别|对比|"
    r"原理|概念|what is|why|how does|explain)",
    re.I,
)
_DIAGRAM_RE = re.compile(
    r"(流程图|架构图|时序图|类图|状态图|思维导图|mermaid|Mermaid|画图|绘制|"
    r"diagram|flowchart|mindmap)",
    re.I,
)
_CODE_CTX_RE = re.compile(
    r"(\[Web 编辑器\]|\[Web 预览\]|\[Web 项目\]|--- file:|@当前|@选中|附带当前文件)",
    re.I,
)


def list_work_modes() -> list[dict[str, str]]:
    """供 API / UI 使用的工作模式列表（不含 auto）。"""
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "description": spec.description,
            "phases": spec.phases,
        }
        for spec in WORK_MODES.values()
    ]


def get_mode_spec(mode_id: WorkModeId | str) -> WorkModeSpec:
    mid = mode_id if mode_id in WORK_MODES else "chat"
    return WORK_MODES[mid]  # type: ignore[index]


def normalize_mode_choice(choice: str | None) -> WorkModeChoice:
    c = (choice or AUTO_MODE).strip().lower()
    if c == AUTO_MODE:
        return AUTO_MODE
    if c in WORK_MODES:
        return c  # type: ignore[return-value]
    return AUTO_MODE


def classify_work_mode(message: str) -> WorkModeId:
    """根据用户消息自动推断工作模式。"""
    text = (message or "").strip()
    if not text:
        return "clarify"
    if _DIAGRAM_RE.search(text):
        return "diagram"
    if _DEBUG_RE.search(text):
        return "debug"
    if _REVIEW_RE.search(text):
        return "review"
    if _EXPLORE_RE.search(text) and not _IMPLEMENT_RE.search(text):
        return "explore"
    has_impl = bool(_IMPLEMENT_RE.search(text))
    has_explain = bool(_EXPLAIN_RE.search(text))
    has_ctx = bool(_CODE_CTX_RE.search(text))
    if has_impl or has_ctx:
        return "implement"
    if has_explain and not has_impl:
        return "explain"
    if len(text) < 12:
        return "clarify"
    return "chat"


def resolve_work_mode(
    message: str,
    selected: str | None = AUTO_MODE,
) -> tuple[WorkModeId, Literal["auto", "manual"]]:
    """解析最终工作模式：用户手动指定优先，否则自动识别。"""
    choice = normalize_mode_choice(selected)
    if choice != AUTO_MODE:
        return choice, "manual"  # type: ignore[return-value]
    return classify_work_mode(message), "auto"


def format_mode_note(mode_id: WorkModeId, source: Literal["auto", "manual"]) -> str:
    spec = get_mode_spec(mode_id)
    src = "自动识别" if source == "auto" else "手动选择"
    return f"工作模式：{spec.label}（{src}）"


def enrich_user_turn(
    message: str,
    *,
    selected: str | None = AUTO_MODE,
) -> tuple[str, WorkModeId, Literal["auto", "manual"]]:
    """注入本轮工作模式指令，返回 (增强消息, 模式 id, 来源)。"""
    text = (message or "").strip()
    if not text:
        return message, "clarify", "auto"
    mode_id, source = resolve_work_mode(text, selected)
    spec = get_mode_spec(mode_id)
    src_tag = "自动识别" if source == "auto" else "用户指定"
    header = f"[工作模式：{spec.label} · {spec.id} · {src_tag}]"
    body = f"{header}\n{spec.turn_rules}\n\n{text}"
    return body, mode_id, source


# 兼容旧 API
def classify_task_intent(message: str) -> str:
    return classify_work_mode(message)


def build_full_system_prompt(
    sandbox: str,
    *,
    base: str,
    include_work_mode: bool = True,
    extra: str | None = None,
) -> str:
    parts = [base.format(sandbox=sandbox)]
    if include_work_mode:
        parts.append(WORK_MODE_OVERVIEW)
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(parts)
