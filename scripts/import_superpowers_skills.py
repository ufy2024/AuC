#!/usr/bin/env python3
"""从 https://github.com/obra/superpowers 导入 Agent Skills。

用法:
  python scripts/import_superpowers_skills.py
  python scripts/import_superpowers_skills.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "auc" / "skill_library" / "bundled"
MANIFEST = ROOT / "auc" / "skill_library" / "bundled" / "_superpowers_manifest.json"

sys.path.insert(0, str(ROOT))

from auc.skill_library.sources import (
    SUPERPOWERS_BRANCH,
    SUPERPOWERS_REPO,
    SUPERPOWERS_URL,
)
from auc.skill_library.superpowers_loader import (
    discover_superpowers_skill_paths,
    enrich_superpowers_skill,
)
from auc.skills import slugify


def fetch_repo_zip() -> Path:
    url = f"https://github.com/{SUPERPOWERS_REPO}/archive/refs/heads/{SUPERPOWERS_BRANCH}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "ufy-auc-import"})
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        tmp.write(resp.read())
    tmp.close()
    extract = Path(tempfile.mkdtemp(prefix="superpowers-skills-"))
    with zipfile.ZipFile(tmp.name) as zf:
        zf.extractall(extract)
    Path(tmp.name).unlink(missing_ok=True)
    subs = list(extract.iterdir())
    if len(subs) == 1 and subs[0].is_dir():
        return subs[0]
    return extract


def _existing_slugs() -> set[str]:
    slugs: set[str] = set()
    if not BUNDLED.is_dir():
        return slugs
    for d in BUNDLED.iterdir():
        if d.is_dir() and (d / "SKILL.md").is_file():
            slugs.add(d.name)
    return slugs


def import_skills(*, dry_run: bool = False) -> dict[str, object]:
    repo_root = fetch_repo_zip()
    paths = discover_superpowers_skill_paths(repo_root)
    existing = _existing_slugs()
    used_slugs: dict[str, str] = {}
    imported: list[dict[str, str]] = []
    skipped: list[str] = []

    for src in paths:
        rel = str(src.relative_to(repo_root))
        try:
            raw = src.read_text(encoding="utf-8")
        except OSError:
            skipped.append(rel)
            continue
        enriched = enrich_superpowers_skill(
            raw,
            rel_path=rel,
            source_url=f"{SUPERPOWERS_URL}/blob/{SUPERPOWERS_BRANCH}/{rel}",
        )
        if not enriched:
            skipped.append(rel)
            continue
        name_line = next((ln for ln in enriched.splitlines() if ln.startswith("name:")), "")
        orig_name = name_line.split(":", 1)[-1].strip().strip('"').strip("'") if name_line else src.parent.name
        name = orig_name
        slug = slugify(name)
        if slug in existing or slug in used_slugs:
            slug = slugify(f"super-{name}")[:48]
            name = slug
            enriched = enriched.replace(f"name: {orig_name}\n", f"name: {name}\n", 1)
        used_slugs[slug] = rel
        dest = BUNDLED / slug / "SKILL.md"
        imported.append({"slug": slug, "name": name, "path": rel, "dest": str(dest.relative_to(ROOT))})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(enriched, encoding="utf-8")

    manifest = {
        "source": SUPERPOWERS_URL,
        "branch": SUPERPOWERS_BRANCH,
        "count": len(imported),
        "skills": imported,
        "skipped": skipped,
    }
    if not dry_run:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(repo_root.parent, ignore_errors=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Import obra/superpowers into AuC bundled library")
    parser.add_argument("--dry-run", action="store_true", help="Only report, do not write files")
    args = parser.parse_args()
    manifest = import_skills(dry_run=args.dry_run)
    print(f"Imported {manifest['count']} skills from {SUPERPOWERS_URL}")
    if manifest.get("skipped"):
        print(f"Skipped {len(manifest['skipped'])} files")
    if args.dry_run:
        for item in manifest["skills"]:
            print(f"  {item['slug']} <- {item['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
