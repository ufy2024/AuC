"""affaan-m/ECC (Everything Claude Code) 技能导入元数据。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    enrich_skill_frontmatter,
)

# 按技能名关键词 → (division, roles, emoji)
ECC_HINTS: list[DivisionHint] = [
    (("frontend", "react", "vue", "angular", "swiftui", "flutter", "android", "ios-icon", "ui-", "motion", "accessibility", "design-system", "liquid-glass"), "design", ["engineering-frontend-developer"], "🎨"),
    (("backend", "api-design", "fastapi", "django", "nestjs", "springboot", "laravel", "quarkus", "golang", "rust", "python-patterns", "java-coding", "kotlin", "postgres", "mysql", "redis", "prisma"), "engineering", ["engineering-backend-architect", "coder"], "💻"),
    (("security", "hipaa", "defi", "llm-trading"), "specialized", ["engineering-security-auditor"], "🔒"),
    (("test", "tdd", "e2e", "eval-harness", "verification", "benchmark", "qa"), "testing", ["engineering-code-reviewer"], "🧪"),
    (("deploy", "docker", "kubernetes", "devops", "git-workflow", "github-ops", "homelab", "network", "cisco"), "operations", ["engineering-devops-automator"], "⚙️"),
    (("market", "investor", "brand", "content", "seo", "marketing", "article-writing", "social"), "marketing", ["marketing-content-creator"], "📣"),
    (("agent", "mcp", "orchestr", "autonomous", "continuous-learning", "prompt"), "engineering", ["coder"], "🤖"),
    (("healthcare", "logistics", "finance-billing", "inventory", "carrier"), "specialized", ["operations-business-analyst"], "🏢"),
    (("research", "deep-research", "documentation", "architecture-decision"), "product", ["product-manager"], "📊"),
    (("ecc-guide", "ecc-recipes", "configure-ecc"), "education", ["coder"], "📖"),
]


def enrich_ecc_skill(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
) -> str | None:
    return enrich_skill_frontmatter(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=ECC_HINTS,
        catalog="ecc",
    )


def discover_ecc_skill_paths(repo_root: Path) -> list[Path]:
    """仅 ``skills/<slug>/SKILL.md`` 顶层 canonical 技能（不含 docs/.cursor 副本）。"""
    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            out.append(skill_md)
    return out
