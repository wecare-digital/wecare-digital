"""Smoke test proving the pytest harness can import real shared Lambda utils.

This imports ``lambda_utils.ecommerce.money`` (a pure, boto3-free module, though
importing any ``lambda_utils.*`` submodule triggers the package ``__init__`` which
eagerly pulls in middleware that needs boto3) and asserts a trivially true
property of its public API. FEAT-002 expands this placeholder into real
behavioral coverage of the money / pricing / auth / template utilities.
"""

from lambda_utils.ecommerce.money import Money, positive_paise


def test_money_constructs_in_inr():
    assert Money(0).currency == "INR"
    assert Money(1499).paise == 1499


def test_positive_paise_passes_through_positive_int():
    assert positive_paise(1) == 1
