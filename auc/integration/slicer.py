from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from auc.ports.package import CodeSnippet, ContextPackage

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
}


@dataclass
class SlicerConfig:
    max_files: int = 8
    max_bytes_per_file: int = 4096
    max_total_bytes: int = 32000
    context_lines: int = 40


class SemanticSlicer:
    """通过类 ripgrep 搜索构建 ContextPackage（AuM 参考实现）。"""

    def __init__(self, config: SlicerConfig | None = None) -> None:
        self._config = config or SlicerConfig()

    async def slice(self, intent: str, repo_root: str) -> ContextPackage:
        keywords = _extract_keywords(intent)
        root = Path(repo_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"repo_root not found: {repo_root}")

        hits = await asyncio.to_thread(
            _search_repo, root, keywords, self._config
        )
        snippets = [
            CodeSnippet(
                path=str(path.relative_to(root)),
                content=content,
                line_range=line_range,
                relevance_score=score,
            )
            for path, content, line_range, score in hits
        ]
        token_est = sum(len(s.content) // 4 for s in snippets)
        return ContextPackage(
            package_id=str(uuid.uuid4()),
            intent_summary=intent[:200],
            snippets=snippets,
            token_estimate=token_est,
            provenance={"keywords": keywords, "repo_root": str(root)},
        )


def _extract_keywords(intent: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", intent)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        low = t.lower()
        if low not in seen and low not in {"the", "and", "for", "with", "how"}:
            seen.add(low)
            out.append(t)
    return out[:8] or [intent[:32]]


def _search_repo(
    root: Path,
    keywords: list[str],
    config: SlicerConfig,
) -> list[tuple[Path, str, tuple[int, int] | None, float]]:
    results: list[tuple[Path, str, tuple[int, int] | None, float]] = []
    total_bytes = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in {
            ".py",
            ".md",
            ".ts",
            ".tsx",
            ".js",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".rs",
            ".go",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        score = 0.0
        for kw in keywords:
            if kw in text or kw.lower() in text.lower():
                score += 1.0

        if score <= 0:
            continue

        excerpt, line_range = _excerpt_around_match(text, keywords, config.context_lines)
        if len(excerpt) > config.max_bytes_per_file:
            excerpt = excerpt[: config.max_bytes_per_file] + "\n..."

        if total_bytes + len(excerpt) > config.max_total_bytes:
            break
        total_bytes += len(excerpt)
        results.append((path, excerpt, line_range, score))

        if len(results) >= config.max_files:
            break

    results.sort(key=lambda x: x[3], reverse=True)
    return results


def _excerpt_around_match(
    text: str,
    keywords: list[str],
    context_lines: int,
) -> tuple[str, tuple[int, int] | None]:
    lines = text.splitlines()
    match_idx = 0
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw in line or kw.lower() in line.lower():
                match_idx = i
                break
        else:
            continue
        break

    start = max(0, match_idx - context_lines // 2)
    end = min(len(lines), match_idx + context_lines // 2 + 1)
    excerpt_lines = lines[start:end]
    return "\n".join(excerpt_lines), (start + 1, end)
