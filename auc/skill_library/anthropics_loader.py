"""anthropics/skills 官方 Agent Skills 导入元数据。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    discover_skill_paths,
    enrich_skill_frontmatter,
)

ANTHROPICS_HINTS: list[DivisionHint] = [
    (("docx", "pdf", "pptx", "xlsx", "doc-coauthoring"), "specialized", ["coder"], "📄"),
    (("mcp-builder", "claude-api"), "engineering", ["coder", "engineering-backend-architect"], "🔌"),
    (("webapp-testing", "web-artifacts"), "testing", ["engineering-code-reviewer"], "🧪"),
    (
        ("frontend-design", "canvas-design", "algorithmic-art", "theme-factory", "brand-guidelines"),
        "design",
        ["engineering-frontend-developer", "design-ui-designer"],
        "🎨",
    ),
    (("internal-comms", "slack-gif"), "marketing", ["marketing-content-creator"], "📢"),
    (("skill-creator",), "engineering", ["coder"], "🛠️"),
]

SKIP_PREFIXES = ("template/",)


def discover_anthropics_skill_paths(repo_root: Path) -> list[Path]:
    return discover_skill_paths(repo_root, skip_prefixes=SKIP_PREFIXES)


def enrich_anthropics_skill(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
) -> str | None:
    return enrich_skill_frontmatter(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=ANTHROPICS_HINTS,
        catalog="anthropics",
    )
