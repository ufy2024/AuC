"""anbeime/skill 仓库技能导入：元数据增强与领域映射。"""

from __future__ import annotations

from pathlib import Path

from auc.skill_library.bundled_loader import (
    DivisionHint,
    discover_skill_paths as _discover,
    enrich_skill_frontmatter as _enrich,
)

_DIVISION_HINTS: list[DivisionHint] = [
    (("frontend", "web-design", "web-to-app", "ui-ux"), "design", ["engineering-frontend-developer", "coder"], "🎨"),
    (("legal", "contract", "law-"), "specialized", ["legal-contract-reviewer"], "⚖️"),
    (("finance", "stock", "trading"), "specialized", ["finance-analyst"], "💹"),
    (("wechat", "xiaohongshu", "post-to", "content-", "copywriter", "hotspot"), "marketing", ["marketing-content-creator"], "📣"),
    (("ecommerce", "shopping", "avatar", "video-marketing"), "marketing", ["marketing-growth-hacker"], "🛒"),
    (("chrome-automation", "web-to-app"), "operations", ["engineering-devops-automator"], "🌐"),
    (("agent-team", "agentkit"), "engineering", ["coder", "engineering-backend-architect"], "🤖"),
    (("data-story", "research-writer"), "product", ["product-manager"], "📊"),
    (("bedtime", "companion", "xiaoyue"), "education", ["education-tutor"], "💬"),
    (("icon-generator", "illustrator"), "design", ["design-ui-designer"], "🖼️"),
    (("historical", "dream-video", "infinitetalk"), "marketing", ["marketing-content-creator"], "🎬"),
]


def enrich_skill_frontmatter(raw_text: str, *, rel_path: str, source_url: str) -> str | None:
    return _enrich(
        raw_text,
        rel_path=rel_path,
        source_url=source_url,
        hints=_DIVISION_HINTS,
        catalog="anbeime",
    )


def discover_skill_paths(repo_root: Path) -> list[Path]:
    return _discover(repo_root)
