"""
Webhook endpoints for Persona (KYC) and Plaid (banking).
Verification is performed via signature validation.
"""
import hmac
import hashlib
import json
import time
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, status, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt as jose_jwt
from jose.exceptions import JWTError
from app.database import get_db
from app.config import settings
from app.models.kyc import KYCVerification, KYCStatus
from app.models.banking import LinkedAccount
from app.models.payment import Subscription, SubscriptionStatus
from app.integrations.plaid_client import PlaidClient
from app.integrations.stripe_client import StripeClient, subscription_id_from_invoice
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


def _parse_persona_event(data: dict) -> dict:
    """Extract the inquiry id + status from a Persona webhook body.

    Persona nests the affected resource under ``data.attributes.payload.data``; the
    TOP-LEVEL ``data.id`` is the EVENT id (``evt_...``), NOT the inquiry id
    (``inq_...``). Reading the top-level id (the old bug) meant the KYC lookup never
    matched and the webhook silently no-op'd. Falls back to a flat shape defensively,
    and derives status from the event name (e.g. ``inquiry.approved`` -> ``approved``)
    when the resource omits an explicit ``status``.
    """
    top = (data or {}).get("data", {}) or {}
    event_attrs = top.get("attributes", {}) or {}
    event_type = event_attrs.get("name") or top.get("type")

    inner = ((event_attrs.get("payload") or {}).get("data")) or {}
    resource = inner if inner.get("id") else top
    attributes = resource.get("attributes") or {}

    inquiry_id = resource.get("id") or attributes.get("inquiry-id")
    status_value = (attributes.get("status") or "").lower()
    if not status_value and event_type and "." in event_type:
        status_value = event_type.rsplit(".", 1)[-1].lower()

    return {
        "event_type": event_type,
        "inquiry_id": inquiry_id,
        "status": status_value,
        "attributes": attributes,
    }


@router.post("/persona")
@limiter.exempt
async def persona_webhook(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive Persona webhook events: verification approved, rejected, document requested.
    Updates user KYC status automatically, then captures the user's docs/images and
    extracted fields for later admin review (as a background task).
    """
    body = await request.body()
    signature = request.headers.get("Persona-Signature", "")
    if not verify_persona_signature(body, signature):
        record_webhook_failure("persona")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")
    try:
        data = json.loads(body)
        parsed = _parse_persona_event(data)
        event_type = parsed["event_type"]
        inquiry_id = parsed["inquiry_id"]
        attributes = parsed["attributes"]
        status_value = parsed["status"]
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
        # Map Persona statuses to our KYCStatus
        if status_value in ("approved", "completed"):
            kyc.status = KYCStatus.APPROVED
            kyc.verified_at = datetime.utcnow()
            kyc.rejection_reason = None
        elif status_value in ("declined", "failed", "rejected"):
            kyc.status = KYCStatus.REJECTED
            kyc.rejection_reason = attributes.get("rejection-reason") or attributes.get("reason") or "Verification rejected"
        elif status_value in ("pending", "in-progress", "needs-review", "marked-for-review"):
            kyc.status = KYCStatus.PENDING_REVIEW
        # document-requested: Persona may send when more documents are needed
        if "document" in (event_type or "") or "document-requested" in str(attributes):
            kyc.documents_submitted = True
        await db.commit()
        logger.info(f"Persona webhook: updated KYC {kyc.id} to {kyc.status}")

        # On a terminal outcome, notify the user (bell + realtime WS) — without the
        # Persona redirect flow enabled this is how the user learns the result —
        # and capture the user's Persona docs/images + fields for admin review.
        # Capture runs after we ack Persona so a slow download never blocks the 200.
        if status_value in ("approved", "completed", "declined", "failed", "rejected"):
            try:
                from app.services.notification_service import NotificationService
                from app.models.notification import NotificationType
                if kyc.status == KYCStatus.APPROVED:
                    await NotificationService.create_notification(
                        db=db, account_id=kyc.account_id,
                        notification_type=NotificationType.KYC_APPROVED,
                        title="Identity verification approved",
                        message="Your identity verification is complete. You now have full access to the platform.",
                        metadata=f'{{"event": "kyc_approved", "inquiry_id": "{inquiry_id}"}}',
                        send_email=False,
                    )
                elif kyc.status == KYCStatus.REJECTED:
                    await NotificationService.create_notification(
                        db=db, account_id=kyc.account_id,
                        notification_type=NotificationType.GENERAL,
                        title="Identity verification unsuccessful",
                        message=(
                            f"Your identity verification could not be completed. "
                            f"Reason: {kyc.rejection_reason or 'Verification rejected'}. "
                            f"You can restart verification from your account."
                        ),
                        metadata=f'{{"event": "kyc_rejected", "inquiry_id": "{inquiry_id}"}}',
                        send_email=False,
                    )
            except Exception as e:
                logger.error(f"Persona webhook: failed to notify user for KYC {kyc.id}: {e}")

            from app.services.persona_capture import PersonaCaptureService
            background.add_task(PersonaCaptureService.capture, kyc.account_id, inquiry_id)

        return {"received": True}
    except Exception as e:
        record_webhook_failure("persona")
        logger.error(f"Persona webhook error: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed")


def _period_from_stripe_subscription(sub: dict) -> tuple:
    """(start, end) as aware UTC datetimes, or (None, None)."""
    from datetime import timezone as _tz

    def to_dt(ts):
        return datetime.fromtimestamp(ts, tz=_tz.utc) if ts else None

    return to_dt(sub.get("current_period_start")), to_dt(sub.get("current_period_end"))


def _plan_from_stripe_subscription(sub: dict):
    """(plan_tier, billing_cycle, amount) from the subscription's active price.

    Our Stripe prices carry plan_tier / billing_cycle in metadata (set at catalog
    creation), so Stripe is the source of truth for which plan the customer actually
    pays for. This is what lets an upgrade land locally only after its invoice is paid.
    """
    from decimal import Decimal

    items = ((sub.get("items") or {}).get("data") or [])
    if not items:
        return None, None, None
    price = items[0].get("price") or {}
    meta = price.get("metadata") or {}
    unit_amount = price.get("unit_amount")
    amount = (Decimal(unit_amount) / Decimal(100)) if unit_amount is not None else None
    return meta.get("plan_tier"), meta.get("billing_cycle"), amount


async def _apply_stripe_subscription_event(db: AsyncSession, event: dict) -> str:
    """Apply one Stripe event to the local Subscription row. Idempotent by design:
    Stripe redelivers, and a second invoice.payment_succeeded must not double-apply."""
    event_type = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    if event_type in ("invoice.payment_succeeded", "invoice.payment_failed"):
        sub_id = subscription_id_from_invoice(obj)
        if not sub_id:
            logger.info(f"Stripe {event_type}: invoice has no subscription; ignoring")
            return "ignored_no_subscription"
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub_id = obj.get("id")
    else:
        return "ignored_unhandled_type"

    if not sub_id:
        logger.warning(f"Stripe {event_type}: could not resolve subscription id")
        return "ignored_no_id"

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        logger.info(f"Stripe {event_type}: no local subscription for {sub_id}")
        return "ignored_unknown_subscription"

    if event_type == "invoice.payment_succeeded":
        if subscription.status == SubscriptionStatus.ACTIVE:
            return "noop_already_active"
        subscription.status = SubscriptionStatus.ACTIVE
    elif event_type == "invoice.payment_failed":
        subscription.status = SubscriptionStatus.PAST_DUE
    elif event_type == "customer.subscription.deleted":
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.utcnow()
    elif event_type == "customer.subscription.updated":
        start, end = _period_from_stripe_subscription(obj)
        if start:
            subscription.current_period_start = start
        if end:
            subscription.current_period_end = end

        tier, cycle, amount = _plan_from_stripe_subscription(obj)
        if tier:
            subscription.plan_tier = tier
        if cycle:
            subscription.billing_cycle = cycle
        if amount is not None:
            subscription.amount = amount

        if obj.get("status") == "canceled":
            subscription.status = SubscriptionStatus.CANCELLED
        elif obj.get("status") == "active" and subscription.status != SubscriptionStatus.ACTIVE:
            subscription.status = SubscriptionStatus.ACTIVE

    await db.commit()
    logger.info(f"Stripe {event_type}: subscription {subscription.id} -> {subscription.status}")
    return "applied"


@router.post("/stripe")
@limiter.exempt
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Canonical Stripe webhook. Open router — Stripe cannot authenticate.

    Security rests on HMAC signature verification, exactly as Persona's does. Never
    mount this under a router carrying an auth or KYC dependency: the previous home
    (/api/v1/payments/webhook) was KYC-gated and returned 401 to every Stripe event.
    """
    body = await request.body()
    signature = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature")
    if not signature:
        record_webhook_failure("stripe")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature")

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not set; rejecting webhook (fail closed)")
        record_webhook_failure("stripe")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    event = StripeClient.verify_webhook_signature(body, signature)
    if not event:
        record_webhook_failure("stripe")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        outcome = await _apply_stripe_subscription_event(db, event)
        return {"received": True, "outcome": outcome}
    except Exception as e:
        record_webhook_failure("stripe")
        logger.error(f"Stripe webhook error: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed"
        )


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
