"""Regression: asset share-link routes must keep their exact gating.

The bug this fixes: GET /assets/{id}/shared was written as a public endpoint
(the per-share access code is the credential) but was mounted on the KYC-gated
assets router, so every anonymous share-link visit got 401 AUTH_REQUIRED — the
endpoint's entire audience is people without accounts. Any future move back
under a gated router must fail loudly here.

Also pins the companion endpoint: GET /assets/shared-with-me must require auth
(it lists grants addressed to the caller's verified email) but must NOT require
KYC — recipients are fresh signups.

Runs under pytest *or* standalone:  python tests/test_shared_asset_route_open.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.exceptions import GoneException
from app.main import app

SHARED_PATH = "/api/v1/assets/{asset_id}/shared"
SHARED_WITH_ME_PATH = "/api/v1/assets/shared-with-me"


def _routes_for(path):
    return [r for r in app.routes if getattr(r, "path", None) == path]


def _dependency_names(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}


def test_shared_route_exists_exactly_once():
    routes = _routes_for(SHARED_PATH)
    assert len(routes) == 1, (
        f"expected exactly one {SHARED_PATH} route, found {len(routes)} — "
        "a duplicate on the gated router would shadow or re-gate it"
    )


def test_shared_route_is_anonymous():
    (route,) = _routes_for(SHARED_PATH)
    names = _dependency_names(route)
    for forbidden in ("get_current_user", "require_kyc_verified"):
        assert forbidden not in names, (
            f"{forbidden} guards {SHARED_PATH}; share recipients have no account. "
            "This is the exact bug that 401'd every share link."
        )


def test_shared_with_me_requires_auth_but_not_kyc():
    routes = _routes_for(SHARED_WITH_ME_PATH)
    assert len(routes) == 1, f"{SHARED_WITH_ME_PATH} missing or duplicated"
    names = _dependency_names(routes[0])
    assert "get_current_user" in names, "shared-with-me must be authenticated"
    assert "require_kyc_verified" not in names, (
        "shared-with-me must not be KYC-gated; recipients are fresh signups"
    )


def test_gone_exception_contract():
    exc = GoneException("This share link has expired", code="SHARE_LINK_EXPIRED")
    assert exc.status_code == 410
    assert exc.code == "SHARE_LINK_EXPIRED"


def test_email_verified_check_uses_either_flag():
    # Regression: User.is_verified is the KYC/investor flag (kyc.py overwrites
    # it, often to False), NOT email verification. Every real verified-email
    # account had is_verified=False and got 403 EMAIL_NOT_VERIFIED from
    # shared-with-me. The canonical check accepts either signal.
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.api.v1.subscriptions import is_email_verified

    ts = datetime.now(timezone.utc)
    assert is_email_verified(SimpleNamespace(is_verified=False, email_verified_at=ts))
    assert is_email_verified(SimpleNamespace(is_verified=True, email_verified_at=None))
    assert not is_email_verified(SimpleNamespace(is_verified=False, email_verified_at=None))


def test_shared_with_me_gates_on_canonical_email_check():
    # Pin the endpoint to is_email_verified — reading current_user.is_verified
    # directly reintroduces the KYC-flag lockout.
    import inspect

    from app.api.v1.assets import get_assets_shared_with_me

    src = inspect.getsource(get_assets_shared_with_me)
    assert "is_email_verified(" in src, "shared-with-me must use the canonical email check"
    assert "current_user.is_verified" not in src, (
        "current_user.is_verified is the KYC/investor flag; using it locks out "
        "every email-verified account whose KYC state ever changed"
    )


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
