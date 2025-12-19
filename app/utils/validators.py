from typing import Optional
from pydantic import EmailStr, validator
from app.config import settings


def validate_file_type(filename: str) -> bool:
    extension = filename.split(".")[-1].lower()
    return extension in settings.ALLOWED_FILE_TYPES


def validate_file_size(file_size: int) -> bool:
    return file_size <= settings.MAX_UPLOAD_SIZE


def validate_currency(currency: str) -> bool:
    valid_currencies = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD"]
    return currency.upper() in valid_currencies


def validate_account_type(account_type: str) -> bool:
    valid_types = ["individual", "corporate", "trust"]
    return account_type.lower() in valid_types


def validate_order_type(order_type: str) -> bool:
    valid_types = ["market", "limit", "stop"]
    return order_type.lower() in valid_types

