from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from auc.types import ToolPrivilege


@dataclass
class ProjectRules:
    version: int = 1
    build_commands: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    style_notes: list[str] = field(default_factory=list)
    tool_policy: dict[str, ToolPrivilege] = field(default_factory=dict)
    sandbox_root: str | None = None
    raw_markdown: str | None = None


class ProjectRulesPort(Protocol):
    async def load_rules(self, repo_root: str) -> ProjectRules: ...


_SECTION = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_BULLET = re.compile(r"^-\s+(.+)$", re.MULTILINE)
_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_front_matter(text: str) -> dict[str, str]:
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}
    data: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def parse_aurules_markdown(text: str) -> ProjectRules:
    fm = _parse_front_matter(text)
    body = _FRONT_MATTER.sub("", text, count=1) if fm else text
    rules = ProjectRules(
        version=int(fm.get("version", "1")),
        sandbox_root=fm.get("sandbox_root"),
        raw_markdown=text,
    )
    for title, section in _split_sections(body):
        bullets = [m.group(1).strip() for m in _BULLET.finditer(section)]
        lower = title.lower()
        if "build" in lower:
            rules.build_commands.extend(bullets)
        elif "test" in lower:
            rules.test_commands.extend(bullets)
        elif "style" in lower or "code" in lower:
            rules.style_notes.extend(bullets)
    return rules


def _split_sections(body: str) -> list[tuple[str, str]]:
    matches = list(_SECTION.finditer(body))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((m.group(1).strip(), body[start:end]))
    return sections


class FileRulesPort:
    """Load `.aurules` or `AUM.md` from a repository root."""

    async def load_rules(self, repo_root: str) -> ProjectRules:
        root = Path(repo_root)
        for name in (".aurules", "AUM.md", "CLAUDE.md"):
            path = root / name
            if path.is_file():
                return parse_aurules_markdown(path.read_text(encoding="utf-8"))
        return ProjectRules()
