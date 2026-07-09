"""R6 自治级别：三级 × 四类工具 12 格矩阵全断言。"""

from auc.policy.autonomy import AutonomyPolicy, normalize_autonomy
from auc.tools.base import ToolPolicy

L1 = ToolPolicy(name="read_file", privilege="L1")
L2_FILES = ToolPolicy(name="write_file", privilege="L2", mutates_files=True)
L2_STATE = ToolPolicy(name="run_command", privilege="L2", mutates_state=True)
L3 = ToolPolicy(name="fetch_url", privilege="L3")

# (级别, 工具) -> 是否需要审批
MATRIX = {
    ("confirm-all", "L1"): False,
    ("confirm-all", "L2f"): True,
    ("confirm-all", "L2s"): True,
    ("confirm-all", "L3"): True,
    ("auto-edit", "L1"): False,
    ("auto-edit", "L2f"): False,
    ("auto-edit", "L2s"): True,
    ("auto-edit", "L3"): True,
    ("full-auto", "L1"): False,
    ("full-auto", "L2f"): False,
    ("full-auto", "L2s"): False,
    ("full-auto", "L3"): True,  # L3 行硬编码，永不放宽
}

POLICIES = {"L1": L1, "L2f": L2_FILES, "L2s": L2_STATE, "L3": L3}


def test_full_matrix() -> None:
    for (level, kind), expected in MATRIX.items():
        policy = AutonomyPolicy(level=level)  # type: ignore[arg-type]
        assert policy.requires_approval(POLICIES[kind]) is expected, (level, kind)


def test_normalize() -> None:
    assert normalize_autonomy("full-auto") == "full-auto"
    assert normalize_autonomy("CONFIRM-ALL") == "confirm-all"
    assert normalize_autonomy(None) == "auto-edit"
    assert normalize_autonomy("bogus") == "auto-edit"


def test_plain_l2_tool_never_blocked() -> None:
    plain = ToolPolicy(name="echo", privilege="L2")
    for level in ("confirm-all", "auto-edit", "full-auto"):
        assert not AutonomyPolicy(level=level).requires_approval(plain)  # type: ignore[arg-type]


def test_auto_approve_skips_all() -> None:
    pol = AutonomyPolicy(level="full-auto", auto_approve=True)
    assert pol.skips_all_approval()
    assert not pol.requires_approval(L3)
