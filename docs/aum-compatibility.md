# AuM 联调与版本兼容

AuC v0.2 在 `auc.integration` 提供 **AuM 参考实现**，便于独立仓库 AuM 复用或替换。

## 端口映射

| AuM 能力 | AuC 参考实现 | 生产替换 |
|----------|--------------|----------|
| SemanticSlicer | `auc.integration.SemanticSlicer` | AuM 向量索引 + grep |
| Rules Matrix | `auc.ports.FileRulesPort` | AuM 缓存解析 |
| Memory | `auc.ports.InMemoryMemoryPort` | AuM `SessionStore` 后端 |
| Au-Nuggets | `auc.integration.NuggetsMemoryPort` | AuM YAML 仓库 |
| L3 2FA | `TelegramApprovalPort` / `QQApprovalPort` / `ConsoleApprovalPort` | AuM IM 网关 |
| 分派 | `auc.integration.MetaDispatcher` | AuM 调度器 |

## 推荐挂载（与 AuM 仓库联调）

```python
from auc.integration import AuMStack, SpecialistRegistry, SpecialistSpec
from auc.integration.qq import QQApprovalPort
from auc.integration.telegram import TelegramApprovalPort

stack = AuMStack.create(
    registry=registry,
    approval=QQApprovalPort(),  # 或 TelegramApprovalPort()
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
| `QQ_ONEBOT_HTTP_URL` | `QQApprovalPort` OneBot 11 HTTP 基址 |
| `QQ_TARGET_USER_ID` | QQ 私聊目标（与群二选一） |
| `QQ_TARGET_GROUP_ID` | QQ 群目标 |
| `QQ_APP_ID` / `QQ_CLIENT_SECRET` | QQ 官方机器人（`backend=official`） |

## CLI

```bash
auc slice "stop_loss" --repo .
auc dispatch "fix stop_loss" "change pct to 0.03" --repo . --nuggets au-nuggets.yaml
auc openai "Hello"   # 需 OPENAI_API_KEY
```
