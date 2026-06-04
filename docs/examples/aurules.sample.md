# `.aurules` 示例（复制到项目根并重命名为 `.aurules`）

```markdown
---
version: 1
project: quant-agent
tool_policy:
  git_push: L3
  live_trading_api: L3
  docker_build: L2
sandbox_root: /workspace
---

## Build Commands
- Development: `npm run dev`
- Production Build: `docker build -t quant-agent:v1 .`

## Test Commands
- Critical Path: `pytest tests/test_risk_manager.py`

## Code Style
- Strict type hinting required for all Python code.
- Never hardcode OKX/Binance API keys; use environment variables.

## Specialist Notes
- Prefer AuM-delivered ContextPackage for code edits; do not scan entire repo.
```

参见 [aurules.md](../aurules.md)。
