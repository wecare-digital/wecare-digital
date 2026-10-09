"""Payment-attempt identity before payment, order identity only after payment.

The invariant under test is the business rule: **an order does not exist until a payment has
been authoritatively verified as paid.** So these tests assert as much about what is NOT
created as about what is.

Uses `crm_fake_dynamo.FakeDynamo` rather than a recording stub, for the reason that file
states: everything worth testing here *is* the ConditionExpression, and a fake that accepts any
condition would let a broken guard pass.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402
from lambda_utils import identifiers  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402

TABLE = 'stack-wecare-digital-WixOrderIds'


@pytest.fixture
def table():
    # The live table's key is `orderId` (measured via DescribeTable), even though the Amplify
    # model declares `wixOrderId`. Tests bind to the physical truth.
    return FakeDynamo(keys={TABLE: 'orderId'}).Table(TABLE)


def _scripted(values):
    """A generator yielding a fixed sequence, to force collisions deterministically."""
    it = iter(values)
    return lambda *a, **k: next(it)


def _keys_with(table, prefix):
    return [k for k in table.rows if str(k).startswith(prefix)]


# ════════════════════════════════════════════════════════════════════════════
# identifiers
# ════════════════════════════════════════════════════════════════════════════

def test_uuid7_is_version_7_and_time_ordered():
    a = identifiers.new_uuid7(now_ms=1_700_000_000_000)
    b = identifiers.new_uuid7(now_ms=1_700_000_001_000)
    assert identifiers.is_uuid7(a) and identifiers.is_uuid7(b)
    assert a < b, 'UUIDv7 must sort by time as a string'
    assert identifiers.uuid7_timestamp_ms(a) == 1_700_000_000_000


def test_uuid7_is_unique_at_volume():
    assert len({identifiers.new_uuid7() for _ in range(20000)}) == 20000


def test_ulid_is_26_chars_crockford_and_time_ordered():
    a = identifiers.new_ulid(now_ms=1_700_000_000_000)
    b = identifiers.new_ulid(now_ms=1_700_000_001_000)
    assert len(a) == identifiers.ULID_LENGTH == 26
    assert identifiers.is_ulid(a) and a < b
    assert identifiers.ulid_timestamp_ms(a) == 1_700_000_000_000
    for forbidden in 'ILOU':
        assert forbidden not in a


def test_ulid_is_unique_at_volume():
    assert len({identifiers.new_ulid() for _ in range(20000)}) == 20000


def test_identifiers_do_not_use_the_random_module():
    """SnapStart freezes `random`'s seed into the snapshot, so every restored sandbox would
    replay the same identifiers."""
    import inspect
    source = inspect.getsource(identifiers)
    assert 'import secrets' in source
    assert 'import random' not in source


# ════════════════════════════════════════════════════════════════════════════
# Meta reference_id constraints
# ════════════════════════════════════════════════════════════════════════════

def test_meta_reference_id_limit_is_thirty_five():
    assert order_keys.META_REFERENCE_ID_MAX_LENGTH == 35


@pytest.mark.parametrize('value', ['WD-PAY-ABC123', 'WD.PAY_123-x', 'a', 'A' * 35])
def test_valid_reference_ids_are_accepted(value):
    assert order_keys.is_valid_meta_reference_id(value)


@pytest.mark.parametrize('value', [
    '',                       # Meta: cannot be empty
    'A' * 36,                 # Meta: not more than 35 characters
    'WD PAY 123',             # space is outside the charset
    'WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST',  # the legacy order number itself
    'ref/123', 'ref#123', 'ref@123', None, 12345,
])
def test_invalid_reference_ids_are_rejected(value):
    assert not order_keys.is_valid_meta_reference_id(value)
    with pytest.raises(ValueError):
        order_keys.assert_valid_meta_reference_id(value)


def test_the_legacy_order_number_can_never_be_a_reference_id():
    """Why the two identifiers are separate: 47 chars, with spaces and colons.

    Pinned as a LITERAL rather than taken from the generator. The generator no longer emits
    this shape - FEAT-005 moved it to `WD-ORD-` + 8 - and the string above is a historical
    fact about numbers already issued, which is what has to keep being rejected.
    """
    number = 'WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST'
    assert len(number) > order_keys.META_REFERENCE_ID_MAX_LENGTH
    assert not order_keys.is_valid_meta_reference_id(number)


def test_a_current_order_number_is_meta_valid_and_still_must_not_be_a_reference():
    """The sensitivity companion, and the reason length was never the real protection.

    A current number is 15 characters of permitted charset, so `is_valid_meta_reference_id`
    answers True for it as a STRING - which is exactly why the refusal lives in
    `is_wd_order_number` and in `outbound-whatsapp._sanitize_reference_id`, not in a length
    check. An order number is not a payment reference regardless of whether Meta would take
    the bytes.
    """
    from lambda_utils.ecommerce.wix_domain import _generate_wd_order_number
    number = _generate_wd_order_number('2026-02-22T18:00:00Z')
    assert order_keys.is_valid_meta_reference_id(number)
    assert not number.startswith(order_keys.REFERENCE_ID_PREFIX)
    assert order_keys.is_wd_order_number(number)


def test_assert_valid_reference_never_truncates():
    """The defect being removed: truncation maps two distinct references onto one string, so
    two orders reconcile against a single payment."""
    over = 'WD-PAY-' + 'A' * 40
    with pytest.raises(ValueError):
        order_keys.assert_valid_meta_reference_id(over)


def test_minted_references_are_meta_valid_and_unique():
    minted = {order_keys.mint_payment_reference() for _ in range(5000)}
    assert len(minted) == 5000
    assert all(order_keys.is_valid_meta_reference_id(r) for r in minted)
    assert all(len(r) <= order_keys.RAZORPAY_RECEIPT_MAX_LENGTH for r in minted)


def test_mint_does_not_use_the_random_module():
    import inspect
    source = inspect.getsource(order_keys)
    assert 'import secrets' in source
    assert 'import random' not in source


# ════════════════════════════════════════════════════════════════════════════
# the public order number: WD-ORD- + 8
# ════════════════════════════════════════════════════════════════════════════

def test_public_order_number_is_the_prefix_plus_eight_safe_symbols():
    """WD-ORD-XXXXXXXX. Was a bare 12 characters until the owner chose the readable prefix.

    Eight symbols of entropy, not six, and the decision was measured: over this 30-symbol
    alphabet six symbols is ~29.4 bits, giving a 50% chance of a collision by ~33,800 orders and
    a 1-in-7,290 blind guess against a 100,000-order corpus. Eight is ~39.3 bits - 1 in 6,561,000
    - and keeps the retry loop theoretical past a million orders. A collision is never *wrong*
    (the conditional write refuses it) but it must not become the hot path, and the number must
    not be enumerable.
    """
    for _ in range(500):
        number = order_keys.mint_public_order_number()
        assert number.startswith(order_keys.PUBLIC_ORDER_NUMBER_PREFIX)
        assert len(number) == order_keys.PUBLIC_ORDER_NUMBER_LENGTH == 15
        tail = number[len(order_keys.PUBLIC_ORDER_NUMBER_PREFIX):]
        assert len(tail) == order_keys.PUBLIC_ORDER_NUMBER_ENTROPY == 8
        assert number == number.upper()
        assert all(c in order_keys.PUBLIC_ORDER_NUMBER_ALPHABET for c in tail)
        assert order_keys.is_public_order_number(number)
        assert order_keys.is_current_public_order_number(number)


def test_only_the_tail_is_random():
    """A reader must never have to wonder whether the prefix came out of the random source."""
    tails = {order_keys.mint_public_order_number()[7:] for _ in range(200)}
    assert len(tails) > 190, 'the tail is not varying, so the entropy is not where it should be'
    prefixes = {order_keys.mint_public_order_number()[:7] for _ in range(200)}
    assert prefixes == {'WD-ORD-'}


def test_historical_twelve_character_numbers_still_resolve():
    """NOT optional. Numbers already issued are printed on receipts, sitting in customers'
    WhatsApp history and quoted to support. A validator that stopped recognising them would break
    tracking and receipt lookup for every order placed before the prefix existed."""
    legacy = 'KMP4X9Q2DTR7'
    assert len(legacy) == order_keys.LEGACY_PUBLIC_ORDER_NUMBER_LENGTH == 12
    assert order_keys.is_public_order_number(legacy)
    # ...but nothing mints that shape any more, and the stricter predicate says so.
    assert not order_keys.is_current_public_order_number(legacy)


def test_the_minter_never_produces_the_legacy_shape():
    """Otherwise the migration silently has not happened."""
    for _ in range(300):
        assert order_keys.is_current_public_order_number(order_keys.mint_public_order_number())


def test_public_order_number_alphabet_excludes_confusable_characters():
    """It gets read aloud to support and typed into a tracking box.

    Six exclusions, not five: U goes as well as 0, 1, I, L and O, because U and V are the pair
    that gets confused when a number is spoken rather than read.
    """
    for forbidden in '01OILU':
        assert forbidden not in order_keys.PUBLIC_ORDER_NUMBER_ALPHABET
    assert len(order_keys.PUBLIC_ORDER_NUMBER_ALPHABET) == 30


def test_public_order_number_is_not_time_ordered():
    """Unlike orderId. A time-ordered public number leaks order volume to anyone holding two."""
    numbers = [order_keys.mint_public_order_number() for _ in range(200)]
    assert numbers != sorted(numbers)


def test_public_order_numbers_are_unique_at_volume():
    assert len({order_keys.mint_public_order_number() for _ in range(20000)}) == 20000


@pytest.mark.parametrize('value', [
    '', 'SHORT', 'A' * 13, None, 12345,
    '0KMP4X9Q2DTR',            # 0 is outside the alphabet
    'IKMP4X9Q2DTR',            # I is outside the alphabet
    '7kmp4x9q2dtr',            # lowercase
    'WD-ORD-ABC',              # prefixed but too short
    'WD-ORD-ABCDEFGHJ',        # prefixed but too long
    'WD-ORD-ABCDEF0H',         # 0 in the tail
    'WD-ORD-abcdefgh',         # lowercase tail
    'WDORD-ABCDEFGH',          # prefix mangled
    'wd-ord-ABCDEFGH',         # prefix lowercase
    ' WD-ORD-ABCDEFGH',        # leading space - not trimmed, deliberately
])
def test_invalid_public_order_numbers_are_rejected(value):
    assert not order_keys.is_public_order_number(value)
    assert not order_keys.is_current_public_order_number(value)


# ════════════════════════════════════════════════════════════════════════════
# BEFORE PAYMENT — a reference binds to an attempt and creates NO order
# ════════════════════════════════════════════════════════════════════════════

def test_allocating_a_payment_reference_creates_no_order_identity(table):
    """The central rule. Starting a payment must not mint an order number."""
    attempt = order_keys.new_payment_attempt_id()
    reference = order_keys.allocate_payment_reference(table, payment_attempt_id=attempt)

    assert order_keys.is_valid_meta_reference_id(reference)
    assert _keys_with(table, order_keys.ORDER_NUMBER_PREFIX) == [], \
        'an order number was reserved before payment'
    assert _keys_with(table, order_keys.PAYMENT_ATTEMPT_PREFIX) == []
    assert _keys_with(table, order_keys.PROVIDER_PAYMENT_PREFIX) == []

    row = table.get_item(
        Key={'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + reference})['Item']
    assert row['paymentAttemptId'] == attempt
    assert 'orderNumber' not in row and 'orderIdRef' not in row


def test_the_reference_row_resolves_to_its_attempt(table):
    attempt = order_keys.new_payment_attempt_id()
    reference = order_keys.allocate_payment_reference(table, payment_attempt_id=attempt)
    resolved = order_keys.resolve_payment_reference(table, reference)
    assert resolved['paymentAttemptId'] == attempt


def test_an_unknown_reference_resolves_to_nothing(table):
    """A payment event naming an unknown reference must not mint anything."""
    assert order_keys.resolve_payment_reference(table, 'WD-PAY-NEVERSEEN') is None


def test_a_legacy_reference_row_still_resolves(table):
    """Rows written before the split used REFERENCE#. Nothing writes it now."""
    table.put_item(Item={'orderId': order_keys.LEGACY_REFERENCE_PREFIX + 'WD-PAY-OLD1',
                         'paymentAttemptId': 'legacy-attempt'})
    assert order_keys.resolve_payment_reference(
        table, 'WD-PAY-OLD1')['paymentAttemptId'] == 'legacy-attempt'


def test_a_reference_cannot_be_bound_twice(table):
    assert order_keys.reserve_payment_reference(
        table, reference_id='WD-PAY-FIXED1', payment_attempt_id='a1') is True
    assert order_keys.reserve_payment_reference(
        table, reference_id='WD-PAY-FIXED1', payment_attempt_id='a2') is False
    row = table.get_item(Key={'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + 'WD-PAY-FIXED1'})
    assert row['Item']['paymentAttemptId'] == 'a1', 'the second binding overwrote the first'


def test_reference_allocation_fails_closed_on_a_storage_error(table):
    table.parent.arm_failure(TABLE, 'put_item', FakeClientError('ProvisionedThroughputExceeded'))
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.allocate_payment_reference(table, payment_attempt_id='a1')
    assert table.parent.count(TABLE) == 0


def test_a_read_error_is_not_reported_as_an_unknown_reference(table):
    """Absence means 'do not create an order', so a throttle must not look like absence."""
    table.parent.arm_failure(TABLE, 'get_item', FakeClientError('ThrottlingException'))
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.resolve_payment_reference(table, 'WD-PAY-ABC123')


def test_the_pre_payment_api_cannot_reserve_an_order_number():
    """§20: there must be no function that mints an order number while starting a payment."""
    assert not hasattr(order_keys, 'allocate_order_identity')


# ════════════════════════════════════════════════════════════════════════════
# AFTER PAID — order identity, claimed exactly once
# ════════════════════════════════════════════════════════════════════════════

def test_claiming_an_order_reserves_a_number_only_for_the_winner(table):
    attempt = order_keys.new_payment_attempt_id()
    order_id = order_keys.new_order_id()

    claimed, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=order_id,
        provider_transaction_id='pay_LIVE001')
    assert (claimed, won) == (order_id, True)

    number = order_keys.reserve_public_order_number(table, order_id=order_id)
    order_keys.record_order_number_on_claim(
        table, payment_attempt_id=attempt, order_number=number)

    stored = order_keys.resolve_order_for_payment(table, attempt)
    assert stored['orderIdRef'] == order_id
    assert stored['orderNumber'] == number
    assert order_keys.is_public_order_number(number)


def test_a_duplicate_webhook_creates_exactly_one_order(table):
    """Five deliveries of one captured payment => one order, one number."""
    attempt = order_keys.new_payment_attempt_id()
    first_id = order_keys.new_order_id()

    order_id, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=first_id,
        provider_transaction_id='pay_DUP')
    assert won is True
    number = order_keys.reserve_public_order_number(table, order_id=order_id)
    order_keys.record_order_number_on_claim(
        table, payment_attempt_id=attempt, order_number=number)

    for _ in range(4):
        again_id, again_won = order_keys.claim_order_for_payment(
            table, payment_attempt_id=attempt, order_id=order_keys.new_order_id(),
            provider_transaction_id='pay_DUP')
        assert again_won is False
        assert again_id == first_id

    assert len(_keys_with(table, order_keys.ORDER_NUMBER_PREFIX)) == 1
    assert len(_keys_with(table, order_keys.PAYMENT_ATTEMPT_PREFIX)) == 1


def test_one_provider_payment_can_fund_only_one_order(table):
    """§65. Even across two different payment attempts."""
    first = order_keys.new_order_id()
    order_keys.claim_order_for_payment(
        table, payment_attempt_id='attempt-1', order_id=first,
        provider_transaction_id='pay_SHARED')

    adopted, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id='attempt-2', order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_SHARED')
    assert won is False
    assert adopted == first


def test_a_loser_never_burns_an_order_number(table):
    """Claim first, reserve second. That ordering is what makes this true."""
    order_keys.claim_order_for_payment(
        table, payment_attempt_id='attempt-1', order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_RACE')
    before = len(_keys_with(table, order_keys.ORDER_NUMBER_PREFIX))

    _, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id='attempt-2', order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_RACE')
    assert won is False
    assert len(_keys_with(table, order_keys.ORDER_NUMBER_PREFIX)) == before


def test_an_order_number_collision_regenerates_without_overwriting(table):
    taken = order_keys.reserve_public_order_number(
        table, order_id='o1', generate=_scripted(['AAAAAAAAAAAA']))
    before = dict(table.get_item(
        Key={'orderId': order_keys.ORDER_NUMBER_PREFIX + taken})['Item'])

    got = order_keys.reserve_public_order_number(
        table, order_id='o2', generate=_scripted([taken, 'BBBBBBBBBBBB']))

    assert got == 'BBBBBBBBBBBB'
    after = table.get_item(Key={'orderId': order_keys.ORDER_NUMBER_PREFIX + taken})['Item']
    assert after == before, 'the pre-existing reservation was mutated'


def test_exhausting_order_number_attempts_fails_closed(table):
    order_keys.reserve_public_order_number(
        table, order_id='o1', generate=_scripted(['CCCCCCCCCCCC']))
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.reserve_public_order_number(
            table, order_id='o2', generate=lambda: 'CCCCCCCCCCCC', attempts=3)


def test_a_storage_error_yields_no_order_number_at_all(table):
    """The dc7d409a philosophy, preserved: never return an unreserved identifier."""
    table.parent.arm_failure(TABLE, 'put_item', FakeClientError('InternalServerError'))
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.reserve_public_order_number(table, order_id='o1')
    assert _keys_with(table, order_keys.ORDER_NUMBER_PREFIX) == []


def test_ten_thousand_order_numbers_contain_no_duplicate(table):
    numbers = [order_keys.reserve_public_order_number(table, order_id=f'o{i}')
               for i in range(10000)]
    assert len(set(numbers)) == 10000
    assert len(_keys_with(table, order_keys.ORDER_NUMBER_PREFIX)) == 10000


def test_recording_a_bad_order_number_is_refused(table):
    order_keys.claim_order_for_payment(
        table, payment_attempt_id='a1', order_id='o1', provider_transaction_id='pay_1')
    with pytest.raises(ValueError):
        order_keys.record_order_number_on_claim(
            table, payment_attempt_id='a1', order_number='not-a-number')


def test_a_crash_between_claim_and_reserve_is_recoverable(table):
    """The claim exists with no number. Re-entry must see that and finish the job."""
    attempt, order_id = 'a1', order_keys.new_order_id()
    order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=order_id,
        provider_transaction_id='pay_CRASH')

    interrupted = order_keys.resolve_order_for_payment(table, attempt)
    assert interrupted['orderIdRef'] == order_id
    assert 'orderNumber' not in interrupted, 'no number should exist yet'

    resumed_id, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_CRASH')
    assert (resumed_id, won) == (order_id, False)

    number = order_keys.reserve_public_order_number(table, order_id=resumed_id)
    order_keys.record_order_number_on_claim(
        table, payment_attempt_id=attempt, order_number=number)
    assert order_keys.resolve_order_for_payment(table, attempt)['orderNumber'] == number


# ════════════════════════════════════════════════════════════════════════════
# the invariants, stated as the business states them
# ════════════════════════════════════════════════════════════════════════════

def _order_count(table, attempt):
    row = order_keys.resolve_order_for_payment(table, attempt)
    return 1 if row and row.get('orderIdRef') else 0


@pytest.mark.parametrize('terminal_state', ['PAYMENT_FAILED', 'PAYMENT_CANCELLED',
                                            'PAYMENT_EXPIRED', 'PAYMENT_PENDING'])
def test_a_payment_that_is_not_paid_has_zero_orders(table, terminal_state):
    """§76. The attempt and its reference exist; the order does not."""
    attempt = order_keys.new_payment_attempt_id()
    order_keys.allocate_payment_reference(
        table, payment_attempt_id=attempt, extra={'status': terminal_state})

    assert _order_count(table, attempt) == 0
    assert _keys_with(table, order_keys.ORDER_NUMBER_PREFIX) == []


def test_a_paid_verified_payment_has_exactly_one_order(table):
    attempt = order_keys.new_payment_attempt_id()
    order_keys.allocate_payment_reference(table, payment_attempt_id=attempt)
    order_id, _ = order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_OK')
    number = order_keys.reserve_public_order_number(table, order_id=order_id)
    order_keys.record_order_number_on_claim(
        table, payment_attempt_id=attempt, order_number=number)

    assert _order_count(table, attempt) == 1


def test_a_failed_attempt_retried_keeps_its_lineage_and_gets_a_new_reference(table):
    """§35. A genuine retry is a new attempt; a delivery retry is not."""
    first = order_keys.new_payment_attempt_id()
    first_ref = order_keys.allocate_payment_reference(
        table, payment_attempt_id=first, extra={'status': 'PAYMENT_FAILED'})

    second = order_keys.new_payment_attempt_id()
    second_ref = order_keys.allocate_payment_reference(
        table, payment_attempt_id=second, extra={'retryOf': first, 'attemptNumber': 2})

    assert second != first and second_ref != first_ref
    row = table.get_item(
        Key={'orderId': order_keys.PAYMENT_REFERENCE_PREFIX + second_ref})['Item']
    assert row['retryOf'] == first
    assert _order_count(table, first) == 0 and _order_count(table, second) == 0


def test_a_message_delivery_retry_keeps_the_same_reference(table):
    """Re-sending the same order_details must not mint a second reference."""
    attempt = order_keys.new_payment_attempt_id()
    reference = order_keys.allocate_payment_reference(table, payment_attempt_id=attempt)
    for _ in range(3):
        assert order_keys.resolve_payment_reference(
            table, reference)['paymentAttemptId'] == attempt
    assert len(_keys_with(table, order_keys.PAYMENT_REFERENCE_PREFIX)) == 1


# ════════════════════════════════════════════════════════════════════════════
# reservations must never expire
# ════════════════════════════════════════════════════════════════════════════

def test_no_reservation_row_carries_a_ttl(table):
    """A TTL on a uniqueness reservation is an identifier that gets reissued once it expires.
    The live table has TTL DISABLED; this asserts the rows would not opt in either."""
    attempt = order_keys.new_payment_attempt_id()
    order_keys.allocate_payment_reference(table, payment_attempt_id=attempt)
    order_id, _ = order_keys.claim_order_for_payment(
        table, payment_attempt_id=attempt, order_id=order_keys.new_order_id(),
        provider_transaction_id='pay_TTL')
    order_keys.reserve_public_order_number(table, order_id=order_id)

    for row in table.parent.all_rows(TABLE):
        assert 'ttl' not in row
        assert 'expiresAt' not in row


# ════════════════════════════════════════════════════════════════════════════
# legacy WD numbers, for orders synced from Wix
# ════════════════════════════════════════════════════════════════════════════

def test_is_wd_order_number_matches_the_format_actually_generated():
    """The predicate must match whatever the generator emits TODAY.

    The original defect was `startswith('WD-ORD-')` against a generator that emitted a SPACE
    at index 6. FEAT-005 moved the generator to the current `WD-ORD-` + 8 form, so the shape
    being matched is now the prefixed one - and a hex-only tail pattern would have missed it,
    which is the second half of the same defect pointing the other way.
    """
    from lambda_utils.ecommerce.wix_domain import _generate_wd_order_number
    number = _generate_wd_order_number('2026-02-22T18:00:00Z')
    assert order_keys.is_current_public_order_number(number), \
        'format changed; this test is now stale'
    assert order_keys.is_wd_order_number(number)


def test_is_wd_order_number_also_matches_the_two_legacy_spellings():
    """Still True for history, which is the half FEAT-005 must not touch."""
    assert order_keys.is_wd_order_number('WD-ORD-A1B2C3D4')
    assert order_keys.is_wd_order_number('WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST')


@pytest.mark.parametrize('value', ['', 'WD-ORD', 'ORD-A1B2C3D4', 'WD-PAY-A1B2C3D4', None])
def test_is_wd_order_number_rejects_non_order_numbers(value):
    assert not order_keys.is_wd_order_number(value)


def test_legacy_reservation_still_fails_closed(table):
    """Used by the Wix sync path for orders that already exist and are already paid."""
    table.parent.arm_failure(TABLE, 'put_item', FakeClientError('ProvisionedThroughputExceeded'))
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.reserve_order_number(table, '2026-02-22T18:00:00Z')
    assert table.parent.count(TABLE) == 0


def test_recover_crash_between_provider_claim_and_attempt_claim(table):
    provider_key = order_keys.PROVIDER_PAYMENT_PREFIX + 'pay-recovery'
    table.put_item(Item={'orderId': provider_key, 'orderIdRef': 'committed-order',
                        'paymentAttemptId': 'attempt-recovery', 'providerTransactionId': 'pay-recovery'})
    order_id, won = order_keys.claim_order_for_payment(
        table, payment_attempt_id='attempt-recovery', order_id='discard-this-new-id',
        provider_transaction_id='pay-recovery')
    assert won and order_id == 'committed-order'
    assert order_keys.resolve_order_for_payment(table, 'attempt-recovery')['orderIdRef'] == 'committed-order'


def test_concurrent_numbering_preserves_the_first_public_number(table):
    order_keys.claim_order_for_payment(table, payment_attempt_id='attempt-number', order_id='order-number')
    first = order_keys.record_order_number_on_claim(
        table, payment_attempt_id='attempt-number', order_number='ABCDEFGHJKMN')
    second = order_keys.record_order_number_on_claim(
        table, payment_attempt_id='attempt-number', order_number='PQRSTVWXYZ23')
    assert first == second == 'ABCDEFGHJKMN'
