from __future__ import annotations

import json

from auc.cli import main
from auc.evolution_loop import run_evolution_cycle
from auc.messages import ChatMessage
from auc.skills import (
    Skill,
    SkillStore,
    matched_skill_messages,
    parse_skill_md,
    promotion_candidates,
    should_promote,
    slugify,
)

SAMPLE = """---
name: fix-mermaid-gantt
description: 修复 Mermaid gantt 语法
triggers: ["mermaid", "gantt", "甘特图"]
source: manual
---
# 操作步骤
1. 为 title 加双引号
2. 校验渲染
"""


def test_slugify():
    assert slugify("Fix Mermaid Gantt!") == "fix-mermaid-gantt"
    assert slugify("") == "skill"


def test_parse_skill_md():
    sk = parse_skill_md(SAMPLE, path="/x/SKILL.md")
    assert sk is not None
    assert sk.name == "fix-mermaid-gantt"
    assert "mermaid" in sk.triggers
    assert "操作步骤" in sk.body


def test_parse_skill_md_invalid():
    assert parse_skill_md("no frontmatter") is None
    assert parse_skill_md("---\ndescription: x\n---\nbody") is None  # 缺 name


def test_render_roundtrip():
    sk = parse_skill_md(SAMPLE)
    again = parse_skill_md(sk.render_md())
    assert again.name == sk.name
    assert again.triggers == sk.triggers


def test_store_write_list_match(tmp_path):
    store = SkillStore(str(tmp_path))
    sk = parse_skill_md(SAMPLE)
    store.write(sk, draft=False)

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].name == "fix-mermaid-gantt"

    matched = store.match("我的 mermaid 甘特图 渲染失败了")
    assert len(matched) == 1
    assert matched[0].name == "fix-mermaid-gantt"

    # 不命中
    assert store.match("kubernetes helm") == []


def test_store_drafts_and_promote(tmp_path):
    store = SkillStore(str(tmp_path))
    draft = Skill(name="my-skill", description="d", triggers=["foo"], body="step")
    store.write(draft, draft=True)

    assert store.list() == []  # 草案不在正式列表
    assert len(store.list(include_drafts=True)) == 1

    promoted = store.promote("my-skill")
    assert promoted is not None
    assert promoted.draft is False
    assert promoted.source == "promoted"
    assert len(store.list()) == 1
    assert store.get("my-skill", draft=True) is None  # 草案已移除


def test_store_promote_missing(tmp_path):
    store = SkillStore(str(tmp_path))
    assert store.promote("nope") is None


def test_store_remove(tmp_path):
    store = SkillStore(str(tmp_path))
    store.write(parse_skill_md(SAMPLE), draft=False)
    assert store.remove("fix-mermaid-gantt") is True
    assert store.list() == []
    assert store.remove("fix-mermaid-gantt") is False


def test_draft_from_episode(tmp_path):
    store = SkillStore(str(tmp_path))
    sk = store.draft_from_episode(
        episode_id="ep-1",
        goal="修复 gantt 语法",
        tags=["gantt", "mermaid"],
        lesson="给 title 加引号",
        commands=["mermaid parse x"],
    )
    assert sk.draft is True
    assert sk.promoted_from == "ep-1"
    assert store.get(sk.name, draft=True) is not None
    assert "mermaid parse x" in sk.body


def test_matched_skill_messages(tmp_path):
    store = SkillStore(str(tmp_path))
    store.write(parse_skill_md(SAMPLE), draft=False)
    msgs = matched_skill_messages(store, "mermaid gantt 出错")
    assert len(msgs) == 1
    assert msgs[0].role == "system"
    assert "技能·fix-mermaid-gantt" in msgs[0].content


def test_should_promote_threshold():
    assert should_promote(recall_count=3, adopted_count=2) is True
    assert should_promote(recall_count=2, adopted_count=2) is False
    assert should_promote(recall_count=4, adopted_count=1) is False


class _Ep:
    def __init__(self, id, tags, lesson):
        self.id = id
        self.tags = tags
        self.lesson = lesson


class FakeMemory:
    def __init__(self, episodes):
        self._eps = episodes
        self.saved = []

    def snapshot_episodes(self, agent_id=None):
        return self._eps

    def save_lesson(self, tags, lesson, *, agent_id=None):
        self.saved.append((tags, lesson))
        return "ok"


def test_promotion_candidates_and_autodraft(tmp_path):
    # 预置度量：让 ep-1 满足阈值（先跑两次采纳 + 手动拉满）
    from auc.evolution_loop import EvolutionMetrics

    m = EvolutionMetrics(str(tmp_path))
    for _ in range(3):
        m.record_recall("ep-1")
        m.record_adoption("ep-1")
    m.save()
    assert "ep-1" in promotion_candidates(m)

    store = SkillStore(str(tmp_path))
    mem = FakeMemory([_Ep("ep-1", ["gantt", "mermaid"], "修复 gantt：title 加引号")])

    # 跑一次命中 ep-1 的 Run，触发自动起草草案
    msgs = [
        ChatMessage(role="user", content="再次修复 gantt mermaid 图"),
        ChatMessage(role="assistant", content="完成"),
    ]
    summary = run_evolution_cycle(
        mem,
        sandbox_root=str(tmp_path),
        status="completed",
        messages=msgs,
        run_id="r1",
        agent_id="chat:default",
        skill_store=store,
    )
    assert "ep-1" in summary["drafted"]
    drafts = store.list(include_drafts=True)
    assert any(d.draft and d.promoted_from == "ep-1" for d in drafts)


def test_cli_skills_list_empty(tmp_path, capsys):
    code = main(["skills", "list", "--sandbox", str(tmp_path)])
    assert code == 0


def test_cli_skills_flow(tmp_path, capsys):
    store = SkillStore(str(tmp_path))
    store.write(Skill(name="s1", description="d", triggers=["t"], body="b"), draft=True)

    # promote then show then remove
    assert main(["skills", "promote", "s1", "--sandbox", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["skills", "list", "--sandbox", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["name"] == "s1"
    assert main(["skills", "show", "s1", "--sandbox", str(tmp_path)]) == 0
    assert main(["skills", "remove", "s1", "--sandbox", str(tmp_path)]) == 0
