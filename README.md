# AuC

**Agents-ufy-Core** — ufy 体系中的单智能体 Python 核心框架。

AuC 基于 asyncio，提供可插拔推理循环（默认 ReAct）、LLM 适配、工具注册与可观测事件流。长期记忆与会话持久化由 [AuM](https://github.com/ufy2024/AuM) 通过端口协议实现；**不安装 AuM 亦可运行**。

当前仓库处于**架构与接口设计阶段**（文档先行，Python 实现见路线图）。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 总体架构、设计原则、Run 数据流 |
| [docs/interfaces.md](docs/interfaces.md) | Protocol 与数据类接口草案 |
| [docs/loops.md](docs/loops.md) | 可插拔 Loop、ReAct 状态机、自定义指南 |
| [docs/aum-integration.md](docs/aum-integration.md) | 与 AuM 的边界与挂载方式 |
| [docs/glossary.md](docs/glossary.md) | 术语表 |
| [docs/examples/minimal-react.md](docs/examples/minimal-react.md) | 最小 ReAct 时序示例 |
| [docs/adr/001-async-pluggable-loop.md](docs/adr/001-async-pluggable-loop.md) | ADR：async + 可插拔 Loop |
| [docs/adr/002-memory-boundary.md](docs/adr/002-memory-boundary.md) | ADR：记忆外置 AuM |

## 与 AuM 的关系

- **AuC**：单 Agent 的推理—行动循环、工具、短期 `ContextWindow`。
- **AuM**：实现 `MemoryPort` / `ContextComposer`，提供跨 Run 记忆与 `SessionStore`。

详见 [docs/aum-integration.md](docs/aum-integration.md)。

## 实现路线图

### 阶段 1 — 核心骨架

- [ ] `auc` 包目录与 `pyproject.toml`
- [ ] `ContextWindow`、`ToolRegistry`、`ModelClient` 协议与内存实现
- [ ] `ReActLoop` + `AgentLoopRunner` + `DefaultAgent`
- [ ] 至少一个 LLM 适配器（如 OpenAI 兼容）

### 阶段 2 — 可观测与易用性

- [ ] `run_stream` 与 `EventBus`
- [ ] `@tool` 装饰器与 schema 生成
- [ ] 示例 CLI 与 `pytest-asyncio` 测试

### 阶段 3 — AuM 联调

- [ ] 与 AuM 集成测试 `MemoryPort` / `ContextComposer`
- [ ] 文档化推荐挂载配置与版本兼容说明

## 仓库

https://github.com/ufy2024/AuC

## 许可

待定（实现阶段补充 LICENSE）。
