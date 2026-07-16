"""Security & permission checks: RBAC matrix, JWT, hashing, gates, webhooks.

QA requirement: "Security and permission checks". Four layers are pinned here:

1. The role→permission matrix (an accidental grant to INVESTOR/ADVISOR is a
   privilege escalation; an accidental revoke from ADMIN bricks the admin UI).
2. Router-level gates: every /admin route must carry require_admin; every
   route in a KYC-gated module must carry require_kyc_verified (server-side
   enforcement, not frontend hiding).
3. Token & password crypto behavior (tamper/expiry/type-confusion rejection).
4. Webhook signature verification failing CLOSED — an unsigned Persona
   webhook must never be able to forge a KYC approval.

Runs under pytest *or* standalone:  python tests/test_security_permissions.py
"""
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute

from app.core.permissions import Permission, Role, ROLE_PERMISSIONS, has_permission
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_password_hash,
    verify_password,
)
from app.main import app

# Modules whose ENTIRE router is included with the KYC gate in app/main.py.
KYC_GATED_MODULES = {
    "portfolio", "trading", "payments", "banking", "documents", "files",
    "support", "reports", "chat", "chat_conversations", "analytics",
    "investment", "tasks", "reminders", "concierge", "crm", "entities",
    "compliance", "referrals", "advisor",
}

ADMIN_ONLY_PERMISSIONS = {
    Permission.MANAGE_USERS,
    Permission.WRITE_USERS,
    Permission.APPROVE_LISTINGS,
    Permission.MANAGE_MARKETPLACE,
    Permission.MANAGE_SUBSCRIPTIONS,
}


def _api_routes():
    return [r for r in app.routes if isinstance(r, APIRoute)]

def _deps(route):
    return {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}


# ---------------------------------------------------------------- RBAC matrix

def test_admin_holds_every_permission():
    missing = [p for p in Permission if not has_permission(Role.ADMIN, p)]
    assert not missing, f"ADMIN lost permissions {missing} — admin UI features will 403"


def test_admin_only_permissions_not_leaked():
    for role in (Role.INVESTOR, Role.ADVISOR):
        leaked = [p for p in ADMIN_ONLY_PERMISSIONS if has_permission(role, p)]
        assert not leaked, (
            f"{role.value} was granted admin-only permissions {leaked} — privilege escalation"
        )


def test_investor_permission_set_exact():
    expected = {
        Permission.READ_USERS, Permission.READ_ASSETS, Permission.READ_PORTFOLIO,
        Permission.WRITE_PORTFOLIO, Permission.TRADE, Permission.CREATE_LISTINGS,
    }
    actual = set(ROLE_PERMISSIONS[Role.INVESTOR])
    assert actual == expected, (
        f"INVESTOR permission set drifted: +{actual - expected} -{expected - actual}"
    )


def test_advisor_is_support_staff_not_marketplace_actor():
    # Advisors run support/CRM; they must NOT create listings (they moderate).
    assert has_permission(Role.ADVISOR, Permission.MANAGE_SUPPORT)
    assert has_permission(Role.ADVISOR, Permission.VIEW_ANALYTICS)
    assert not has_permission(Role.ADVISOR, Permission.CREATE_LISTINGS)
    assert not has_permission(Role.ADVISOR, Permission.APPROVE_LISTINGS)


def test_unknown_role_gets_no_permissions():
    assert not has_permission("ghost", Permission.MANAGE_USERS)


# ------------------------------------------------------------- router gating

def test_every_admin_route_requires_admin():
    admin_routes = [r for r in _api_routes() if r.endpoint.__module__ == "app.api.v1.admin"]
    assert len(admin_routes) >= 30, f"admin router shrank to {len(admin_routes)} routes"
    unguarded = [
        (sorted(r.methods), r.path) for r in admin_routes if "require_admin" not in _deps(r)
    ]
    assert not unguarded, f"admin routes WITHOUT require_admin gate: {unguarded}"


def test_every_gated_module_route_requires_kyc():
    unguarded = []
    for r in _api_routes():
        module = r.endpoint.__module__.rsplit(".", 1)[-1]
        if module in KYC_GATED_MODULES and "require_kyc_verified" not in _deps(r):
            unguarded.append((module, r.path))
    assert not unguarded, (
        f"routes in KYC-gated modules missing the gate: {unguarded} — "
        "server-side KYC enforcement has a hole"
    )


def test_assets_and_marketplace_gate_everything_not_deliberately_public():
    # These two domains have a deliberate public surface (browse, share links).
    # Anything NOT on the public_router must carry the KYC gate.
    from app.api.v1 import assets, marketplace

    public = set()
    for router, prefix in (
        (assets.public_router, "/api/v1/assets"),
        (marketplace.public_router, "/api/v1/marketplace"),
    ):
        for r in router.routes:
            public.add((prefix + r.path, tuple(sorted(r.methods))))

    leaks = []
    for r in _api_routes():
        if r.endpoint.__module__ not in ("app.api.v1.assets", "app.api.v1.marketplace"):
            continue
        if (r.path, tuple(sorted(r.methods))) in public:
            continue
        if "require_kyc_verified" not in _deps(r):
            leaks.append((sorted(r.methods), r.path))
    assert not leaks, (
        f"assets/marketplace routes neither public nor KYC-gated: {leaks} — "
        "either an exposure or an unlisted contract change"
    )


def test_kyc_gate_exempts_admins_and_uses_stable_error_code():
    import inspect
    from app.api.deps import require_kyc_verified

    src = inspect.getsource(require_kyc_verified)
    assert "Role.ADMIN" in src and "return current_user" in src, (
        "admin exemption removed — admins never do KYC and would be locked out"
    )
    assert 'code="KYC_REQUIRED"' in src, (
        "KYC_REQUIRED error code changed — the frontend keys its redirect on it"
    )


# ------------------------------------------------------------ token security

def test_access_token_roundtrip_carries_claims():
    token = create_access_token({"sub": "user-123", "role": "investor"})
    payload = decode_access_token(token)
    assert payload and payload["sub"] == "user-123" and payload["role"] == "investor"
    assert payload["type"] == "access"


def test_tampered_token_rejected():
    token = create_access_token({"sub": "user-123"})
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    assert decode_access_token(forged) is None, "signature tampering must invalidate the token"


def test_expired_token_rejected():
    token = create_access_token({"sub": "user-123"}, expires_delta=timedelta(minutes=-5))
    assert decode_access_token(token) is None, "expired tokens must not decode"


def test_refresh_and_access_tokens_are_not_interchangeable():
    # Type confusion: a stolen refresh token must not work as an access token
    # (and vice versa) — each decoder checks the embedded "type" claim.
    refresh = create_refresh_token({"sub": "user-123"})
    access = create_access_token({"sub": "user-123"})
    assert decode_access_token(refresh) is None, "refresh token accepted as access token"
    assert decode_refresh_token(access) is None, "access token accepted as refresh token"
    assert decode_refresh_token(refresh) is not None


def test_garbage_token_rejected_not_crashing():
    assert decode_access_token("not.a.jwt") is None
    assert decode_access_token("") is None


# --------------------------------------------------------- password security

def test_password_hash_roundtrip():
    hashed = get_password_hash("S3cure!pass")
    assert hashed != "S3cure!pass" and hashed.startswith("$2")
    assert verify_password("S3cure!pass", hashed)
    assert not verify_password("S3cure!wrong", hashed)


def test_same_password_hashes_differently():
    # Salted hashing: identical passwords must not produce identical hashes.
    assert get_password_hash("repeat-me") != get_password_hash("repeat-me")


def test_empty_credentials_never_verify():
    hashed = get_password_hash("anything")
    assert not verify_password("", hashed)
    assert not verify_password("anything", "")


# ------------------------------------------------------------ webhook crypto

def test_persona_webhook_fails_closed_without_secret():
    # An attacker who can reach the webhook URL must not be able to forge a
    # KYC approval just because the secret is unconfigured.
    from app.api.v1.webhooks import verify_persona_signature
    from app.config import settings

    original = settings.PERSONA_WEBHOOK_SECRET
    try:
        settings.PERSONA_WEBHOOK_SECRET = ""
        assert verify_persona_signature(b'{"data": {}}', "t=1,v1=deadbeef") is False
    finally:
        settings.PERSONA_WEBHOOK_SECRET = original


def test_persona_webhook_signature_verification_is_real_hmac():
    import hashlib
    import hmac as hmac_mod

    from app.api.v1.webhooks import verify_persona_signature
    from app.config import settings

    original = settings.PERSONA_WEBHOOK_SECRET
    try:
        settings.PERSONA_WEBHOOK_SECRET = "test-secret"
        body = b'{"data": {"attributes": {}}}'
        good = hmac_mod.new(b"test-secret", b"1700000000." + body, hashlib.sha256).hexdigest()
        assert verify_persona_signature(body, f"t=1700000000,v1={good}") is True
        assert verify_persona_signature(body, f"t=1700000000,v1={'0' * 64}") is False
        assert verify_persona_signature(body, "malformed-header") is False
    finally:
        settings.PERSONA_WEBHOOK_SECRET = original


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
