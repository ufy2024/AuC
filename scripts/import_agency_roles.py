#!/usr/bin/env python3
"""从 agency-agents 拉取角色 Markdown 到 auc/roles/bundled/。

- 中文（zh）：https://github.com/jnMetaCode/agency-agents-zh
- 英文（en）：https://github.com/msitarzewski/agency-agents
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROLE_SOURCES: dict[str, dict[str, str]] = {
    "zh": {
        "repo": "jnMetaCode/agency-agents-zh",
        "branch": "main",
        "url": "https://github.com/jnMetaCode/agency-agents-zh",
        "dir": "agency-zh",
    },
    "en": {
        "repo": "msitarzewski/agency-agents",
        "branch": "main",
        "url": "https://github.com/msitarzewski/agency-agents",
        "dir": "agency",
    },
}

SKIP_PREFIXES = (
    ".cursor/",
    ".github/",
    "skills/",
    "integrations/",
    "examples/",
    "scripts/",
)
SKIP_FILES = {"README.md", "CONTRIBUTING.md", "LICENSE.md", "PULL_REQUEST_TEMPLATE.md"}


def should_import(path: str) -> bool:
    if not path.endswith(".md"):
        return False
    if path in SKIP_FILES or path.split("/")[-1] in SKIP_FILES:
        return False
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return False
    parts = path.split("/")
    if len(parts) != 2:
        return False
    division, _name = parts
    if division.startswith("."):
        return False
    return bool(re.match(r"^[a-z][a-z0-9-]*$", division))


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ufy-auc-import"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def fetch_raw(repo: str, branch: str, path: str) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ufy-auc-import"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return resp.read().decode()


def import_locale(locale: str, *, roles_root: Path) -> int:
    cfg = ROLE_SOURCES[locale]
    repo = cfg["repo"]
    branch = cfg["branch"]
    dest_root = roles_root / cfg["dir"]
    if dest_root.is_dir():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)

    api = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    print(f"[{locale}] Fetching {cfg['url']} ...")
    data = fetch_json(api)
    paths = [t["path"] for t in data.get("tree", []) if should_import(t["path"])]
    print(f"[{locale}] Importing {len(paths)} files → {dest_root}")
    ok = 0
    for rel in paths:
        division, fname = rel.split("/", 1)
        dest_dir = dest_root / division
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / fname
        try:
            content = fetch_raw(repo, branch, rel)
            dest.write_text(content, encoding="utf-8")
            ok += 1
            if ok % 25 == 0:
                print(f"  ... {ok}/{len(paths)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {rel}: {exc}", file=sys.stderr)
    (dest_root / ".source").write_text(
        f"locale: {locale}\nsource: {cfg['url']}\nbranch: {branch}\n"
        f"import_script: scripts/import_agency_roles.py\n",
        encoding="utf-8",
    )
    print(f"[{locale}] Done: {ok} files.")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Import agency-agents role bundles")
    parser.add_argument(
        "--locale",
        choices=["zh", "en", "all"],
        default="all",
        help="zh=agency-agents-zh, en=original agency-agents, all=both",
    )
    args = parser.parse_args()
    roles_root = Path(__file__).resolve().parents[1] / "auc" / "roles" / "bundled"
    roles_root.mkdir(parents=True, exist_ok=True)

    locales = ["zh", "en"] if args.locale == "all" else [args.locale]
    total = 0
    for loc in locales:
        total += import_locale(loc, roles_root=roles_root)
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
