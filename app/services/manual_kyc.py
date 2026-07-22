"""Manual KYC fallback — pure helpers for the tokenized verification link flow.

When Persona verification fails (status rejected/expired), an admin can email
the user a manual-verification link. The token in that link is the credential:
the user opens a public page, uploads a selfie + ID document, and the KYC moves
to pending_review for admin review. Route handlers live in app/api/v1/kyc.py
(public token endpoints) and app/api/v1/admin.py (send-link); everything
policy-shaped lives here so it can be tested without a database.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.security import generate_reset_token
from app.models.kyc import KYCStatus
from app.utils.upload_helpers import resolve_content_type

MANUAL_LINK_TTL_DAYS = 7
MANUAL_UPLOAD_MAX_BYTES = 10 * 1024 * 1024

# Upload slot -> KYCDocument.document_type (mirrors Persona's
# government_id_front / government_id_back / selfie_center naming).
MANUAL_DOC_TYPES = {
    "selfie": "manual_selfie",
    "id_front": "manual_id_front",
    "id_back": "manual_id_back",
}

_SELFIE_ALLOWED = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
_DOCUMENT_ALLOWED = _SELFIE_ALLOWED | {"application/pdf"}

# Only failed verifications go through the manual fallback; anything still
# moving through Persona (or already approved) keeps its normal flow.
_SENDABLE_STATUSES = {KYCStatus.REJECTED, KYCStatus.EXPIRED}


def issue_manual_token(now: Optional[datetime] = None) -> tuple:
    """Mint a (token, expires_at) pair for a manual verification link."""
    now = now or datetime.now(timezone.utc)
    return generate_reset_token(), now + timedelta(days=MANUAL_LINK_TTL_DAYS)


def _as_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def manual_token_state(expires_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    """State of a FOUND token record: 'ok' or 'expired'.

    (An unknown/cleared token never reaches here — that's a 404 at the route.)
    Naive datetimes are normalized to UTC; legacy rows can come back tz-naive
    and naive<->aware comparison raises.
    """
    expires_at = _as_aware_utc(expires_at)
    if expires_at is None:
        return "expired"
    now = _as_aware_utc(now) or datetime.now(timezone.utc)
    return "ok" if expires_at >= now else "expired"


def manual_verification_url(token: str, base: Optional[str] = None) -> str:
    if not base:
        from app.config import settings
        base = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"
    return f"{base.rstrip('/')}/manual-verification?token={token}"


def can_send_manual_link(status: KYCStatus) -> bool:
    return status in _SENDABLE_STATUSES


def validate_manual_upload(field: str, filename: str, reported_type: Optional[str], size: int) -> str:
    """Validate one uploaded file for its slot; return the resolved content type.

    Raises ValueError with a user-safe message on any policy violation.
    """
    if field not in MANUAL_DOC_TYPES:
        allowed = ", ".join(MANUAL_DOC_TYPES)
        raise ValueError(f"Unknown upload field '{field}'. Expected one of: {allowed}.")
    if size > MANUAL_UPLOAD_MAX_BYTES:
        raise ValueError(
            f"File for '{field}' is too large ({size} bytes). Maximum size is 10MB."
        )
    content_type = resolve_content_type(filename or "upload", reported_type)
    allowed_types = _SELFIE_ALLOWED if field == "selfie" else _DOCUMENT_ALLOWED
    if content_type not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ValueError(
            f"Unsupported file type '{content_type}' for '{field}'. Allowed: {allowed}."
        )
    return content_type
