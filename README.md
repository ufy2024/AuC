# AuC

**Agents-ufy-Core** — ufy 体系中的单智能体 Python 核心框架。

AuC 基于 asyncio，提供可插拔推理循环（默认 ReAct）、LLM 适配、工具权限分级（L1/L2/L3）与可观测事件流。与 [AuM](https://github.com/ufy2024/AuM) 协同时，吸收 **Claude Code** 式工程纪律：**上下文切片**、**项目军规（`.aurules`）**、**高危操作 IM 二次授权**。

**v0.2.0** — 支持 **OpenAI 兼容** 与 **Anthropic** 大模型，可通过 [配置文件](docs/model-config.md)、环境变量或 CLI 参数切换。

## 快速开始

```bash
cd AuC
pip install -e ".[dev]"   # 需 httpx: pip install 'auc[openai]'

auc config init              # 生成 .auc.yaml
export OPENAI_API_KEY=sk-... # 或 ANTHROPIC_API_KEY
auc config show
auc chat "你好"              # 按配置调用大模型
auc chat "hi" -p anthropic -m claude-sonnet-4-20250514

python examples/minimal_run.py
PYTHONPATH=. python -m pytest -q
```

大模型配置详见 [docs/model-config.md](docs/model-config.md)。

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

| 机制 | 文档 | 实现 |
|------|------|------|
| **Au-Context Slicer** | [docs/context-slicer.md](docs/context-slicer.md) | `SemanticSlicer` |
| **Au-Rules Matrix** | [docs/aurules.md](docs/aurules.md) | `FileRulesPort` |
| **L3 二次授权** | [docs/tool-privilege.md](docs/tool-privilege.md) | `TelegramApprovalPort`, `ConsoleApprovalPort` |

总览：[docs/design-philosophy.md](docs/design-philosophy.md) · AuM 联调：[docs/aum-compatibility.md](docs/aum-compatibility.md)

## 文档

| 文档 | 说明 |
|------|------|
| [docs/design-philosophy.md](docs/design-philosophy.md) | 设计哲学与生态蓝图 |
| [docs/architecture.md](docs/architecture.md) | 总体架构 |
| [docs/interfaces.md](docs/interfaces.md) | 接口草案 |
| [docs/model-config.md](docs/model-config.md) | OpenAI / Anthropic 配置 |
| [docs/aum-compatibility.md](docs/aum-compatibility.md) | AuM 联调与版本 |
| [docs/loops.md](docs/loops.md) | Loop 与 Gate |
| [docs/adr/](docs/adr/) | ADR 001–005 |

## 实现路线图

### 阶段 1 — 核心骨架

- [x] `auc` 包与 `pyproject.toml`
- [x] `ContextWindow`、`ToolRegistry`、`ModelClient`、`ToolPrivilegeGate`
- [x] `ReActLoop` + `AgentLoopRunner` + `DefaultAgent`
- [x] `OpenAICompatibleClient`（`pip install 'auc[openai]'`）

### 阶段 2 — 可观测与军规

- [x] `run_stream` / `EventBus`（含 `approval_*`）
- [x] `FileRulesPort` + `.aurules` 解析
- [x] `@tool` 装饰器、`make_file_tools` 沙盒读写
- [x] `auc` CLI、`pytest`、GitHub Actions CI

### 阶段 3 — AuM 联调（生产闭环）

- [x] `SemanticSlicer` → `ContextPackage`
- [x] `DefaultComposer` + `NuggetsMemoryPort` + `SlicerPolicy`
- [x] `TelegramApprovalPort` / `ConsoleApprovalPort`
- [x] [docs/aum-compatibility.md](docs/aum-compatibility.md)

### 阶段 4 — 进化与多端

- [x] `NuggetsStore` / YAML `au-nuggets.yaml`
- [x] `MetaDispatcher` + `SpecialistRegistry`（IM 遥控基础）
- [ ] 独立 AuM 仓库生产化（持久化、向量索引、Webhook 而非轮询）

## 仓库

https://github.com/ufy2024/AuC

## 许可

MIT — 见 [LICENSE](LICENSE)。
