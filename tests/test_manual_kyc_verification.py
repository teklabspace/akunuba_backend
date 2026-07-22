"""Manual KYC fallback verification — token link, uploads, review, approval email.

Feature (2026-07-21): when Persona verification fails, the user lands in the
admin verification queue as `rejected`. The admin can email them a tokenized
manual-verification link (no login needed); the user submits a selfie + ID
document, stored in our private kyc-documents bucket as KYCDocument rows; the
KYC flips to pending_review for admin review; approval emails the user a
login-button email.

Pins:
  - token lifecycle helpers (issue / expiry / naive-datetime normalization)
  - which KYC statuses may receive a link (rejected, expired ONLY)
  - upload validation (selfie = image only; ID = image or PDF; 10MB cap)
  - route wiring: manual-verification endpoints are PUBLIC (token is the
    credential), send-link endpoint is admin-gated
  - VERIFICATION_LINK_EXPIRED error contract (410) + registry entries
  - both admin approve endpoints send the login-link approval email

Runs under pytest *or* standalone:  python tests/test_manual_kyc_verification.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import GoneException
from app.models.kyc import KYCStatus, KYCVerification
from app.services.manual_kyc import (
    MANUAL_DOC_TYPES,
    MANUAL_LINK_TTL_DAYS,
    MANUAL_UPLOAD_MAX_BYTES,
    can_send_manual_link,
    issue_manual_token,
    manual_token_state,
    manual_verification_url,
    validate_manual_upload,
)
from app.main import app

MANUAL_GET_PATH = "/api/v1/kyc/manual-verification/{token}"
MANUAL_POST_PATH = "/api/v1/kyc/manual-verification/{token}"
SEND_LINK_PATH = "/api/v1/admin/users/{user_id}/kyc/send-verification-link"


# ---------------------------------------------------------------- token helpers

def test_issue_manual_token_shape_and_ttl():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    token, expires_at = issue_manual_token(now=now)
    assert isinstance(token, str) and len(token) >= 32, "token must be a long random string"
    assert expires_at == now + timedelta(days=MANUAL_LINK_TTL_DAYS)
    assert MANUAL_LINK_TTL_DAYS == 7


def test_issue_manual_token_is_unique_per_call():
    a, _ = issue_manual_token()
    b, _ = issue_manual_token()
    assert a != b


def test_manual_token_state_ok_and_expired():
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    assert manual_token_state(now + timedelta(hours=1), now=now) == "ok"
    assert manual_token_state(now - timedelta(seconds=1), now=now) == "expired"


def test_manual_token_state_normalizes_naive_datetimes():
    # Legacy/driver rows can come back tz-naive; comparing naive<->aware raises
    # (real class of prod 500s in this codebase) — the helper must normalize.
    now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    naive_future = datetime(2026, 7, 22, 12, 0)
    naive_past = datetime(2026, 7, 20, 12, 0)
    assert manual_token_state(naive_future, now=now) == "ok"
    assert manual_token_state(naive_past, now=now) == "expired"


def test_manual_token_state_missing_expiry_is_expired():
    assert manual_token_state(None) == "expired"


def test_manual_verification_url_shape():
    url = manual_verification_url("tok123", base="https://app.example.com")
    assert url == "https://app.example.com/manual-verification?token=tok123"
    assert manual_verification_url("t", base="https://app.example.com/").startswith(
        "https://app.example.com/manual-verification?token="
    ), "trailing slash on base must not produce a double slash"


# ------------------------------------------------------------- send-link gating

def test_can_send_manual_link_only_for_failed_states():
    assert can_send_manual_link(KYCStatus.REJECTED)
    assert can_send_manual_link(KYCStatus.EXPIRED)
    for status in (
        KYCStatus.NOT_STARTED,
        KYCStatus.IN_PROGRESS,
        KYCStatus.PENDING_REVIEW,
        KYCStatus.APPROVED,
    ):
        assert not can_send_manual_link(status), (
            f"{status} must not be eligible for a manual link — only failed "
            "(rejected/expired) verifications go through the manual fallback"
        )


# ------------------------------------------------------------- upload validation

def test_manual_doc_types_cover_required_and_optional_slots():
    assert MANUAL_DOC_TYPES == {
        "selfie": "manual_selfie",
        "id_front": "manual_id_front",
        "id_back": "manual_id_back",
    }


def test_validate_selfie_accepts_images_only():
    assert validate_manual_upload("selfie", "me.png", "image/png", 1024) == "image/png"
    assert validate_manual_upload("selfie", "me.jpg", None, 1024) == "image/jpeg"
    try:
        validate_manual_upload("selfie", "me.pdf", "application/pdf", 1024)
        assert False, "a selfie must be a photo, not a PDF"
    except ValueError:
        pass


def test_validate_id_document_accepts_images_and_pdf():
    assert validate_manual_upload("id_front", "id.jpg", "image/jpeg", 1024) == "image/jpeg"
    assert validate_manual_upload("id_back", "id.pdf", "application/pdf", 1024) == "application/pdf"
    try:
        validate_manual_upload("id_front", "id.exe", "application/octet-stream", 1024)
        assert False, "unknown binary types must be rejected"
    except ValueError:
        pass


def test_validate_manual_upload_enforces_size_cap():
    assert MANUAL_UPLOAD_MAX_BYTES == 10 * 1024 * 1024
    try:
        validate_manual_upload("selfie", "me.png", "image/png", MANUAL_UPLOAD_MAX_BYTES + 1)
        assert False, "files over the 10MB cap must be rejected"
    except ValueError:
        pass
    # exactly at the cap is fine
    assert validate_manual_upload("selfie", "me.png", "image/png", MANUAL_UPLOAD_MAX_BYTES)


def test_validate_manual_upload_rejects_unknown_field():
    try:
        validate_manual_upload("passport_scan", "x.png", "image/png", 10)
        assert False, "only the three known slots may be uploaded"
    except ValueError:
        pass


# ------------------------------------------------------------------ model shape

def test_kyc_model_has_manual_link_columns():
    cols = KYCVerification.__table__.columns
    assert "manual_token" in cols
    assert "manual_token_expires_at" in cols
    assert "manual_submitted_at" in cols
    assert cols["manual_token"].unique, "manual_token lookups require uniqueness"


# ---------------------------------------------------------------- route wiring

def _routes_for(path):
    return [r for r in app.routes if getattr(r, "path", None) == path]


def _dependency_names(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}


def _routes_for_method(path, method):
    return [r for r in _routes_for(path) if method in getattr(r, "methods", set())]


def test_manual_verification_routes_exist_and_are_public():
    for method in ("GET", "POST"):
        routes = _routes_for_method(MANUAL_GET_PATH, method)
        assert len(routes) == 1, f"expected exactly one {method} {MANUAL_GET_PATH}"
        names = _dependency_names(routes[0])
        for forbidden in ("get_current_user", "require_kyc_verified"):
            assert forbidden not in names, (
                f"{forbidden} guards {method} {MANUAL_GET_PATH}; the token IS the "
                "credential — failed-KYC users may not be able to use the app"
            )


def test_send_link_route_is_admin_gated():
    routes = _routes_for_method(SEND_LINK_PATH, "POST")
    assert len(routes) == 1, f"expected exactly one POST {SEND_LINK_PATH}"
    assert "require_admin" in _dependency_names(routes[0]), (
        "send-verification-link mints a credential for someone else's identity "
        "check — it must be admin-only"
    )


# ------------------------------------------------------------- error contract

def test_expired_link_error_contract():
    exc = GoneException("This verification link has expired", code="VERIFICATION_LINK_EXPIRED")
    assert exc.status_code == 410
    assert exc.code == "VERIFICATION_LINK_EXPIRED"


def test_error_code_registered_in_both_doc_files():
    js = (ROOT / "doc" / "api_error_codes.js").read_text(encoding="utf-8")
    md = (ROOT / "doc" / "API_ERROR_CODES.md").read_text(encoding="utf-8")
    assert "VERIFICATION_LINK_EXPIRED: 410" in js
    assert "VERIFICATION_LINK_EXPIRED" in md


# -------------------------------------------------------- approval email wiring

def test_both_admin_approve_endpoints_send_login_email():
    import inspect
    from app.api.v1.admin import approve_user_kyc, approve_kyc

    for fn in (approve_user_kyc, approve_kyc):
        src = inspect.getsource(fn)
        assert "send_kyc_approved_email" in src, (
            f"{fn.__name__} must email the user an approval email with the "
            "login link — bell notification alone was the pre-feature behavior"
        )


def test_submission_endpoint_notifies_admins_and_invalidates_token():
    import inspect
    from app.api.v1.kyc import submit_manual_verification

    src = inspect.getsource(submit_manual_verification)
    assert "notify_admins" in src, "admins must hear about new manual submissions"
    assert "manual_token = None" in src.replace("kyc.manual_token = None", "manual_token = None"), (
        "the token must be invalidated after a successful submission"
    )
    assert "PENDING_REVIEW" in src, "submission must move the KYC into the review queue"


def _run_standalone():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
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
