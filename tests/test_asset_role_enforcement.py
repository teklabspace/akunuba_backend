"""Tests for the investor-only asset write rule (QA finding 0b, 2026-07-19).

Only the `investor` role may create or edit assets. The frontend hides the
add/edit wizard for advisors and admins, but QA confirmed an advisor token
could still POST /assets directly — the check must live server-side and
return 403 INVESTOR_ROLE_REQUIRED.

Pure-helper tests, no DB — run via pytest or
`python tests/test_asset_role_enforcement.py`.
"""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.assets import (
    create_asset,
    create_valuation,
    delete_asset,
    delete_asset_document,
    delete_asset_photo,
    ensure_investor_can_write_assets,
    update_asset,
    update_asset_valuation,
    upload_asset_document,
    upload_asset_photo,
    upload_file_assets,
)
from app.core.exceptions import ForbiddenException
from app.core.permissions import Role


def _user(role):
    return SimpleNamespace(role=role)


def test_investor_is_allowed():
    ensure_investor_can_write_assets(_user(Role.INVESTOR))  # must not raise


def test_advisor_is_rejected_with_403():
    with pytest.raises(ForbiddenException) as exc_info:
        ensure_investor_can_write_assets(_user(Role.ADVISOR))
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "INVESTOR_ROLE_REQUIRED"


def test_admin_is_rejected_with_403():
    with pytest.raises(ForbiddenException) as exc_info:
        ensure_investor_can_write_assets(_user(Role.ADMIN))
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "INVESTOR_ROLE_REQUIRED"


def test_plain_string_roles_behave_like_the_enum():
    # User.role can surface as a raw string; Role is a str-Enum so equality
    # must hold either way.
    ensure_investor_can_write_assets(_user("investor"))
    with pytest.raises(ForbiddenException):
        ensure_investor_can_write_assets(_user("advisor"))


def test_all_asset_write_routes_call_the_gate():
    """Route-wiring guard: the rule is only real if every write endpoint invokes it.

    Scope confirmed by product 2026-07-20: create, edit, delete, valuations,
    and media upload/delete are all investor-only. Appraisal endpoints are
    deliberately NOT here (appraisals are how staff/AI write valuations).
    """
    for route in (
        create_asset,
        update_asset,
        delete_asset,
        create_valuation,
        update_asset_valuation,
        upload_asset_photo,
        delete_asset_photo,
        upload_asset_document,
        delete_asset_document,
        upload_file_assets,
    ):
        source = inspect.getsource(route)
        assert "ensure_investor_can_write_assets(current_user)" in source, (
            f"{route.__name__} does not enforce the investor-only rule"
        )


def test_delegated_creation_is_the_only_exception_to_the_investor_rule():
    """Milestone 2 (2026-08-14) narrowed the rule above, deliberately.

    create_asset and update_asset now call the investor gate only on their
    non-delegated branch, so the string assertion above still passes but no
    longer proves those two routes are investor-only. These assertions pin the
    replacement rule: the delegated branch is reachable ONLY by spending a grant.
    """
    create_src = inspect.getsource(create_asset)
    assert "acquire_creation_grant(" in create_src, (
        "delegated creation must go through the grant helper, not an ad-hoc check"
    )
    assert "consume_creation_grant(" in create_src, "the grant must be spent on create"
    # Consumption has to happen inside the asset's own transaction.
    assert create_src.index("consume_creation_grant(") < create_src.index("await db.commit()"), (
        "grant consumed after commit — a crash between the two would let it be spent twice"
    )

    update_src = inspect.getsource(update_asset)
    assert "find_edit_grant(" in update_src, "delegated edit must be gated on a live grant"


def test_delete_stays_owner_only_even_for_a_delegate():
    """An advisor must never be able to delete a client's asset."""
    source = inspect.getsource(delete_asset)
    assert "ensure_investor_can_write_assets(current_user)" in source
    assert "find_edit_grant" not in source, "delete_asset must not honour a delegation grant"


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
