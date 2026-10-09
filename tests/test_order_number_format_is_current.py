"""FEAT-005: the one shape this system still MINTS, and every shape it still RECOGNISES.

Owner instruction: use the latest order-number format and remove the old form where
applicable. "Remove the old form" is read here as STOP PRODUCING it, never as stop
RECOGNISING it. Orders were really issued in the legacy shape: those numbers are printed on
receipts, sitting in customers' WhatsApp history and quoted to support, so a validator that
forgot them would break tracking and receipt lookup for every order placed before the
change. That is data-integrity breakage, not tidying.

So two things have to be true at the same time, and this file asserts both:

  * EVERY minter produces `WD-ORD-` + 8 symbols of `PUBLIC_ORDER_NUMBER_ALPHABET`. There are
    two that matter - our own checkout, and the Wix backfill that assigns a display number
    to orders Wix already holds. Checkout was already there; the backfill was not.
  * EVERY legacy shape still resolves, through the predicate that owns it.

WHICH PREDICATE OWNS WHICH SHAPE, because this was documented wrongly and the wrong version
is the dangerous one to act on:

    value                                            is_public  is_current  is_wd
    'KMP4X9Q2DTR7'              bare 12, legacy        True       False      False
    'WD-ORD-K4M7PQR9'           current                True       True       True
    'WD-ORD-A1B2C3D4'           legacy compact         False      False      True
    'WD-ORD - A1B2C3D4 - ...'   legacy spaced          False      False      True

`is_public_order_number` does NOT accept the spaced form and never did - its two branches are
the current prefixed form and the bare 12-character one, both over an alphabet that excludes
0, 1, I, L, O and U. The spaced and compact `WD-ORD` numbers the Wix path minted are 8 HEX
characters, so `A1B2C3D4` fails that alphabet on the `1`. The predicate that owns those two
is `is_wd_order_number`, and it is the one the Wix idempotency check and the
reference_id refusal both call. Hence the `is_wd` column above: it had to learn the current
form, or switching the minter would have silently broken both of them.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'messaging',
                                                'whatsapp-business-api')))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import order_creation as oc  # noqa: E402
from lambda_utils.ecommerce import order_keys, payment_attempt  # noqa: E402
from lambda_utils.ecommerce.wix_domain import _generate_wd_order_number  # noqa: E402

TABLE = 'stack-wecare-digital-WixOrderIds'
CUSTOMER = 'CUS_01J0000000000000000000000'
REFERENCE = 'WD-PAY-ABCDEFGHJKMNPQ'
TXN = 'pay_LIVE0000000001'
AMOUNT = 59900
NOW = 1_700_000_000

ORDER_DATE = '2026-02-22T18:00:00Z'

#: The two legacy shapes, as literals. Written out rather than generated, because the
#: generator is the thing this FEAT changes - a fixture that called it would stop describing
#: history the moment the minter moved, which is exactly the mistake being corrected here.
LEGACY_BARE_TWELVE = 'KMP4X9Q2DTR7'
LEGACY_SPACED = 'WD-ORD - A1B2C3D4 - 22-02-2026 - 23:30:00 - IST'
LEGACY_COMPACT = 'WD-ORD-A1B2C3D4'


@pytest.fixture
def table():
    return FakeDynamo(keys={TABLE: 'orderId'}).Table(TABLE)


def _paid():
    return lambda _ref: (True, TXN, AMOUNT, 'INR')


# ════════════════════════════════════════════════════════════════════════════
# the minters
# ════════════════════════════════════════════════════════════════════════════

def test_checkout_mints_the_current_public_format(table):
    """Our own checkout, down the real reconciliation path. It already did this.

    No production change was needed here - `order_creation._finish_numbering` reserves
    through `reserve_public_order_number`. This is the LOCK: `test_order_creation` asserts
    the looser `is_public_order_number`, which a legacy-shaped number would also satisfy, so
    on its own it could not notice checkout regressing to the old form.
    """
    stored = payment_attempt.build(
        customer_id=CUSTOMER, reference_id=REFERENCE, amount_paise=AMOUNT,
        configuration_name='WECAREDIGITAL', now=NOW)
    outcome = oc.reconcile_payment(
        table=table, reference_id=REFERENCE,
        verify_payment=_paid(),
        load_attempt=lambda _ref: stored,
    )
    assert outcome.outcome == oc.ORDER_CREATED
    assert order_keys.is_current_public_order_number(outcome.order_number)


def test_the_wix_backfill_minter_produces_the_current_format():
    """The one production change: the backfill generator no longer mints the old shape.

    `WD-ORD - {UUID8} - {DD-MM-YYYY} - {HH:MM:SS} - IST` is gone. Asserted over many draws
    because the alphabet is wider than hex: a generator still emitting 8 hex characters
    would pass a single-draw check about two thirds of the time per character.
    """
    for _ in range(300):
        number = _generate_wd_order_number(ORDER_DATE)
        assert order_keys.is_current_public_order_number(number)
        assert ' - ' not in number
        assert 'IST' not in number
        assert not re.search(r'\d{2}-\d{2}-\d{4}', number), 'the number still carries a date'


def test_the_backfill_number_carries_no_timestamp():
    """Deliberate, and the reason is the same one recorded on `mint_public_order_number`.

    A public number that encodes when the order was placed leaks order volume to anyone
    holding two of them. The `order_date` argument stays in the signature because
    `reserve_order_number` calls every generator with it, but it no longer reaches the value.
    """
    assert _generate_wd_order_number('2026-02-22T18:00:00Z') != \
        _generate_wd_order_number('2026-02-22T18:00:00Z')
    for value in ('', None, '2026-01-01', 'not-a-date'):
        assert order_keys.is_current_public_order_number(_generate_wd_order_number(value))


def test_a_reserved_backfill_number_is_the_current_format(table):
    """Through `reserve_order_number`, which is what `wix-store` actually calls."""
    number = order_keys.reserve_order_number(table, ORDER_DATE)
    assert order_keys.is_current_public_order_number(number)
    assert order_keys.ORDER_NUMBER_PREFIX + number in table.rows


def test_a_backfill_collision_regenerates_without_overwriting(table):
    """The retry loop still works, and the row that already exists is never overwritten.

    The reservation is a conditional write, so a collision must be refused by DynamoDB and
    answered with a fresh candidate - not resolved by clobbering the winner.
    """
    taken = order_keys.reserve_order_number(table, ORDER_DATE,
                                            extra={'wixOrderId': 'first'})
    scripted = iter([taken, 'WD-ORD-K4M7PQR9'])
    got = order_keys.reserve_order_number(
        table, ORDER_DATE, generate=lambda *a, **k: next(scripted),
        extra={'wixOrderId': 'second'})

    assert got == 'WD-ORD-K4M7PQR9'
    assert order_keys.is_current_public_order_number(got)
    assert table.rows[order_keys.ORDER_NUMBER_PREFIX + taken]['wixOrderId'] == 'first'
    assert table.rows[order_keys.ORDER_NUMBER_PREFIX + got]['wixOrderId'] == 'second'


def test_exhausting_backfill_attempts_still_fails_closed(table):
    """A number that could not be reserved is never returned. Unchanged by the new shape."""
    taken = order_keys.reserve_order_number(table, ORDER_DATE)
    with pytest.raises(order_keys.OrderIdentityUnavailable):
        order_keys.reserve_order_number(table, ORDER_DATE,
                                        generate=lambda *a, **k: taken)


# ════════════════════════════════════════════════════════════════════════════
# the legacy shapes still resolve - this is the half that must NOT change
# ════════════════════════════════════════════════════════════════════════════

def test_a_legacy_bare_twelve_character_number_still_validates():
    """`is_public_order_number` is NOT narrowed. Historical orders keep resolving."""
    assert len(LEGACY_BARE_TWELVE) == order_keys.LEGACY_PUBLIC_ORDER_NUMBER_LENGTH == 12
    assert order_keys.is_public_order_number(LEGACY_BARE_TWELVE)
    # ...and the stricter predicate still says nothing mints that shape any more.
    assert not order_keys.is_current_public_order_number(LEGACY_BARE_TWELVE)


def test_the_legacy_spaced_and_compact_wd_numbers_still_validate():
    """Both legacy `WD-ORD` spellings, through the predicate that owns them.

    `is_wd_order_number` is what `wix-store` asks before reusing a stored mapping and what
    the outbound sender asks before refusing to send an order number as a payment reference.
    Those two sites are the reason this must keep answering True for history.
    """
    for legacy in (LEGACY_SPACED, LEGACY_COMPACT):
        assert order_keys.is_wd_order_number(legacy)
    # The spaced form is 8 HEX characters, which is outside the public alphabet on the `1`.
    # Recorded because the opposite was written down, and acting on it would have meant
    # widening `is_public_order_number` for a claim that was never true.
    assert not order_keys.is_public_order_number(LEGACY_SPACED)
    assert not order_keys.is_public_order_number(LEGACY_COMPACT)


def test_the_current_format_is_recognised_as_a_wd_order_number():
    """The gap that switching the minter would otherwise have opened, at two live sites.

    `_WD_ORDER_NUMBER_RE` matched 8 HEX characters, and the public alphabet runs past F. So a
    freshly minted backfill number would have been invisible to:

      * `wix-store._get_or_create_wd_order_number`, whose reuse check is this predicate - it
        would have regenerated and overwritten the mapping on every call, which is the exact
        defect that check was added to fix; and
      * `outbound-whatsapp._sanitize_reference_id`, which refuses an order number as a
        payment reference (R2.9) by asking this predicate - a 15-character `WD-ORD-K4M7PQR9`
        is Meta-valid as a string, so it would have been handed to Meta as a reference.

    Widening, never narrowing: every legacy answer above is unchanged.
    """
    for _ in range(300):
        assert order_keys.is_wd_order_number(_generate_wd_order_number(ORDER_DATE))
    assert order_keys.is_wd_order_number('WD-ORD-K4M7PQR9')


@pytest.mark.parametrize('value', [
    '', None, 12345, 'WD-PAY-ABCDEFGHJKMNPQ', 'WD-REQ-K4M7PQR9', 'WD-ORD',
    'WD-ORD-K4M7PQR', 'WD-ORDER-K4M7PQR9', 'KMP4X9Q2DTR7',
])
def test_widening_the_wd_predicate_did_not_make_it_accept_anything(value):
    """The sensitivity half. A wider pattern that matches everything proves nothing."""
    assert not order_keys.is_wd_order_number(value)


# ════════════════════════════════════════════════════════════════════════════
# display: the short id a customer reads
# ════════════════════════════════════════════════════════════════════════════

def test_the_short_id_is_the_eight_distinguishing_characters_in_both_shapes():
    """`flows.orders.extract_short_id` feeds the Flow dropdown and the stored `shortId`.

    It split the legacy value on `' - '` and fell back to the first 12 characters, so a
    current-format number came out as `WD-ORD-K4M7` - a truncated prefix with the only
    distinguishing part cut off. The Wix sync stores this value and the dropdown title shows
    it, so the fallback had to learn the current shape when the minter moved.
    """
    from flows.orders import extract_short_id

    assert extract_short_id(LEGACY_SPACED) == 'A1B2C3D4'
    assert extract_short_id('WD-ORD-K4M7PQR9') == 'K4M7PQR9'
    assert extract_short_id('') == ''
    # Not an order number at all: the old fallback is untouched for everything else.
    assert extract_short_id('some-internal-uuid-value') == 'some-interna'


def test_the_short_id_of_a_minted_backfill_number_is_its_tail():
    number = _generate_wd_order_number(ORDER_DATE)
    from flows.orders import extract_short_id

    short = extract_short_id(number)
    assert short == number[len(order_keys.PUBLIC_ORDER_NUMBER_PREFIX):]
    assert len(short) == order_keys.PUBLIC_ORDER_NUMBER_ENTROPY == 8
