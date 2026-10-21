"""One contact row per person and one order shape for every channel.

`lambda_utils.contact_store` is how the WhatsApp inbox, Flows, website checkout and staff tools
find a person in ContactsTable, whichever writer minted the row. `ecommerce.order_record` is the
one order shape and the one way to read OrderTable back, so website checkout orders, WhatsApp
catalog orders and staff-entered orders list, pick and track alike.
"""
from __future__ import annotations

import importlib
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
WBA = ROOT / 'amplify' / 'functions' / 'messaging' / 'whatsapp-business-api'
for _path in (str(SHARED), str(WBA), str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils import contact_store, flow_completion as fc, shared_tables  # noqa: E402
from lambda_utils.ecommerce import finalization, order_record, payment_attempt  # noqa: E402

CONTACTS = shared_tables.CONTACTS.default_name
ORDERS = shared_tables.ORDERS.default_name
SUBMISSIONS = shared_tables.FLOW_SUBMISSIONS.default_name


def contacts_db(*rows):
    fake = FakeDynamo({CONTACTS: 'id'}, {CONTACTS: {
        contact_store.PHONE_INDEX: ('phone', None),
        contact_store.BSUID_INDEX: ('bsuid', None),
    }})
    for row in rows:
        fake.Table(CONTACTS).put_item(Item=dict(row))
    return fake


# ── contacts ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('raw,digits,canonical', [
    ('+91 98765 43210', '919876543210', '+919876543210'),
    ('919876543210', '919876543210', '+919876543210'),
    ('9876543210', '9876543210', '+9876543210'),   # no country is ever guessed
    ('123', '', ''),
    (None, '', ''),
])
def test_one_spelling_for_new_writes(raw, digits, canonical):
    assert contact_store.digits(raw) == digits
    assert contact_store.canonical_phone(raw) == canonical


def test_lookup_variants_cover_every_stored_spelling():
    assert contact_store.phone_variants('+91 98765 43210') == [
        '+919876543210', '919876543210', '+91 98765 43210']


def test_the_inbox_row_is_found_by_its_deterministic_key():
    db = contacts_db({'id': 'wa919876543210', 'contactId': 'wa919876543210',
                      'phone': '+919876543210'})
    assert contact_store.lookup_id(db.Table(CONTACTS), '+91 98765 43210') == 'wa919876543210'
    assert (CONTACTS, 'query:phone-index') not in db.calls, 'the cheap key read should win'


def test_a_website_minted_row_is_found_through_the_phone_index():
    """The defect this module closes: a hand-derived `wa{phone}` get missed this row."""
    website_id = '6f1c2d3e-0000-5000-8000-000000000001'
    db = contacts_db({'id': website_id, 'contactId': website_id, 'phone': '+919876543210',
                      'checkoutCustomerId': 'sub-1'})
    assert contact_store.lookup_id(db.Table(CONTACTS), '919876543210') == website_id


def test_a_bare_digits_row_written_by_an_old_writer_is_still_found():
    db = contacts_db({'id': 'legacy-1', 'contactId': 'legacy-1', 'phone': '919876543210'})
    assert contact_store.lookup_id(db.Table(CONTACTS), '+919876543210') == 'legacy-1'


def test_a_bsuid_recipient_resolves_the_same_live_contact():
    db = contacts_db({'id': 'contact-bsuid', 'contactId': 'contact-bsuid',
                      'phone': '+918100640044', 'bsuid': 'US.13491208655302741918'})
    row = contact_store.find_by_bsuid(db.Table(CONTACTS), 'US.13491208655302741918')
    assert row is not None
    assert row['id'] == 'contact-bsuid'
    assert (CONTACTS, 'query:bsuid-index') in db.calls


def test_soft_deleted_rows_are_never_returned():
    db = contacts_db({'id': 'wa919876543210', 'contactId': 'wa919876543210',
                      'phone': '+919876543210', 'deletedAt': 1})
    assert contact_store.lookup(db.Table(CONTACTS), '+919876543210') is None


def test_flow_contact_lookup_uses_the_shared_store(monkeypatch):
    from flows import common as flows_common
    website_id = '6f1c2d3e-0000-5000-8000-000000000002'
    db = contacts_db({'id': website_id, 'contactId': website_id, 'phone': '+918100640044'})
    monkeypatch.setattr(flows_common, 'dynamodb', db)
    assert flows_common.find_contact_by_phone('918100640044') == website_id


# ── orders ─────────────────────────────────────────────────────────────────────────

WEBSITE_ORDER = {
    'orderId': '0192f3a4-5b6c-7d8e-9f00-112233445566', 'orderNumber': 'WD-ORD-K4M7PQR9',
    'amountPaise': 59900, 'currency': 'INR', 'paymentStatus': 'PAYMENT_PAID',
    'orderStatus': 'active', 'status': 'active', 'source': 'website', 'channel': 'website',
    'customerPhone': '+918100640044', 'createdAt': Decimal('1760500000'),
}
LEGACY_ORDER = {
    'orderId': 'WD-ORD - A1B2C3D4 - 22-02-2026 - 18:00:00 - IST', 'shortId': 'A1B2C3D4',
    'source': 'manual', 'totalAmount': Decimal('499.00'), 'paymentStatus': 'pending',
    'orderStatus': 'fulfilled', 'status': 'active', 'orderDateIST': '22 Feb 2026, 06:00 PM',
    'customerPhone': '918100640044', 'createdAt': 1760400000,
}


def test_a_checkout_order_reads_in_the_shared_vocabulary():
    view = order_record.view(WEBSITE_ORDER)
    assert view['orderNumber'] == 'WD-ORD-K4M7PQR9' and view['shortId'] == 'K4M7PQR9'
    assert view['paymentStatus'] == 'paid' and view['channel'] == 'website'
    assert view['amountPaise'] == 59900 and view['createdAt'] == 1760500000
    assert WEBSITE_ORDER['paymentStatus'] == 'PAYMENT_PAID', 'view must not mutate the row'


def test_a_legacy_order_reads_in_the_same_shape():
    view = order_record.view(LEGACY_ORDER)
    assert view['orderNumber'] == 'WD-ORD-A1B2C3D4'
    assert view['amountPaise'] == 49900
    # `orderStatus` is the field status updates write; a stale `status` copy must not win.
    assert view['status'] == 'fulfilled'
    assert view['channel'] == 'website'


def test_a_staff_order_is_written_in_the_shared_shape():
    item = order_record.staff_order(
        {'customerPhone': '98100 640044', 'customerName': 'QA', 'totalAmount': 499.5,
         'channel': 'WhatsApp', 'itemsSummary': 'Consultation'},
        short='ABCD1234', now=1760000000, contact_id='wa918100640044',
        customer_phone='+918100640044')
    assert item['orderId'] == item['orderNumber'] == 'WD-ORD-ABCD1234'
    assert item['amountPaise'] == 49950 and item['totalAmount'] == Decimal('499.5')
    assert item['channel'] == 'whatsapp' and item['source'] == 'manual'
    assert item['contactId'] == 'wa918100640044' and item['customerPhone'] == '+918100640044'
    assert not any(isinstance(v, float) for v in item.values()), 'DynamoDB refuses floats'


def test_the_flow_order_picker_offers_orders_from_every_channel(monkeypatch):
    """The WhatsApp Flow dropdown used to keep only 'WD-ORD' ids, so a customer's website
    and WhatsApp-catalog orders (UUIDv7 ids) never appeared in it."""
    from flows import orders as flow_orders
    db = FakeDynamo({ORDERS: 'orderId'}, {ORDERS: {'customerPhone': ('customerPhone', None)}})
    db.Table(ORDERS).put_item(Item=dict(WEBSITE_ORDER))
    db.Table(ORDERS).put_item(Item=dict(LEGACY_ORDER))
    monkeypatch.setattr(flow_orders, 'dynamodb', db)

    choices = flow_orders.fetch_orders_for_flow('+918100640044', '')
    assert [c['id'] for c in choices] == [WEBSITE_ORDER['orderId'], LEGACY_ORDER['orderId']]
    assert choices[0]['title'].startswith('K4M7PQR9 — ')
    assert choices[1]['title'] == 'A1B2C3D4 — 22 Feb 2026, 06:00 PM'
    assert flow_orders.order_label(WEBSITE_ORDER['orderId']) == 'K4M7PQR9'


def _paid_attempt(**extra):
    attempt = payment_attempt.build(customer_id='sub-1', reference_id='WD-PAY-ABCDEFGHJKMNPQ',
                                    amount_paise=59900, configuration_name='WECAREDIGITAL')
    attempt = payment_attempt.transition(attempt, payment_attempt.PAYMENT_PAID)
    attempt.update(checkoutMode='WEBSITE_RAZORPAY_STANDARD', snapshotHash='h',
                   purchasedSnapshot={'cart': {'lineItems': []}}, **extra)
    return attempt


class _Attempts:
    def update_item(self, **_):
        return {}


class _Orders:
    def __init__(self):
        self.items = []

    def put_item(self, Item=None, **_):
        self.items.append(dict(Item))

    def update_item(self, **_):
        return {}


def _accept(attempt):
    orders = _Orders()
    finalization.accept_paid(
        attempts=_Attempts(), orders=orders, keys=None, attempt=attempt,
        outcome={'hasOrder': True, 'orderId': '0192f3a4-5b6c-7d8e-9f00-112233445566',
                 'orderNumber': 'WD-ORD-K4M7PQR9', 'providerPaymentId': 'pay_1'},
        verified_captured_paise=59900)
    return orders.items[0]


def test_every_paid_order_carries_its_contact_and_short_number():
    order = _accept(_paid_attempt(contactId='wa918100640044', channel='whatsapp'))
    assert order['contactId'] == 'wa918100640044'
    assert order['shortId'] == 'K4M7PQR9'
    assert order['channel'] == order['source'] == 'whatsapp'


def test_a_captured_checkout_order_starts_processing_not_active():
    order = _accept(_paid_attempt(channel='website'))
    assert order['paymentStatus'] == 'PAYMENT_PAID'
    assert order['orderStatus'] == order['status'] == 'processing'


def test_an_attempt_without_a_contact_writes_no_contact_field():
    assert 'contactId' not in _accept(_paid_attempt())


# ── the staff order API (both service-api copies share the shape) ──────────────────

@pytest.fixture()
def service_api(monkeypatch):
    module = importlib.import_module('service_api')
    db = FakeDynamo(
        {ORDERS: 'orderId', CONTACTS: 'id', SUBMISSIONS: 'submissionId',
         shared_tables.STATUS_HISTORY.default_name: 'historyId'},
        {CONTACTS: {contact_store.PHONE_INDEX: ('phone', None)},
         ORDERS: {'customerPhone': ('customerPhone', None)}})
    monkeypatch.setattr(module, 'dynamodb', db)
    monkeypatch.setattr(fc, '_table', lambda: db.Table(SUBMISSIONS))
    return module, db


def _body(response):
    import json
    return response['statusCode'], json.loads(response['body'])


def test_a_staff_order_lands_on_the_customers_contact(service_api):
    module, db = service_api
    db.Table(CONTACTS).put_item(Item={'id': 'wa918100640044', 'contactId': 'wa918100640044',
                                      'phone': '+918100640044'})
    status, order = _body(module._create_order({'customerPhone': '918100640044',
                                                'totalAmount': 250}))
    assert status == 201
    stored = db.all_rows(ORDERS)[0]
    assert stored['contactId'] == 'wa918100640044'
    assert stored['customerPhone'] == '+918100640044' and stored['amountPaise'] == 25000
    assert order['orderNumber'] == stored['orderId']


def test_a_status_update_never_creates_a_phantom_order(service_api):
    module, db = service_api
    status, _ = _body(module._update_order('WD-ORD-NOPE0000', {'status': 'fulfilled'}))
    assert status == 404
    assert db.all_rows(ORDERS) == []


def test_the_phone_filter_lists_every_spelling(service_api):
    module, db = service_api
    db.Table(ORDERS).put_item(Item=dict(WEBSITE_ORDER))
    db.Table(ORDERS).put_item(Item=dict(LEGACY_ORDER))
    status, body = _body(module._list_orders({'phone': '+91 81006 40044'}))
    assert status == 200 and body['count'] == 2
    assert {o['paymentStatus'] for o in body['orders']} == {'paid', 'pending'}
