"""API surface audit: the endpoint contract the frontend and Postman suite call.

QA requirement: "API testing". Pins the existence and HTTP method of every
critical endpoint across all modules, static-before-dynamic route ordering
(the /documents/statistics 422 bug class), and the absence of path+method
collisions (two routers share the /api/v1/chat prefix — a collision silently
shadows one handler).

Runs under pytest *or* standalone:  python tests/test_api_surface_audit.py
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute

from app.main import app

# (method, path) pairs the frontend/Postman collection depend on. Removing or
# renaming any of these is a breaking API change and must be deliberate.
CRITICAL_ENDPOINTS = [
    # Auth & session
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/request-password-reset"),
    ("POST", "/api/v1/auth/reset-password"),
    # Users & accounts
    ("GET", "/api/v1/users/me"),
    ("PUT", "/api/v1/users/me"),
    ("GET", "/api/v1/accounts"),
    # KYC / KYB
    ("POST", "/api/v1/kyc/start"),
    ("GET", "/api/v1/kyc/status"),
    ("GET", "/api/v1/kyc/rejection-reason"),
    ("POST", "/api/v1/kyc/resubmit"),
    ("POST", "/api/v1/kyb/start"),
    ("GET", "/api/v1/kyb/status"),
    ("POST", "/api/v1/kyb/submit"),
    # Assets lifecycle
    ("POST", "/api/v1/assets"),
    ("GET", "/api/v1/assets"),
    ("GET", "/api/v1/assets/{asset_id}"),
    ("PUT", "/api/v1/assets/{asset_id}"),
    ("DELETE", "/api/v1/assets/{asset_id}"),
    ("POST", "/api/v1/assets/{asset_id}/appraisals"),
    ("POST", "/api/v1/assets/{asset_id}/sale-requests"),
    ("GET", "/api/v1/assets/ai/usage"),
    ("GET", "/api/v1/assets/{asset_id}/shared"),
    ("GET", "/api/v1/assets/shared-with-me"),
    # Marketplace browse (public) + trade workflow
    ("GET", "/api/v1/marketplace/search"),
    ("GET", "/api/v1/marketplace/categories"),
    ("GET", "/api/v1/marketplace/listings"),
    ("GET", "/api/v1/marketplace/listings/{listing_id}"),
    ("POST", "/api/v1/marketplace/listings"),
    ("POST", "/api/v1/marketplace/listings/{listing_id}/approve"),
    ("POST", "/api/v1/marketplace/listings/{listing_id}/reject"),
    ("POST", "/api/v1/marketplace/listings/{listing_id}/offers"),
    ("POST", "/api/v1/marketplace/offers/{offer_id}/accept"),
    ("POST", "/api/v1/marketplace/offers/{offer_id}/reject"),
    ("POST", "/api/v1/marketplace/offers/{offer_id}/counter"),
    ("POST", "/api/v1/marketplace/offers/{offer_id}/withdraw"),
    # Escrow workflow
    ("GET", "/api/v1/marketplace/escrow/{escrow_id}"),
    ("POST", "/api/v1/marketplace/escrow/{escrow_id}/fund"),
    ("POST", "/api/v1/marketplace/escrow/{escrow_id}/release"),
    ("POST", "/api/v1/marketplace/escrow/{escrow_id}/refund"),
    ("POST", "/api/v1/marketplace/escrow/{escrow_id}/dispute"),
    ("POST", "/api/v1/admin/escrow/{escrow_id}/release"),
    ("POST", "/api/v1/admin/escrow/{escrow_id}/refund"),
    # Payments & subscriptions
    ("GET", "/api/v1/subscriptions"),
    ("POST", "/api/v1/subscriptions"),
    ("GET", "/api/v1/subscriptions/plans"),
    ("GET", "/api/v1/subscriptions/limits"),
    ("POST", "/api/v1/subscriptions/cancel"),
    ("PATCH", "/api/v1/admin/subscriptions/{subscription_id}/plan"),
    ("PATCH", "/api/v1/admin/subscriptions/{subscription_id}/cancel"),
    # Banking
    ("POST", "/api/v1/banking/link-token"),
    # Documents
    ("POST", "/api/v1/documents/upload"),
    ("GET", "/api/v1/documents/statistics"),
    ("GET", "/api/v1/documents/{document_id}"),
    # Support tickets (both canonical and alias reply paths)
    ("POST", "/api/v1/support/tickets"),
    ("GET", "/api/v1/support/tickets"),
    ("POST", "/api/v1/support/tickets/{ticket_id}/replies"),
    ("POST", "/api/v1/support/tickets/{ticket_id}/comments"),
    ("GET", "/api/v1/support/tickets/{ticket_id}/replies"),
    ("GET", "/api/v1/support/tickets/{ticket_id}/comments"),
    # Notifications
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/notifications/unread-count"),
    ("POST", "/api/v1/notifications/read-all"),
    # Referrals
    ("GET", "/api/v1/referrals"),
    ("GET", "/api/v1/referrals/list"),
    # Admin & CRM
    ("GET", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/subscriptions"),
    ("GET", "/api/v1/crm/users"),
    # Webhooks (external integrations)
    ("POST", "/api/v1/webhooks/stripe"),
    ("POST", "/api/v1/webhooks/persona"),
    ("POST", "/api/v1/webhooks/plaid"),
]


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _route_set():
    pairs = set()
    for r in _api_routes():
        for m in r.methods:
            pairs.add((m, r.path))
    return pairs


def test_all_critical_endpoints_exist():
    mounted = _route_set()
    missing = [ep for ep in CRITICAL_ENDPOINTS if ep not in mounted]
    assert not missing, (
        "critical endpoints missing from the app — breaking API change:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in missing)
    )


def test_no_path_method_collisions():
    # chat.router and chat_conversations.router share /api/v1/chat; a duplicate
    # (path, method) means FastAPI serves whichever registered first and the
    # other handler is dead code.
    c = Counter()
    for r in _api_routes():
        for m in r.methods:
            c[(m, r.path)] += 1
    dups = sorted(k for k, v in c.items() if v > 1)
    assert not dups, f"duplicate (method, path) registrations shadow handlers: {dups}"


def test_documents_statistics_registered_before_dynamic_route():
    # Regression pin for the reported 422: GET /documents/statistics was being
    # captured by /documents/{document_id} and failed UUID parsing. FastAPI
    # matches in registration order, so the static path must come first.
    paths = [r.path for r in _api_routes()]
    static_idx = paths.index("/api/v1/documents/statistics")
    dynamic_idx = paths.index("/api/v1/documents/{document_id}")
    assert static_idx < dynamic_idx, (
        "/documents/statistics is registered AFTER /documents/{document_id} — "
        "it will 422 as a failed UUID parse (reported QA bug)"
    )


def test_support_reply_alias_shares_handler():
    # /comments is an alias for /replies; both must dispatch to the same
    # endpoint function or their behavior drifts apart.
    routes = {
        r.path: r for r in _api_routes()
        if r.path in (
            "/api/v1/support/tickets/{ticket_id}/replies",
            "/api/v1/support/tickets/{ticket_id}/comments",
        ) and "POST" in r.methods
    }
    assert len(routes) == 2, f"expected both reply paths, found {sorted(routes)}"
    handlers = {r.endpoint.__name__ for r in routes.values()}
    assert len(handlers) == 1, (
        f"replies/comments dispatch to different handlers {handlers} — alias drift"
    )


def test_marketplace_browse_endpoints_are_public():
    # The home page renders from /search + /categories with no session; if
    # these gain an auth dependency, the public marketplace goes blank.
    for path in ("/api/v1/marketplace/search", "/api/v1/marketplace/categories"):
        (route,) = [r for r in _api_routes() if r.path == path and "GET" in r.methods]
        dep_names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "require_kyc_verified" not in dep_names, f"{path} must not be KYC-gated"
        assert "get_current_user" not in dep_names, f"{path} must stay anonymous"


def test_webhooks_have_no_auth_dependencies():
    # Stripe/Persona/Plaid sign their own requests; a JWT dependency here
    # breaks every integration callback.
    for path in ("/api/v1/webhooks/stripe", "/api/v1/webhooks/persona", "/api/v1/webhooks/plaid"):
        (route,) = [r for r in _api_routes() if r.path == path and "POST" in r.methods]
        dep_names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
        assert "get_current_user" not in dep_names, f"{path} must not require a user JWT"
        assert "require_kyc_verified" not in dep_names, f"{path} must not be KYC-gated"


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
