# ADR 001：asyncio 运行时与可插拔 AgentLoop

- **状态**：已接受
- **日期**：2026-06-04
- **决策者**：AuC 架构设计

## 背景

AuC 需要作为 ufy 单智能体核心，支持 LLM 调用、并发工具执行与流式输出。需在「运行时模型」与「推理循环抽象」上做出稳定、可扩展的基线决策。

## 决策

1. **以 asyncio 作为唯一一等运行时**：所有 I/O 边界（`ModelClient`、`Tool.invoke`、`MemoryPort`）均为 `async`。
2. **推理循环通过 `AgentLoop` Protocol 可插拔**：默认提供 `ReActLoop`；`AgentLoopRunner` 统一驱动 `step` / `should_continue`。
3. **不在 AuC 核心提供同步 API**；若未来需要，在独立适配层用 `asyncio.run` 包装（非首期目标）。

## 理由

| 考量 | asyncio | 同步为主 |
|------|---------|----------|
| 流式 token | 自然 `AsyncIterator` | 需线程/队列桥接 |
| 多工具并行 | `asyncio.gather` | 阻塞或线程池 |
| 与主流 LLM SDK | 多数已提供 async | 需额外包装 |
| 复杂度 | 调用方需 async 上下文 | 脚本更简单 |

单智能体框架的主要成本在 I/O；async 与 LLM、HTTP 工具、AuM 存储的延迟模型一致。

可插拔 Loop 避免将 Plan-Execute、Human-in-the-loop 等模式硬编码进 `Agent`；`Agent` 保持薄门面，Loop 可独立测试与替换。

## 后果

### 正面

- 流式 `run_stream` 与 `complete_stream` 设计一致。
- 自定义 Loop 无需 fork Agent 实现。
- 测试可用 `pytest-asyncio` 与内存替身。

### 负面

- 纯脚本用户必须 `asyncio.run(main())` 或运行在 async 框架（FastAPI 等）内。
- 同步 CPU 密集工具需在工具内自行 `to_thread`，AuC 不自动 offload。

## 备选方案（未采纳）

- **同步 API + 内部 async**：双倍维护，首期不采用。
- **固定 ReAct、不可插拔**：阻碍 Plan-Execute 等场景，不采用。

## 相关文档

- [architecture.md](../architecture.md)
- [loops.md](../loops.md)
- [interfaces.md](../interfaces.md)
