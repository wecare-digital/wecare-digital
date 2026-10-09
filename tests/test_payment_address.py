"""FEAT-003: channel-aware payability. Storage is international; India rules run at pay time."""
import os
import sys

import pytest

SHARED = os.path.join(os.path.dirname(__file__), "..", "amplify", "functions", "shared")
sys.path.insert(0, os.path.abspath(SHARED))

from lambda_utils.ecommerce import payment_address as pa  # noqa: E402


def _india(pin="700012", state="West Bengal"):
    return {
        "addressLine1": "12 Example Road",
        "city": "Kolkata",
        "state": state,
        "postalCode": pin,
        "countryCode": "IN",
        "country": "India",
    }


def _non_india(state="CA"):
    return {
        "addressLine1": "1 Market St",
        "city": "San Francisco",
        "state": state,
        "postalCode": "94105",
        "countryCode": "US",
        "country": "United States",
    }


def test_india_valid_passes_both_channels():
    pa.assert_payable(_india(), channel=pa.WEBSITE_RAZORPAY)
    pa.assert_payable(_india(), channel=pa.WHATSAPP_ORDER_DETAILS)


def test_india_bad_pin_raises_invalid_pin_naming_postalcode():
    with pytest.raises(pa.UnpayableAddress) as e:
        pa.assert_payable(_india(pin="70001"), channel=pa.WEBSITE_RAZORPAY)
    assert e.value.code == "INVALID_PIN"
    assert e.value.field == "postalCode"


def test_india_unmappable_state_raises_naming_state():
    with pytest.raises(pa.UnpayableAddress) as e:
        pa.assert_payable(_india(state="Atlantis"), channel=pa.WEBSITE_RAZORPAY)
    assert e.value.code == "UNMAPPABLE_STATE"
    assert e.value.field == "state"


def test_non_india_iso_state_passes_website():
    # A full ISO 3166-2 code (country-prefixed) is what to_wix_address requires for non-India.
    pa.assert_payable(_non_india(state="US-CA"), channel=pa.WEBSITE_RAZORPAY)


def test_non_india_plain_state_name_refused_on_website():
    # A bare state name (no ISO 3166-2 country prefix) cannot map -> refused.
    with pytest.raises(pa.UnpayableAddress):
        pa.assert_payable(_non_india(state="California"), channel=pa.WEBSITE_RAZORPAY)


def test_non_india_refused_on_whatsapp_regardless():
    with pytest.raises(pa.UnpayableAddress) as e:
        pa.assert_payable(_non_india(state="US-CA"), channel=pa.WHATSAPP_ORDER_DETAILS)
    assert e.value.code == "COUNTRY_NOT_PAYABLE_ON_CHANNEL"
    assert e.value.field == "country"


def test_for_meta_beneficiary_emits_exactly_seven_keys():
    out = pa.for_meta_beneficiary(_india(), recipient_name="A. Customer")
    assert set(out.keys()) == {
        "name", "address_line1", "address_line2", "city", "state", "country", "postal_code",
    }
    assert out["country"] == "India"
    assert out["name"] == "A. Customer"


def test_for_meta_beneficiary_refuses_non_india():
    with pytest.raises(pa.UnpayableAddress):
        pa.for_meta_beneficiary(_non_india(), recipient_name="X")


def test_for_wix_india_returns_wix_shape():
    out = pa.for_wix(_india())
    assert out.get("country") == "IN"
    assert "subdivision" in out


@pytest.mark.parametrize("channel", ["unknown", "", None, 17, [], {}])
@pytest.mark.parametrize("address", [_india(), _non_india(state="US-CA")], ids=["india", "international"])
def test_unknown_channel_is_refused_before_country_acceptance(address, channel):
    with pytest.raises(pa.UnpayableAddress) as exc:
        pa.assert_payable(address, channel=channel)
    assert exc.value.code == "UNKNOWN_CHANNEL"
    assert exc.value.field == ""


@pytest.mark.parametrize("channel", ["unknown", "", None, 17, [], {}])
def test_unknown_channel_precedes_address_access(channel):
    with pytest.raises(pa.UnpayableAddress) as exc:
        pa.assert_payable(None, channel=channel)
    assert exc.value.code == "UNKNOWN_CHANNEL"
