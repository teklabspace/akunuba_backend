"""KYC/KYB flow verification: onboarding endpoints, status vocabulary, gates.

QA requirement: "KYC/KYB flow verification". The verification flow has strict
invariants: onboarding routes must stay reachable BEFORE verification (a KYC
gate on /kyc/* is a lockout), status enums are lowercase strings the frontend
switches on, the Persona webhook is the only unauthenticated writer and it
must be signature-verified, and rejected users must be able to read WHY and
retry. Session-resume behavior is pinned separately in
test_kyc_resume_session.py / test_kyc_url_freshness.py.

Runs under pytest *or* standalone:  python tests/test_kyc_kyb_flow.py
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute

from app.main import app
from app.models.kyc import KYCStatus
from app.models.kyb import KYBStatus


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]

def _deps(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}

def _route(method, path):
    matches = [r for r in _api_routes() if r.path == path and method in r.methods]
    assert matches, f"{method} {path} is not mounted"
    return matches[0]


# ------------------------------------------------------------ endpoint set

def test_kyc_flow_endpoints_exist():
    for method, path in (
        ("POST", "/api/v1/kyc/start"),
        ("GET", "/api/v1/kyc/status"),
        ("POST", "/api/v1/kyc/resubmit"),
        ("GET", "/api/v1/kyc/rejection-reason"),
    ):
        _route(method, path)


def test_kyb_flow_endpoints_exist():
    for method, path in (
        ("POST", "/api/v1/kyb/start"),
        ("POST", "/api/v1/kyb/upload-document"),
        ("GET", "/api/v1/kyb/status"),
        ("POST", "/api/v1/kyb/submit"),
    ):
        _route(method, path)


def test_onboarding_routes_are_not_kyc_gated():
    # Chicken-and-egg: users must reach KYC/KYB endpoints BEFORE being
    # verified. A require_kyc_verified dependency here locks everyone out.
    for method, path in (
        ("POST", "/api/v1/kyc/start"),
        ("GET", "/api/v1/kyc/status"),
        ("POST", "/api/v1/kyb/start"),
        ("GET", "/api/v1/kyb/status"),
    ):
        assert "require_kyc_verified" not in _deps(_route(method, path)), (
            f"{method} {path} is KYC-gated — unverified users can never verify"
        )


def test_kyc_routes_still_require_a_session():
    # Not gated ≠ anonymous: starting/reading KYC must identify the caller.
    for method, path in (
        ("POST", "/api/v1/kyc/start"),
        ("GET", "/api/v1/kyc/status"),
        ("GET", "/api/v1/kyc/rejection-reason"),
    ):
        assert "get_current_user" in _deps(_route(method, path)), (
            f"{method} {path} lost its auth dependency — anyone could read/start KYC"
        )


# --------------------------------------------------------- status vocabulary

def test_kyc_status_values_are_lowercase_strings():
    # The frontend and the Persona mappers switch on these exact lowercase
    # values; capitalizing them (a real past trap) breaks every consumer.
    expected = {
        "not_started", "in_progress", "pending_review",
        "approved", "rejected", "expired",
    }
    assert {s.value for s in KYCStatus} == expected
    assert all(s.value == s.value.lower() for s in KYCStatus)


def test_kyb_status_mirrors_kyc_vocabulary():
    assert {s.value for s in KYBStatus} == {s.value for s in KYCStatus}, (
        "KYB and KYC status vocabularies drifted apart — shared frontend "
        "components render both"
    )


# ------------------------------------------------------------ webhook writer

def test_persona_webhook_reads_nested_inquiry_id():
    # Regression pin: top-level data.id is the EVENT id (evt_...); the inquiry
    # id lives at data.attributes.payload.data.id. Using the wrong one made
    # every KYC webhook update a silent no-op (real past bug).
    from app.api.v1 import webhooks

    src = inspect.getsource(webhooks._parse_persona_event)
    assert "payload" in src, "_parse_persona_event no longer reads the nested payload"


def test_kyc_document_capture_uses_private_bucket_and_signed_urls():
    # Identity documents are PII: they live in the private kyc-documents
    # bucket and are only ever served via short-lived signed URLs. A move to
    # the public images bucket is a data breach, not a refactor.
    from app.config import settings
    from app.integrations import supabase_client

    assert settings.KYC_DOCUMENTS_BUCKET == "kyc-documents", (
        "private kyc-documents bucket setting changed"
    )
    src = inspect.getsource(supabase_client)
    assert "create_signed_url" in src, "signed-url accessor for private files missing"


def test_admin_kyc_review_endpoints_exist():
    # Human review leg of the flow: admins approve/reject and can force
    # document recapture.
    for method, path in (
        ("POST", "/api/v1/admin/users/{user_id}/kyc/approve"),
        ("POST", "/api/v1/admin/users/{user_id}/kyc/reject"),
        ("POST", "/api/v1/admin/users/{user_id}/kyc/recapture"),
    ):
        route = _route(method, path)
        assert "require_admin" in _deps(route), f"{path} must be admin-only"


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
