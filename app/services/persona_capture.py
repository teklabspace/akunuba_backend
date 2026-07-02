"""Capture a user's Persona verification artifacts into our own system.

On a terminal Persona webhook (approved/declined/completed) we pull the inquiry's
verifications, extract the identity fields + per-check results, download the
uploaded ID/selfie images, and store copies in a private Supabase bucket so an
admin can later review and override the automated decision.

The parsing (`parse_inquiry`) is pure and unit-tested; `PersonaCaptureService.capture`
does the network + DB side and is designed to never raise into the caller (it
records failure on the KYC row so an admin can trigger a re-capture).
"""
import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, delete

from app.config import settings
from app.integrations.persona_client import PersonaClient
from app.integrations.supabase_client import SupabaseClient
from app.models.kyc import KYCVerification, KYCDocument, KYCCaptureStatus
from app.utils.logger import logger


# Persona (kebab-case) attribute -> our snake_case field name.
FIELD_KEYS = {
    "name-first": "name_first",
    "name-middle": "name_middle",
    "name-last": "name_last",
    "birthdate": "birthdate",
    "identification-number": "identification_number",
    "expiration-date": "expiration_date",
    "issue-date": "issue_date",
    "address-street-1": "address_street_1",
    "address-street-2": "address_street_2",
    "address-city": "address_city",
    "address-subdivision": "address_subdivision",
    "address-postal-code": "address_postal_code",
    "country-code": "country_code",
    "sex": "sex",
}

_PHOTO_SUFFIX = "-photo-url"


def _safe_doc_type(raw: str) -> str:
    """Sanitize a document_type so it's safe as a storage-path segment.

    Persona is trusted, but this is cheap defense-in-depth: strip anything that
    isn't [a-z0-9_], collapsing the rest so a key like '../../x' can't traverse.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", (raw or "").lower()).strip("_")
    return cleaned or "document"


def parse_inquiry(inquiry_json: Dict[str, Any]) -> Dict[str, Any]:
    """Pure transform: Persona inquiry(+verifications) JSON -> fields/checks/photos.

    Returns {"extracted_fields": {...}, "checks": [...], "photos": [{document_type, url}]}.
    Defensive against missing keys / shape drift.
    """
    included = inquiry_json.get("included") or []
    fields: Dict[str, Any] = {}
    checks: List[Dict[str, Any]] = []
    photos: List[Dict[str, str]] = []

    for obj in included:
        otype = obj.get("type", "") or ""
        if not otype.startswith("verification"):
            continue
        vtype = otype.split("/")[-1].replace("-", "_")  # e.g. government_id, selfie
        attrs = obj.get("attributes", {}) or {}

        # Extracted identity fields (take the first non-empty value seen).
        for k, dest in FIELD_KEYS.items():
            v = attrs.get(k)
            if v and not fields.get(dest):
                fields[dest] = v

        # Per-check results.
        for c in (attrs.get("checks") or []):
            checks.append({
                "verification": vtype,
                "name": c.get("name"),
                "status": c.get("status"),
                "reasons": c.get("reasons") or [],
            })

        # Photo URLs (front/back/center/left/right...).
        for k, v in attrs.items():
            if isinstance(k, str) and k.endswith(_PHOTO_SUFFIX) and v:
                position = k[: -len(_PHOTO_SUFFIX)]
                doc_type = _safe_doc_type(f"{vtype}_{position}")
                photos.append({"document_type": doc_type, "url": v})

    return {"extracted_fields": fields, "checks": checks, "photos": photos}


def _sniff_image(data: bytes) -> tuple:
    """Return (extension, mime) from magic bytes; default to jpeg."""
    if data[:8].startswith(b"\x89PNG"):
        return "png", "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if data[:4] == b"%PDF":
        return "pdf", "application/pdf"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    return "jpg", "image/jpeg"


class PersonaCaptureService:
    @staticmethod
    async def capture(account_id: UUID, inquiry_id: str) -> None:
        """Fetch + store a user's Persona docs/fields/checks. Never raises."""
        from app.database import AsyncSessionLocal

        bucket = settings.KYC_DOCUMENTS_BUCKET
        async with AsyncSessionLocal() as db:
            kyc = (await db.execute(
                select(KYCVerification).where(KYCVerification.account_id == account_id)
            )).scalar_one_or_none()
            if not kyc:
                logger.warning(f"KYC capture: no KYC row for account {account_id}")
                return

            kyc.capture_status = KYCCaptureStatus.PENDING
            await db.commit()

            try:
                inquiry = await asyncio.to_thread(
                    PersonaClient.get_inquiry_with_verifications, inquiry_id
                )
                if not inquiry:
                    raise RuntimeError("Could not fetch inquiry+verifications from Persona")

                parsed = parse_inquiry(inquiry)
                await asyncio.to_thread(SupabaseClient.ensure_bucket, bucket, False)

                # Re-capture is idempotent: clear prior docs for this KYC first.
                await db.execute(delete(KYCDocument).where(KYCDocument.kyc_id == kyc.id))

                stored = 0
                for photo in parsed["photos"]:
                    data = await asyncio.to_thread(PersonaClient.download_file, photo["url"])
                    if not data:
                        continue
                    ext, mime = _sniff_image(data)
                    path = f"kyc/{account_id}/{inquiry_id}/{photo['document_type']}.{ext}"
                    await asyncio.to_thread(
                        SupabaseClient.upload_file, bucket, path, data, mime, True
                    )
                    db.add(KYCDocument(
                        kyc_id=kyc.id,
                        account_id=account_id,
                        persona_inquiry_id=inquiry_id,
                        document_type=photo["document_type"],
                        bucket=bucket,
                        file_path=path,
                        mime_type=mime,
                        file_size=len(data),
                        persona_source_url=photo["url"],
                    ))
                    stored += 1

                kyc.extracted_fields = parsed["extracted_fields"] or None
                kyc.checks = parsed["checks"] or None
                if stored > 0:
                    kyc.documents_submitted = True
                kyc.capture_status = KYCCaptureStatus.CAPTURED
                kyc.capture_error = None
                kyc.captured_at = datetime.utcnow()
                await db.commit()
                logger.info(f"KYC capture done for account {account_id}: {stored} file(s)")

            except Exception as e:
                await db.rollback()
                # Record failure on a fresh read so an admin can re-capture.
                kyc2 = (await db.execute(
                    select(KYCVerification).where(KYCVerification.account_id == account_id)
                )).scalar_one_or_none()
                if kyc2:
                    kyc2.capture_status = KYCCaptureStatus.FAILED
                    kyc2.capture_error = str(e)[:500]
                    await db.commit()
                logger.error(f"KYC capture failed for account {account_id}: {e}", exc_info=True)
