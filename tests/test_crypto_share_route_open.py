"""Regression: crypto portfolio share-link routes must keep their exact gating.

Same trap as tests/test_shared_asset_route_open.py, one router over: every
route in app/api/v1/portfolio.py is mounted behind auth + require_kyc_verified,
so a share-resolve endpoint added to the default `router` would 401 every
anonymous visit — and share recipients have no account by definition. The
resolve endpoint therefore lives on portfolio.public_router.

Runs under pytest *or* standalone:  python tests/test_crypto_share_route_open.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app

SHARED_PATH = "/api/v1/portfolio/crypto/shared"
CREATE_PATH = "/api/v1/portfolio/crypto/share"


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
            f"{forbidden} guards {SHARED_PATH}; share recipients have no account"
        )


def test_creating_a_share_link_still_requires_auth_and_kyc():
    # Only the resolve side is public. Generating a link exposes the owner's
    # holdings, so it stays on the gated router.
    routes = _routes_for(CREATE_PATH)
    assert routes, f"{CREATE_PATH} missing"
    post = [r for r in routes if "POST" in getattr(r, "methods", set())]
    assert post, f"{CREATE_PATH} has no POST"
    names = _dependency_names(post[0])
    assert "require_kyc_verified" in names, (
        "share-link creation must stay behind the KYC gate"
    )


def test_shared_payload_excludes_owner_identifiers():
    """The snapshot is for whoever holds the link — it must not leak asset ids,
    the account id, or the owner's identity."""
    import inspect

    from app.api.v1.portfolio import _crypto_snapshot

    source = inspect.getsource(_crypto_snapshot)
    for leaked in ('"account_id"', '"asset_id"', '"user_id"', '"email"'):
        assert leaked not in source, f"shared crypto snapshot exposes {leaked}"


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
