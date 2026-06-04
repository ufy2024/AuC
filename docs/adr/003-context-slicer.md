# ADR 003：任务级代码上下文由 AuM Slicer 交付

- **状态**：已接受
- **日期**：2026-06-04
- **决策者**：AuC / AuM 联合架构

## 背景

整仓源码进入模型上下文导致 Token 成本与幻觉风险；Claude Code 类工具依赖 grep/索引只喂相关片段。Specialist Agent 若裸读目录，无法保证生产级可控性。

## 决策

1. 引入 **`ContextPackage`** 类型（AuC 定义），由 **AuM SemanticSlicer** 在分派前生成。
2. Specialist Run **生产环境默认 `require_package=True`**。
3. AuC 不内置向量索引；可提供 repo 工具供 AuM Slicer 调用，不对 Specialist 默认开放无界 `grep`。

## 后果

- **正面**：成本可控、幻觉降低、分派路径可审计（`provenance`）。
- **负面**：AuM 成为分派必备组件；简单 demo 需关闭 `require_package` 或提供最小 Package。

## 相关文档

- [context-slicer.md](../context-slicer.md)
- [interfaces.md](../interfaces.md)
