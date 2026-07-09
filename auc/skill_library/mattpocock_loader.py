"""mattpocock/skills 仓库技能导入元数据。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    discover_skill_paths,
    enrich_skill_frontmatter,
)

MATTPOCOCK_HINTS: list[DivisionHint] = [
    (("tdd", "code-review", "diagnosing-bugs", "merge-conflicts", "implement", "prototype"), "engineering", ["coder", "engineering-code-reviewer"], "💻"),
    (("domain-modeling", "codebase-design", "architecture", "refactor"), "engineering", ["engineering-backend-architect", "coder"], "🏗️"),
    (("research", "to-spec", "to-tickets", "triage", "wayfinder"), "product", ["product-manager", "coder"], "🎯"),
    (("grill", "teach", "handoff", "writing-great-skills"), "education", ["education-tutor"], "📚"),
    (("git-guardrails", "pre-commit", "migrate", "scaffold"), "operations", ["engineering-devops-automator"], "⚙️"),
    (("obsidian", "edit-article", "writing-"), "custom", [], "✍️"),
]

SKIP_PREFIXES = ("skills/deprecated/",)


def discover_mattpocock_skill_paths(repo_root: Path) -> list[Path]:
    return discover_skill_paths(repo_root, skip_prefixes=SKIP_PREFIXES)


def enrich_mattpocock_skill(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
) -> str | None:
    # 路径优先：skills/engineering/tdd → engineering 领域
    division_override: str | None = None
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "skills":
        cat = parts[1]
        if cat == "engineering":
            division_override = "engineering"
        elif cat == "productivity":
            division_override = "education"
        elif cat == "misc":
            division_override = "operations"
        elif cat == "personal":
            division_override = "custom"
        elif cat == "in-progress":
            division_override = "custom"

    enriched = enrich_skill_frontmatter(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=MATTPOCOCK_HINTS,
        catalog="mattpocock",
    )
    if enriched is None or division_override is None:
        return enriched
    # 简单覆盖 division 行
    lines = enriched.splitlines()
    out: list[str] = []
    for ln in lines:
        if ln.startswith("division:"):
            out.append(f"division: {division_override}")
        else:
            out.append(ln)
    return "\n".join(out) + ("\n" if enriched.endswith("\n") else "")
