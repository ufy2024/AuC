# ADR 004：项目军规通过 .aurules / AUM.md 强制前置

- **状态**：已接受
- **日期**：2026-06-04

## 背景

Claude Code 依赖 `CLAUDE.md` 降低「猜命令」试错。ufy 项目同样需要机器可读的 Build/Test/Style 红线。

## 决策

1. 标准文件名：**`.aurules`**（优先）、**`AUM.md`**；可选兼容 `CLAUDE.md`。
2. AuM 解析为 **`ProjectRules`** 并缓存于 Rules Matrix。
3. AuC 经 **`ProjectRulesPort`** 在每次 Run 启动时注入 **RulesBlock** 至 system 上下文最前。
4. `.aurules` 可声明 `tool_policy`，与 AuC `ToolPrivilege` 合并。

## 后果

- **正面**：编译/测试路径一致；密钥等红线可声明式禁止。
- **负面**：无 Rules 文件的仓库需生成模板或显式 `rules=None` 降级。

## 相关文档

- [aurules.md](../aurules.md)
