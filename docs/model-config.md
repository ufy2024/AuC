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

## Web 模型检索（Base URL + API Key）

顶栏 **model-pill** 打开「模型配置」弹窗，按 **Base URL + API Key** 接入大模型：

1. 填写 **Base URL** 与 **API Key**（点 `AILab` 可一键预填网关）。
2. 点 **检索模型** → 后端 `POST /api/settings/model/models` 拉取网关 `GET {base}/models`
   （Anthropic 风格端点回退 `GET {base}/v1/models`），把可用模型渲染成可点击按钮。
3. **点击按钮选择**；当输入框为空或当前模型不在列表中时**自动选中首个**。
4. **检索不到时**（中转未实现 `/models`、返回 404/空），提示回退到**手动填写模型 ID**，输入框始终可手动编辑。

接口契约：

```jsonc
// 请求
POST /api/settings/model/models
{ "provider": "openai", "base_url": "http://ailab.hcrdi.com/api", "api_key": "sk-..." }
// 成功
{ "ok": true, "models": ["deepseek-chat", "deepseek-coder"], "current": "deepseek-chat" }
// 失败（前端据此回退手动填写）
{ "ok": false, "models": [], "error": "HTTP 404" }
```

> 安全：未传 `api_key` 时复用会话当前配置的密钥；响应只回模型 id，不回写密钥。

## 智能路由（模型名填 `auto`）

把**模型 ID 填 `auto`**即开启智能路由：AuC 优先把规范化后的 `auto:<策略>` 作为 `model`
透传给网关，由**网关按请求内容自动选出最优模型**。

| 模型名 | 策略 | 含义 | 适用 |
|--------|------|------|------|
| `auto`（= `auto:cost_optimized`） | 成本优先 | 能力达标就选最便宜 | 一般任务（默认） |
| `auto:balanced` | 均衡 | 能力 / 成本 / 延迟兼顾 | 默认折中 |
| `auto:quality_first` | 质量优先 | 优先选能力最强 | 复杂推理、关键输出 |
| `auto:latency_critical` | 低延迟优先 | 优先选响应最快 | 交互、补全 |

- 不带后缀的 `auto` 使用默认策略 `cost_optimized`；未知策略回退默认。
- 网关**实际选中的模型**从响应体 `model` 字段读回，运行时在 Web/CLI 显示
  `⟿ 实际模型：<resolved>`（多步内模型变化会再次提示）。
- Web「模型配置」弹窗提供 4 个策略快捷按钮；也可直接在模型框手填 `auto:<策略>`。

### 网关无 `auto` 时由本地维护路由（自动回退）

许多「中转」并未实现网关侧 `auto` 路由（填 `auto` 会报「模型不存在/无效」）。此时
AuC **自动本地接管路由**，无需任何额外配置：

1. 首次请求仍把 `auto:<策略>` 透传网关；
2. 若网关回报模型无效（HTTP 400/404/422 或文本指向「模型不存在」），AuC 立即
   调用网关 `/models` 拉取可用模型列表；
3. 用 `auc/model/local_routing.py` 按策略从中**选出一个真实模型**（启发式估算每个
   模型的能力 / 成本 / 速度三维分值，按策略加权取最优，并排除 embedding/rerank/
   tts/image 等非对话模型），用其重试本次请求；
4. 选型结果**在该客户端内缓存**，后续请求直接复用，不再重复探测；
5. 运行时显示 `⚙ 本地路由选定：<model>`（区别于网关选型的 `⟿ 实际模型`）。

> 本地选型仅依据模型名启发式（标准 `/models` 不返回能力/价格元数据）；若网关连
> `/models` 也未实现，则无法本地路由，会原样抛出错误，请改填具体模型 ID。

## 依赖

```bash
pip install -e '.[llm]'   # 或 .[chat] / .[all]
```
