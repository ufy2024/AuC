"""角色智能路由测试。"""

from __future__ import annotations

from auc.roles import load_role_catalog
from auc.roles.routing import (
    AUTO_ROLE_ID,
    format_auto_role_note,
    is_auto_role,
    route_role,
)


def test_is_auto_role() -> None:
    assert is_auto_role("auto")
    assert is_auto_role(" AUTO ")
    assert not is_auto_role("coder")


def test_route_role_reviewer_keywords() -> None:
    catalog = load_role_catalog()
    rid = route_role("请帮我 code review 这段代码", catalog)
    assert rid == "engineering-code-reviewer"


def test_route_role_backend_keywords() -> None:
    catalog = load_role_catalog()
    rid = route_role(
        "作为 backend architect 设计微服务 API 网关、OAuth 与云基础设施",
        catalog,
    )
    assert rid == "engineering-backend-architect"


def test_route_role_default_when_no_match() -> None:
    catalog = load_role_catalog()
    rid = route_role("", catalog)
    assert rid == catalog.default_role_id


def test_auto_role_in_catalog_payload() -> None:
    from auc.roles import roles_payload

    items = roles_payload()
    assert items[0]["id"] == AUTO_ROLE_ID
    assert items[0].get("auto") is True


def test_format_auto_role_note() -> None:
    catalog = load_role_catalog()
    note = format_auto_role_note("engineering-code-reviewer", catalog=catalog)
    assert "智能选择" in note
