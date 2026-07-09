"""obra/superpowers Agent Skills 导入元数据。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    discover_skill_paths,
    enrich_skill_frontmatter,
)

SUPERPOWERS_HINTS: list[DivisionHint] = [
    (
        ("brainstorming", "writing-plans", "executing-plans"),
        "product",
        ["product-manager", "coder"],
        "💡",
    ),
    (
        ("test-driven-development", "systematic-debugging", "verification-before-completion"),
        "engineering",
        ["coder", "engineering-code-reviewer"],
        "🧪",
    ),
    (
        ("code-review", "requesting-code-review", "receiving-code-review"),
        "engineering",
        ["engineering-code-reviewer", "coder"],
        "🔍",
    ),
    (
        ("dispatching-parallel-agents", "subagent-driven-development"),
        "engineering",
        ["coder", "engineering-backend-architect"],
        "🤖",
    ),
    (
        ("git-worktrees", "finishing-a-development-branch"),
        "operations",
        ["engineering-devops-automator", "coder"],
        "🌿",
    ),
    (
        ("writing-skills", "using-superpowers"),
        "education",
        ["coder"],
        "📖",
    ),
]


def discover_superpowers_skill_paths(repo_root: Path) -> list[Path]:
    return discover_skill_paths(repo_root)


def enrich_superpowers_skill(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
) -> str | None:
    return enrich_skill_frontmatter(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=SUPERPOWERS_HINTS,
        catalog="superpowers",
    )
