"""Full functional coverage smoke: every product module is mounted and serving.

QA requirement: "Full functional testing across all modules". This suite pins
the platform's module inventory — if a router silently drops out of
app/main.py registration (a real class of deploy accident), an entire feature
area 404s while /health stays green. Each module must be present with at
least one route, the global response-envelope and exception plumbing must be
wired, and both realtime WebSocket endpoints must exist.

Runs under pytest *or* standalone:  python tests/test_functional_module_smoke.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.main import app

# Every product module that must be serving routes, keyed by the module name
# under app/api/v1/. Dropping any of these from main.py registration is a
# platform outage for that feature area.
EXPECTED_MODULES = {
    "auth_new", "users", "accounts", "kyc", "kyb", "subscriptions",
    "notifications", "assets", "marketplace", "admin", "market", "webhooks",
    "portfolio", "trading", "payments", "banking", "documents", "files",
    "support", "reports", "chat", "chat_conversations", "analytics",
    "investment", "tasks", "reminders", "concierge", "crm", "entities",
    "compliance", "referrals", "advisor",
}


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _module_of(route):
    return route.endpoint.__module__.rsplit(".", 1)[-1]


def test_every_product_module_is_mounted():
    mounted = {_module_of(r) for r in _api_routes()}
    missing = EXPECTED_MODULES - mounted
    assert not missing, (
        f"modules with ZERO routes mounted: {sorted(missing)} — "
        "a feature area has dropped out of app/main.py router registration"
    )


def test_route_count_sanity():
    count = len(_api_routes())
    assert count >= 400, (
        f"only {count} API routes mounted (expected 400+) — "
        "a large router block has been lost"
    )


def test_all_v1_routes_live_under_api_v1_prefix():
    # Everything except app-level utility routes must be namespaced.
    allowed_bare = {"/", "/health", "/{full_path:path}"}
    stragglers = [
        r.path for r in _api_routes()
        if not r.path.startswith("/api/v1") and r.path not in allowed_bare
    ]
    assert not stragglers, f"routes outside /api/v1 namespace: {stragglers}"


def test_health_root_and_docs_exposed():
    paths = {r.path for r in _api_routes()}
    assert "/health" in paths, "health probe missing — deploy checks will fail"
    assert "/" in paths
    assert app.docs_url == "/docs", "Swagger UI must stay at /docs"
    assert app.openapi_url == "/openapi.json"


def test_response_envelope_middleware_installed():
    names = {m.cls.__name__ for m in app.user_middleware}
    assert any("ResponseEnvelope" in n for n in names), (
        f"ResponseEnvelopeMiddleware missing from middleware stack {names} — "
        "clients depend on the success/status_code/message/data envelope"
    )


def test_cors_middleware_installed():
    names = {m.cls.__name__ for m in app.user_middleware}
    assert "CORSMiddleware" in names, "CORS middleware missing — every browser call breaks"


def test_exception_handlers_registered():
    # FastAPI keys handlers by exception class; the app registers handlers for
    # HTTPException, validation errors, and a catch-all. Losing the catch-all
    # returns bare tracebacks to clients.
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError

    handled = set(app.exception_handlers.keys())
    assert HTTPException in handled, "HTTPException handler missing"
    assert RequestValidationError in handled, "422 validation handler missing"
    assert Exception in handled, "global catch-all handler missing"


def test_realtime_websocket_routes_registered():
    ws_paths = {r.path for r in app.routes if isinstance(r, WebSocketRoute)}
    assert "/api/v1/ws/notifications" in ws_paths, (
        "notifications WebSocket missing — the bell never updates live"
    )
    assert "/ws/chat" in ws_paths, "chat WebSocket missing — no realtime chat delivery"


def test_options_catch_all_for_preflight():
    # The explicit OPTIONS catch-all guarantees CORS preflights get answered
    # even for unknown paths (kept because some hosts strip auto-OPTIONS).
    options_routes = [
        r for r in _api_routes() if "OPTIONS" in r.methods and "full_path" in r.path
    ]
    assert options_routes, "OPTIONS catch-all route missing — preflights may 405"


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
