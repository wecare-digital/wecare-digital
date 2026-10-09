"""`list_orders` offers public order numbers only, and eligibility is a separate question.

`list_orders` had two jobs. It built the SELECT_RECORD choices for the paid Submit Request Flow,
falling back to the internal order UUID when a row had no `orderNumber` - which
`flows/customer_commands.order_page` already refuses, with the comment "Never fall back to internal
UUIDs as customer-facing order numbers". Two paths, one product, opposite rules. And its return
value doubled as a boolean eligibility gate at `flows/catalog_services.py`, so narrowing it
naively would flip a customer whose prior orders are all legacy and unnumbered from ELIGIBLE to
REFUSED - purchase-blocking, on the gated native path where it is hardest to notice.

So the display rule goes inside `list_orders`' loop, where `orderNumber` and `oid` are both in
scope, and eligibility moves to `has_prior_order`. The two tests that matter most here are
`test_list_orders_returns_a_plain_list`, which fails if the skipped count is ever returned
alongside the list - a 2-tuple is always truthy, so it would make the NO_ORDERS screen unreachable
and serialise a tuple into a live Flow - and `test_a_legacy_only_customer_is_still_eligible`, which
asserts both halves of the separation at once.
"""
import importlib
import json
import logging
import pathlib
import sys
from unittest.mock import Mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from coupon_fake_dynamo import FakeTable  # noqa: E402
from test_paid_submit_request import flow_module, setup  # noqa: E402,F401 - reused rigs
from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import order_keys  # noqa: E402
from lambda_utils.ecommerce import paid_submit_request as paid  # noqa: E402
from lambda_utils.ecommerce import service_requests  # noqa: E402

OWNER = '11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
STRANGER = '22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
PHONE = '+919876543210'

#: The paid Submit Request purchase itself. Never offerable as its own parent order.
PARENT = {'customerId': OWNER, 'orderId': 'ffffffff-ffff-4fff-8fff-ffffffffffff'}

#: A mintable current-format number: `WD-ORD-` plus 8 characters of the minter's alphabet.
NUMBERED = 'WD-ORD-HJKMNPQR'

#: A bare 12-character number from BEFORE the prefix existed. Nothing mints this any more, but
#: every order that carries one is printed on a receipt and sitting in a customer's chat history.
LEGACY_BARE = 'HJKMNPQRSTVW'

#: An internal order id, UUID-shaped - exactly what must never reach a customer as a label.
UNNUMBERED_ID = 'd1f0a7c2-9b3e-4c51-8a6d-77c2f0e41b95'


def _orders(*rows, owner=OWNER):
    """An OrderTable fake carrying the GSI `list_orders` queries."""
    table = FakeTable(key_attr='orderId', name='orders',
                      indexes={'customerId-createdAt-index': ('customerId', 'createdAt')})
    for index, row in enumerate(rows):
        table.seed({'customerId': owner, 'createdAt': index + 1, **row})
    return table


def _records(caplog):
    """Every structured record `list_orders` emitted, parsed."""
    found = []
    for record in caplog.records:
        try:
            found.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    return found


# ---------------------------------------------------------------------------
# 1. The display rule
# ---------------------------------------------------------------------------

def test_orders_without_a_public_number_are_not_offered():
    """A row with no `orderNumber` is skipped, not labelled with its internal UUID."""
    orders = _orders({'orderId': 'numbered', 'orderNumber': NUMBERED},
                     {'orderId': UNNUMBERED_ID})
    result = paid.list_orders(orders, PARENT)
    assert result == [{'id': 'numbered', 'title': NUMBERED}]
    # Stated as a property too, not only as an equality: no offered label may be an internal id.
    # Asked through `is_cognito_subject` so the UUID pattern is not copied into this file either.
    assert not any(customer_auth.is_cognito_subject(choice['title']) for choice in result)
    assert all(choice['title'] != choice['id'] for choice in result)


def test_a_legacy_bare_twelve_character_number_is_still_offered():
    """`is_public_order_number`, NOT `is_current_public_order_number`.

    The looser predicate deliberately accepts the bare 12-character form minted before the prefix
    existed. The stricter one would silently drop every order placed before that change, which is
    a narrower defect wearing the same fix.
    """
    orders = _orders({'orderId': 'legacy', 'orderNumber': LEGACY_BARE},
                     {'orderId': 'current', 'orderNumber': NUMBERED})
    assert order_keys.is_public_order_number(LEGACY_BARE)
    assert not order_keys.is_current_public_order_number(LEGACY_BARE)
    offered = {choice['id']: choice['title'] for choice in paid.list_orders(orders, PARENT)}
    assert offered == {'legacy': LEGACY_BARE, 'current': NUMBERED}


def test_the_parent_order_is_still_excluded():
    """Sensitivity proof: the new `continue` did not disturb the existing self-exclusion.

    The parent row carries a perfectly good number here, so the display rule cannot be what
    removes it - only the `oid == row['orderId']` test can. A stranger's row is seeded alongside
    for the same reason, against the ownership recheck.
    """
    orders = _orders({'orderId': PARENT['orderId'], 'orderNumber': NUMBERED},
                     {'orderId': 'sibling', 'orderNumber': LEGACY_BARE})
    orders.seed({'orderId': 'stranger', 'customerId': STRANGER, 'createdAt': 9,
                 'orderNumber': 'WD-ORD-MNPQRSTV'})
    assert [choice['id'] for choice in paid.list_orders(orders, PARENT)] == ['sibling']


# ---------------------------------------------------------------------------
# 2. The shape. This is the test that catches the tuple mistake.
# ---------------------------------------------------------------------------

def test_list_orders_returns_a_plain_list(setup, flow_module, monkeypatch):
    """A plain `list[dict]`, so an empty selector stays falsy and NO_ORDERS stays reachable.

    Returning `(choices, skipped)` instead would be always truthy: `flows/paid_submit_request`'s
    `if not choices:` would never fire, the NO_ORDERS screen would be unreachable, and a tuple
    would be serialised into a LIVE Flow screen. The screen is driven here rather than inspected,
    because "the caller still branches correctly" is the actual requirement.
    """
    requests, keys, orders, row = setup
    empty = paid.list_orders(_orders({'orderId': UNNUMBERED_ID}), PARENT)
    assert type(empty) is list
    assert empty == []
    assert not empty

    _, token = paid.prepare(requests, keys, row['requestId'])
    monkeypatch.setattr(flow_module, 'tables', lambda: (requests, keys, orders))
    assert flow_module.route('INIT', '', {}, token)['screen'] == 'SELECT_RECORD'
    # The one offerable order loses its number, so nothing is offerable any more.
    orders.rows['earlier'].pop('orderNumber')
    assert flow_module.route('INIT', '', {}, token)['screen'] == 'NO_ORDERS'


# ---------------------------------------------------------------------------
# 3. The separation. This is the test that would have caught the naive fix.
# ---------------------------------------------------------------------------

def test_a_legacy_only_customer_is_still_eligible(monkeypatch):
    """Eligible to buy, and simply shown a shorter selector. Both halves, asserted together.

    A customer whose prior orders are all legacy and unnumbered is still entitled to buy Submit
    Request. `has_prior_order` answers that question and deliberately does NOT apply the display
    rule; `list_orders` applies the display rule and answers nothing about entitlement. The third
    assertion drives the real call site, because the regression this prevents is purchase-blocking
    and lives at `flows/catalog_services.py`, not in either function.
    """
    orders = _orders({'orderId': UNNUMBERED_ID}, {'orderId': 'also-unnumbered'})

    assert paid.has_prior_order(orders, PARENT) is True
    assert paid.list_orders(orders, PARENT) == []

    # Eligibility is still OWNED and still excludes the purchase itself.
    assert paid.has_prior_order(_orders({'orderId': UNNUMBERED_ID}, owner=STRANGER), PARENT) is False
    assert paid.has_prior_order(_orders({'orderId': PARENT['orderId']}), PARENT) is False
    assert paid.has_prior_order(_orders(), PARENT) is False

    # And the call site no longer refuses this customer.
    monkeypatch.syspath_prepend(str(ROOT / 'amplify/functions/messaging/whatsapp-business-api'))
    module = importlib.import_module('flows.catalog_services')
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': OWNER})
    tables = {'stack-wecare-digital-ContactsTable': contacts,
              'stack-wecare-digital-WixOrderIds': FakeTable(key_attr='orderId'),
              'stack-wecare-digital-OrderTable': orders,
              'stack-wecare-digital-ServiceRequestsTable': FakeTable(key_attr='requestId')}
    db = Mock()
    db.Table.side_effect = lambda name: tables[name]
    cognito = Mock()
    cognito.list_users.return_value = {'Users': [{'Enabled': True, 'Attributes': [
        {'Name': 'sub', 'Value': OWNER}, {'Name': 'phone_number', 'Value': PHONE},
        {'Name': 'phone_number_verified', 'Value': 'true'}]}]}
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    sends = []
    monkeypatch.setattr(module, '_send', lambda client, row, **body: sends.append(body))
    monkeypatch.setattr(module.store, 'request_intent', lambda *a, **k: {'intentId': 'intent-1'})
    monkeypatch.setattr(module, '_invoke', lambda *a, **k: {'outcome': 'CATALOG_SERVICE_PREPARED'})
    result = module.handle({'contactId': 'contact', 'senderPhone': PHONE,
                            'phoneNumberId': 'sender', 'sourceMessageId': 'message',
                            'lines': [{'productId': next(iter(service_requests.SERVICE_PRODUCT_IDS)),
                                       'variantId': service_requests.SERVICE_VARIANT_BY_KIND['SUBMIT_REQUEST'],
                                       'quantity': 1}]}, Mock())
    assert result['outcome'] != 'SUBMIT_REQUEST_PARENT_ORDER_REQUIRED'
    assert not any('could not find an earlier order' in str(body.get('content', ''))
                   for body in sends)


# ---------------------------------------------------------------------------
# 4. The log line
# ---------------------------------------------------------------------------

def test_the_skipped_count_is_logged_without_identifiers(caplog):
    """A count, and nothing else. Never a fileId, orderId, phone or filename.

    `log_event`'s `**kwargs` makes the posture explicit at the call site: exactly one keyword and
    it is a number. The second half of this test is the one that matters - it reads every value in
    the record and refuses any that carries an identifier from the fixture.
    """
    orders = _orders({'orderId': 'numbered', 'orderNumber': NUMBERED},
                     {'orderId': UNNUMBERED_ID},
                     {'orderId': 'also-unnumbered'})
    caplog.set_level(logging.INFO, logger=paid.logger.name)
    result = paid.list_orders(orders, PARENT)
    assert [choice['id'] for choice in result] == ['numbered']

    [record] = [found for found in _records(caplog)
                if found.get('event') == 'order_choices_unnumbered']
    assert record['skipped'] == 2
    assert set(record) == {'event', 'skipped'}
    rendered = json.dumps(record)
    for identifier in (UNNUMBERED_ID, 'also-unnumbered', PARENT['orderId'], OWNER, PHONE):
        assert identifier not in rendered

    # Nothing to report when nothing was skipped: no empty-count noise on the paid path.
    caplog.clear()
    paid.list_orders(_orders({'orderId': 'numbered', 'orderNumber': NUMBERED}), PARENT)
    assert not [found for found in _records(caplog)
                if found.get('event') == 'order_choices_unnumbered']
