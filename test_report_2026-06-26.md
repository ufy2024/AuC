# AuC 系统测试报告

**测试日期**: 2026-06-26
**Python 版本**: 3.13.13
**pytest 版本**: 9.0.3

---

## 总体结果

| 指标 | 数量 | 占比 |
|------|------|------|
| 总计 | 556 | 100% |
| 通过 | 544 | 97.8% |
| 失败 | 9 | 1.6% |
| 跳过 | 3 | 0.5% |
| **执行时间** | **17.81s** | |

---

## 失败分析：1 个根因 → 9 个测试失败

所有 9 个失败测试都是**同一个根因**：运行环境中存在真实的 `ANTHROPIC_*` 环境变量（`ANTHROPIC_MODEL=deepseek-v4-pro`、`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`、`ANTHROPIC_AUTH_TOKEN=sk-...`），这些环境变量未被测试隔离，导致 `load_model_config()` 读取到真实环境变量值而非测试 mock 值。

### 失败清单

| # | 测试文件 | 测试用例 | 期望值 | 实际值（环境泄漏） |
|---|---------|---------|--------|-------------------|
| 1 | `test_config.py:47` | `test_load_from_settings_json` | `claude-test` | `deepseek-v4-pro` |
| 2 | `test_config.py:61` | `test_legacy_yaml_still_loads` | `gpt-legacy` | `deepseek-v4-pro` |
| 3 | `test_config.py:80` | `test_project_settings_override` | `project-model` | `deepseek-v4-pro` |
| 4 | `test_config.py:107` | `test_env_auc_config` | `from-env-file` | `deepseek-v4-pro` |
| 5 | `test_config.py:239` | `test_migrate_yaml_to_json` | `deepseek` (provider) | `anthropic` |
| 6 | `test_config.py:272` | `test_describe_config_layers_global_and_project` | `local` | `deepseek-v4-pro` |
| 7 | `test_web_api.py:366` | `test_model_settings_get_and_put` | `http://ailab.example/api` | `https://api.deepseek.com/anthropic` |
| 8 | `test_web_api.py:390` | `test_model_settings_normalizes_deepseek_base_url` | `https://api.deepseek.com/v1` | `https://api.deepseek.com/anthropic` |
| 9 | `test_web_model_settings.py:23` | `test_save_model_settings_writes_local_file` | `gpt-test` | `deepseek-v4-pro` |

---

## 修复方案

问题出在 `auc/config.py` 的 `load_model_config()` 函数中，环境变量（`ANTHROPIC_MODEL`、`ANTHROPIC_BASE_URL` 等）的优先级高于文件配置。需要两层修复：

1. **测试侧（快速修复）**：在 `conftest.py` 中添加 `autouse` fixture，在测试期间清除 `ANTHROPIC_*` 环境变量：
   ```python
   @pytest.fixture(autouse=True)
   def _clean_anthropic_env(monkeypatch):
       for k in os.environ:
           if k.startswith("ANTHROPIC_"):
               monkeypatch.delenv(k, raising=False)
   ```

2. **代码侧（更健壮）**：环境变量 `ANTHROPIC_MODEL` 等应由 Claude Code 运行时设置，而非系统级环境变量。如果这些变量必须存在，应在 `load_model_config()` 中明确其优先级语义，并让相关测试正确 mock 这些变量。

---

## 各模块测试分布

| 模块 | 测试文件 | 状态 |
|------|---------|------|
| Agent 核心 | `test_agent_cancel`, `test_autonomy`, `test_checkpoint`, `test_react_loop`, `test_work_mode` | 全部通过 |
| CLI | `test_cli`, `test_cli_jobs`, `test_cli_ui`, `test_cli_mcp`, `test_cli_receipt`, `test_cli_resume`, `test_cli_worktree`, `test_repl_scripted` | 全部通过 |
| 模型客户端 | `test_anthropic_client`, `test_openai_client`, `test_deepseek_anthropic`, `test_model_streaming` | 全部通过 |
| **配置** | **`test_config`** | **6 个失败** |
| Web API | `test_web_api`, `test_web_chat_stream`, `test_web_conversations`, `test_web_projects`, `test_web_terminal`, `test_web_upgrade`, `test_web_workspace` | 2 个失败, 其余通过 |
| Web 设置 | **`test_web_model_settings`** | **1 个失败** |
| 工具 | `test_git_tools`, `test_shell_tool`, `test_search_tools`, `test_todos_tool`, `test_mcp`, `test_fetch_url` | 全部通过 |
| 代码审查 | `test_review`, `test_code_review_fixes`, `test_code_review_p2` | 全部通过 |
| 其他 | `test_roles`, `test_rules`, `test_routines`, `test_skills`, `test_privilege`, `test_plan_mode`, `test_receipt`, `test_hooks`, `test_code_index`, `test_subagent`, `test_usage`, `test_version_check`, `test_vision_proxy`, `test_escalation`, `test_isolation`, `test_sandbox`, `test_editor_context`, `test_compactor`, `test_concurrency`, `test_documents`, `test_eval`, `test_evolution`, `test_evolution_loop`, `test_prompt_optimizer`, `test_property_random`, `test_qq_approval`, `test_telegram_approval`, `test_terminal`, `test_stream_display`, `test_diagrams`, `test_json_util`, `test_nuggets`, `test_slicer`, `test_decision_chain`, `test_dispatcher`, `test_decorator`, `test_config_init_deepseek_template`, `test_role_conversation`, `test_search_perf` | 全部通过 |

---

## 结论

项目核心功能（Agent 循环、CLI、Web API、工具系统、代码审查、角色系统等）全部测试通过。9 个失败测试是测试环境隔离不足导致的**假阳性**，不影响生产代码正确性。修复方式是在测试中屏蔽 `ANTHROPIC_*` 环境变量。
