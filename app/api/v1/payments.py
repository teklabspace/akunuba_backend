from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import Query
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.payment import Payment, PaymentStatus, PaymentMethod, Invoice, Refund
from app.integrations.stripe_client import StripeClient
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from app.utils.helpers import generate_reference_id
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class PaymentIntentCreate(BaseModel):
    amount: Decimal
    currency: str = "USD"
    payment_method: str = "card"
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PaymentIntentResponse(BaseModel):
    payment_intent_id: str
    client_secret: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime


class PaymentResponse(BaseModel):
    id: UUID
    amount: Decimal
    currency: str
    payment_method: str
    status: str
    stripe_payment_intent_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/create-intent", response_model=PaymentIntentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    payment_data: PaymentIntentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe payment intent for subscription payment"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Create Stripe payment intent
    try:
        metadata = payment_data.metadata or {}
        metadata.update({
            "account_id": str(account.id),
            "user_id": str(current_user.id),
        })
        
        stripe_intent = StripeClient.create_payment_intent(
            amount=int(payment_data.amount * 100),  # Convert to cents
            currency=payment_data.currency.lower(),
            metadata=metadata
        )
    except Exception as e:
        logger.error(f"Failed to create Stripe payment intent: {e}")
        raise BadRequestException("Failed to create payment intent")
    
    # Optionally save payment record
    try:
        payment = Payment(
            account_id=account.id,
            amount=payment_data.amount,
            currency=payment_data.currency,
            payment_method=PaymentMethod.CARD,  # Default to card
            status=PaymentStatus.PENDING,
            stripe_payment_intent_id=stripe_intent["id"],
            description=payment_data.description,
        )
        db.add(payment)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to save payment record: {e}")
        # Continue even if payment record save fails
    
    logger.info(f"Payment intent created: {stripe_intent['id']}")
    return PaymentIntentResponse(
        payment_intent_id=stripe_intent["id"],
        client_secret=stripe_intent["client_secret"],
        amount=payment_data.amount,
        currency=payment_data.currency.upper(),
        status=stripe_intent.get("status", "requires_payment_method"),
        created_at=datetime.utcnow()
    )


class PaymentHistoryItem(BaseModel):
    id: str
    invoice_number: Optional[str] = None
    created_at: datetime
    total: Decimal
    currency: str
    # Stripe's own vocabulary: draft | open | paid | uncollectible | void.
    # NOT our PaymentStatus enum — do not map completed/failed onto it.
    status: str
    hosted_invoice_url: Optional[str] = None
    invoice_pdf: Optional[str] = None


class PaymentHistoryResponse(BaseModel):
    data: List[PaymentHistoryItem]
    has_more: bool
    limit: int
    next_starting_after: Optional[str] = None


def _map_stripe_invoice(invoice: dict) -> dict:
    """Stripe invoice -> history item. Amounts arrive in minor units (cents).

    Decimal throughout: float division of 287000 cents yields 2869.9999999999995.
    """
    total_minor = invoice.get("total") or 0
    created = invoice.get("created")
    return {
        "id": invoice.get("id"),
        "invoice_number": invoice.get("number"),
        "created_at": datetime.fromtimestamp(created, tz=timezone.utc) if created else datetime.now(timezone.utc),
        "total": (Decimal(total_minor) / Decimal(100)).quantize(Decimal("0.01")),
        "currency": (invoice.get("currency") or "usd").upper(),
        "status": invoice.get("status") or "draft",
        "hosted_invoice_url": invoice.get("hosted_invoice_url"),
        "invoice_pdf": invoice.get("invoice_pdf"),
    }


@router.get("/history", response_model=PaymentHistoryResponse)
async def get_payment_history(
    limit: int = Query(20, ge=1, le=100),
    starting_after: Optional[str] = Query(None, description="Stripe invoice id cursor"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Investor payment history, read live from Stripe.

    Cursor pagination, not limit/offset: Stripe's API cannot honour an offset and
    emulating one would silently return wrong pages.
    """
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    # No Stripe customer => never subscribed => empty history. Not an error.
    if not account.stripe_customer_id:
        return PaymentHistoryResponse(data=[], has_more=False, limit=limit, next_starting_after=None)

    try:
        page = StripeClient.list_invoices(
            customer_id=account.stripe_customer_id, limit=limit, starting_after=starting_after
        )
    except Exception as e:
        # An empty list means "no invoices". It must never mean "Stripe is down."
        logger.error(f"Stripe invoice list failed for account {account.id}: {e}")
        raise HTTPException(status_code=502, detail="Billing provider unavailable. Please try again.")

    rows = [_map_stripe_invoice(inv) for inv in page.get("data", [])]
    has_more = bool(page.get("has_more"))
    return PaymentHistoryResponse(
        data=[PaymentHistoryItem(**r) for r in rows],
        has_more=has_more,
        limit=limit,
        next_starting_after=rows[-1]["id"] if rows and has_more else None,
    )


@router.post("/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    amount: Decimal,
    currency: str = "USD",
    description: Optional[str] = None,
    due_date: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create an invoice"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    invoice_number = generate_reference_id("INV")
    
    invoice = Invoice(
        account_id=account.id,
        invoice_number=invoice_number,
        amount=amount,
        currency=currency,
        description=description,
        due_date=due_date,
    )
    
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)
    
    logger.info(f"Invoice created: {invoice.id}")
    return invoice


class PaymentMethodResponse(BaseModel):
    id: str
    type: str
    card: Optional[Dict[str, Any]] = None
    created: int

    class Config:
        from_attributes = True


class RefundCreate(BaseModel):
    amount: Optional[Decimal] = None  # None for full refund
    reason: Optional[str] = None


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    amount: Decimal
    currency: str
    stripe_refund_id: Optional[str] = None
    reason: Optional[str] = None
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None

    class Config:
        from_attributes = True


class InvoiceResponse(BaseModel):
    id: UUID
    invoice_number: str
    amount: Decimal
    currency: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payment_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentMethodCardInfo(BaseModel):
    brand: str
    last4: str
    exp_month: Optional[int] = None
    exp_year: Optional[int] = None


class PaymentMethodItemResponse(BaseModel):
    id: str
    type: str
    card: Optional[PaymentMethodCardInfo] = None
    is_default: bool = False


class PaymentMethodsResponse(BaseModel):
    data: List[PaymentMethodItemResponse]


@router.get("/payment-methods", response_model=PaymentMethodsResponse)
async def get_payment_methods(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get saved payment methods for the user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get or create Stripe customer
    try:
        customer = StripeClient.get_or_create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        
        # Get payment methods
        payment_methods_data = StripeClient.list_payment_methods(customer["id"])
        methods_list = payment_methods_data.get("data", [])
        
        # Format response
        formatted_methods = []
        for method in methods_list:
            card_info = None
            if method.get("type") == "card" and method.get("card"):
                card_data = method["card"]
                card_info = PaymentMethodCardInfo(
                    brand=card_data.get("brand", ""),
                    last4=card_data.get("last4", ""),
                    exp_month=card_data.get("exp_month"),
                    exp_year=card_data.get("exp_year")
                )
            
            formatted_methods.append(PaymentMethodItemResponse(
                id=method.get("id", ""),
                type=method.get("type", "card"),
                card=card_info,
                is_default=False  # TODO: Track default payment method
            ))
        
        return PaymentMethodsResponse(data=formatted_methods)
    except Exception as e:
        logger.error(f"Failed to get payment methods: {e}")
        raise BadRequestException("Failed to retrieve payment methods")


class AddPaymentMethodRequest(BaseModel):
    payment_method_id: str
    is_default: bool = True


@router.post("/payment-methods", response_model=PaymentMethodItemResponse, status_code=status.HTTP_201_CREATED)
async def add_payment_method(
    payment_method_data: AddPaymentMethodRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a new payment method"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        customer = StripeClient.get_or_create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        
        payment_method = StripeClient.attach_payment_method(
            payment_method_data.payment_method_id,
            customer["id"]
        )
        
        # Format response
        card_info = None
        if payment_method.get("type") == "card" and payment_method.get("card"):
            card_data = payment_method["card"]
            card_info = PaymentMethodCardInfo(
                brand=card_data.get("brand", ""),
                last4=card_data.get("last4", "")
            )
        
        return PaymentMethodItemResponse(
            id=payment_method.get("id", ""),
            type=payment_method.get("type", "card"),
            card=card_info,
            is_default=payment_method_data.is_default
        )
    except Exception as e:
        logger.error(f"Failed to add payment method: {e}")
        raise BadRequestException("Failed to add payment method")


@router.delete("/payment-methods/{method_id}")
async def remove_payment_method(
    method_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a saved payment method"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        # Check if payment method exists and belongs to user's customer
        customer = StripeClient.get_or_create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        
        # Get payment methods to check if it's default
        payment_methods_data = StripeClient.list_payment_methods(customer["id"])
        methods_list = payment_methods_data.get("data", [])
        
        # Check if method exists
        method_exists = any(m.get("id") == method_id for m in methods_list)
        if not method_exists:
            raise NotFoundException("Payment method", method_id)
        
        # TODO: Check if it's default and prevent deletion if it is
        # For now, allow deletion
        
        StripeClient.detach_payment_method(method_id)
        return {"message": "Payment method removed successfully"}
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove payment method: {e}")
        raise BadRequestException("Failed to remove payment method")


class RefundCreateResponse(BaseModel):
    refund: RefundResponse
    message: str


@router.post("/{payment_id}/refund", response_model=RefundCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_refund(
    payment_id: UUID,
    refund_data: RefundCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a refund for a payment"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    payment_result = await db.execute(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.account_id == account.id
        )
    )
    payment = payment_result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundException("Payment", str(payment_id))
    
    if payment.status != PaymentStatus.COMPLETED:
        raise BadRequestException("Payment cannot be refunded. Reason: Payment is not completed")
    
    if not payment.stripe_charge_id:
        raise BadRequestException("Payment charge ID not found")
    
    try:
        refund_amount = int(refund_data.amount * 100) if refund_data.amount else None
        stripe_refund = StripeClient.create_refund(
            charge_id=payment.stripe_charge_id,
            amount=refund_amount,
            reason=refund_data.reason
        )
        
        refund = Refund(
            payment_id=payment.id,
            amount=Decimal(str(stripe_refund["amount"] / 100)),
            currency=stripe_refund.get("currency", "usd").upper(),
            stripe_refund_id=stripe_refund["id"],
            reason=refund_data.reason,
            status=stripe_refund.get("status", "pending")
        )
        
        # Update payment status if full refund
        if not refund_data.amount or refund_data.amount >= payment.amount:
            payment.status = PaymentStatus.REFUNDED
        
        db.add(refund)
        await db.commit()
        await db.refresh(refund)
        
        # Calculate estimated completion (typically 5-10 business days)
        estimated_completion = datetime.now(timezone.utc) + timedelta(days=7)
        
        # Build refund response with additional fields
        refund_response = RefundResponse(
            id=refund.id,
            payment_id=refund.payment_id,
            amount=refund.amount,
            currency=refund.currency,
            stripe_refund_id=refund.stripe_refund_id,
            reason=refund.reason,
            status=refund.status,
            created_at=refund.created_at,
            completed_at=None,  # Will be set when refund completes
            estimated_completion=estimated_completion
        )
        
        logger.info(f"Refund created: {refund.id} for payment {payment_id}")
        return RefundCreateResponse(
            refund=refund_response,
            message="Refund request submitted successfully"
        )
    except Exception as e:
        logger.error(f"Failed to create refund: {e}")
        raise BadRequestException(f"Failed to create refund: {str(e)}")


class RefundsListResponse(BaseModel):
    data: List[RefundResponse]
    total: int
    total_refunded: Decimal


@router.get("/{payment_id}/refunds", response_model=RefundsListResponse)
async def get_refunds(
    payment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get refunds for a payment"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    payment_result = await db.execute(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.account_id == account.id
        )
    )
    payment = payment_result.scalar_one_or_none()
    
    if not payment:
        raise NotFoundException("Payment", str(payment_id))
    
    result = await db.execute(
        select(Refund).where(Refund.payment_id == payment_id)
        .order_by(Refund.created_at.desc())
    )
    refunds = result.scalars().all()
    
    # Calculate total refunded
    total_refunded = sum([refund.amount for refund in refunds]) if refunds else Decimal("0.00")
    
    # Format refunds with completed_at (use updated_at if status is succeeded)
    refunds_data = []
    for refund in refunds:
        completed_at = None
        if refund.status == "succeeded" and refund.created_at:
            # If succeeded, completed_at is typically same as created_at or slightly after
            # In production, you'd track this separately
            completed_at = refund.created_at
        
        refunds_data.append(RefundResponse(
            id=refund.id,
            payment_id=refund.payment_id,
            amount=refund.amount,
            currency=refund.currency,
            stripe_refund_id=refund.stripe_refund_id,
            reason=refund.reason,
            status=refund.status,
            created_at=refund.created_at,
            completed_at=completed_at,
            estimated_completion=None  # Not needed in list view
        ))
    
    return RefundsListResponse(
        data=refunds_data,
        total=len(refunds),
        total_refunded=total_refunded
    )


@router.get("/invoices", response_model=List[InvoiceResponse])
async def list_invoices(
    status_filter: Optional[str] = Query(None, description="Filter by status: paid, unpaid, overdue"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List invoices"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Invoice).where(Invoice.account_id == account.id)
    
    if status_filter == "paid":
        query = query.where(Invoice.paid_at.isnot(None))
    elif status_filter == "unpaid":
        query = query.where(Invoice.paid_at.is_(None))
    elif status_filter == "overdue":
        query = query.where(
            Invoice.paid_at.is_(None),
            Invoice.due_date < datetime.utcnow()
        )
    
    result = await db.execute(query.order_by(Invoice.created_at.desc()))
    invoices = result.scalars().all()
    
    return invoices


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get invoice details"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.account_id == account.id
        )
    )
    invoice = result.scalar_one_or_none()
    
    if not invoice:
        raise NotFoundException("Invoice", str(invoice_id))
    
    return invoice


@router.post("/invoices/{invoice_id}/pay", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def pay_invoice(
    invoice_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pay an invoice"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    invoice_result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.account_id == account.id
        )
    )
    invoice = invoice_result.scalar_one_or_none()
    
    if not invoice:
        raise NotFoundException("Invoice", str(invoice_id))
    
    if invoice.paid_at:
        raise BadRequestException("Invoice already paid")
    
    # Create payment intent
    try:
        stripe_intent = StripeClient.create_payment_intent(
            amount=int(invoice.amount * 100),
            currency=invoice.currency.lower(),
            metadata={
                "account_id": str(account.id),
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
            }
        )
    except Exception as e:
        logger.error(f"Failed to create payment intent: {e}")
        raise BadRequestException("Failed to create payment intent")
    
    payment = Payment(
        account_id=account.id,
        amount=invoice.amount,
        currency=invoice.currency,
        payment_method=PaymentMethod.CARD,  # Default, can be made configurable
        status=PaymentStatus.PENDING,
        stripe_payment_intent_id=stripe_intent["id"],
        description=f"Payment for invoice {invoice.invoice_number}",
    )
    
    db.add(payment)
    invoice.payment_id = payment.id
    await db.commit()
    await db.refresh(payment)
    
    logger.info(f"Payment created for invoice {invoice_id}: {payment.id}")
    return payment


@router.get("/stats")
async def get_payment_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get payment statistics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    from sqlalchemy import func
    
    # Total paid (completed payments only)
    total_result = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        )
    )
    total_paid = total_result.scalar() or Decimal("0")
    
    # Total payments count
    count_result = await db.execute(
        select(func.count(Payment.id)).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        )
    )
    total_payments = count_result.scalar() or 0
    
    # Last payment date
    last_payment_result = await db.execute(
        select(Payment.created_at).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        ).order_by(Payment.created_at.desc()).limit(1)
    )
    last_payment_date = last_payment_result.scalar_one_or_none()
    
    # Payment methods count
    try:
        customer = StripeClient.get_or_create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        payment_methods_data = StripeClient.list_payment_methods(customer["id"])
        payment_methods_count = len(payment_methods_data.get("data", []))
    except Exception as e:
        logger.error(f"Failed to get payment methods count: {e}")
        payment_methods_count = 0
    
    return {
        "total_paid": float(total_paid),
        "total_payments": total_payments,
        "last_payment_date": last_payment_date.isoformat() if last_payment_date else None,
        "payment_methods_count": payment_methods_count
    }

