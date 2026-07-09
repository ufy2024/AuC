"""内置技能库通用导入：元数据增强、触发词提取、路径发现。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from auc.skills import parse_skill_md, slugify

_SKIP_PARTS = frozenset({"__MACOSX", ".git", "node_modules"})
_EN_STOP = frozenset(
    "a an the and or for to in on of with is are be this that use when user "
    "skill create build make help your with high quality should also not any "
    "the this that into from through whether".split()
)

DivisionHint = tuple[tuple[str, ...], str, list[str], str]


def infer_meta(
    slug: str,
    rel_path: str,
    description: str,
    hints: list[DivisionHint],
) -> tuple[str, list[str], str]:
    hay = f"{slug} {rel_path} {description}".lower()
    for keys, division, roles, emoji in hints:
        if any(k in hay for k in keys):
            return division, roles, emoji
    if "test" in hay or "qa" in hay:
        return "testing", ["engineering-code-reviewer"], "🧪"
    return "custom", [], "⚡"


def tokens_from_text(text: str, *, limit: int = 12) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z][a-zA-Z0-9-]{2,}|\.[a-z]{2,4}", text.lower())
    out: list[str] = []
    for w in words:
        w = w.strip(".")
        if w in _EN_STOP or len(w) < 2:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def triggers_from_description(description: str, name: str) -> list[str]:
    """从 Anthropic 风格 description 提取触发词（引号短语、扩展名等）。"""
    found: list[str] = []
    for m in re.finditer(r"'([^']{2,40})'|\"([^\"]{2,40})\"|(\.[a-z]{2,5})", description, re.I):
        phrase = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
        if phrase and phrase not in found:
            found.append(phrase.lstrip("."))
    found.extend(tokens_from_text(f"{name} {description}", limit=12))
    # 去重保序
    out: list[str] = []
    for t in found:
        if t not in out:
            out.append(t)
    return out[:12]


def enrich_skill_frontmatter(
    raw_text: str,
    *,
    rel_path: str,
    source_url: str,
    hints: list[DivisionHint],
    catalog: str = "bundled",
) -> str | None:
    sk = parse_skill_md(raw_text)
    if sk is None:
        return None
    slug = slugify(sk.name)
    division, roles, emoji = infer_meta(slug, rel_path, sk.description, hints)
    triggers = list(sk.triggers)
    if not triggers:
        triggers = triggers_from_description(sk.description, sk.name)
    if not triggers:
        triggers = [slug.replace("-", " ")]

    front: dict[str, Any] = {
        "name": sk.name,
        "description": sk.description,
        "triggers": triggers[:12],
        "source": "bundled",
        "builtin": True,
        "source_url": source_url,
        "division": division,
        "emoji": emoji,
        "catalog": catalog,
    }
    if roles:
        front["roles"] = roles
    fm = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n{sk.body.rstrip()}\n"


def discover_skill_paths(
    repo_root: Path,
    *,
    skip_prefixes: tuple[str, ...] = (),
) -> list[Path]:
    if not repo_root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(repo_root.rglob("SKILL.md")):
        rel = str(p.relative_to(repo_root))
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        if p.name.startswith("._"):
            continue
        if any(rel.startswith(pref) for pref in skip_prefixes):
            continue
        out.append(p)
    return out
