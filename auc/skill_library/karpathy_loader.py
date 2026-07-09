"""multica-ai/andrej-karpathy-skills 导入元数据。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    discover_skill_paths,
    enrich_skill_frontmatter,
)

KARPATHY_HINTS: list[DivisionHint] = [
    (
        ("karpathy", "guidelines", "simplicity", "surgical", "refactor", "review"),
        "engineering",
        ["coder", "engineering-code-reviewer"],
        "🎯",
    ),
]


def discover_karpathy_skill_paths(repo_root: Path) -> list[Path]:
    """仅 ``skills/<slug>/SKILL.md`` canonical 技能。"""
    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        return discover_skill_paths(repo_root, skip_prefixes=(".cursor", ".claude-plugin"))
    out: list[Path] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            out.append(skill_md)
    return out


def enrich_karpathy_skill(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
) -> str | None:
    return enrich_skill_frontmatter(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=KARPATHY_HINTS,
        catalog="karpathy",
    )
