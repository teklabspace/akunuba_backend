from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
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
    payment_method: PaymentMethod
    description: Optional[str] = None


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


@router.post("/create-intent", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    payment_data: PaymentIntentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a payment intent"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Create Stripe payment intent
    try:
        stripe_intent = StripeClient.create_payment_intent(
            amount=int(payment_data.amount * 100),  # Convert to cents
            currency=payment_data.currency.lower(),
            metadata={
                "account_id": str(account.id),
                "user_id": str(current_user.id),
            }
        )
    except Exception as e:
        logger.error(f"Failed to create Stripe payment intent: {e}")
        raise BadRequestException("Failed to create payment intent")
    
    payment = Payment(
        account_id=account.id,
        amount=payment_data.amount,
        currency=payment_data.currency,
        payment_method=payment_data.payment_method,
        status=PaymentStatus.PENDING,
        stripe_payment_intent_id=stripe_intent["id"],
        description=payment_data.description,
    )
    
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    
    logger.info(f"Payment intent created: {payment.id}")
    return payment


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events"""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        event = StripeClient.verify_webhook_signature(payload, signature)
        if not event:
            raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    
    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id")
        result = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
        )
        payment = result.scalar_one_or_none()
        
        if payment:
            payment.status = PaymentStatus.COMPLETED
            payment.stripe_charge_id = data.get("charges", {}).get("data", [{}])[0].get("id")
            await db.commit()
            
            logger.info(f"Payment completed: {payment.id}")
    
    elif event_type == "payment_intent.payment_failed":
        payment_intent_id = data.get("id")
        result = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
        )
        payment = result.scalar_one_or_none()
        
        if payment:
            payment.status = PaymentStatus.FAILED
            await db.commit()
            
            logger.info(f"Payment failed: {payment.id}")
    
    elif event_type == "payment_intent.processing":
        payment_intent_id = data.get("id")
        result = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
        )
        payment = result.scalar_one_or_none()
        
        if payment:
            payment.status = PaymentStatus.PROCESSING
            await db.commit()
            
            logger.info(f"Payment processing: {payment.id}")
    
    elif event_type == "charge.refunded":
        charge_id = data.get("id")
        refund_id = data.get("refunds", {}).get("data", [{}])[0].get("id") if data.get("refunds") else None
        
        # Find payment by charge ID
        result = await db.execute(
            select(Payment).where(Payment.stripe_charge_id == charge_id)
        )
        payment = result.scalar_one_or_none()
        
        if payment and refund_id:
            # Check if refund already exists
            refund_result = await db.execute(
                select(Refund).where(Refund.stripe_refund_id == refund_id)
            )
            if not refund_result.scalar_one_or_none():
                refund = Refund(
                    payment_id=payment.id,
                    amount=Decimal(str(data.get("amount_refunded", 0) / 100)),
                    currency=data.get("currency", "usd").upper(),
                    stripe_refund_id=refund_id,
                    status="succeeded"
                )
                db.add(refund)
            
            # Update payment status if fully refunded
            if data.get("refunded"):
                payment.status = PaymentStatus.REFUNDED
            
            await db.commit()
            logger.info(f"Refund processed: {refund_id} for payment {payment.id}")
    
    elif event_type == "invoice.payment_succeeded":
        # Handle invoice payment success
        invoice_id = data.get("id")
        payment_intent_id = data.get("payment_intent")
        
        if payment_intent_id:
            result = await db.execute(
                select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
            )
            payment = result.scalar_one_or_none()
            
            if payment:
                # Find invoice linked to this payment
                invoice_result = await db.execute(
                    select(Invoice).where(Invoice.payment_id == payment.id)
                )
                invoice = invoice_result.scalar_one_or_none()
                
                if invoice:
                    invoice.paid_at = datetime.utcnow()
                    await db.commit()
                    logger.info(f"Invoice paid: {invoice.id}")
    
    return {"status": "success"}


@router.get("/history", response_model=List[PaymentResponse])
async def get_payment_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get payment history"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Payment).where(Payment.account_id == account.id)
        .order_by(Payment.created_at.desc())
    )
    payments = result.scalars().all()
    
    return payments


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


@router.get("/payment-methods", response_model=List[PaymentMethodResponse])
async def get_payment_methods(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get saved payment methods"""
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
        payment_methods = StripeClient.list_payment_methods(customer["id"])
        return payment_methods.get("data", [])
    except Exception as e:
        logger.error(f"Failed to get payment methods: {e}")
        raise BadRequestException("Failed to retrieve payment methods")


@router.post("/payment-methods", response_model=PaymentMethodResponse)
async def add_payment_method(
    payment_method_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a payment method"""
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
            payment_method_id,
            customer["id"]
        )
        
        return payment_method
    except Exception as e:
        logger.error(f"Failed to add payment method: {e}")
        raise BadRequestException("Failed to add payment method")


@router.delete("/payment-methods/{method_id}")
async def remove_payment_method(
    method_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a payment method"""
    try:
        StripeClient.detach_payment_method(method_id)
        return {"message": "Payment method removed successfully"}
    except Exception as e:
        logger.error(f"Failed to remove payment method: {e}")
        raise BadRequestException("Failed to remove payment method")


@router.post("/payments/{payment_id}/refund", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
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
        raise BadRequestException("Only completed payments can be refunded")
    
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
        
        logger.info(f"Refund created: {refund.id} for payment {payment_id}")
        return refund
    except Exception as e:
        logger.error(f"Failed to create refund: {e}")
        raise BadRequestException("Failed to create refund")


@router.get("/payments/{payment_id}/refunds", response_model=List[RefundResponse])
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
    
    return refunds


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
    
    # Total revenue
    total_result = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        )
    )
    total_revenue = total_result.scalar() or Decimal("0")
    
    # Total transactions
    count_result = await db.execute(
        select(func.count(Payment.id)).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        )
    )
    total_transactions = count_result.scalar() or 0
    
    # Average transaction value
    avg_value = total_revenue / total_transactions if total_transactions > 0 else Decimal("0")
    
    # Payment method breakdown
    method_result = await db.execute(
        select(
            Payment.payment_method,
            func.count(Payment.id).label("count"),
            func.sum(Payment.amount).label("total")
        ).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        ).group_by(Payment.payment_method)
    )
    method_breakdown = [
        {
            "method": row.payment_method.value,
            "count": row.count,
            "total": float(row.total)
        }
        for row in method_result.all()
    ]
    
    return {
        "total_revenue": float(total_revenue),
        "total_transactions": total_transactions,
        "average_transaction_value": float(avg_value),
        "payment_method_breakdown": method_breakdown
    }

