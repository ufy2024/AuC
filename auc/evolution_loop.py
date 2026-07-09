"""R20 自动复盘 + R23 进化度量：把「被动 distill」升级为自动闭环。

- **R20 Retrospector**：Run 结束后自动复盘（零额外模型调用的启发式基线，可采样）：
  成功任务提取可复用路径（命令序列 + 关键决策），失败/取消任务自动归因（错误类型 +
  卡点 + 规避建议），写入当前角色 `evolution.yaml`（带 `run_id`、标签、置信度）。
- **R23 EvolutionMetrics**：`.auc/evolution-stats.json` 记录每条经验的
  `recall_count / adopted_count / linked_runs{success,fail}`；启发式「采纳」判定
  （召回条目关键词出现在本 Run 工具调用/输出中即记 adopted）；召回权重
  `×(1+log(1+adopted))`；零命中超 180 天降权、连续负收益（失败>成功）标记可归档。

安全底线：进化产物只影响提示/技能层，不绕过 L1-L3；自我修改类一律 L3 人审（见 R21/R22）。
零新增依赖。
"""

from __future__ import annotations

import copy
import json
import logging
import math
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auc.fslock import atomic_write_text, file_lock
from auc.messages import ChatMessage

logger = logging.getLogger("auc.evolution_loop")
_STALE_DAYS = 180
_TOKEN_RE = re.compile(r"[a-zA-Z_\-\u4e00-\u9fff]{3,}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── R20 复盘 ──
@dataclass
class RetroEntry:
    outcome: str  # success | failure | cancelled
    goal: str
    summary: str
    tags: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    error: str = ""
    confidence: float = 0.5
    run_id: str = ""


def _last_user_goal(messages: list[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "user" and m.content and not m.tool_call_id:
            return m.content.strip()
    return ""


def _collect_commands(messages: list[ChatMessage]) -> list[str]:
    cmds: list[str] = []
    for m in messages:
        for tc in m.tool_calls or []:
            if tc.name == "run_command":
                c = str((tc.arguments or {}).get("command") or "").strip()
                if c:
                    cmds.append(c)
    return cmds


def _last_assistant(messages: list[ChatMessage]) -> str:
    for m in reversed(messages):
        if m.role == "assistant" and m.content:
            return m.content.strip()
    return ""


def _tags(goal: str, tools: list[str]) -> list[str]:
    toks = [t.lower() for t in _TOKEN_RE.findall(goal)]
    toks.extend(t.lower() for t in tools)
    return list(dict.fromkeys(toks))[:10]


def build_retro_entry(
    *,
    status: str,
    messages: list[ChatMessage],
    run_id: str = "",
    error: str = "",
) -> RetroEntry | None:
    """从一次 Run 的消息与状态构建结构化复盘条目（启发式，无模型调用）。"""
    goal = _last_user_goal(messages)
    if not goal:
        return None
    tools = list(dict.fromkeys(m.name for m in messages if m.role == "tool" and m.name))
    commands = _collect_commands(messages)
    final = _last_assistant(messages)

    if status == "completed":
        outcome, confidence = "success", 0.7
        parts = [f"成功路径｜目标: {goal[:200]}"]
        if commands:
            parts.append("命令: " + " ; ".join(commands[:6]))
        elif tools:
            parts.append("工具: " + ", ".join(tools))
        if final:
            parts.append("结论: " + final[:200])
        summary = "\n".join(parts)
    elif status == "cancelled":
        outcome, confidence = "cancelled", 0.3
        summary = f"已取消｜目标: {goal[:200]}" + (f"\n卡点: {error[:200]}" if error else "")
    else:
        outcome, confidence = "failure", 0.5
        blocker = error or final or "未知错误"
        summary = (
            f"失败归因｜目标: {goal[:200]}\n错误: {blocker[:200]}\n"
            f"规避: 重试前先核对" + ("命令: " + commands[-1][:120] if commands else "上一步输入")
        )

    return RetroEntry(
        outcome=outcome,
        goal=goal,
        summary=summary,
        tags=_tags(goal, tools),
        commands=commands,
        error=error,
        confidence=confidence,
        run_id=run_id,
    )


class Retrospector:
    """复盘器：可采样；将复盘条目写入 memory（经其 save_lesson 入当前角色存储）。"""

    def __init__(self, *, sample_rate: float = 1.0, rng: random.Random | None = None) -> None:
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self._rng = rng or random.Random()

    def should_run(self) -> bool:
        if self.sample_rate >= 1.0:
            return True
        if self.sample_rate <= 0.0:
            return False
        return self._rng.random() < self.sample_rate

    def retrospect(
        self,
        *,
        status: str,
        messages: list[ChatMessage],
        run_id: str = "",
        error: str = "",
        memory: Any = None,
        agent_id: str | None = None,
    ) -> RetroEntry | None:
        if not self.should_run():
            return None
        entry = build_retro_entry(
            status=status, messages=messages, run_id=run_id, error=error
        )
        if entry is None:
            return None
        if memory is not None and hasattr(memory, "save_lesson"):
            tag_str = ",".join([*entry.tags, f"outcome:{entry.outcome}"])
            lesson = entry.summary + f"\n[run={entry.run_id} conf={entry.confidence:.2f}]"
            try:
                memory.save_lesson(tag_str, lesson, agent_id=agent_id)
            except TypeError:
                memory.save_lesson(tag_str, lesson)
            except Exception:  # noqa: BLE001 复盘不得影响主流程
                logger.debug("保存复盘 lesson 失败", exc_info=True)
        return entry


# ── R23 进化度量 ──
@dataclass
class EntryStat:
    id: str
    recall_count: int = 0
    adopted_count: int = 0
    success: int = 0
    fail: int = 0
    created_at: str = ""
    last_recall: str = ""

    @property
    def net(self) -> int:
        return self.success - self.fail

    def weight(self) -> float:
        return 1.0 + math.log(1.0 + self.adopted_count)


class EvolutionMetrics:
    """进化度量持久化到 `<sandbox>/.auc/evolution-stats.json`。"""

    def __init__(self, sandbox_root: str) -> None:
        self._path = Path(sandbox_root).resolve() / ".auc" / "evolution-stats.json"
        self.stats: dict[str, EntryStat] = {}
        self._baseline: dict[str, EntryStat] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def _lock_path(self) -> Path:
        return self._path.with_suffix(".json.lock")

    @staticmethod
    def _read_disk(path: Path) -> dict[str, EntryStat]:
        out: dict[str, EntryStat] = {}
        if not path.is_file():
            return out
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("进化度量加载失败，按空数据处理: %s", path, exc_info=True)
            return out
        fields = {f for f in EntryStat.__dataclass_fields__}  # type: ignore[attr-defined]
        for raw in data.get("entries", []):
            stat = EntryStat(**{k: v for k, v in raw.items() if k in fields})
            out[stat.id] = stat
        return out

    def _load(self) -> None:
        self.stats = self._read_disk(self._path)
        # 记录加载基线，save 时据此计算增量、合并到最新磁盘状态（防并发丢更新）。
        self._baseline = copy.deepcopy(self.stats)

    def save(self) -> None:
        """在跨进程锁下 re-read → 合并增量 → 原子写，避免并发写丢失计数更新。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._lock_path):
            merged = self._read_disk(self._path)
            for eid, cur in self.stats.items():
                base = self._baseline.get(eid)
                disk = merged.get(eid)
                if disk is None:
                    merged[eid] = copy.deepcopy(cur)
                    continue
                b = base or EntryStat(id=eid)
                # 计数字段：磁盘值 + 本会话增量（cur - baseline）
                disk.recall_count += cur.recall_count - b.recall_count
                disk.adopted_count += cur.adopted_count - b.adopted_count
                disk.success += cur.success - b.success
                disk.fail += cur.fail - b.fail
                # 时间戳取较新者
                if cur.last_recall and cur.last_recall > (disk.last_recall or ""):
                    disk.last_recall = cur.last_recall
                if not disk.created_at:
                    disk.created_at = cur.created_at
            data = {"version": 1, "entries": [asdict(s) for s in merged.values()]}
            atomic_write_text(
                self._path, json.dumps(data, ensure_ascii=False, indent=2)
            )
            # 写盘后同步内存与基线到合并结果，供后续继续累加。
            self.stats = merged
            self._baseline = copy.deepcopy(merged)

    def _get(self, entry_id: str) -> EntryStat:
        if entry_id not in self.stats:
            self.stats[entry_id] = EntryStat(id=entry_id, created_at=_now().isoformat())
        return self.stats[entry_id]

    def record_recall(self, entry_id: str) -> None:
        s = self._get(entry_id)
        s.recall_count += 1
        s.last_recall = _now().isoformat()

    def record_adoption(self, entry_id: str) -> None:
        self._get(entry_id).adopted_count += 1

    def record_link(self, entry_id: str, *, success: bool) -> None:
        s = self._get(entry_id)
        if success:
            s.success += 1
        else:
            s.fail += 1

    def weight(self, entry_id: str) -> float:
        return self.stats[entry_id].weight() if entry_id in self.stats else 1.0

    def is_stale(self, entry_id: str, *, now: datetime | None = None, days: int = _STALE_DAYS) -> bool:
        s = self.stats.get(entry_id)
        if s is None or not s.last_recall:
            return False
        try:
            last = datetime.fromisoformat(s.last_recall)
        except ValueError:
            return False
        return (now or _now()) - last > _timedelta_days(days)

    def archive_candidates(self, *, min_links: int = 3) -> list[str]:
        out = []
        for s in self.stats.values():
            if (s.success + s.fail) >= min_links and s.net < 0:
                out.append(s.id)
        return out

    def update_from_run(
        self,
        entries: list[tuple[str, list[str]]],
        run_text: str,
        *,
        success: bool,
    ) -> list[str]:
        """对 (entry_id, keywords) 列表做启发式召回/采纳记账，返回被采纳的 id。

        **召回（recall）与采纳（adoption）解耦**，避免二者同增导致晋升阈值形同虚设：

        - **召回**：任一 keyword（≥3 字）命中本 Run 文本（指令/工具/命令/输出）即视为
          该经验与本 Run *相关*——无论成败都记 recall + 成败链接。
        - **采纳**：更强信号——被召回**且本 Run 成功**，才视为该经验被*有效采纳*。

        如此 `adopted_count / recall_count` 便是「召回后成功率」，晋升阈值（≥0.5）
        才有实义（见 `skills.should_promote`）。
        """
        text = run_text.lower()
        adopted: list[str] = []
        changed = False
        for entry_id, keywords in entries:
            hit = any(
                kw and len(kw) >= 3 and kw.lower() in text for kw in keywords
            )
            if not hit:
                continue
            # 召回 + 成败链接：与成败无关，只要相关就记。
            self.record_recall(entry_id)
            self.record_link(entry_id, success=success)
            changed = True
            # 采纳：仅在本 Run 成功时计入，使召回≠采纳。
            if success:
                self.record_adoption(entry_id)
                adopted.append(entry_id)
        # 失败 Run 也更新了 recall/link，须一并落盘（不能仅在有采纳时保存）。
        if changed:
            self.save()
        return adopted

    def render(self) -> str:
        if not self.stats:
            return "进化度量：暂无数据"
        rows = sorted(self.stats.values(), key=lambda s: s.adopted_count, reverse=True)
        lines = [f"进化度量：共 {len(rows)} 条经验", ""]
        for s in rows:
            lines.append(
                f"{s.id}: 召回 {s.recall_count} · 采纳 {s.adopted_count} · "
                f"成/败 {s.success}/{s.fail} · 权重 {s.weight():.2f}"
            )
        archive = self.archive_candidates()
        if archive:
            lines.append("")
            lines.append(f"建议归档（连续负收益）: {', '.join(archive)}")
        return "\n".join(lines)


def _timedelta_days(days: int):  # noqa: ANN202
    from datetime import timedelta

    return timedelta(days=days)


def build_run_text(messages: list[ChatMessage]) -> str:
    """汇总一次 Run 的可匹配文本（用户/助手内容 + 工具名 + 命令）。"""
    parts: list[str] = []
    for m in messages:
        if m.content:
            parts.append(m.content)
        if m.role == "tool" and m.name:
            parts.append(m.name)
        for tc in m.tool_calls or []:
            parts.append(tc.name)
            cmd = (tc.arguments or {}).get("command")
            if cmd:
                parts.append(str(cmd))
    return "\n".join(parts)


def run_evolution_cycle(
    memory: Any,
    *,
    sandbox_root: str,
    status: str,
    messages: list[ChatMessage],
    run_id: str = "",
    agent_id: str | None = None,
    sample_rate: float = 1.0,
    retrospector: Retrospector | None = None,
    skill_store: Any = None,
) -> dict[str, Any]:
    """R20+R23(+R21) 闭环入口：复盘 + 度量 + 技能晋升草案。Run 结束后由 CLI/Web 调用。

    1) 对**既有**经验做采纳/成败记账（R23）；
    2) 满足阈值的经验自动起草技能草案（R21，仅草案，生效需 L3 人审）；
    3) 复盘本 Run 写入新经验（R20）。
    """
    summary: dict[str, Any] = {"adopted": [], "retro": None, "drafted": []}
    success = status == "completed"

    episodes_by_id: dict[str, Any] = {}
    pre_entries: list[tuple[str, list[str]]] = []
    if memory is not None and hasattr(memory, "snapshot_episodes"):
        try:
            for ep in memory.snapshot_episodes(agent_id):
                episodes_by_id[ep.id] = ep
                kws = list(ep.tags) + _TOKEN_RE.findall(ep.lesson)[:6]
                pre_entries.append((ep.id, kws))
        except Exception:  # noqa: BLE001
            logger.debug("快照 episodes 失败，跳过度量记账", exc_info=True)
            pre_entries = []

    if pre_entries:
        try:
            metrics = EvolutionMetrics(sandbox_root)
            run_text = build_run_text(messages)
            summary["adopted"] = metrics.update_from_run(
                pre_entries, run_text, success=success
            )
            if skill_store is not None:
                summary["drafted"] = _draft_promotions(
                    metrics, skill_store, episodes_by_id
                )
        except Exception:  # noqa: BLE001 度量失败不影响主流程
            logger.debug("进化度量更新/技能起草失败", exc_info=True)

    retro = (retrospector or Retrospector(sample_rate=sample_rate)).retrospect(
        status=status,
        messages=messages,
        run_id=run_id,
        agent_id=agent_id,
        memory=memory,
    )
    if retro is not None:
        summary["retro"] = retro.outcome
    return summary


def _draft_promotions(
    metrics: "EvolutionMetrics", skill_store: Any, episodes_by_id: dict[str, Any]
) -> list[str]:
    """R21：对满足阈值且尚无技能/草案的经验，自动起草技能草案。"""
    from auc.skills import promotion_candidates

    drafted: list[str] = []
    for entry_id in promotion_candidates(metrics):
        ep = episodes_by_id.get(entry_id)
        if ep is None:
            continue
        goal = (ep.lesson.splitlines()[0] if ep.lesson else entry_id)[:80]
        try:
            if skill_store.get(_skill_name(goal, entry_id)) is not None:
                continue
            if skill_store.get(_skill_name(goal, entry_id), draft=True) is not None:
                continue
            skill_store.draft_from_episode(
                episode_id=entry_id,
                goal=goal,
                tags=list(ep.tags),
                lesson=ep.lesson,
            )
            drafted.append(entry_id)
        except Exception:  # noqa: BLE001 起草失败不影响主流程
            logger.debug("技能草案起草失败: %s", entry_id, exc_info=True)
            continue
    return drafted


def _skill_name(goal: str, entry_id: str) -> str:
    from auc.skills import slugify

    return slugify(goal or entry_id)
