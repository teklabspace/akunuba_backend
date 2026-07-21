"""Regression suite for the "Akunuba Platform — QA Bug Report" findings.

QA requirement: "Regression testing after fixes". Each test is named for the
bug it re-verifies (INV = investor section, ADM = admin section of the
report). A test here failing means a shipped QA fix has regressed.

Two findings remain OPEN by design and are pinned as known gaps at the bottom
(admin subscription creation, CRM task detail) — those tests assert the
CURRENT documented state and must be updated when the features ship.

Runs under pytest *or* standalone:  python tests/test_regression_qa_bug_report.py
"""
import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute

from app.main import app


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]

def _deps(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}

def _route(method, path):
    matches = [r for r in _api_routes() if r.path == path and method in r.methods]
    assert matches, f"{method} {path} is not mounted"
    return matches[0]

def _has_route(method, path):
    return any(r.path == path and method in r.methods for r in _api_routes())


# INV-BUG-01 — appraisal request 422 on lowercase appraisal_type ------------

def test_bug_inv01_appraisal_type_accepts_any_casing():
    from app.models.asset import AppraisalType

    assert AppraisalType("comprehensive") is AppraisalType.COMPREHENSIVE
    assert AppraisalType("EXPEDITED") is AppraisalType.EXPEDITED
    assert AppraisalType("iNsUrAnCe") is AppraisalType.INSURANCE
    assert AppraisalType("api") is AppraisalType.API


def test_bug_inv01_appraisal_type_still_rejects_unknown_values():
    from app.models.asset import AppraisalType

    try:
        AppraisalType("teleportation")
    except ValueError:
        return
    raise AssertionError("unknown appraisal_type must still be rejected")


def test_bug_inv01_appraisal_vocabulary_matches_documented_contract():
    from app.models.asset import AppraisalType

    assert {t.value for t in AppraisalType} == {
        "Concierge", "API", "Standard", "Comprehensive", "Expedited", "Insurance",
    }


# INV-BUG-02 — share link "couldn't be accessed" ----------------------------

def test_bug_inv02_share_link_route_is_public():
    route = _route("GET", "/api/v1/assets/{asset_id}/shared")
    names = _deps(route)
    assert "get_current_user" not in names and "require_kyc_verified" not in names, (
        "share-link route re-gated — anonymous recipients get 401 again"
    )


# INV-BUG-03 — "Request to Sell" failing upstream ---------------------------

def test_bug_inv03_sale_request_endpoint_exists_and_is_gated():
    route = _route("POST", "/api/v1/assets/{asset_id}/sale-requests")
    assert "require_kyc_verified" in _deps(route), "sale requests are investor actions"


# INV-BUG-04 — notifications feed empty + "Something went wrong" ------------

def test_bug_inv04_notifications_feed_is_user_addressed_not_account_addressed():
    # Staff/admins have no Account row; an account lookup here blanked their
    # feed. The endpoint must key off current_user.id directly.
    from app.api.v1.notifications import get_notifications

    src = inspect.getsource(get_notifications)
    assert "get_account" not in src, "notifications list re-acquired an account dependency"
    assert "user_id" in src, "notifications list no longer filters by user_id"


def test_bug_inv04_notification_serializer_contract():
    from types import SimpleNamespace
    from app.api.v1.notifications import serialize_notification
    from app.models.notification import NotificationType

    fake = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        notification_type=NotificationType.GENERAL,
        title="t", message="m", meta_data=None, is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    payload = serialize_notification(fake)
    for key in ("id", "type", "title", "message", "read", "is_read", "created_at"):
        assert key in payload, f"serializer dropped '{key}' — frontend can't parse the feed"


# INV-BUG-06 / ADM "Failed to get link token" — Plaid host misconfig --------

def test_bug_inv06_plaid_env_name_maps_to_full_api_url():
    # The SDK uses `host` verbatim; the literal env name "sandbox" produced
    # DNS failures (HTTPConnectionPool(host='sandbox')). The client must map
    # env names to full URLs and default safely.
    from app.integrations import plaid_client

    src = inspect.getsource(plaid_client)
    assert "https://sandbox.plaid.com" in src, "sandbox URL mapping missing"
    assert "https://production.plaid.com" in src, "production URL mapping missing"
    assert "plaid_host_map" in src, "env-name→URL map removed"
    assert ".lower()" in src, "PLAID_ENV must be case-insensitive"


# INV-BUG-07 — GET /referrals 500 -------------------------------------------

def test_bug_inv07_referral_routes_exist():
    _route("GET", "/api/v1/referrals")
    _route("GET", "/api/v1/referrals/list")


def test_bug_inv07_referral_stats_are_null_safe():
    # Zero-referral accounts crashed aggregation; sums must seed Decimals and
    # batch lookups must guard the empty case.
    from app.api.v1 import referrals

    src = inspect.getsource(referrals)
    assert 'Decimal("0.00")' in src or "Decimal('0.00')" in src, (
        "referral reward aggregation lost its Decimal zero seed"
    )
    assert "NotFoundException" in src, "missing account must 404, not 500"


# INV-BUG-09 — ticket comments 405 ------------------------------------------

def test_bug_inv09_comments_alias_routes_exist():
    for method in ("POST", "GET"):
        assert _has_route(method, "/api/v1/support/tickets/{ticket_id}/replies"), (
            f"{method} /replies missing"
        )
        assert _has_route(method, "/api/v1/support/tickets/{ticket_id}/comments"), (
            f"{method} /comments alias missing — frontend calls this path (was 405)"
        )


# INV-BUG-10 — /documents/statistics 422 uuid_parsing ------------------------

def test_bug_inv10_statistics_wins_over_uuid_route():
    paths = [r.path for r in _api_routes()]
    assert paths.index("/api/v1/documents/statistics") < paths.index(
        "/api/v1/documents/{document_id}"
    ), "static /statistics is shadowed by the {document_id} route again (422s)"


# ADM-BUG-01 — asset create 500 on naive/aware datetime comparison ----------

def test_bug_adm01_naive_future_acquisition_date_is_422_not_500():
    from pydantic import ValidationError
    from app.schemas.asset import AssetCreate

    naive_future = datetime.utcnow() + timedelta(days=30)  # deliberately naive
    try:
        AssetCreate(name="X", acquisition_date=naive_future)
    except ValidationError:
        pass  # correct: clean validation error → 422 envelope
    except TypeError as e:  # pragma: no cover
        raise AssertionError(f"naive-vs-aware comparison crash is back: {e}")
    else:
        raise AssertionError("future acquisition_date accepted — validator removed")


def test_bug_adm01_past_dates_accepted_in_both_flavors():
    from app.schemas.asset import AssetCreate

    AssetCreate(name="X", acquisition_date=datetime.utcnow() - timedelta(days=1))
    AssetCreate(name="X", acquisition_date=datetime.now(timezone.utc) - timedelta(days=1))


# ADM-BUG-02 — GET /assets/ai/usage 500 -------------------------------------

def test_bug_adm02_ai_usage_route_exists_and_counts_are_null_safe():
    _route("GET", "/api/v1/assets/ai/usage")

    from app.api.v1 import assets
    src = inspect.getsource(assets._count_ai_appraisals_this_month)
    assert "or 0" in src, "AI appraisal count lost its null guard"
    src = inspect.getsource(assets._count_ai_reviews_this_month)
    assert "or 0" in src, "AI review count lost its null guard"


# ADM-BUG-04 — admin subscription plan change 500 ----------------------------

def test_bug_adm04_admin_plan_change_route_exists_and_is_admin_only():
    route = _route("PATCH", "/api/v1/admin/subscriptions/{subscription_id}/plan")
    assert "require_admin" in _deps(route)


# ADM-BUG-14 — admins receive no notifications -------------------------------

def test_bug_adm14_notify_admins_reaches_accountless_admins():
    # Admins typically have NO Account row. An inner JOIN through Account
    # silently skipped every real admin — tickets and KYC submissions
    # notified nobody. The fan-out must select admin USERS (outer-joining the
    # optional account only for the email leg).
    from app.services.notification_service import NotificationService

    src = inspect.getsource(NotificationService.notify_admins)
    assert "outerjoin" in src, (
        "notify_admins reverted to an Account inner join — accountless admins "
        "are skipped again (reported bug)"
    )
    assert "Role.ADMIN" in src and "is_active" in src, (
        "notify_admins must target active admin users"
    )


def test_bug_adm14_appraisal_staff_fanout_selects_users_directly():
    from app.services import appraisal_notifications

    src = inspect.getsource(appraisal_notifications)
    assert "Role.ADMIN" in src and "Role.ADVISOR" in src, (
        "appraisal staff fan-out no longer targets staff roles"
    )


# ADM-BUG-16 — Persona verification fails with generic error -----------------

def test_bug_adm16_rejection_reason_endpoint_exists():
    route = _route("GET", "/api/v1/kyc/rejection-reason")
    assert "get_current_user" in _deps(route), "rejection reason is per-user data"


# ADM-BUG-18 — incomplete asset cannot be deleted by admin --------------------
# The admin delete-any-asset branch from this fix was later REMOVED on purpose:
# business rule 2026-07-19/20 makes asset writes (incl. delete) investor-only
# (see tests/test_asset_role_enforcement.py). What survives from ADM-18 is the
# crash fix itself: media-independent deletion + the 409 transaction guard.

def test_bug_adm18_delete_survives_incomplete_media_and_guards_transactions():
    from app.api.v1.assets import delete_asset

    src = inspect.getsource(delete_asset)
    assert "ensure_investor_can_write_assets" in src, (
        "delete must enforce the investor-only rule that replaced admin delete"
    )
    assert 'code="ASSET_HAS_TRANSACTIONS"' in src, (
        "transaction guard must refuse with 409, not crash"
    )


def test_bug_adm18_asset_children_cascade_on_delete():
    from app.models.asset import Asset

    for rel_name in ("photos", "documents", "appraisals"):
        rel = getattr(Asset, rel_name).property
        assert rel.cascade.delete_orphan, (
            f"Asset.{rel_name} lost delete-orphan cascade — orphan rows will "
            "block deletion with FK errors (reported bug)"
        )


# ADM-BUG-20 — staff offer rejected after full form entry ---------------------

def test_bug_adm20_staff_purchase_block_is_a_clean_403():
    from app.api.v1.marketplace import create_offer
    from app.core.exceptions import ForbiddenException

    src = inspect.getsource(create_offer)
    assert 'code="STAFF_CANNOT_BUY"' in src, (
        "machine-readable staff block removed — frontend can't pre-disable the form"
    )
    assert ForbiddenException("x").status_code == 403


# ADM-BUG-05 (CRM) — assign-user dropdown empty -------------------------------

def test_bug_adm05_crm_users_endpoint_exists_with_name_fallback():
    _route("GET", "/api/v1/crm/users")

    from app.api.v1 import crm
    src = inspect.getsource(crm)
    assert "email" in src, "CRM user list lost its email fallback for blank names"


# ----------------------------------------------------------- KNOWN OPEN GAPS
# These assert the CURRENT state so the tracked gaps are visible in every
# run. When the feature ships, flip the assertion and close the report item.

def test_known_open_gap_admin_subscription_create_endpoint_missing():
    # QA ADM-BUG-16(a): admin "add subscription" has no backend route; the
    # admin UI action cannot succeed. Tracked as OPEN — self-serve creation
    # lives at POST /api/v1/subscriptions (Stripe checkout) only.
    assert not _has_route("POST", "/api/v1/admin/subscriptions"), (
        "POST /admin/subscriptions now EXISTS — ship note: close QA bug "
        "ADM-BUG-16(a) and replace this pin with real coverage"
    )


def test_known_open_gap_crm_task_detail_endpoint_missing():
    # QA ADM-BUG-19: CRM Reports "Task N" click dead-ends; /crm/updates emits
    # task ids but no CRM detail route exists to fetch one. Tracked as OPEN.
    crm_paths = [r.path for r in _api_routes() if r.path.startswith("/api/v1/crm/")]
    assert not any("{" in p and "task" in p.lower() for p in crm_paths), (
        "a CRM task detail route now EXISTS — close QA bug ADM-BUG-19 and "
        "replace this pin with real coverage"
    )


def _run_standalone():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
