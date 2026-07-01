"""agency-agents 角色库来源（按语言环境）。"""

from __future__ import annotations

import os
from typing import Literal

RoleLocale = Literal["zh", "en"]

ROLE_CATALOG_SOURCES: dict[str, str] = {
    "zh": "https://github.com/jnMetaCode/agency-agents-zh",
    "en": "https://github.com/msitarzewski/agency-agents",
}

ROLE_CATALOG_DIRS: dict[str, str] = {
    "zh": "agency-zh",
    "en": "agency",
}


def normalize_role_locale(raw: str | None) -> RoleLocale:
    val = str(raw or os.environ.get("AUC_ROLE_LOCALE") or "zh").strip().lower()
    if val.startswith("zh") or val in ("cn", "chinese"):
        return "zh"
    return "en"


def role_catalog_source_url(locale: str | None = None) -> str:
    loc = normalize_role_locale(locale)
    return ROLE_CATALOG_SOURCES[loc]
