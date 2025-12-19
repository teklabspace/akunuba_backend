from pydantic import BaseModel
from typing import Optional, List, Any
from decimal import Decimal


class MessageResponse(BaseModel):
    message: str


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int

