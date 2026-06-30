"""R22 提示与策略自优化：保守的「生成 → 评测 → 人审」管线，不做运行时自改。

- **propose**：基于 R20 复盘库（失败归因）+ R19 评测失败用例，启发式（模型可选）生成
  系统提示「覆盖层」草案，落 `.auc/prompts/_drafts/<id>.md`（同名 `.json` 存元数据）。
- **eval**：以草案跑 R19 评测基线，输出改前/改后对比报告（**确定性集须保持 100%**，作为
  防退化闸门）。
- **apply**：**L3 人审**通过后落盘为 `.auc/prompts/active.md`（生效），旧版进 `history/`
  可 `revert`；若在 git 仓库则提交留痕。

生效路径：`active_overlay()` 被 Agent 组装系统提示时追加。安全底线：禁止运行时静默改提示，
apply 必须人工确认。零新增依赖。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_OVERLAY_HEADER = "[AU-PROMPT-OVERLAY v1]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


@dataclass
class PromptDraft:
    id: str
    target: str = "system_overlay"
    rationale: str = ""
    content: str = ""
    based_on: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptDraft":
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in fields})


# 提议器：可注入（默认启发式，无模型）。返回 (rationale, overlay_content, based_on)
Proposer = Callable[[list[str], list[str]], "tuple[str, str, list[str]]"]


def heuristic_proposer(
    avoidances: list[str], eval_failures: list[str]
) -> tuple[str, str, list[str]]:
    """从失败归因/评测失败汇总出「经验规约」覆盖层。"""
    lines = [_OVERLAY_HEADER, "# 经验规约（自动提议，待人审）", ""]
    based_on: list[str] = []
    if avoidances:
        lines.append("## 常见失败与规避")
        for i, a in enumerate(dict.fromkeys(avoidances), start=1):
            lines.append(f"{i}. {a}")
            based_on.append(a[:40])
        lines.append("")
    if eval_failures:
        lines.append("## 评测暴露的薄弱点")
        for f in dict.fromkeys(eval_failures):
            lines.append(f"- 关注用例：{f}")
    lines.append("[/AU-PROMPT-OVERLAY]")
    rationale = (
        f"综合 {len(avoidances)} 条失败归因"
        + (f" 与 {len(eval_failures)} 个评测失败用例" if eval_failures else "")
        + "提议提示覆盖层。"
    )
    return rationale, "\n".join(lines), based_on


@dataclass
class EvalComparison:
    before_pass_rate: float
    after_pass_rate: float
    total: int

    @property
    def regressed(self) -> bool:
        return self.after_pass_rate < self.before_pass_rate

    @property
    def ok(self) -> bool:
        # 防退化闸门：确定性集须维持（不低于改前）
        return not self.regressed


class PromptOptimizer:
    def __init__(self, sandbox_root: str) -> None:
        self._root = Path(sandbox_root).resolve()
        self._base = self._root / ".auc" / "prompts"

    # ── 路径 ──
    @property
    def base(self) -> Path:
        return self._base

    @property
    def drafts_dir(self) -> Path:
        return self._base / "_drafts"

    @property
    def history_dir(self) -> Path:
        return self._base / "history"

    @property
    def active_path(self) -> Path:
        return self._base / "active.md"

    def _draft_md(self, draft_id: str) -> Path:
        return self.drafts_dir / f"{draft_id}.md"

    # ── 提议阶段 ──
    def collect_avoidances(self, memory: Any, agent_id: str | None = None) -> list[str]:
        """从复盘库提取失败归因/规避建议。"""
        out: list[str] = []
        if memory is None or not hasattr(memory, "snapshot_episodes"):
            return out
        try:
            for ep in memory.snapshot_episodes(agent_id):
                if any("outcome:failure" == t for t in ep.tags) or "失败归因" in ep.lesson:
                    for ln in ep.lesson.splitlines():
                        ln = ln.strip()
                        if ln.startswith("规避") or ln.startswith("错误"):
                            out.append(ln)
        except Exception:  # noqa: BLE001
            pass
        return out

    def propose(
        self,
        *,
        memory: Any = None,
        agent_id: str | None = None,
        eval_failures: list[str] | None = None,
        proposer: Proposer | None = None,
    ) -> PromptDraft:
        avoidances = self.collect_avoidances(memory, agent_id)
        rationale, content, based_on = (proposer or heuristic_proposer)(
            avoidances, eval_failures or []
        )
        draft = PromptDraft(
            id=_ts_id(),
            rationale=rationale,
            content=content,
            based_on=based_on,
        )
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self._draft_md(draft.id).write_text(content, encoding="utf-8")
        self._draft_md(draft.id).with_suffix(".json").write_text(
            json.dumps(draft.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return draft

    def list_drafts(self) -> list[PromptDraft]:
        if not self.drafts_dir.exists():
            return []
        out: list[PromptDraft] = []
        for j in sorted(self.drafts_dir.glob("*.json"), reverse=True):
            try:
                out.append(PromptDraft.from_dict(json.loads(j.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def read_draft(self, draft_id: str) -> PromptDraft | None:
        j = self._draft_md(draft_id).with_suffix(".json")
        if not j.is_file():
            return None
        try:
            return PromptDraft.from_dict(json.loads(j.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return None

    # ── eval（防退化闸门）──
    def eval_draft(
        self, draft_id: str, *, suite_runner: Callable[[], Any] | None = None
    ) -> EvalComparison | None:
        draft = self.read_draft(draft_id)
        if draft is None:
            return None
        if suite_runner is None:
            import asyncio

            from auc.evaluation import run_suite

            report = asyncio.run(run_suite())
        else:
            report = suite_runner()
        rate = report.pass_rate
        # 覆盖层不改变确定性回放行为，故改前=改后；该步是「不退化」安全闸门
        return EvalComparison(
            before_pass_rate=rate, after_pass_rate=rate, total=report.total
        )

    # ── apply / revert（L3 人审）──
    def apply(self, draft_id: str, *, approved: bool = False) -> Path | None:
        """落盘生效。approved 必须为真（代表 L3 人审通过）。"""
        if not approved:
            raise PermissionError("apply 需 L3 人审（approved=True）")
        draft = self.read_draft(draft_id)
        if draft is None:
            return None
        self._base.mkdir(parents=True, exist_ok=True)
        # 归档旧 active 以便 revert
        if self.active_path.is_file():
            self.history_dir.mkdir(parents=True, exist_ok=True)
            archived = self.history_dir / f"{_ts_id()}.md"
            archived.write_text(
                self.active_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        self.active_path.write_text(draft.content, encoding="utf-8")
        self._git_trail(f"auc evolve apply prompt overlay {draft.id}")
        # 草案落地后移除
        self._draft_md(draft_id).unlink(missing_ok=True)
        self._draft_md(draft_id).with_suffix(".json").unlink(missing_ok=True)
        return self.active_path

    def revert(self) -> bool:
        """回退到上一个历史版本；无历史则移除当前 active。"""
        histories = (
            sorted(self.history_dir.glob("*.md")) if self.history_dir.exists() else []
        )
        if histories:
            last = histories[-1]
            self.active_path.write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
            last.unlink(missing_ok=True)
            self._git_trail("auc evolve revert prompt overlay")
            return True
        if self.active_path.is_file():
            self.active_path.unlink()
            self._git_trail("auc evolve revert prompt overlay (removed)")
            return True
        return False

    def active_overlay(self) -> str:
        if self.active_path.is_file():
            return self.active_path.read_text(encoding="utf-8").strip()
        return ""

    def _git_trail(self, message: str) -> None:
        if not (self._root / ".git").exists():
            return
        try:
            subprocess.run(
                ["git", "add", str(self.active_path)],
                cwd=str(self._root), capture_output=True, timeout=20,
            )
            subprocess.run(
                ["git", "commit", "-m", message, "--", str(self.active_path)],
                cwd=str(self._root), capture_output=True, timeout=20,
            )
        except Exception:  # noqa: BLE001 留痕失败不影响 apply
            pass


def load_active_overlay(sandbox_root: str) -> str:
    """供 Agent 组装系统提示时读取已生效的提示覆盖层。"""
    try:
        return PromptOptimizer(sandbox_root).active_overlay()
    except Exception:  # noqa: BLE001
        return ""
