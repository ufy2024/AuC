#!/usr/bin/env python3
"""从 https://github.com/anbeime/skill 导入 SKILL.md 到 auc/skill_library/bundled/。

用法:
  python scripts/import_anbeime_skills.py
  python scripts/import_anbeime_skills.py --dry-run
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
MANIFEST = ROOT / "auc" / "skill_library" / "bundled" / "_anbeime_manifest.json"

sys.path.insert(0, str(ROOT))

from auc.skill_library.anbeime_loader import discover_skill_paths, enrich_skill_frontmatter
from auc.skill_library.sources import ANBEIME_SKILL_BRANCH, ANBEIME_SKILL_REPO, ANBEIME_SKILL_URL
from auc.skills import slugify


def fetch_repo_zip() -> Path:
    url = f"https://github.com/{ANBEIME_SKILL_REPO}/archive/refs/heads/{ANBEIME_SKILL_BRANCH}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "ufy-auc-import"})
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
        tmp.write(resp.read())
    tmp.close()
    extract = Path(tempfile.mkdtemp(prefix="anbeime-skill-"))
    with zipfile.ZipFile(tmp.name) as zf:
        zf.extractall(extract)
    Path(tmp.name).unlink(missing_ok=True)
    subs = list(extract.iterdir())
    if len(subs) == 1 and subs[0].is_dir():
        return subs[0]
    return extract


def import_skills(*, dry_run: bool = False) -> dict[str, object]:
    repo_root = fetch_repo_zip()
    paths = discover_skill_paths(repo_root)
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
        enriched = enrich_skill_frontmatter(
            raw,
            rel_path=rel,
            source_url=f"{ANBEIME_SKILL_URL}/blob/{ANBEIME_SKILL_BRANCH}/{rel}",
        )
        if not enriched:
            skipped.append(rel)
            continue
        # 从增强后的 frontmatter 取 name
        name_line = next((ln for ln in enriched.splitlines() if ln.startswith("name:")), "")
        name = name_line.split(":", 1)[-1].strip().strip('"').strip("'") if name_line else src.parent.name
        slug = slugify(name)
        if slug in used_slugs and used_slugs[slug] != rel:
            # 同名技能：用路径后缀消歧
            slug = slugify(f"{name}-{src.parent.name}")[:48]
        used_slugs[slug] = rel
        dest = BUNDLED / slug / "SKILL.md"
        imported.append({"slug": slug, "name": name, "path": rel, "dest": str(dest.relative_to(ROOT))})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(enriched, encoding="utf-8")

    manifest = {
        "source": ANBEIME_SKILL_URL,
        "branch": ANBEIME_SKILL_BRANCH,
        "count": len(imported),
        "skills": imported,
        "skipped": skipped,
    }
    if not dry_run:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(repo_root.parent, ignore_errors=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Import anbeime/skill into AuC bundled library")
    parser.add_argument("--dry-run", action="store_true", help="Only report, do not write files")
    args = parser.parse_args()
    manifest = import_skills(dry_run=args.dry_run)
    print(f"Imported {manifest['count']} skills from {ANBEIME_SKILL_URL}")
    if manifest.get("skipped"):
        print(f"Skipped {len(manifest['skipped'])} files")
    if args.dry_run:
        for item in manifest["skills"][:5]:
            print(f"  {item['slug']} <- {item['path']}")
        if manifest["count"] > 5:
            print(f"  ... and {manifest['count'] - 5} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
