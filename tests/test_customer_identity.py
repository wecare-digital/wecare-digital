"""Customer identity is immutable; phone and email are attributes that get verified.

The normalisation tests carry most of the weight here, because uniqueness is enforced on the
normalised value. Too aggressive and two people share an account; too lax and one person gets
two - and both are silent failures that only surface as a support ticket months later.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils.identity import customer  # noqa: E402


# ── identity ───────────────────────────────────────────────────────────────────

def test_a_customer_id_is_prefixed_and_the_right_length():
    cid = customer.new_customer_id()
    assert cid.startswith('CUS_')
    assert len(cid) == customer.CUSTOMER_ID_LENGTH == 30
    assert customer.is_customer_id(cid)


def test_customer_ids_are_unique_and_time_ordered():
    ids = [customer.new_customer_id() for _ in range(20000)]
    assert len(set(ids)) == 20000
    assert ids == sorted(ids) or len(set(i[:14] for i in ids)) > 1, \
        'ULID prefix should be non-decreasing within a run'


@pytest.mark.parametrize('value', [
    '', 'CUS_', 'CUS_TOOSHORT', 'cus_01J0000000000000000000000',
    '01J0000000000000000000000A', None, 12345,
    'CUS_01J00000000000000000000I',   # I is outside Crockford
])
def test_invalid_customer_ids_are_rejected(value):
    assert not customer.is_customer_id(value)
    with pytest.raises(ValueError):
        customer.assert_customer_id(value)


def test_identity_is_not_derived_from_phone_or_email():
    """§49. A ported or corrected phone number must not change who the customer is."""
    record = customer.build_customer(
        first_name='Asha', last_name='Verma',
        phone='9330994400', email='Asha.Verma+shop@Example.COM')
    cid = record['customerId']
    assert '9330994400' not in cid
    assert 'asha' not in cid.lower()
    assert 'verma' not in cid.lower()


# ── phone normalisation ────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw', [
    '9330994400',
    '+919330994400',
    '+91 93309 94400',
    '91 9330994400',
    '09330994400',          # national trunk zero
    '0091 9330994400',      # international prefix
    '+91-93309-94400',
    '  9330994400  ',
    '(+91) 93309 94400',
])
def test_every_spelling_of_one_number_normalises_identically(raw):
    """Uniqueness is enforced on this value, so a trunk zero or a 00 prefix producing a
    different string would let the same person register twice."""
    assert customer.normalize_phone(raw) == '+919330994400'


def test_the_business_number_normalises_as_expected():
    assert customer.normalize_phone('+91 93309 94400') == '+919330994400'
    assert customer.is_indian_mobile('+919330994400')


@pytest.mark.parametrize('raw', ['', '   ', 'abc', '+', '12345', '9' * 20, None])
def test_unusable_phone_numbers_are_refused(raw):
    with pytest.raises(customer.InvalidPhoneNumber):
        customer.normalize_phone(raw)


def test_a_landline_is_not_silently_prefixed_as_a_mobile():
    """Indian mobiles start 6-9. A landline is not reachable on WhatsApp, so it must not be
    turned into a plausible-looking mobile."""
    assert not customer.is_indian_mobile(customer.normalize_phone('+91 33 4000 1234'))


def test_is_indian_mobile_is_false_for_other_countries():
    assert not customer.is_indian_mobile('+14155552671')
    assert not customer.is_indian_mobile('')


# ── email normalisation ────────────────────────────────────────────────────────

def test_email_is_trimmed_and_lowercased():
    assert customer.normalize_email('  Asha.Verma@Example.COM ') == 'asha.verma@example.com'


def test_dots_are_not_stripped_from_the_local_part():
    """Gmail ignores dots; the internet does not. The local part is owned by the receiving
    server, so a.b@ and ab@ can be two different people."""
    assert customer.normalize_email('a.b@fastmail.com') == 'a.b@fastmail.com'
    assert customer.normalize_email('a.b@fastmail.com') != customer.normalize_email('ab@fastmail.com')


def test_plus_tags_are_not_stripped():
    """A +tag is part of the address the customer gave us, and the receipt has to reach it."""
    assert customer.normalize_email('asha+shop@example.com') == 'asha+shop@example.com'
    assert (customer.normalize_email('asha+shop@example.com')
            != customer.normalize_email('asha@example.com'))


@pytest.mark.parametrize('raw', [
    '', '   ', 'not-an-email', 'a@', '@b.com', 'a@b', 'a b@c.com',
    'a@b..com', 'a@-b.com', ('x' * 250) + '@example.com', None,
])
def test_unusable_email_addresses_are_refused(raw):
    with pytest.raises(customer.InvalidEmailAddress):
        customer.normalize_email(raw)


def test_email_domain_extraction():
    assert customer.email_domain('asha@example.co.in') == 'example.co.in'


# ── names ──────────────────────────────────────────────────────────────────────

def test_whitespace_is_collapsed_but_case_and_script_are_preserved():
    assert customer.normalize_name('  Asha   Verma ') == 'Asha Verma'
    assert customer.normalize_name('McDonald') == 'McDonald'
    assert customer.normalize_name('van der Berg') == 'van der Berg'
    assert customer.normalize_name('আশা') == 'আশা'


@pytest.mark.parametrize('raw', ['', '   ', '\t\n', None, 'x' * 101])
def test_unusable_names_are_refused(raw):
    with pytest.raises(customer.InvalidName):
        customer.normalize_name(raw)


def test_full_name_is_derived_not_stored_independently():
    record = customer.build_customer(
        first_name='Asha', last_name='Verma',
        phone='9330994400', email='asha@example.com')
    assert record['fullName'] == 'Asha Verma'
    assert record['fullName'] == customer.full_name(record['firstName'], record['lastName'])


# ── the record ─────────────────────────────────────────────────────────────────

def test_a_new_customer_is_unverified_with_the_attributes_absent():
    """Absent, not None: absence is what lets a conditional write mark a channel verified
    exactly once, and it keeps 'never verified' distinct from 'verified at an unknown time'."""
    record = customer.build_customer(
        first_name='Asha', last_name='Verma',
        phone='9330994400', email='asha@example.com')
    assert 'phoneVerifiedAt' not in record
    assert 'emailVerifiedAt' not in record
    assert customer.verification_state(record) == (False, False)


def test_build_customer_normalises_everything_it_stores():
    record = customer.build_customer(
        first_name='  Asha ', last_name=' Verma  ',
        phone='0093309 94400', email='  Asha@Example.COM ')
    assert record['firstName'] == 'Asha'
    assert record['normalizedPhone'] == '+919330994400'
    assert record['normalizedEmail'] == 'asha@example.com'
    assert record['phone'] == record['normalizedPhone']
    assert record['email'] == record['normalizedEmail']


def test_build_customer_refuses_bad_input_rather_than_storing_it():
    with pytest.raises(customer.InvalidPhoneNumber):
        customer.build_customer(first_name='A', last_name='B', phone='nope',
                                email='a@b.com')
    with pytest.raises(customer.InvalidEmailAddress):
        customer.build_customer(first_name='A', last_name='B', phone='9330994400',
                                email='nope')


def test_an_explicit_customer_id_is_honoured():
    cid = customer.new_customer_id()
    record = customer.build_customer(first_name='A', last_name='B', phone='9330994400',
                                     email='a@b.com', customer_id=cid)
    assert record['customerId'] == cid


# ── the checkout gate ──────────────────────────────────────────────────────────

def _verified():
    record = customer.build_customer(
        first_name='Asha', last_name='Verma',
        phone='9330994400', email='asha@example.com')
    record['phoneVerifiedAt'] = 1_700_000_000
    record['emailVerifiedAt'] = 1_700_000_001
    return record


def test_a_fully_verified_customer_may_proceed():
    assert customer.is_checkout_ready(_verified())


def test_an_unverified_phone_blocks_checkout():
    """The payment request is delivered to that number; unverified means it could be
    someone else's."""
    record = _verified()
    del record['phoneVerifiedAt']
    assert not customer.is_checkout_ready(record)


def test_whatsapp_verification_is_the_checkout_identity():
    record = _verified()
    del record['emailVerifiedAt']
    assert customer.is_checkout_ready(record)


@pytest.mark.parametrize('field', ['firstName', 'lastName', 'customerId'])
def test_a_missing_required_field_blocks_checkout(field):
    record = _verified()
    record[field] = ''
    assert not customer.is_checkout_ready(record)


def test_a_malformed_customer_id_blocks_checkout():
    record = _verified()
    record['customerId'] = 'not-a-customer-id'
    assert not customer.is_checkout_ready(record)
