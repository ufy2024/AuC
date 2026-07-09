from __future__ import annotations

from auc.skills import (
    SkillPrefs,
    SkillStore,
    bundled_skills_root,
    iter_bundled_skill_files,
    matched_skill_messages,
    skill_matches_role,
)
from auc.web.skill_settings import load_skill_prefs, save_skill_prefs


def test_iter_bundled_skill_files_includes_anbeime() -> None:
    files = iter_bundled_skill_files()
    assert len(files) >= 350
    paths = {str(p) for p in files}
    assert any("frontend-design" in p for p in paths)


def test_bundled_anbeime_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    skills = store.list()
    assert len(skills) >= 60
    fe = store.get("frontend-design")
    assert fe is not None
    assert fe.division == "design"
    assert "anbeime/skill" in fe.source_url
    assert fe.triggers


def test_anbeime_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_anbeime_manifest.json"
    assert manifest.is_file()


def test_anthropics_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    assert store.get("docx") is not None
    assert store.get("pdf") is not None
    assert store.get("mcp-builder") is not None
    docx = store.get("docx")
    assert docx is not None
    assert "anthropics/skills" in docx.source_url
    assert "docx" in docx.triggers or "word" in " ".join(docx.triggers).lower()


def test_anthropics_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_anthropics_manifest.json"
    assert manifest.is_file()


def test_mattpocock_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    assert store.get("tdd") is not None
    tdd = store.get("tdd")
    assert tdd is not None
    assert "mattpocock/skills" in tdd.source_url
    assert tdd.division == "engineering"
    assert store.get("code-review") is not None


def test_mattpocock_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_mattpocock_manifest.json"
    assert manifest.is_file()


def test_superpowers_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    assert store.get("brainstorming") is not None
    bs = store.get("brainstorming")
    assert bs is not None
    assert "obra/superpowers" in bs.source_url
    assert store.get("systematic-debugging") is not None
    assert store.get("test-driven-development") is not None


def test_superpowers_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_superpowers_manifest.json"
    assert manifest.is_file()


def test_ecc_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    skills = store.list()
    ecc = [s for s in skills if "affaan-m/ECC" in s.source_url]
    assert len(ecc) >= 200
    cs = store.get("coding-standards")
    assert cs is not None
    assert "affaan-m/ECC" in cs.source_url
    sr = store.get("security-review")
    assert sr is not None


def test_ecc_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_ecc_manifest.json"
    assert manifest.is_file()
    assert manifest.stat().st_size > 100


def test_karpathy_skills_loaded() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    sk = store.get("karpathy-guidelines")
    assert sk is not None
    assert "multica-ai/andrej-karpathy-skills" in sk.source_url
    assert sk.division == "engineering"
    assert "coder" in sk.roles
    matched = store.match("llm coding mistakes when writing code", role_id="coder")
    assert any(s.name == "karpathy-guidelines" for s in matched)


def test_karpathy_manifest_exists() -> None:
    manifest = bundled_skills_root() / "_karpathy_manifest.json"
    assert manifest.is_file()


def test_bundled_ui_ux_pro_max_loaded() -> None:
    root = bundled_skills_root()
    assert (root / "ui-ux-pro-max" / "SKILL.md").is_file()
    store = SkillStore("/tmp/unused-sandbox")
    skills = store.list()
    names = {s.name for s in skills}
    assert "ui-ux-pro-max" in names
    sk = store.get("ui-ux-pro-max")
    assert sk is not None
    assert sk.builtin is True
    assert sk.division == "design"
    assert "engineering-frontend-developer" in sk.roles
    assert sk.source_url.startswith("https://github.com/")


def test_skill_match_respects_role() -> None:
    store = SkillStore("/tmp/unused-sandbox")
    matched = store.match("请优化 landing page 的 UI 设计", role_id="engineering-frontend-developer")
    assert any(s.name == "ui-ux-pro-max" for s in matched)
    assert store.match("kubernetes helm deploy", role_id="engineering-frontend-developer") == []


def test_manual_skill_prefs(tmp_path) -> None:
    store = SkillStore(str(tmp_path))
    prefs = SkillPrefs(mode="manual", pinned=["ui-ux-pro-max"])
    save_skill_prefs(str(tmp_path), prefs)
    loaded = load_skill_prefs(str(tmp_path))
    assert loaded.mode == "manual"
    assert loaded.pinned == ["ui-ux-pro-max"]
    msgs = matched_skill_messages(
        store,
        "hello",
        role_id="coder",
        prefs=loaded,
    )
    assert len(msgs) == 1
    assert "ui-ux-pro-max" in msgs[0].content


def test_skill_matches_role_empty_roles() -> None:
    from auc.skills import Skill

    sk = Skill(name="x", roles=[])
    assert skill_matches_role(sk, "any-role") is True
