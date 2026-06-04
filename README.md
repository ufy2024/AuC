# AuC

**Agents-ufy-Core** — ufy 体系中的单智能体 Python 核心框架。

AuC 基于 asyncio，提供可插拔推理循环（默认 ReAct）、LLM 适配、工具权限分级（L1/L2/L3）与可观测事件流。与 [AuM](https://github.com/ufy2024/AuM) 协同时，吸收 **Claude Code** 式工程纪律：**上下文切片**、**项目军规（`.aurules`）**、**高危操作 IM 二次授权**；不安装 AuM 亦可运行（开发模式）。

**v0.1.0** 已提供可运行的 Python 核心实现（`auc` 包），与 `docs/` 架构文档对齐。

## 快速开始

```bash
cd AuC
pip install -e ".[dev]"   # 或: PYTHONPATH=. python ...
python examples/minimal_run.py
PYTHONPATH=. python -m pytest -q
```

```python
import asyncio
from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient, make_echo_tool
from auc.messages import ToolCall
from auc.model import AssistantMessage

async def main():
    reg = DefaultToolRegistry()
    t, p = make_echo_tool()
    reg.register(t, p)
    model = InMemoryModelClient(responses=[
        AssistantMessage(content=None, tool_calls=[ToolCall(id="1", name="echo", arguments={"x": 1})]),
        AssistantMessage(content="done", tool_calls=None),
    ])
    agent = DefaultAgent(AgentConfig(agent_id="demo", model=model, tools=reg))
    print((await agent.run("run echo")).output)

asyncio.run(main())
```

## 设计亮点（Claude Code 经验）

| 机制 | 文档 | 职责 |
|------|------|------|
| **Au-Context Slicer** | [docs/context-slicer.md](docs/context-slicer.md) | AuM 切片 → `ContextPackage`，防 Token 灾难与幻觉 |
| **Au-Rules Matrix** | [docs/aurules.md](docs/aurules.md) | `.aurules` / `AUM.md` 军规，Run 前强制注入 |
| **L3 二次授权** | [docs/tool-privilege.md](docs/tool-privilege.md) | AuC 门控 + AuM Telegram 等人机批复 |

总览：[docs/design-philosophy.md](docs/design-philosophy.md)

## 文档

| 文档 | 说明 |
|------|------|
| [docs/design-philosophy.md](docs/design-philosophy.md) | 设计哲学与 AuM+AuC 生态蓝图 |
| [docs/architecture.md](docs/architecture.md) | 总体架构、设计原则、Run 数据流 |
| [docs/interfaces.md](docs/interfaces.md) | Protocol 与数据类接口草案 |
| [docs/loops.md](docs/loops.md) | 可插拔 Loop、ReAct、PrivilegeGate |
| [docs/aum-integration.md](docs/aum-integration.md) | AuM 分派、Slicer、Rules、2FA |
| [docs/context-slicer.md](docs/context-slicer.md) | 动态项目裁剪 |
| [docs/aurules.md](docs/aurules.md) | 项目军规矩阵 |
| [docs/tool-privilege.md](docs/tool-privilege.md) | 工具分级与 IM 2FA |
| [docs/glossary.md](docs/glossary.md) | 术语表 |
| [docs/examples/minimal-react.md](docs/examples/minimal-react.md) | 最小 ReAct 时序 |
| [docs/examples/aurules.sample.md](docs/examples/aurules.sample.md) | `.aurules` 示例 |
| [docs/adr/](docs/adr/) | 架构决策记录 001–005 |

## 与 AuM 的关系

- **AuC**：Specialist 执行体 — Loop、工具、L1/L2/L3 门控、短期 `ContextWindow`。
- **AuM**：Meta 层 — 任务分派、Slicer、Rules Matrix、`MemoryPort`、`ApprovalPort`（IM）、`Au-Nuggets`。

详见 [docs/aum-integration.md](docs/aum-integration.md)。

## 实现路线图

### 阶段 1 — 核心骨架

- [x] `auc` 包目录与 `pyproject.toml`
- [x] `ContextWindow`、`ToolRegistry`、`ModelClient`、`ToolPrivilegeGate`
- [x] `ReActLoop` + `AgentLoopRunner` + `DefaultAgent`
- [ ] OpenAI 兼容 LLM 适配器（可选依赖 `auc[openai]`，待实现）

### 阶段 2 — 可观测与军规

- [x] `run_stream` 与 `EventBus`（含 `approval_*` 事件）
- [x] `FileRulesPort` + `.aurules` 解析
- [x] `@tool` 装饰器与 `privilege` 标注
- [x] `examples/minimal_run.py` 与 `pytest` 测试

### 阶段 3 — AuM 联调（生产闭环）

- [ ] `MemoryPort` / `ContextComposer` / `SemanticSlicer` / `ApprovalPort`
- [ ] `ContextPackage` 挂载与 `SlicerPolicy`
- [ ] Telegram（或通用 IM）L3 审批卡片
- [ ] 与 AuM 联调文档与版本兼容说明

### 阶段 4 — 进化与多端（AuM 为主）

- [ ] `Au-Nuggets` YAML 技能召回
- [ ] OpenClaw 式 IM 遥控与 Specialist 动态注册（AuM）

## 仓库

https://github.com/ufy2024/AuC

## 许可

待定（实现阶段补充 LICENSE）。
