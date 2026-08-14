"""Guard-helper tests for delegated asset creation (Milestone 1).

Pure-helper tests, no DB — matching tests/test_asset_role_enforcement.py.
Run via pytest or `python tests/test_delegation_guards.py`.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.delegation import (
    DEFAULT_GRANT_TTL_DAYS,
    ensure_can_revoke_grant,
    ensure_request_is_cancellable,
    ensure_request_is_decidable,
    grant_is_usable,
)
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException
from app.core.permissions import Role

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
INVESTOR_ID = "11111111-1111-1111-1111-111111111111"
ADVISOR_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"


def _user(user_id, role=Role.INVESTOR):
    return SimpleNamespace(id=user_id, role=role)


def _request(status="pending", investor_id=INVESTOR_ID):
    return SimpleNamespace(status=status, investor_id=investor_id)


def _grant(status="active", expires_at=None, investor_id=INVESTOR_ID):
    return SimpleNamespace(status=status, expires_at=expires_at, investor_id=investor_id)


# -- ensure_request_is_cancellable -------------------------------------------

def test_owner_can_cancel_pending_request():
    ensure_request_is_cancellable(_request(), _user(INVESTOR_ID))  # must not raise


def test_non_owner_cannot_cancel():
    with pytest.raises(ForbiddenException) as exc:
        ensure_request_is_cancellable(_request(), _user(OTHER_ID))
    assert exc.value.status_code == 403
    assert exc.value.code == "NOT_REQUEST_OWNER"


def test_cannot_cancel_an_already_approved_request():
    with pytest.raises(BadRequestException):
        ensure_request_is_cancellable(_request(status="approved"), _user(INVESTOR_ID))


# -- ensure_request_is_decidable ---------------------------------------------

def test_pending_request_is_decidable():
    ensure_request_is_decidable(_request())  # must not raise


def test_deciding_twice_conflicts():
    with pytest.raises(ConflictException):
        ensure_request_is_decidable(_request(status="approved"))


# -- grant_is_usable ---------------------------------------------------------

def test_active_grant_with_no_expiry_is_usable():
    assert grant_is_usable(_grant(), NOW) is True


def test_active_grant_before_expiry_is_usable():
    assert grant_is_usable(_grant(expires_at=NOW + timedelta(days=1)), NOW) is True


def test_expired_grant_is_not_usable():
    assert grant_is_usable(_grant(expires_at=NOW - timedelta(seconds=1)), NOW) is False


def test_grant_expiring_exactly_now_is_not_usable():
    assert grant_is_usable(_grant(expires_at=NOW), NOW) is False


def test_consumed_grant_is_not_usable():
    assert grant_is_usable(_grant(status="consumed"), NOW) is False


def test_revoked_grant_is_not_usable():
    assert grant_is_usable(_grant(status="revoked"), NOW) is False


# -- ensure_can_revoke_grant -------------------------------------------------

def test_investor_can_revoke_their_own_grant():
    ensure_can_revoke_grant(_grant(), _user(INVESTOR_ID))  # must not raise


def test_admin_can_revoke_any_grant():
    ensure_can_revoke_grant(_grant(), _user(OTHER_ID, role=Role.ADMIN))  # must not raise


def test_advisor_cannot_revoke_their_own_grant():
    with pytest.raises(ForbiddenException) as exc:
        ensure_can_revoke_grant(_grant(), _user(ADVISOR_ID, role=Role.ADVISOR))
    assert exc.value.code == "CANNOT_REVOKE_GRANT"


def test_cannot_revoke_a_consumed_grant():
    with pytest.raises(BadRequestException):
        ensure_can_revoke_grant(_grant(status="consumed"), _user(INVESTOR_ID))


def test_default_ttl_is_thirty_days():
    assert DEFAULT_GRANT_TTL_DAYS == 30


def test_investor_endpoints_enforce_the_investor_role():
    """Route-wiring guard: the rule is only real if every entry point calls it."""
    import inspect

    from app.api.v1.delegation import (
        create_advisor_request,
        list_advisor_directory,
        list_my_advisor_requests,
    )

    for route in (create_advisor_request, list_my_advisor_requests, list_advisor_directory):
        source = inspect.getsource(route)
        assert "_ensure_investor(current_user)" in source, (
            f"{route.__name__} does not enforce the investor-only rule"
        )


def test_cancel_route_delegates_to_the_guard_helper():
    import inspect

    from app.api.v1.delegation import cancel_advisor_request

    source = inspect.getsource(cancel_advisor_request)
    assert "ensure_request_is_cancellable(req, current_user)" in source


def test_admin_decision_routes_use_the_decidable_guard():
    import inspect

    from app.api.v1.admin import (
        admin_approve_advisor_request,
        admin_reject_advisor_request,
    )

    for route in (admin_approve_advisor_request, admin_reject_advisor_request):
        source = inspect.getsource(route)
        assert "ensure_request_is_decidable(req)" in source, (
            f"{route.__name__} can decide a non-pending request"
        )
        assert "with_for_update()" in source, (
            f"{route.__name__} does not lock the request row -- two admins could double-decide"
        )


def test_approval_issues_a_grant_and_reuses_the_existing_chat_helper():
    import inspect

    from app.api.v1.admin import admin_approve_advisor_request

    source = inspect.getsource(admin_approve_advisor_request)
    assert "AssetDelegationGrant(" in source, "approval must issue a grant"
    assert "_get_or_create_advisor_chat(db, advisor, investor)" in source, (
        "approval must reuse the existing advisor-chat helper"
    )


def test_revoke_route_delegates_to_the_guard_and_locks_the_row():
    import inspect

    from app.api.v1.delegation import revoke_delegation_grant

    source = inspect.getsource(revoke_delegation_grant)
    assert "ensure_can_revoke_grant(grant, current_user)" in source
    assert "with_for_update()" in source


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
