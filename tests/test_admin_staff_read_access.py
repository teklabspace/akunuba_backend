"""Tests for staff (admin OR advisor) read access to the admin asset detail.

Frontend change request 2026-08-07: advisors work the concierge appraisal
queue and the Appraisal Details "View Asset" button loads
GET /admin/assets/{asset_code}. That endpoint moves from require_admin to
require_staff (read-only); every other /admin/* endpoint stays admin-only.

Pure-helper tests, no DB — run via pytest or
`python tests/test_admin_staff_read_access.py`.
"""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.params import Depends as DependsParam

from app.api.v1.admin import admin_get_asset_by_code, require_staff, router
from app.core.exceptions import ForbiddenException
from app.core.permissions import Role


def _user(role):
    return SimpleNamespace(role=role)


def test_admin_is_allowed():
    user = _user(Role.ADMIN)
    assert require_staff(user) is user


def test_advisor_is_allowed():
    user = _user(Role.ADVISOR)
    assert require_staff(user) is user


def test_investor_is_rejected_with_403():
    with pytest.raises(ForbiddenException) as exc_info:
        require_staff(_user(Role.INVESTOR))
    assert exc_info.value.status_code == 403


def test_plain_string_roles_behave_like_the_enum():
    # User.role can surface as a raw string; Role is a str-Enum so equality
    # must hold either way.
    assert require_staff(_user("admin"))
    assert require_staff(_user("advisor"))
    with pytest.raises(ForbiddenException):
        require_staff(_user("investor"))


def _depends_on(endpoint, dependency):
    return any(
        isinstance(p.default, DependsParam) and p.default.dependency is dependency
        for p in inspect.signature(endpoint).parameters.values()
    )


def test_asset_detail_route_uses_require_staff():
    assert _depends_on(admin_get_asset_by_code, require_staff)


def test_no_other_admin_route_uses_require_staff():
    """Scope guard: require_staff opens exactly ONE read-only endpoint.

    Any new /admin/* route reaching for require_staff must be a deliberate
    product decision, not a copy-paste — widen this list when that happens.
    """
    staff_routes = {
        route.endpoint.__name__
        for route in router.routes
        if _depends_on(route.endpoint, require_staff)
    }
    assert staff_routes == {"admin_get_asset_by_code"}


def _run_standalone():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001 - surface any failure
                failures += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failures else 'OK'}")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
