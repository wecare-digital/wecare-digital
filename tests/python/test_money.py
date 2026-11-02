"""Behavioural tests for lambda_utils.ecommerce.money.

Money is the integer-paise primitive the whole payment path is built on. These
tests exercise the real Money dataclass, Money.from_decimal_string and
positive_paise so that relaxing any guard (allowing a float, a fractional paise,
a non-INR currency or a zero amount) breaks an assertion.
"""

from decimal import Decimal

import pytest

from lambda_utils.ecommerce.money import Money, positive_paise


def test_money_accepts_nonnegative_integer_inr():
    assert Money(0).paise == 0
    assert Money(0).currency == "INR"
    assert Money(149950).paise == 149950


def test_money_rejects_float_paise():
    with pytest.raises(ValueError):
        Money(1499.0)  # type: ignore[arg-type]


def test_money_rejects_negative_paise():
    with pytest.raises(ValueError):
        Money(-1)


def test_money_rejects_non_inr_currency():
    with pytest.raises(ValueError):
        Money(100, "USD")


def test_money_rejects_bool_paise():
    # bool is an int subclass; the `type(...) is not int` guard must still reject it.
    with pytest.raises(ValueError):
        Money(True)  # type: ignore[arg-type]


def test_from_decimal_string_parses_rupees_and_paise():
    assert Money.from_decimal_string("1499.50") == Money(149950)
    assert Money.from_decimal_string("1499") == Money(149900)
    # A single fraction digit is left-padded to paise, not misread.
    assert Money.from_decimal_string("1499.5") == Money(149950)


def test_from_decimal_string_rejects_junk_and_non_strings():
    with pytest.raises(ValueError):
        Money.from_decimal_string("1499.5x")
    with pytest.raises(ValueError):
        Money.from_decimal_string("1499.505")  # more than two fraction digits
    with pytest.raises(ValueError):
        Money.from_decimal_string(1499)  # type: ignore[arg-type]


def test_positive_paise_accepts_one_and_integral_decimal():
    assert positive_paise(1) == 1
    assert positive_paise(Decimal("1499")) == 1499


def test_positive_paise_rejects_zero():
    with pytest.raises(ValueError):
        positive_paise(0)


def test_positive_paise_rejects_bool():
    with pytest.raises(ValueError):
        positive_paise(True)


def test_positive_paise_rejects_fractional_decimal():
    with pytest.raises(ValueError):
        positive_paise(Decimal("1.5"))
