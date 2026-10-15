"""Exact positive minor units, including DynamoDB's Decimal representation."""

from decimal import Decimal
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Money:
    """INR minor units. Floats, fractional paise and implicit rounding are forbidden."""

    paise: int
    currency: str = "INR"

    def __post_init__(self):
        if (type(self.paise) is not int or not 0 <= self.paise <= 9007199254740991
                or self.currency != "INR"):
            raise ValueError("money must be nonnegative integer paise in INR")

    @classmethod
    def from_decimal_string(cls, amount):
        """Parse an exact decimal-rupee string ("1499", "1499.50") into paise.

        The native price-summary shapes (delivery options, service line totals) carry money
        as decimal strings; floats, numbers and more than two fraction digits are refused.
        """
        if not isinstance(amount, str) or not re.fullmatch(r"[0-9]{1,14}(?:\.[0-9]{1,2})?", amount):
            raise ValueError("amount must be an exact decimal string")
        whole, _, fraction = amount.partition(".")
        return cls(int(whole) * 100 + int(fraction.ljust(2, "0")))


def positive_paise(value):
    if isinstance(value, bool):
        raise ValueError("amount must be positive integer paise")
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("amount must be positive integer paise")
        value = int(value)
    if not isinstance(value, int) or not 0 < value <= 9007199254740991:
        raise ValueError("amount must be positive integer paise")
    return value
