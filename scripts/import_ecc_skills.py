#!/usr/bin/env python3
"""从 https://github.com/affaan-m/ECC 导入 Everything Claude Code 技能库。

仅导入仓库根目录 ``skills/<name>/SKILL.md``（278 个 canonical 技能），
跳过 docs/*、.cursor/*、.agents/* 等副本。

用法:
  python scripts/import_ecc_skills.py
  python scripts/import_ecc_skills.py --dry-run
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
MANIFEST = ROOT / "auc" / "skill_library" / "bundled" / "_ecc_manifest.json"

sys.path.insert(0, str(ROOT))

from auc.skill_library.ecc_loader import discover_ecc_skill_paths, enrich_ecc_skill
from auc.skill_library.sources import ECC_BRANCH, ECC_REPO, ECC_URL
from auc.skills import slugify


def fetch_repo_zip() -> Path:
    url = f"https://github.com/{ECC_REPO}/archive/refs/heads/{ECC_BRANCH}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "ufy-auc-import"})
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        tmp.write(resp.read())
    tmp.close()
    extract = Path(tempfile.mkdtemp(prefix="ecc-skills-"))
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
    paths = discover_ecc_skill_paths(repo_root)
    existing = _existing_slugs()
    used_slugs: dict[str, str] = {}
    imported: list[dict[str, str]] = []
    skipped: list[str] = []
    conflicts: list[str] = []

    for src in paths:
        rel = str(src.relative_to(repo_root))
        try:
            raw = src.read_text(encoding="utf-8")
        except OSError:
            skipped.append(rel)
            continue
        enriched = enrich_ecc_skill(
            raw,
            rel_path=rel,
            source_url=f"{ECC_URL}/blob/{ECC_BRANCH}/{rel}",
        )
        if not enriched:
            skipped.append(rel)
            continue
        name_line = next((ln for ln in enriched.splitlines() if ln.startswith("name:")), "")
        orig_name = name_line.split(":", 1)[-1].strip().strip('"').strip("'") if name_line else src.parent.name
        name = orig_name
        slug = slugify(name)
        if slug in existing or slug in used_slugs:
            slug = slugify(f"ecc-{name}")[:48]
            name = slug
            conflicts.append(orig_name)
            enriched = enriched.replace(f"name: {orig_name}\n", f"name: {name}\n", 1)
        used_slugs[slug] = rel
        dest = BUNDLED / slug / "SKILL.md"
        imported.append({"slug": slug, "name": name, "path": rel, "dest": str(dest.relative_to(ROOT))})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(enriched, encoding="utf-8")

    manifest = {
        "source": ECC_URL,
        "branch": ECC_BRANCH,
        "count": len(imported),
        "conflicts_renamed": conflicts,
        "skills": imported,
        "skipped": skipped,
    }
    if not dry_run:
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(repo_root.parent, ignore_errors=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Import affaan-m/ECC skills into AuC bundled library")
    parser.add_argument("--dry-run", action="store_true", help="Only report, do not write files")
    args = parser.parse_args()
    manifest = import_skills(dry_run=args.dry_run)
    print(f"Imported {manifest['count']} skills from {ECC_URL}")
    conflicts = manifest.get("conflicts_renamed") or []
    if conflicts:
        print(f"Renamed {len(conflicts)} conflicting skills with ecc- prefix")
    if manifest.get("skipped"):
        print(f"Skipped {len(manifest['skipped'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
