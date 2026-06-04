# AuM 联调与版本兼容

AuC v0.2 在 `auc.integration` 提供 **AuM 参考实现**，便于独立仓库 AuM 复用或替换。

## 端口映射

| AuM 能力 | AuC 参考实现 | 生产替换 |
|----------|--------------|----------|
| SemanticSlicer | `auc.integration.SemanticSlicer` | AuM 向量索引 + grep |
| Rules Matrix | `auc.ports.FileRulesPort` | AuM 缓存解析 |
| Memory | `auc.ports.InMemoryMemoryPort` | AuM `SessionStore` 后端 |
| Au-Nuggets | `auc.integration.NuggetsMemoryPort` | AuM YAML 仓库 |
| L3 2FA | `TelegramApprovalPort` / `ConsoleApprovalPort` | AuM IM 网关 |
| 分派 | `auc.integration.MetaDispatcher` | AuM 调度器 |

## 推荐挂载（与 AuM 仓库联调）

```python
from auc.integration import AuMStack, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import TelegramApprovalPort

stack = AuMStack.create(
    registry=registry,
    approval=TelegramApprovalPort(),
    nuggets_path="au-nuggets.yaml",
    require_package=True,
)
result = await stack.dispatcher.dispatch(intent, message, repo_root="/path/to/repo")
```

## 版本约定

| AuC 版本 | 协议 |
|----------|------|
| 0.2.x | `ContextPackage`, `ProjectRules`, `ApprovalPort`, `RunStatus.pending_approval` |

AuM 应声明兼容的 `auc>=0.2,<0.3`。

## 环境变量

| 变量 | 用途 |
|------|------|
| `OPENAI_API_KEY` | `OpenAICompatibleClient` |
| `TELEGRAM_BOT_TOKEN` | `TelegramApprovalPort` |
| `TELEGRAM_CHAT_ID` | 审批消息目标聊天 |

## CLI

```bash
auc slice "stop_loss" --repo .
auc dispatch "fix stop_loss" "change pct to 0.03" --repo . --nuggets au-nuggets.yaml
auc openai "Hello"   # 需 OPENAI_API_KEY
```
