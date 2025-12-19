import stripe
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any

stripe.api_key = settings.STRIPE_SECRET_KEY


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
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata=metadata or {},
            )
            return subscription
        except Exception as e:
            logger.error(f"Failed to create Stripe subscription: {e}")
            raise

    @staticmethod
    def cancel_subscription(subscription_id: str) -> Dict[str, Any]:
        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
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

