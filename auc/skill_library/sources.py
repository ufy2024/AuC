"""内置技能库来源元数据。"""

from __future__ import annotations

ANBEIME_SKILL_REPO = "anbeime/skill"
ANBEIME_SKILL_BRANCH = "main"
ANBEIME_SKILL_URL = "https://github.com/anbeime/skill"

ANTHROPICS_SKILLS_REPO = "anthropics/skills"
ANTHROPICS_SKILLS_BRANCH = "main"
ANTHROPICS_SKILLS_URL = "https://github.com/anthropics/skills"

MATTPOCOCK_SKILLS_REPO = "mattpocock/skills"
MATTPOCOCK_SKILLS_BRANCH = "main"
MATTPOCOCK_SKILLS_URL = "https://github.com/mattpocock/skills"

SUPERPOWERS_REPO = "obra/superpowers"
SUPERPOWERS_BRANCH = "main"
SUPERPOWERS_URL = "https://github.com/obra/superpowers"

ECC_REPO = "affaan-m/ECC"
ECC_BRANCH = "main"
ECC_URL = "https://github.com/affaan-m/ECC"

KARPATHY_REPO = "multica-ai/andrej-karpathy-skills"
KARPATHY_BRANCH = "main"
KARPATHY_URL = "https://github.com/multica-ai/andrej-karpathy-skills"

UI_UX_PRO_MAX_URL = "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"


def skill_catalog_source_url(source: str = "anbeime") -> str:
    if source == "ui-ux-pro-max":
        return UI_UX_PRO_MAX_URL
    if source == "anthropics":
        return ANTHROPICS_SKILLS_URL
    if source == "mattpocock":
        return MATTPOCOCK_SKILLS_URL
    if source == "superpowers":
        return SUPERPOWERS_URL
    if source == "ecc":
        return ECC_URL
    if source == "karpathy":
        return KARPATHY_URL
    return ANBEIME_SKILL_URL
