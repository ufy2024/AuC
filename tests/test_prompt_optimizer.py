from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from auc.prompt_optimizer import (
    EvalComparison,
    PromptOptimizer,
    heuristic_proposer,
    load_active_overlay,
)


@dataclass
class _Ep:
    tags: list[str] = field(default_factory=list)
    lesson: str = ""


class _Mem:
    def __init__(self, episodes):
        self._eps = episodes

    def snapshot_episodes(self, agent_id=None):
        return self._eps


def _mem():
    return _Mem(
        [
            _Ep(
                tags=["outcome:failure"],
                lesson="失败归因：xxx\n规避：先跑测试再提交\n无关行",
            ),
            _Ep(tags=["outcome:success"], lesson="一切正常"),
        ]
    )


# ── 启发式提议器 ──
def test_heuristic_proposer_builds_overlay():
    rationale, content, based_on = heuristic_proposer(
        ["规避：先跑测试", "规避：先跑测试", "错误：忘记 import"], ["case-a"]
    )
    assert "经验规约" in content
    assert "先跑测试" in content
    assert "case-a" in content
    # 去重：两条相同的规避只保留一条
    assert content.count("规避：先跑测试") == 1
    assert based_on


# ── collect_avoidances ──
def test_collect_avoidances(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    av = opt.collect_avoidances(_mem(), agent_id="chat:default")
    assert any("先跑测试" in a for a in av)
    assert all("无关行" not in a for a in av)


def test_collect_avoidances_no_memory(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    assert opt.collect_avoidances(None) == []


# ── propose ──
def test_propose_writes_draft(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    draft = opt.propose(memory=_mem(), agent_id="chat:default", eval_failures=["c1"])
    assert opt._draft_md(draft.id).is_file()
    assert opt._draft_md(draft.id).with_suffix(".json").is_file()
    assert "先跑测试" in draft.content
    listed = opt.list_drafts()
    assert any(d.id == draft.id for d in listed)
    assert opt.read_draft(draft.id) is not None
    assert opt.read_draft("nope") is None


# ── eval（防退化闸门）──
def test_eval_draft_no_regression(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    draft = opt.propose(memory=_mem())

    class _Rep:
        pass_rate = 1.0
        total = 3

    cmp = opt.eval_draft(draft.id, suite_runner=lambda: _Rep())
    assert cmp is not None
    assert cmp.ok
    assert not cmp.regressed
    assert cmp.before_pass_rate == cmp.after_pass_rate


def test_eval_draft_missing(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    assert opt.eval_draft("missing", suite_runner=lambda: None) is None


def test_eval_comparison_regressed():
    c = EvalComparison(before_pass_rate=1.0, after_pass_rate=0.5, total=2)
    assert c.regressed
    assert not c.ok


# ── apply / revert（L3 人审）──
def test_apply_requires_approval(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    draft = opt.propose(memory=_mem())
    with pytest.raises(PermissionError):
        opt.apply(draft.id, approved=False)


def test_apply_and_overlay_and_revert(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    d1 = opt.propose(memory=_mem())
    path = opt.apply(d1.id, approved=True)
    assert path is not None and path.is_file()
    # 生效：load_active_overlay 读得到内容
    assert "经验规约" in load_active_overlay(str(tmp_path))
    # 草案已落地移除
    assert not opt._draft_md(d1.id).is_file()

    # 第二次 apply 归档旧版到 history
    d2 = opt.propose(memory=_Mem([_Ep(tags=["outcome:failure"], lesson="规避：第二条")]))
    opt.apply(d2.id, approved=True)
    assert "第二条" in opt.active_overlay()
    assert list(opt.history_dir.glob("*.md"))

    # revert 回退到上一个版本
    assert opt.revert() is True
    assert "第二条" not in opt.active_overlay()


def test_revert_removes_when_no_history(tmp_path):
    opt = PromptOptimizer(str(tmp_path))
    d1 = opt.propose(memory=_mem())
    opt.apply(d1.id, approved=True)
    assert opt.active_path.is_file()
    assert opt.revert() is True
    assert not opt.active_path.is_file()
    assert opt.revert() is False


def test_load_active_overlay_empty(tmp_path):
    assert load_active_overlay(str(tmp_path)) == ""


# ── CLI ──
def test_cli_evolve_propose_and_drafts(tmp_path, capsys):
    from auc.cli import main

    code = main(["evolve", "propose", "--sandbox", str(tmp_path)])
    assert code == 0
    assert "已生成草案" in capsys.readouterr().out
    code = main(["evolve", "drafts", "--sandbox", str(tmp_path), "--json"])
    assert code == 0
    import json as _json

    data = _json.loads(capsys.readouterr().out)
    assert data and "id" in data[0]


def test_cli_evolve_apply_requires_yes_then_applies(tmp_path, capsys):
    from auc.cli import main

    main(["evolve", "propose", "--sandbox", str(tmp_path), "--json"])
    import json as _json

    draft_id = _json.loads(capsys.readouterr().out)["id"]

    # 无 --yes：返回 2，提示需人审
    code = main(["evolve", "apply", draft_id, "--sandbox", str(tmp_path)])
    assert code == 2

    # 带 --yes：落盘生效
    code = main(["evolve", "apply", draft_id, "--sandbox", str(tmp_path), "--yes"])
    assert code == 0
    assert "已落盘生效" in capsys.readouterr().out
    assert load_active_overlay(str(tmp_path))

    # revert 回退
    code = main(["evolve", "revert", "--sandbox", str(tmp_path)])
    assert code == 0


def test_cli_evolve_eval(tmp_path, capsys):
    from auc.cli import main

    main(["evolve", "propose", "--sandbox", str(tmp_path), "--json"])
    import json as _json

    draft_id = _json.loads(capsys.readouterr().out)["id"]
    code = main(["evolve", "eval", draft_id, "--sandbox", str(tmp_path), "--json"])
    assert code == 0
    data = _json.loads(capsys.readouterr().out)
    assert data["ok"] is True
