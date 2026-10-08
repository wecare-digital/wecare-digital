"""The stored delivery address either prices the cart correctly or is refused by name.

Three kinds of assertion live here, and the difference between them is the point of the file:

* **`pytest.raises(UnusableAddress)` with a `code` and a `field`** — the form has to mark one
  input, so a refusal that cannot name the field is a refusal the customer cannot act on. Using
  `pytest.raises(UnusableAddress)` rather than a bare `except Exception` is deliberate: a
  `TypeError` or `AttributeError` from a hostile JSON *type* must FAIL these tests rather than
  satisfy them, because the handler catches only `UnusableAddress` and anything else escapes the
  Lambda with no CORS headers at all.
* **assertions on the RETURNED VALUE** — the step-4-input pins. Their failure mode is a silent
  store, not a refusal, so a status code or a raised error cannot see them.
* **`from_contact` never raising** — the read side degrades to "confirm your address" rather than
  to a 503 or a priced cart with the wrong tax split.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import contact_address, wix_address  # noqa: E402

VALID = {
    "addressLine1": "12 MG Road",
    "addressLine2": "Flat 3B",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postalCode": "560001",
}


def address(**overrides):
    """A valid India address with `overrides` applied; a `None` value removes the key."""
    out = dict(VALID)
    out.update(overrides)
    return {key: value for key, value in out.items() if value is not None}


def refusal(raw):
    """`(code, field)` of the `UnusableAddress` raised, failing on any other exception."""
    with pytest.raises(contact_address.UnusableAddress) as caught:
        contact_address.normalize_for_storage(raw)
    return caught.value.code, caught.value.field


# -- step 1: there has to be an address -------------------------------------------------

@pytest.mark.parametrize("raw", [None, {}, "", "12 MG Road", [], 0, ["12 MG Road"]])
def test_anything_that_is_not_a_non_empty_object_is_address_required(raw):
    assert refusal(raw) == ("ADDRESS_REQUIRED", "")


# -- step 2: required fields and lengths, each naming its own field ----------------------

@pytest.mark.parametrize("field", ["addressLine1", "city", "state", "postalCode"])
def test_a_missing_required_field_is_refused_by_name(field):
    assert refusal(address(**{field: None})) == ("FIELD_REQUIRED", field)


@pytest.mark.parametrize("field", ["addressLine1", "city", "state", "postalCode"])
def test_a_whitespace_only_required_field_is_refused_by_name(field):
    assert refusal(address(**{field: "   "})) == ("FIELD_REQUIRED", field)


@pytest.mark.parametrize("field,limit", [
    ("addressLine1", 200),
    ("addressLine2", 200),
    ("locality", 100),
    ("city", 100),
    ("state", 100),
    ("postalCode", 100),
    ("country", 100),
    ("countryCode", 2),
])
def test_an_over_long_field_is_refused_by_name_rather_than_truncated(field, limit):
    # `_text` caps at `limit + 1`, so an over-long value still FAILS the length rule instead of
    # being silently truncated into compliance.
    assert refusal(address(**{field: "x" * (limit + 40)})) == ("FIELD_TOO_LONG", field)


def test_a_field_exactly_at_its_limit_is_accepted():
    out = contact_address.normalize_for_storage(address(addressLine1="x" * 200))
    assert out["addressLine1"] == "x" * 200


def test_whitespace_is_collapsed_rather_than_preserved():
    out = contact_address.normalize_for_storage(address(addressLine1="  12   MG   Road  "))
    assert out["addressLine1"] == "12 MG Road"


# -- hostile JSON types escape only as UnusableAddress ----------------------------------

@pytest.mark.parametrize("hostile", [{"x": 1}, ["Bengaluru"], True, False])
def test_a_non_scalar_on_a_required_field_is_field_required_and_not_a_type_error(hostile):
    assert refusal(address(city=hostile)) == ("FIELD_REQUIRED", "city")


def test_an_integer_postal_code_is_stringified_and_stored():
    # FEAT-003: storage no longer runs the India PIN regex (that moved to payment_address).
    # `_text` still stringifies, so an integer postal code is stored as its string form.
    out = contact_address.normalize_for_storage(address(postalCode=56001))
    assert out["postalCode"] == "56001"
    out2 = contact_address.normalize_for_storage(address(postalCode=560001))
    assert out2["postalCode"] == "560001"


def test_an_integer_country_code_defaults_rather_than_raising_attribute_error():
    # `_text` makes 91 the string "91". FEAT-003: storage no longer runs the Wix-mappability
    # check, so this is accepted at storage; the countryCode is coerced to the "91" string,
    # upper-cased and length-bounded to two chars. The payability of such an address is a
    # payment_address question, not a storage one.
    out = contact_address.normalize_for_storage(address(countryCode=91))
    assert isinstance(out["countryCode"], str)


# -- the two step-4-input pins, asserted on the RETURNED VALUE ---------------------------

def test_a_non_scalar_on_an_optional_field_is_stored_as_empty_not_stringified():
    # Fails if step 4 is handed `raw`: `identity.address._clean` stringifies rather than refuses,
    # so `addressLine2` would be stored as "{'long_name': 'Flat 3B'}" and printed on the
    # identity card's Deliver line.
    out = contact_address.normalize_for_storage(
        address(addressLine2={"long_name": "Flat 3B"}))
    assert out["addressLine2"] == ""
    assert "long_name" not in out["fullAddress"]


def test_a_non_scalar_country_code_defaults_to_in_rather_than_misnaming_state():
    # A non-scalar countryCode is coerced to "" by `_text`, then defaulted to IN at step 2.
    out = contact_address.normalize_for_storage(address(countryCode={"x": 1}))
    assert out["countryCode"] == "IN"


# -- FEAT-003: the India PIN rule MOVED to payment_address; storage now accepts these -----

def test_an_india_address_with_no_country_code_is_stored_without_pin_validation():
    # The India-only form posts no countryCode. Storage defaults it to IN and stores the given
    # postal code WITHOUT the PIN regex — the PIN rule is now payment_address.assert_payable's.
    out = contact_address.normalize_for_storage(address(postalCode="056001", countryCode=None))
    assert out["countryCode"] == "IN"
    assert out["postalCode"] == "056001"


@pytest.mark.parametrize("pin", ["56001", "5600012", "56000a", "000000", "0560 01"])
def test_storage_accepts_any_pin_shape_now_that_the_rule_moved_to_payment(pin):
    # FEAT-003: these were refused at storage before; now storage keeps them and the India PIN
    # rule is enforced at pay time by payment_address (covered in test_payment_address.py).
    out = contact_address.normalize_for_storage(address(postalCode=pin))
    assert out["postalCode"] == pin.strip() or out["postalCode"] == pin


def test_a_non_india_address_is_not_held_to_the_india_pin_rule():
    out = contact_address.normalize_for_storage({
        "addressLine1": "1 Market St", "city": "San Francisco",
        "state": "US-CA", "postalCode": "94105", "countryCode": "us",
    })
    assert out["postalCode"] == "94105"
    assert out["countryCode"] == "US"


# -- FEAT-003: the money/place-of-supply rule MOVED to payment_address --------------------
# Storage now ACCEPTS these addresses (international); payment_address.assert_payable enforces
# the India subdivision and non-India ISO-3166-2 rules at pay time (see test_payment_address.py).

def test_storage_accepts_an_unresolvable_indian_state_now():
    out = contact_address.normalize_for_storage(address(state="Bangalore State"))
    assert out["state"] == "Bangalore State"


def test_a_state_alias_the_tax_table_knows_is_still_wix_mappable():
    out = contact_address.normalize_for_storage(address(state="Orissa", postalCode="751001"))
    assert wix_address.to_wix_address(out)["subdivision"] == "IN-OR"


def test_storage_accepts_a_non_india_address_without_an_iso_subdivision_now():
    out = contact_address.normalize_for_storage({
        "addressLine1": "1 Market St", "city": "San Francisco",
        "state": "California", "postalCode": "94105", "countryCode": "US",
    })
    assert out["state"] == "California"
    assert out["countryCode"] == "US"


def test_storage_accepts_a_non_india_subdivision_of_another_country_now():
    out = contact_address.normalize_for_storage({
        "addressLine1": "1 Market St", "city": "San Francisco",
        "state": "CA-ON", "postalCode": "94105", "countryCode": "US",
    })
    assert out["countryCode"] == "US"


# -- step 5: metadata and unknown keys ----------------------------------------------------

def test_autocomplete_metadata_never_enters_the_stored_address():
    # latitude/longitude are floats; floats are banned in this path and DynamoDB refuses them.
    out = contact_address.normalize_for_storage(address(
        googlePlaceId="ChIJbU60yXAWrjsR4E9-UejD3_g",
        latitude=12.9715987,
        longitude=77.5945627,
    ))
    assert "googlePlaceId" not in out
    assert "latitude" not in out
    assert "longitude" not in out
    assert not any(isinstance(value, float) for value in out.values())


def test_an_unknown_nested_key_is_dropped_rather_than_refused():
    # A recorded divergence from `cart_v2.delivery_address`, which refuses unknown fields:
    # nothing reads the dropped keys, and refusing them would reject browser autofill extras.
    out = contact_address.normalize_for_storage(address(
        addressId="addr-1", recipientName="Asha Sen", sameAsBilling=True))
    assert "addressId" not in out
    assert "recipientName" not in out
    assert "sameAsBilling" not in out
    assert out["city"] == "Bengaluru"


def test_the_stored_shape_is_exactly_what_normalize_address_emits():
    out = contact_address.normalize_for_storage(address())
    assert set(out) == {
        "addressLine1", "addressLine2", "locality", "city", "state",
        "postalCode", "country", "countryCode", "fullAddress",
    }
    assert out["country"] == "India"
    assert out["countryCode"] == "IN"
    assert out["locality"] == ""
    assert out["fullAddress"] == (
        "12 MG Road, Flat 3B, Bengaluru, Karnataka, 560001, India")


# -- the round trip into the shape that prices the cart -----------------------------------

def test_a_stored_address_converts_into_exactly_the_six_wix_keys():
    wix = wix_address.to_wix_address(contact_address.normalize_for_storage(address()))
    assert wix == {
        "country": "IN",
        "subdivision": "IN-KA",
        "city": "Bengaluru",
        "postalCode": "560001",
        "addressLine": "12 MG Road",
        "addressLine2": "Flat 3B",
    }


# -- from_contact never raises -------------------------------------------------------------

def test_from_contact_returns_the_normalised_address_for_a_good_row():
    row = {"id": "contact-1", contact_address.ATTRIBUTE: address()}
    assert contact_address.from_contact(row)["city"] == "Bengaluru"


@pytest.mark.parametrize("row", [
    None,
    {},
    {"id": "contact-1"},
    "not a row",
    {"id": "contact-1", contact_address.ATTRIBUTE: None},
    {"id": "contact-1", contact_address.ATTRIBUTE: "12 MG Road, Bengaluru"},
    {"id": "contact-1", contact_address.ATTRIBUTE: {"city": "Bengaluru"}},
])
def test_from_contact_returns_none_rather_than_raising(row):
    assert contact_address.from_contact(row) is None


def test_from_contact_returns_a_structurally_valid_legacy_row_but_payable_for_refuses_it():
    # FEAT-003: from_contact is STRUCTURAL only now. An unmappable Indian state is structurally
    # valid, so from_contact returns it — the place-of-supply refusal moved to payment_address,
    # surfaced through payable_for, which is what degrades to a recoverable "confirm your address".
    from lambda_utils.ecommerce import payment_address
    row = {"id": "contact-1",
           contact_address.ATTRIBUTE: address(state="Bangalore State")}
    got = contact_address.from_contact(row)
    assert got is not None and got["state"] == "Bangalore State"

    address_out, err = contact_address.payable_for(row, payment_address.WEBSITE_RAZORPAY)
    assert address_out is None
    assert err is not None and err.code == "UNMAPPABLE_STATE" and err.field == "state"


def test_whatever_from_contact_returns_is_something_to_wix_address_accepts():
    row = {"id": "contact-1", contact_address.ATTRIBUTE: address()}
    loaded = contact_address.from_contact(row)
    assert wix_address.to_wix_address(loaded)["subdivision"] == "IN-KA"
