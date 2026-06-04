from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeSnippet:
    path: str
    content: str
    line_range: tuple[int, int] | None = None
    relevance_score: float | None = None


@dataclass
class ContextPackage:
    package_id: str
    intent_summary: str
    snippets: list[CodeSnippet]
    token_estimate: int
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class SlicerPolicy:
    require_package: bool = False
    max_ad_hoc_read_bytes: int = 8192
    allow_full_repo_grep: bool = False
