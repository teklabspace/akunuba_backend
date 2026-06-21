"""
Webhook endpoints for Persona (KYC) and Plaid (banking).
Verification is performed via signature validation.
"""
import hmac
import hashlib
import json
import time
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt as jose_jwt
from jose.exceptions import JWTError
from app.database import get_db
from app.config import settings
from app.models.kyc import KYCVerification, KYCStatus
from app.models.banking import LinkedAccount
from app.integrations.plaid_client import PlaidClient
from app.services.banking_sync_service import sync_linked_account_transactions, refresh_linked_account_balance
from app.core.metrics import record_webhook_failure
from app.core.rate_limit import limiter
from app.utils.logger import logger

router = APIRouter()

# Cache for Plaid webhook verification JWKs, keyed by key id (kid).
_PLAID_JWK_CACHE: dict = {}


def verify_persona_signature(payload: bytes, signature_header: str) -> bool:
    """Verify Persona webhook signature (HMAC-SHA256).

    Fails closed: if no secret is configured we reject the webhook rather than
    trusting an unsigned request (an attacker could otherwise forge KYC approvals).
    """
    if not settings.PERSONA_WEBHOOK_SECRET:
        logger.error("PERSONA_WEBHOOK_SECRET not set; rejecting webhook (fail closed)")
        return False
    try:
        parts = [p.strip().split("=", 1) for p in signature_header.split(",")]
        params = dict(parts)
        t = params.get("t", "")
        v1 = params.get("v1", "")
        if not t or not v1:
            return False
        body_string = f"{t}.{payload.decode('utf-8')}"
        expected = hmac.new(
            settings.PERSONA_WEBHOOK_SECRET.encode(),
            body_string.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(v1, expected)
    except Exception as e:
        logger.error(f"Persona signature verification error: {e}")
        return False


@router.post("/persona")
@limiter.exempt
async def persona_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive Persona webhook events: verification approved, rejected, document requested.
    Updates user KYC status automatically.
    """
    body = await request.body()
    signature = request.headers.get("Persona-Signature", "")
    if not verify_persona_signature(body, signature):
        record_webhook_failure("persona")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    try:
        data = json.loads(body)
        event_type = data.get("data", {}).get("attributes", {}).get("name") or data.get("data", {}).get("type")
        payload = data.get("data", {})
        inquiry_id = payload.get("id") or (payload.get("attributes") or {}).get("inquiry-id")
        if not inquiry_id:
            logger.warning("Persona webhook missing inquiry id")
            return {"received": True}
        # Find KYC by persona_inquiry_id
        result = await db.execute(
            select(KYCVerification).where(KYCVerification.persona_inquiry_id == inquiry_id)
        )
        kyc = result.scalar_one_or_none()
        if not kyc:
            logger.info(f"Persona webhook: no local KYC for inquiry {inquiry_id}")
            return {"received": True}
        attributes = payload.get("attributes", payload)
        status_value = (attributes.get("status") or "").lower()
        # Map Persona statuses to our KYCStatus
        if status_value in ("approved", "completed"):
            kyc.status = KYCStatus.APPROVED
            kyc.verified_at = datetime.utcnow()
            kyc.rejection_reason = None
        elif status_value in ("declined", "failed", "rejected"):
            kyc.status = KYCStatus.REJECTED
            kyc.rejection_reason = attributes.get("rejection-reason") or attributes.get("reason") or "Verification rejected"
        elif status_value in ("pending", "in-progress", "needs-review"):
            kyc.status = KYCStatus.PENDING_REVIEW
        # document-requested: Persona may send when more documents are needed
        if "document" in (event_type or "") or "document-requested" in str(attributes):
            kyc.documents_submitted = True
        await db.commit()
        logger.info(f"Persona webhook: updated KYC {kyc.id} to {kyc.status}")
        return {"received": True}
    except Exception as e:
        record_webhook_failure("persona")
        logger.error(f"Persona webhook error: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed")


def _get_plaid_verification_key(key_id: str) -> dict:
    """Fetch (and cache) the Plaid JWK used to verify webhook JWTs."""
    if key_id in _PLAID_JWK_CACHE:
        return _PLAID_JWK_CACHE[key_id]
    key = PlaidClient.get_webhook_verification_key(key_id)
    if key:
        _PLAID_JWK_CACHE[key_id] = key
    return key


def verify_plaid_webhook(body: bytes, verification_header: str) -> bool:
    """Verify a Plaid webhook using the Plaid-Verification JWT (ES256).

    Steps per Plaid docs: decode the JWT header to get the key id, fetch the
    matching JWK, verify the ES256 signature, check the token is recent, and
    confirm the SHA-256 of the request body matches the signed claim.
    """
    if not verification_header:
        logger.error("Plaid webhook missing Plaid-Verification header; rejecting")
        return False
    try:
        header = jose_jwt.get_unverified_header(verification_header)
    except JWTError as e:
        logger.error(f"Plaid webhook header decode failed: {e}")
        return False
    if header.get("alg") != "ES256":
        logger.error(f"Plaid webhook unexpected alg: {header.get('alg')}")
        return False
    key_id = header.get("kid")
    if not key_id:
        return False
    jwk = _get_plaid_verification_key(key_id)
    if not jwk:
        logger.error(f"Plaid webhook verification key not found for kid={key_id}")
        return False
    try:
        claims = jose_jwt.decode(
            verification_header,
            jwk,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except JWTError as e:
        logger.error(f"Plaid webhook JWT verification failed: {e}")
        return False
    # Reject tokens older than 5 minutes (replay protection).
    iat = claims.get("iat", 0)
    if abs(time.time() - iat) > 300:
        logger.warning("Plaid webhook timestamp outside tolerance; rejecting")
        return False
    expected_sha = claims.get("request_body_sha256")
    computed_sha = hashlib.sha256(body).hexdigest()
    if not expected_sha or not hmac.compare_digest(str(expected_sha), computed_sha):
        logger.error("Plaid webhook body hash mismatch; rejecting")
        return False
    return True


@router.post("/plaid")
@limiter.exempt
async def plaid_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive Plaid webhooks: transaction updates, account balance updates.
    Verified via the Plaid-Verification JWT (ES256) before any processing.
    """
    body = await request.body()
    verification_header = request.headers.get("Plaid-Verification", "")
    if not verify_plaid_webhook(body, verification_header):
        record_webhook_failure("plaid")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    try:
        data = json.loads(body)
        webhook_type = data.get("webhook_type")
        webhook_code = data.get("webhook_code")
        if webhook_type == "ITEM" and webhook_code == "ERROR":
            logger.warning(f"Plaid item error: {data.get('error')}")
            return {"received": True}
        item_id = data.get("item_id")
        if not item_id:
            return {"received": True}
        # Find linked accounts for this Plaid item
        result = await db.execute(
            select(LinkedAccount).where(
                LinkedAccount.plaid_item_id == item_id,
                LinkedAccount.is_active == True,
            )
        )
        linked_accounts = result.scalars().all()
        for la in linked_accounts:
            try:
                if webhook_type == "TRANSACTIONS":
                    await sync_linked_account_transactions(db, la.id)
                elif webhook_type in ("ITEM", "AUTH") or "balance" in (webhook_code or "").lower():
                    await refresh_linked_account_balance(db, la.id)
            except Exception as e:
                record_webhook_failure("plaid")
                logger.error(f"Plaid webhook sync failed for {la.id}: {e}")
        return {"received": True}
    except Exception as e:
        record_webhook_failure("plaid")
        logger.error(f"Plaid webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed")
