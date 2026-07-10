import stripe
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any

stripe.api_key = settings.STRIPE_SECRET_KEY


def subscription_id_from_invoice(invoice: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract the subscription id from a Stripe invoice, across API versions.

    Pre-2025-03-31 payloads carry ``invoice.subscription`` (a string, or an expanded
    object). From 2025-03-31.basil onward that field was removed and the id moved to
    ``invoice.parent.subscription_details.subscription``. Our webhook endpoint is
    pinned to 2025-11-17.clover, so the new shape is what production delivers — but
    fixtures and older endpoints may use either. The installed library version pins
    OUTBOUND calls only; it does not govern inbound payload shape.

    Returns None for one-off invoices that have no subscription behind them.
    """
    invoice = invoice or {}

    sub = invoice.get("subscription")
    if isinstance(sub, dict):
        return sub.get("id")
    if isinstance(sub, str) and sub:
        return sub

    parent = invoice.get("parent") or {}
    details = parent.get("subscription_details") or {}
    nested = details.get("subscription")
    if isinstance(nested, dict):
        return nested.get("id")
    if isinstance(nested, str) and nested:
        return nested

    return None


def subscription_price_id(sub: Optional[Dict[str, Any]]) -> Optional[str]:
    """The price id of a subscription's single item, or None."""
    items = ((sub or {}).get("items") or {}).get("data") or []
    if not items:
        return None
    return (items[0].get("price") or {}).get("id")


def incomplete_subscription_action(
    prior: Optional[Dict[str, Any]], desired_price_id: str
) -> str:
    """What to do when a purchase lands on an existing INCOMPLETE local subscription.

    Returns one of:
      "reuse"    - same plan, still awaiting payment: hand back its client_secret.
      "replace"  - different plan: cancel it AND void its open invoice, then create.
      "conflict" - Stripe says it is already paid; our row is merely stale. Creating a
                   second subscription here is the double-charge.
      "create"   - nothing live to orphan.

    Never fall through to "create" while a payable invoice exists: an abandoned
    incomplete subscription keeps a finalized, open invoice that the customer can still
    pay, and once we overwrite stripe_subscription_id the webhook can no longer match it.
    """
    if not prior:
        return "create"

    status = prior.get("status")
    if status == "incomplete":
        return "reuse" if subscription_price_id(prior) == desired_price_id else "replace"
    if status in ("active", "trialing", "past_due"):
        return "conflict"
    # canceled, incomplete_expired, unpaid — nothing payable remains.
    return "create"


class StripeClient:
    @staticmethod
    def create_payment_intent(amount: int, currency: str = "usd", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                metadata=metadata or {},
            )
            return intent
        except Exception as e:
            logger.error(f"Failed to create Stripe payment intent: {e}")
            raise

    @staticmethod
    def create_customer(email: str, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata=metadata or {},
            )
            return customer
        except Exception as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise

    @staticmethod
    def create_subscription(customer_id: str, price_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Create a Stripe Subscription whose first invoice awaits payment.

        ``default_incomplete`` stops Stripe charging a payment method that does not
        exist yet, and yields a PaymentIntent client_secret for the frontend to
        confirm. Without the expand, latest_invoice.payment_intent is a bare id.
        """
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"],
                metadata=metadata or {},
            )
            return subscription
        except Exception as e:
            logger.error(f"Failed to create Stripe subscription: {e}")
            raise

    @staticmethod
    def update_subscription_price(subscription_id: str, price_id: str) -> Dict[str, Any]:
        """Swap the subscription's single item to a new price and invoice the proration now.

        ``always_invoice`` bills the difference immediately rather than silently rolling
        it into the next cycle, so an upgrade cannot take effect unpaid.
        """
        try:
            current = stripe.Subscription.retrieve(subscription_id)
            item_id = current["items"]["data"][0]["id"]
            return stripe.Subscription.modify(
                subscription_id,
                items=[{"id": item_id, "price": price_id}],
                proration_behavior="always_invoice",
                expand=["latest_invoice.payment_intent"],
            )
        except Exception as e:
            logger.error(f"Failed to update Stripe subscription price {subscription_id}: {e}")
            raise

    @staticmethod
    def retrieve_subscription(subscription_id: str) -> Dict[str, Any]:
        """Fetch a subscription with its latest invoice + payment intent expanded, so a
        reusable incomplete subscription can hand back its existing client_secret."""
        return stripe.Subscription.retrieve(
            subscription_id, expand=["latest_invoice.payment_intent"]
        )

    @staticmethod
    def discard_incomplete_subscription(sub: Dict[str, Any]) -> None:
        """Cancel an abandoned incomplete subscription and void its open invoice.

        Cancelling alone is not enough: the first invoice of a default_incomplete
        subscription is already finalized and stays payable after cancellation. A
        customer paying it later would be charged for a subscription we no longer track.
        Best-effort — a failure here must not block the new purchase, but it is logged.
        """
        sub_id = sub.get("id")
        try:
            stripe.Subscription.cancel(sub_id)
        except Exception as e:
            logger.error(f"Failed to cancel incomplete subscription {sub_id}: {e}")

        invoice = sub.get("latest_invoice") or {}
        invoice_id = invoice.get("id") if isinstance(invoice, dict) else invoice
        invoice_status = invoice.get("status") if isinstance(invoice, dict) else None
        if not invoice_id:
            return
        try:
            if invoice_status == "draft":
                stripe.Invoice.delete(invoice_id)
            elif invoice_status in (None, "open"):
                stripe.Invoice.void_invoice(invoice_id)
        except Exception as e:
            logger.error(f"Failed to void invoice {invoice_id} of {sub_id}: {e}")

    @staticmethod
    def list_invoices(customer_id: str, limit: int = 20, starting_after: Optional[str] = None) -> Dict[str, Any]:
        """List a customer's invoices, newest first. Cursor pagination only."""
        params: Dict[str, Any] = {"customer": customer_id, "limit": limit}
        if starting_after:
            params["starting_after"] = starting_after
        try:
            return stripe.Invoice.list(**params)
        except Exception as e:
            logger.error(f"Failed to list Stripe invoices for {customer_id}: {e}")
            raise

    @staticmethod
    def cancel_subscription(subscription_id: str, cancel_immediately: bool = False) -> Dict[str, Any]:
        try:
            if cancel_immediately:
                subscription = stripe.Subscription.cancel(subscription_id)
            else:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            return subscription
        except Exception as e:
            logger.error(f"Failed to cancel Stripe subscription: {e}")
            raise

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> Optional[Dict[str, Any]]:
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
            return event
        except ValueError as e:
            logger.error(f"Invalid Stripe webhook payload: {e}")
            return None
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid Stripe webhook signature: {e}")
            return None

    @staticmethod
    def create_refund(charge_id: str, amount: Optional[int] = None, reason: Optional[str] = None) -> Dict[str, Any]:
        """Create a refund for a charge"""
        try:
            refund_params = {
                "charge": charge_id,
            }
            if amount:
                refund_params["amount"] = amount
            if reason:
                refund_params["reason"] = reason
            
            refund = stripe.Refund.create(**refund_params)
            return refund
        except Exception as e:
            logger.error(f"Failed to create Stripe refund: {e}")
            raise

    @staticmethod
    def list_refunds(charge_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """List refunds for a charge or all refunds"""
        try:
            params = {"limit": limit}
            if charge_id:
                params["charge"] = charge_id
            
            refunds = stripe.Refund.list(**params)
            return refunds
        except Exception as e:
            logger.error(f"Failed to list Stripe refunds: {e}")
            raise

    @staticmethod
    def get_refund(refund_id: str) -> Dict[str, Any]:
        """Get refund details"""
        try:
            refund = stripe.Refund.retrieve(refund_id)
            return refund
        except Exception as e:
            logger.error(f"Failed to get Stripe refund: {e}")
            raise

    @staticmethod
    def list_payment_methods(customer_id: str, type: str = "card") -> Dict[str, Any]:
        """List payment methods for a customer"""
        try:
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type=type
            )
            return payment_methods
        except Exception as e:
            logger.error(f"Failed to list Stripe payment methods: {e}")
            raise

    @staticmethod
    def attach_payment_method(payment_method_id: str, customer_id: str) -> Dict[str, Any]:
        """Attach a payment method to a customer"""
        try:
            payment_method = stripe.PaymentMethod.attach(
                payment_method_id,
                customer=customer_id
            )
            return payment_method
        except Exception as e:
            logger.error(f"Failed to attach Stripe payment method: {e}")
            raise

    @staticmethod
    def detach_payment_method(payment_method_id: str) -> Dict[str, Any]:
        """Detach a payment method from a customer"""
        try:
            payment_method = stripe.PaymentMethod.detach(payment_method_id)
            return payment_method
        except Exception as e:
            logger.error(f"Failed to detach Stripe payment method: {e}")
            raise

    @staticmethod
    def retrieve_charge(charge_id: str) -> Dict[str, Any]:
        """Retrieve charge details"""
        try:
            charge = stripe.Charge.retrieve(charge_id)
            return charge
        except Exception as e:
            logger.error(f"Failed to retrieve Stripe charge: {e}")
            raise

    @staticmethod
    def get_or_create_customer(email: str, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get existing customer or create new one"""
        try:
            # Try to find existing customer
            customers = stripe.Customer.list(email=email, limit=1)
            if customers.data:
                return customers.data[0]
            
            # Create new customer
            return StripeClient.create_customer(email, name, metadata)
        except Exception as e:
            logger.error(f"Failed to get or create Stripe customer: {e}")
            raise

