# 大模型配置（OpenAI / Anthropic）

AuC 通过 **配置文件**、**环境变量** 或 **终端参数** 选择 OpenAI 兼容 API 或 Anthropic Messages API。优先级：

**CLI 参数 > 环境变量 > 配置文件 > 默认值**

## 配置文件

搜索顺序（`auc config show` 可查看实际命中路径）：

1. `--config /path/to/file`
2. 环境变量 `AUC_CONFIG`（配置文件路径）
3. **`~/.Au/AuC/config.yaml`**（默认用户配置）
4. `~/.Au/AuC/config.yml`
5. 项目目录 `./.auc.yaml`（可选覆盖）

### 初始化

```bash
# 写入 ~/.Au/AuC/config.yaml（OpenAI 模板）
auc config init

# Anthropic 模板
auc config init --provider anthropic

# 自定义路径
auc config init --path /path/to/custom.yaml
```

### OpenAI 示例

```yaml
provider: openai
model: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
base_url: https://api.openai.com/v1   # 兼容 DeepSeek 等可改此 URL
timeout: 120
max_tokens: 4096
```

### Anthropic 示例

```yaml
provider: anthropic
model: claude-sonnet-4-20250514
api_key: ${ANTHROPIC_API_KEY}
base_url: https://api.anthropic.com
timeout: 120
max_tokens: 4096
```

`api_key` 支持 `${ENV_NAME}`，启动时从环境变量展开。

## 环境变量

| 变量 | 说明 |
|------|------|
| `AUC_CONFIG` | 配置文件路径（等同 `--config`） |
| `AUC_PROVIDER` | `openai` 或 `anthropic` |
| `AUC_MODEL` | 模型 ID |
| `AUC_API_KEY` | 通用 API Key（覆盖文件） |
| `AUC_BASE_URL` | API 根地址 |
| `AUC_TIMEOUT` | 超时秒数 |
| `AUC_MAX_TOKENS` | 最大输出 token（Anthropic） |
| `OPENAI_API_KEY` | provider=openai 时默认 Key |
| `ANTHROPIC_API_KEY` | provider=anthropic 时默认 Key |

## 终端使用

```bash
# 使用配置文件
auc chat "你好"

# 临时指定 Anthropic
auc chat "你好" --provider anthropic --model claude-sonnet-4-20250514

# 指定配置文件
auc chat "你好" -c ~/.Au/AuC/config.yaml

# 查看合并后的配置（Key 脱敏）
auc config show

# 修改默认配置文件
auc config set --provider openai --model gpt-4o
```

## Python API

```python
from auc.config import load_model_config
from auc.model.factory import create_model_client, aclose_model_client

cfg = load_model_config(
    config_path="~/.Au/AuC/config.yaml",
    provider="anthropic",  # 可选覆盖
)
model = create_model_client(cfg)
# ... AgentConfig(model=model) ...
await aclose_model_client(model)
```

## 依赖

```bash
pip install 'auc[openai]'   # 安装 httpx（OpenAI + Anthropic 均需）
```
