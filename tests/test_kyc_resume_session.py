"""Tests for Persona inquiry resume — the "Session expired" dead-link fix.

Persona invalidates an inquiry's hosted-flow session ~24h after creation. A bare
``?inquiry-id=...`` link opened after that lands on Persona's own "Session
expired. Please restart this process or request a new link to continue." page,
which has no restart button — the origin app must mint a fresh link via
``POST /inquiries/{id}/resume`` (returns ``meta.session-token``).

These tests pin:
- ``get_verification_url`` can carry a session token
- ``extract_session_token`` parses Persona's resume payload (kebab + snake)
- ``GET /kyc/status`` actually mints a resume token for in-progress inquiries
- Persona's ``expired`` inquiry status is handled by both sync paths instead of
  falling into the unknown-status branch

Runs under pytest *or* standalone:  python tests/test_kyc_resume_session.py
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.persona_client import PersonaClient


def test_verification_url_includes_session_token():
    url = PersonaClient.get_verification_url(
        "inq_ABC123", "https://app.example.com/kyc/callback", session_token="tok_XYZ"
    )
    assert "inquiry-id=inq_ABC123" in url
    assert "session-token=tok_XYZ" in url
    assert "redirect-uri=https://app.example.com/kyc/callback" in url


def test_verification_url_without_token_unchanged():
    # Backward compatible: no token -> same shape as before.
    url = PersonaClient.get_verification_url("inq_ABC123")
    assert url == "https://inquiry.withpersona.com/verify?inquiry-id=inq_ABC123"


def test_extract_session_token_from_resume_payload():
    kebab = {"data": {"id": "inq_x"}, "meta": {"session-token": "tok_kebab"}}
    snake = {"data": {"id": "inq_x"}, "meta": {"session_token": "tok_snake"}}
    assert PersonaClient.extract_session_token(kebab) == "tok_kebab"
    assert PersonaClient.extract_session_token(snake) == "tok_snake"
    assert PersonaClient.extract_session_token({"meta": {}}) is None
    assert PersonaClient.extract_session_token({}) is None
    assert PersonaClient.extract_session_token(None) is None


def test_resume_inquiry_exists():
    # The client must expose the resume call the status endpoint depends on.
    assert callable(getattr(PersonaClient, "resume_inquiry", None))


def test_status_endpoint_mints_resume_token():
    # Source pin: GET /kyc/status must resume the inquiry (fresh session token)
    # rather than serving a bare inquiry-id link that dies after ~24h.
    from app.api.v1.kyc import get_kyc_status
    src = inspect.getsource(get_kyc_status)
    assert "resume_inquiry" in src, (
        "GET /kyc/status no longer resumes the Persona inquiry - returning "
        "users will hit Persona's 'Session expired' dead end again"
    )


def test_pending_means_user_action_not_review():
    # Persona "pending" = the user started but hasn't finished the flow. All
    # three status mappers must keep it actionable (IN_PROGRESS) — mapping it
    # to PENDING_REVIEW hid the continue link and stranded mid-flow users.
    import re
    from app.api.v1.kyc import get_kyc_status, sync_kyc_status
    from app.api.v1.webhooks import persona_webhook

    src = inspect.getsource(persona_webhook)
    assert '("pending", "in-progress")' in src, (
        "webhook groups Persona 'pending' with review states again"
    )
    for fn in (get_kyc_status, sync_kyc_status):
        s = inspect.getsource(fn)
        # status_str, not verification_status — "completed"+verification-status
        # "pending" genuinely IS under review and must stay PENDING_REVIEW.
        m = re.search(r'status_str == "pending":(.*?)(?:\n\s*elif )', s, re.S)
        assert m, f"{fn.__name__} lost its 'pending' branch"
        assert "KYCStatus.IN_PROGRESS" in m.group(1), (
            f"{fn.__name__} maps Persona 'pending' away from IN_PROGRESS"
        )


def test_both_sync_paths_handle_expired_status():
    # Persona reports 'expired' for stale inquiries; both sync paths must map it
    # explicitly (resume revives it) instead of the unknown-status fallthrough.
    from app.api.v1.kyc import get_kyc_status, sync_kyc_status
    for fn in (get_kyc_status, sync_kyc_status):
        src = inspect.getsource(fn)
        assert '"expired"' in src, f"{fn.__name__} does not handle Persona status 'expired'"


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
