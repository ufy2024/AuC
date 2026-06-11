# 大模型配置（Claude Code `settings.json` 格式）

AuC 与 Claude Code 一致：顶层 **`env`** 注入环境变量，并增加 **配置命名字段** 便于识别多套配置。

```json
{
  "$schema": "https://github.com/ufy2024/AuC/blob/main/docs/schema/settings.schema.json",
  "configName": "DeepSeek V4",
  "configId": "deepseek-v4-anthropic",
  "description": "经 DeepSeek Anthropic 兼容网关",
  "env": {
    "AUC_PROVIDER": "anthropic",
    "ANTHROPIC_AUTH_TOKEN": "${DEEPSEEK_API_KEY}",
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "API_TIMEOUT_MS": "300000",
    "ANTHROPIC_MODEL": "deepseek-chat",
    "ANTHROPIC_SMALL_FAST_MODEL": "deepseek-chat",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-chat",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-chat",
    "AUC_MAX_TOKENS": "8192"
  }
}
```

合并优先级（后者覆盖前者）：`~/.Au/AuC/config.yaml`（legacy）→ `config.json` → **`settings.json`** → `.auc/settings.json` → `.auc/settings.local.json`

运行时：**CLI > 进程环境变量 > 合并后的 `env` > 默认值**

## 命名字段

| 字段 | 说明 |
|------|------|
| `configName` | 显示名称（如「DeepSeek V4」） |
| `configId` | 唯一 ID（如 `deepseek-v4-anthropic`），便于脚本切换 |
| `description` | 配置说明 |

## 常用 `env` 键

| 变量 | 说明 |
|------|------|
| `AUC_PROVIDER` | `openai` / `anthropic` / `deepseek` |
| `ANTHROPIC_AUTH_TOKEN` | Anthropic 网关 Token（Claude Code 同名） |
| `ANTHROPIC_API_KEY` | 原生 Anthropic Key |
| `ANTHROPIC_BASE_URL` | API 根地址 |
| `ANTHROPIC_MODEL` | 主模型 ID |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI 兼容（含 DeepSeek OpenAI 模式） |
| `DEEPSEEK_API_KEY` | DeepSeek Key |
| `API_TIMEOUT_MS` | 超时（毫秒，与 Claude Code 一致） |
| `AUC_MODEL` / `AUC_MAX_TOKENS` | AuC 扩展 |

`env` 内值支持 `${ENV_NAME}` 占位，加载时从环境变量展开。

## CLI

```bash
auc config init --provider deepseek
auc config init --config-name "我的 DeepSeek" --config-id my-ds
auc config show
auc config migrate
auc chat "你好"
```

仍兼容 legacy 顶层 `model` 对象；新配置请只用 `env` + 命名字段。

## 依赖

```bash
pip install -e '.[llm]'   # 或 .[chat] / .[all]
```
