"""Advisor client-scoping tests (gap-analysis requirement #4).

An advisor may only read a client's data when `advisor_clients` actually links
them. Admins bypass the link; investors never get this path at all.

Pure-helper tests, no DB -- matching tests/test_asset_role_enforcement.py.
Run via pytest or `python tests/test_advisor_client_scope.py`.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.advisor import NOT_YOUR_CLIENT, is_advisor_scope_allowed
from app.core.permissions import Role

ADVISOR_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ADVISOR_ID = "44444444-4444-4444-4444-444444444444"
CLIENT_ID = "11111111-1111-1111-1111-111111111111"


def _user(user_id, role):
    return SimpleNamespace(id=user_id, role=role)


def _assignment(advisor_id=ADVISOR_ID):
    return SimpleNamespace(advisor_id=advisor_id, client_id=CLIENT_ID)


def test_admin_is_allowed_without_any_assignment():
    assert is_advisor_scope_allowed(_user("admin-1", Role.ADMIN), None) is True


def test_assigned_advisor_is_allowed():
    assert is_advisor_scope_allowed(_user(ADVISOR_ID, Role.ADVISOR), _assignment()) is True


def test_unassigned_advisor_is_denied():
    assert is_advisor_scope_allowed(_user(ADVISOR_ID, Role.ADVISOR), None) is False


def test_advisor_assigned_to_someone_else_is_denied():
    other = _assignment(advisor_id=OTHER_ADVISOR_ID)
    assert is_advisor_scope_allowed(_user(ADVISOR_ID, Role.ADVISOR), other) is False


def test_investor_is_denied_even_with_an_assignment_row():
    assert is_advisor_scope_allowed(_user(CLIENT_ID, Role.INVESTOR), _assignment()) is False


def test_plain_string_roles_behave_like_the_enum():
    assert is_advisor_scope_allowed(_user("admin-1", "admin"), None) is True
    assert is_advisor_scope_allowed(_user(ADVISOR_ID, "advisor"), _assignment()) is True
    assert is_advisor_scope_allowed(_user(ADVISOR_ID, "advisor"), None) is False


def test_error_code_is_stable():
    # The frontend branches on this string; changing it is a breaking change.
    assert NOT_YOUR_CLIENT == "NOT_YOUR_CLIENT"


def test_every_client_scoped_route_calls_the_guard():
    """Route-wiring guard: scoping is only real if every entry point enforces it."""
    import inspect

    from app.api.v1 import advisor

    routes = (
        advisor.get_client_overview,
        advisor.get_client_assets,
        advisor.get_client_documents,
        advisor.get_client_goals,
        advisor.get_client_requests,
        advisor.get_client_activity,
    )
    for route in routes:
        source = inspect.getsource(route)
        assert "ensure_advisor_of(db, current_user, client_id)" in source, (
            f"{route.__name__} does not enforce advisor client scoping"
        )


def test_document_listing_does_not_leak_storage_paths():
    """Advisors may see that a document exists, not fetch its bytes."""
    import inspect

    from app.api.v1.advisor import get_client_documents

    source = inspect.getsource(get_client_documents)
    # Match attribute access (what an actual leak looks like), not the words --
    # the docstring names these fields precisely to say they are withheld.
    for leaked in ("d.file_path", "d.supabase_storage_path"):
        assert leaked not in source, f"get_client_documents exposes {leaked}"


def test_reading_the_audit_log_is_not_itself_logged():
    """Otherwise opening the activity tab pollutes the record it displays."""
    import inspect

    from app.api.v1.advisor import get_client_activity

    assert "log_activity(" not in inspect.getsource(get_client_activity)


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
