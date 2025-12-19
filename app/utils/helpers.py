from datetime import datetime
from typing import Optional
from decimal import Decimal


def calculate_percentage(value: Decimal, percentage: Decimal) -> Decimal:
    return (value * percentage) / 100


def format_currency(amount: Decimal, currency: str = "USD") -> str:
    return f"{currency} {amount:,.2f}"


def generate_reference_id(prefix: str = "FLG") -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    import random
    random_suffix = random.randint(1000, 9999)
    return f"{prefix}-{timestamp}-{random_suffix}"


def calculate_fee(amount: Decimal, fee_percentage: Decimal) -> Decimal:
    return calculate_percentage(amount, fee_percentage)


def calculate_listing_fee(asset_value: Decimal) -> Decimal:
    return calculate_fee(asset_value, Decimal("2.0"))


def calculate_commission(amount: Decimal, is_premium: bool = False) -> Decimal:
    commission_rate = Decimal("10.0") if is_premium else Decimal("20.0")
    return calculate_fee(amount, commission_rate)

