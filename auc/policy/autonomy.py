"""R6 会话级授权模式：confirm-all / auto-edit / full-auto + auto_approve。

用户可见四档命名与裁决矩阵见 docs/approval-modes.md。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from auc.tools.base import ToolPolicy
from auc.types import AutonomyLevel

AUTONOMY_LEVELS: tuple[AutonomyLevel, ...] = ("confirm-all", "auto-edit", "full-auto")
DEFAULT_AUTONOMY: AutonomyLevel = "auto-edit"

ApprovalModeId = Literal[
    "ask-every-write", "ask-on-state", "ask-on-danger", "auto-approve"
]
DEFAULT_APPROVAL_MODE: ApprovalModeId = "ask-on-state"

_LOCAL_BIND_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})


@dataclass(frozen=True)
class ApprovalModeSpec:
    id: ApprovalModeId
    label_zh: str
    label_en: str
    hint_zh: str
    hint_en: str
    autonomy: AutonomyLevel
    auto_approve: bool


APPROVAL_MODE_SPECS: tuple[ApprovalModeSpec, ...] = (
    ApprovalModeSpec(
        id="ask-every-write",
        label_zh="每次都询问",
        label_en="Ask every write",
        hint_zh="写文件与执行命令前均需确认",
        hint_en="Confirm all file writes and commands",
        autonomy="confirm-all",
        auto_approve=False,
    ),
    ApprovalModeSpec(
        id="ask-on-state",
        label_zh="改状态时询问",
        label_en="Ask on state change",
        hint_zh="写文件自动；执行命令与高危操作需确认（推荐）",
        hint_en="Auto file edits; confirm commands and high-risk ops",
        autonomy="auto-edit",
        auto_approve=False,
    ),
    ApprovalModeSpec(
        id="ask-on-danger",
        label_zh="危险时询问",
        label_en="Ask on danger only",
        hint_zh="仅外链访问、git push 等高危操作需确认",
        hint_en="Confirm URLs, git push, and escalated commands only",
        autonomy="full-auto",
        auto_approve=False,
    ),
    ApprovalModeSpec(
        id="auto-approve",
        label_zh="全部通过（仅本地）",
        label_en="Auto-approve all (local)",
        hint_zh="含外链与 git push；仅限 127.0.0.1 本地绑定",
        hint_en="Includes URLs and git push; localhost bind only",
        autonomy="full-auto",
        auto_approve=True,
    ),
)

_MODE_BY_ID = {s.id: s for s in APPROVAL_MODE_SPECS}
_AUTONOMY_TO_MODE = {s.autonomy: s.id for s in APPROVAL_MODE_SPECS if not s.auto_approve}
_AUTONOMY_TO_MODE["full-auto"] = "ask-on-danger"


def normalize_autonomy(value: str | None) -> AutonomyLevel:
    v = (value or "").strip().lower()
    if v in AUTONOMY_LEVELS:
        return v  # type: ignore[return-value]
    return DEFAULT_AUTONOMY


def normalize_approval_mode(value: str | None) -> ApprovalModeId:
    v = (value or "").strip().lower()
    if v in _MODE_BY_ID:
        return v  # type: ignore[return-value]
    return DEFAULT_APPROVAL_MODE


def auto_approve_permitted(bind_host: str | None) -> bool:
    return (bind_host or "").strip().lower() in _LOCAL_BIND_HOSTS


def approval_mode_spec(mode_id: str | None) -> ApprovalModeSpec:
    return _MODE_BY_ID.get(normalize_approval_mode(mode_id), _MODE_BY_ID[DEFAULT_APPROVAL_MODE])


def approval_modes_payload(*, locale: str = "zh") -> list[dict[str, str]]:
    en = locale.lower().startswith("en")
    out: list[dict[str, str]] = []
    for spec in APPROVAL_MODE_SPECS:
        out.append(
            {
                "id": spec.id,
                "label": spec.label_en if en else spec.label_zh,
                "hint": spec.hint_en if en else spec.hint_zh,
                "autonomy": spec.autonomy,
                "auto_approve": str(spec.auto_approve).lower(),
            }
        )
    return out


@dataclass(frozen=True)
class ApprovalPrefs:
    mode_id: ApprovalModeId
    autonomy: AutonomyLevel
    auto_approve: bool


def resolve_approval_prefs(
    settings: dict[str, Any] | None,
    *,
    bind_host: str | None = None,
    mode_override: str | None = None,
    autonomy_override: str | None = None,
    auto_approve_override: bool | None = None,
) -> ApprovalPrefs:
    """从 settings 与可选覆盖项解析有效授权偏好。"""
    data = settings or {}
    approval = data.get("approval") if isinstance(data.get("approval"), dict) else {}

    if mode_override:
        spec = approval_mode_spec(mode_override)
    elif isinstance(approval.get("mode"), str):
        spec = approval_mode_spec(str(approval["mode"]))
    else:
        autonomy = normalize_autonomy(autonomy_override or str(data.get("autonomy") or ""))
        auto_flag = bool(approval.get("auto_approve"))
        if autonomy == "full-auto" and auto_flag:
            spec = _MODE_BY_ID["auto-approve"]
        else:
            spec = approval_mode_spec(_AUTONOMY_TO_MODE.get(autonomy, DEFAULT_APPROVAL_MODE))

    auto_approve = spec.auto_approve
    if auto_approve_override is not None:
        auto_approve = bool(auto_approve_override)
        if auto_approve:
            spec = _MODE_BY_ID["auto-approve"]
        elif spec.id == "auto-approve":
            spec = _MODE_BY_ID["ask-on-danger"]

    if autonomy_override and not mode_override:
        autonomy = normalize_autonomy(autonomy_override)
        if autonomy != spec.autonomy and not auto_approve:
            spec = approval_mode_spec(_AUTONOMY_TO_MODE.get(autonomy, DEFAULT_APPROVAL_MODE))
            auto_approve = spec.auto_approve

    if auto_approve and not auto_approve_permitted(bind_host):
        spec = _MODE_BY_ID["ask-on-danger"]
        auto_approve = False

    return ApprovalPrefs(
        mode_id=spec.id,
        autonomy=spec.autonomy,
        auto_approve=auto_approve,
    )


@dataclass
class AutonomyPolicy:
    level: AutonomyLevel = DEFAULT_AUTONOMY
    auto_approve: bool = False

    def skips_all_approval(self) -> bool:
        return self.auto_approve and self.level == "full-auto"

    def requires_approval(self, policy: ToolPolicy) -> bool:
        if self.skips_all_approval():
            return False
        if policy.privilege == "L3":
            return True  # 硬规则，永不放宽（auto_approve 走 skips_all_approval）
        if policy.privilege == "L1":
            return False
        if self.level == "confirm-all":
            return policy.mutates_files or policy.mutates_state
        if self.level == "auto-edit":
            return policy.mutates_state
        return False  # full-auto：L2 均放行

    def describe(self, policy: ToolPolicy) -> str:
        if policy.mutates_files:
            kind = "写文件"
        elif policy.mutates_state:
            kind = "改变系统状态"
        else:
            kind = policy.privilege
        return f"授权模式 {self.level}：{kind} 操作需确认"
