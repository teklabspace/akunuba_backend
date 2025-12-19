from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from app.models.order import OrderType, OrderStatus


class OrderCreate(BaseModel):
    order_type: OrderType
    symbol: str
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    side: str


class OrderResponse(BaseModel):
    id: UUID
    order_type: OrderType
    symbol: str
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    side: str
    status: OrderStatus
    filled_quantity: Decimal
    filled_price: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True

