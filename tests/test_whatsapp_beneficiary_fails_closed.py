"""FEAT-003: a supplied-but-unpayable customer_address must FAIL CLOSED — never fall back to
the business beneficiary. A valid India customer_address builds the Meta beneficiary from the
shared shape. A caller supplying no customer_address keeps today's behaviour exactly.

Handler is imported lazily inside the fixture (not at module level), matching test_payments.py
so test_handler_import_isolation stays satisfied.
"""
import os
import sys
from unittest.mock import patch

import pytest

PHONE_1 = "phone-number-id-waba1-direct-1016149501586345"


def _india_addr(pin="700012", state="West Bengal"):
    return {
        "addressLine1": "12 Example Road",
        "city": "Kolkata",
        "state": state,
        "postalCode": pin,
        "countryCode": "IN",
        "country": "India",
    }


def _order(**extra):
    o = {
        "reference_id": "WD-PAY-BEN1",
        "type": "physical-goods",
        "currency": "INR",
        "total_amount": {"value": 10000, "offset": 100},
        "order": {
            "items": [{"name": "Thing", "amount": {"value": 10000}, "quantity": 1}],
            "subtotal": {"value": 10000}, "discount": {"value": 0},
            "shipping": {"value": 0}, "tax": {"value": 0},
        },
    }
    o.update(extra)
    return o


class TestBeneficiaryFailsClosed:
    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "amplify", "functions", "messaging", "outbound-whatsapp"))
        with patch.dict(os.environ, {"AWS_REGION": "us-east-1", "SEND_MODE": "DRY_RUN"}):
            with patch("boto3.resource"), patch("boto3.client"):
                import handler
                self.handler = handler
                self.build = handler._build_message_payload

    def _build(self, order):
        return self.build("+919330994400", "", None, None, False, None, [],
                          is_interactive_payment=True, order_details=order,
                          phone_number_id=PHONE_1)

    def test_valid_india_customer_address_builds_meta_beneficiary_from_shared_shape(self):
        payload = self._build(_order(customer_address=_india_addr(), recipient_name="A. Customer"))
        bens = payload["interactive"]["action"]["parameters"]["beneficiaries"]
        assert len(bens) == 1
        b = bens[0]
        assert set(b.keys()) == {
            "name", "address_line1", "address_line2", "city", "state", "country", "postal_code"}
        assert b["name"] == "A. Customer"
        assert b["country"] == "India"
        assert b["postal_code"] == "700012"
        assert b["address_line1"] != "81/2/7 Phears Ln"  # NOT the business fallback

    def test_supplied_but_unpayable_customer_address_fails_closed_no_business_fallback(self):
        bad = {
            "addressLine1": "1 Market St", "city": "San Francisco",
            "state": "US-CA", "postalCode": "94105", "countryCode": "US", "country": "United States",
        }
        with pytest.raises(self.handler.PaymentConfigurationUnresolved):
            self._build(_order(customer_address=bad, recipient_name="X"))

    def test_india_bad_pin_customer_address_fails_closed(self):
        with pytest.raises(self.handler.PaymentConfigurationUnresolved):
            self._build(_order(customer_address=_india_addr(pin="70001"), recipient_name="X"))

    def test_no_customer_address_keeps_todays_behaviour_business_fallback(self):
        payload = self._build(_order())
        bens = payload["interactive"]["action"]["parameters"]["beneficiaries"]
        assert len(bens) == 1
        assert bens[0]["name"] == "WECARE.DIGITAL"
        assert bens[0]["postal_code"] == "700012"
