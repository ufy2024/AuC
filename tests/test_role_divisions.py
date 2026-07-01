"""角色细分领域与 agency-agents 风格元数据测试。"""

from __future__ import annotations

from auc.roles import BUILTIN_ROLES, divisions_payload, load_role_catalog
from auc.roles.divisions import normalize_division


def test_builtin_core_coder() -> None:
    assert BUILTIN_ROLES["coder"].division == "engineering"
    assert BUILTIN_ROLES["coder"].emoji == "💻"


def test_load_roles_from_agency_bundle() -> None:
    catalog = load_role_catalog()
    assert "engineering-backend-architect" in catalog.roles
    assert catalog.roles["engineering-backend-architect"].division == "engineering"


def test_divisions_payload_order() -> None:
    items = divisions_payload()
    ids = [d["id"] for d in items]
    assert ids[0] == "specialized"
    assert "engineering" in ids
    assert "custom" in ids


def test_normalize_division_fallback() -> None:
    assert normalize_division("engineering") == "engineering"
    assert normalize_division("unknown-division") == "unknown-division"
    assert normalize_division("") == "custom"
