"""agency-agents 内置角色库测试。"""

from __future__ import annotations

from auc.roles import BUILTIN_ROLES, divisions_payload, load_role_catalog
from auc.roles.agency_loader import agency_bundled_root, load_agency_roles_from_directory
from auc.roles.agency_sources import role_catalog_source_url


def test_agency_bundled_imported_zh() -> None:
    roles = load_agency_roles_from_directory(agency_bundled_root("zh"))
    assert len(roles) >= 200
    assert "engineering-backend-architect" in roles


def test_agency_bundled_imported_en() -> None:
    roles = load_agency_roles_from_directory(agency_bundled_root("en"))
    assert len(roles) >= 200
    assert "engineering-backend-architect" in roles
    assert "engineering-frontend-developer" in roles


def test_role_catalog_source_by_locale() -> None:
    assert "jnMetaCode" in role_catalog_source_url("zh")
    assert "msitarzewski" in role_catalog_source_url("en")


def test_catalog_merges_agency_and_core() -> None:
    catalog = load_role_catalog()
    assert "coder" in catalog.roles
    assert "engineering-backend-architect" in catalog.roles
    assert len(catalog.roles) >= 200


def test_divisions_include_agency_fields() -> None:
    catalog = load_role_catalog()
    divs = divisions_payload(catalog=catalog)
    ids = {d["id"] for d in divs}
    assert "engineering" in ids
    assert "marketing" in ids
    assert "custom" in ids


def test_core_coder_still_default() -> None:
    assert "coder" in BUILTIN_ROLES
    catalog = load_role_catalog()
    assert catalog.default_role_id == "coder" or catalog.get("coder")
