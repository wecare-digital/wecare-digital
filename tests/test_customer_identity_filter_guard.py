"""One Cognito-subject predicate guards every `ListUsers` filter, at all SEVEN sites.

Every site in the tree builds its Cognito filter by concatenation - `Filter='sub = "' + value +
'"'` - and the value is a stored attribute (`contact['checkoutCustomerId']`, `row['customerId']`)
rather than handset input. Two sites already refused a malformed subject with their own inline
copy of a UUID regex; five called `ListUsers` with whatever the row held. F-4 gives all seven one
predicate, `customer_auth.is_cognito_subject`, so the literal pattern lives in exactly one file.

The test is built around one property: the `cognito-idp` double RAISES on any call, so reaching
`ListUsers` is a failure however the call site then behaves. Each site is asserted to refuse with
the refusal IT ALREADY RETURNED - the five unguarded sites keep their own outcome, and the two
converted sites keep their own MECHANISM, one returning and one raising. Only the predicate is
shared, and the two pin cases exist so that conversion cannot silently change a working refusal.
"""
import importlib
import importlib.util
import io
import json
import pathlib
import sys
import time
from unittest.mock import Mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import catalog_service_checkout as catalog  # noqa: E402
from lambda_utils.ecommerce import wa_payment_request  # noqa: E402

PHONE = '+919876543210'

#: A well-formed Cognito sub, for the sensitivity halves: canonical, lowercase, hyphenated.
WELL_FORMED = '11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa'

#: The four malformed subjects every site must refuse BEFORE `ListUsers`.
#:
#: The first is the reason the predicate exists: a stored `"` would break the filter syntax into a
#: `ClientError` rather than disclose anything, which is why this is LOW and defence in depth, but
#: an identity path is not where an inconsistency should be left. The last is the one a truthiness
#: check cannot catch: Cognito mints `sub` lowercase, so an uppercase UUID is not a subject this
#: pool issued and is not worth a `ListUsers` call.
MALFORMED = [
    pytest.param('" or sub = "x', id='filter-injection'),
    pytest.param('', id='empty'),
    pytest.param('not-a-uuid', id='not-a-uuid'),
    pytest.param(WELL_FORMED.upper(), id='uppercase-uuid'),
]


def _refusing_cognito():
    """A `cognito-idp` double that fails loudly if a malformed subject ever reaches it."""
    client = Mock()
    client.list_users.side_effect = AssertionError('ListUsers reached with an unvalidated subject')
    return client


def _load(name, relative):
    """By path under a unique module name: the repo has 64 files called handler.py."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flows(monkeypatch, dotted):
    """The flows package, imported as a package so its relative imports resolve."""
    monkeypatch.syspath_prepend(str(ROOT / 'amplify/functions/messaging/whatsapp-business-api'))
    return importlib.import_module(dotted)


# ---------------------------------------------------------------------------
# 1. The five previously-unguarded sites
# ---------------------------------------------------------------------------

def _drive_catalog_services(monkeypatch, subject):
    """`flows/catalog_services.py` - widened `if not owner:`, guarding the ListUsers below it."""
    module = _load('catalog_services_filter_guard',
                   'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py')
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': subject})
    tables = {'stack-wecare-digital-ContactsTable': contacts,
              'stack-wecare-digital-WixOrderIds': FakeTable(key_attr='orderId'),
              'stack-wecare-digital-OrderTable': FakeTable(key_attr='orderId')}
    db = Mock()
    db.Table.side_effect = lambda name: tables[name]
    cognito = _refusing_cognito()
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    monkeypatch.setattr(module, '_send', lambda client, row, **body: None)
    result = module.handle({'contactId': 'contact', 'senderPhone': PHONE,
                            'phoneNumberId': 'sender'}, Mock())
    return result, cognito


def _drive_checkout(monkeypatch, subject):
    """`ecommerce/checkout/handler.py` - widened `if not owner or owner != row[...]`.

    `row['customerId']` is deliberately set to the SAME malformed value, so the pre-existing
    `owner != row.get('customerId')` half cannot be what refuses. Only the new predicate can.

    `phoneNumberId` is seeded to the ONE permitted sender for the same reason. The A2.5
    sender-membership check sits ABOVE this predicate in `_native_catalog_service`, so a session
    row without it refuses `PAYMENT_SENDER_NOT_PERMITTED` and this test would pass on a subject
    that was never examined.
    """
    monkeypatch.setenv('CONTACTS_TABLE', 'contacts')
    monkeypatch.setenv('WHATSAPP_CATALOG_SERVICES_ENABLED', 'true')
    module = _load('checkout_filter_guard', 'amplify/functions/ecommerce/checkout/handler.py')
    monkeypatch.setattr(module.wix_writeback, 'is_enabled', lambda: True)
    token = 'A' * 24
    keys = FakeTable(key_attr='orderId')
    keys.seed({'orderId': catalog.SESSION_PREFIX + token, 'status': 'PREPARING_PAYMENT',
               'expiresAt': int(time.time()) + 3600, 'contactId': 'contact',
               'phoneNumberId': wa_payment_request.PHONE_NUMBER_ID_1,
               'customerId': subject, 'phone': PHONE, 'kind': 'SUBMIT_REQUEST'})
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': subject})
    cognito = _refusing_cognito()
    monkeypatch.setattr(module, '_keys_table', lambda: keys)
    monkeypatch.setattr(module, '_table', lambda name: contacts)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    result = module._native_catalog_service(
        {'internalAction': 'prepareNativeCatalogService', 'catalogToken': token}, '')
    return result, cognito


def _drive_submit_request_review(monkeypatch, subject):
    """`flows/paid_submit_request.py` - the FIRST of the file's two ListUsers, in `send_review`."""
    module = _flows(monkeypatch, 'flows.paid_submit_request')
    requests = FakeTable(key_attr='requestId')
    requests.seed({'requestId': 'REQ#1', 'kind': 'SUBMIT_REQUEST', 'detailsSubmittedAt': 1,
                   'flowContactId': 'contact', 'flowPhone': PHONE, 'customerId': subject})
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': subject})
    db = Mock()
    db.Table.return_value = contacts
    cognito = _refusing_cognito()
    monkeypatch.setattr(module, 'tables',
                        lambda: (requests, FakeTable(key_attr='orderId'), FakeTable(key_attr='orderId')))
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    result = module.send_review({'requestId': 'REQ#1'}, Mock())
    return result, cognito


def _drive_submit_request_invite(monkeypatch, subject):
    """`flows/paid_submit_request.py` - the SECOND ListUsers, in `prepare_and_send`.

    Everything before it is stubbed at the `paid` seam: this site is reached only after the paid
    purchase has been proven, so the guard has to sit between that proof and the Cognito read.
    """
    module = _flows(monkeypatch, 'flows.paid_submit_request')
    row = {'requestId': 'REQ#1', 'customerId': subject, 'orderId': 'order-1',
           'publicRequestId': 'WD-REQ-1', 'kind': 'SUBMIT_REQUEST'}
    cognito = _refusing_cognito()
    monkeypatch.setattr(module, 'tables', lambda: (FakeTable(key_attr='requestId'),
                                                   FakeTable(key_attr='orderId'),
                                                   FakeTable(key_attr='orderId')))
    monkeypatch.setattr(module.order_keys, 'resolve_payment_reference', lambda *a, **k: {})
    monkeypatch.setattr(module.store, 'activate',
                        lambda *a, **k: Mock(outcome=module.store.ACTIVATED))
    monkeypatch.setattr(module.order_keys, 'resolve_order_for_payment',
                        lambda *a, **k: {'orderIdRef': 'order-1'})
    monkeypatch.setattr(module.paid, 'prepare', lambda *a, **k: (row, 'paidsr:1:' + 'x' * 44))
    requests = FakeTable(key_attr='requestId')
    requests.seed({'requestId': 'ORDER#order-1', 'targetRequestId': 'REQ#1'})
    requests.seed({'requestId': 'REQ#1', **row})
    monkeypatch.setattr(module, 'tables', lambda: (requests, FakeTable(key_attr='orderId'),
                                                   FakeTable(key_attr='orderId')))
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: Mock())
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    published = lambda _: {'body': json.dumps({'flow': {'status': 'PUBLISHED'}})}
    result = module.prepare_and_send({'referenceId': 'ref', 'paymentAttemptId': 'attempt',
                                      'orderId': 'order-1'}, Mock(), published)
    return result, cognito


def _drive_paid_vault(monkeypatch, subject):
    """`flows/paid_vault.py` - the paid Vault delivery chain, a LIVE-path site."""
    module = _flows(monkeypatch, 'flows.paid_vault')
    row = {'requestId': 'REQ#1', 'customerId': subject, 'kind': 'VAULT'}
    grant = {'grantId': 'grant-1', 'ownerPhone': PHONE[1:], 'paid': True}
    cognito = _refusing_cognito()
    monkeypatch.setattr(module.vault_access, 'grant_access',
                        lambda *a, **k: (row, {'fileId': 'file-1'}, grant))
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: Mock())
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    result = module.prepare_and_send({'referenceId': 'ref'}, Mock())
    return result, cognito


#: The five sites that had NO guard, each with the refusal that call site already returned.
UNGUARDED = [
    pytest.param(_drive_catalog_services, 'VERIFIED_CUSTOMER_REQUIRED', id='catalog_services'),
    pytest.param(_drive_checkout, 'VERIFIED_CUSTOMER_REQUIRED', id='checkout'),
    pytest.param(_drive_submit_request_review, 'VERIFIED_RECIPIENT_UNAVAILABLE',
                 id='paid_submit_request.send_review'),
    pytest.param(_drive_submit_request_invite, 'VERIFIED_RECIPIENT_UNAVAILABLE',
                 id='paid_submit_request.prepare_and_send'),
    pytest.param(_drive_paid_vault, 'VERIFIED_RECIPIENT_UNAVAILABLE', id='paid_vault'),
]


@pytest.mark.parametrize('drive,refusal', UNGUARDED)
@pytest.mark.parametrize('subject', MALFORMED)
def test_a_malformed_subject_never_reaches_list_users(monkeypatch, drive, refusal, subject):
    result, cognito = drive(monkeypatch, subject)
    assert result['outcome'] == refusal
    cognito.list_users.assert_not_called()


# ---------------------------------------------------------------------------
# 2. The two pin cases: already guarded, and each keeps its own MECHANISM
# ---------------------------------------------------------------------------

def test_customer_commands_still_refuses_a_malformed_subject(monkeypatch):
    """Converted from an inline regex. Still RETURNS, and still carries the sign-in reply."""
    module = _load('customer_commands_filter_guard',
                   'amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py')
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': 'not-a-uuid'})
    db = Mock()
    db.Table.return_value = contacts
    cognito = _refusing_cognito()
    monkeypatch.setattr(module.boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    result = module.handle({'contactId': 'contact', 'senderPhone': PHONE, 'text': 'orders'}, Mock())
    assert result['outcome'] == 'VERIFIED_CUSTOMER_REQUIRED'
    assert module.SIGN_IN_URL in result['reply']
    cognito.list_users.assert_not_called()


def test_customer_orders_still_refuses_a_malformed_subject(monkeypatch):
    """Converted from an inline regex. Still RAISES, and still `CustomerNotAuthorized`.

    The partner of the case above. The two sites share a predicate and differ in refusal
    mechanism, and this is the assertion that keeps the difference from being tidied away.
    """
    module = _flows(monkeypatch, 'flows.customer_orders')
    contacts = FakeTable(key_attr='id')
    contacts.seed({'id': 'contact', 'phone': PHONE, 'checkoutCustomerId': 'not-a-uuid'})
    db = Mock()
    db.Table.return_value = contacts
    cognito = _refusing_cognito()
    monkeypatch.setattr(module.boto3, 'client', lambda *a, **k: cognito)
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        module._verified(db, 'contact', PHONE)
    cognito.list_users.assert_not_called()


# ---------------------------------------------------------------------------
# 3. The predicate itself, and the invariant the whole item exists for
# ---------------------------------------------------------------------------

def test_a_well_formed_subject_is_still_accepted():
    """No behaviour change on well-formed input: the helper is the same full match as before."""
    assert customer_auth.is_cognito_subject(WELL_FORMED)
    for value in ('" or sub = "x', '', 'not-a-uuid', WELL_FORMED.upper(),
                  WELL_FORMED + 'a', 'a' + WELL_FORMED, None, 12345):
        assert not customer_auth.is_cognito_subject(value)


def test_the_uuid_pattern_appears_in_exactly_one_file():
    """The invariant F-4 exists for: one predicate, not seven copies of a regex.

    Asserted over the source tree rather than by behaviour, because 'the pattern is duplicated' is
    not a thing any single call site can observe. Seven sites agreeing today is worth nothing if
    the eighth brings its own copy.
    """
    literal = '0-9a-f]{8}(?:-'
    holders = sorted(path.relative_to(ROOT).as_posix()
                     for path in (ROOT / 'amplify').rglob('*.py')
                     if literal in path.read_text(encoding='utf-8'))
    assert holders == ['amplify/functions/shared/lambda_utils/customer_auth.py']


def test_every_list_users_filter_site_is_guarded():
    """Every `Filter='sub` in the tree is preceded by the shared predicate in its own function.

    The companion to the test above: one says the pattern is not duplicated, this one says no site
    was left behind. A new call site that concatenates a subject into a filter without asking
    `is_cognito_subject` first fails here, which is the only place that can notice it.
    """
    sites = 0
    for path in (ROOT / 'amplify').rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        if "Filter='sub" not in source:
            continue
        for block in source.split('\ndef ')[1:]:
            # A CALL SITE builds the filter AND calls ListUsers. Both conditions, because
            # `customer_auth` quotes the filter expression in prose to say what the predicate is
            # for, and documentation is not a call site.
            if "Filter='sub" not in block or 'list_users(' not in block:
                continue
            sites += block.count("Filter='sub")
            assert 'is_cognito_subject' in block.split("Filter='sub")[0], (
                f"{path.relative_to(ROOT).as_posix()}: a ListUsers filter is built from an "
                f"unvalidated subject in {block.splitlines()[0]}")
    # Eight since `paid_vault.send_review` was split out of the Vault deliver path: the census
    # moves when a site is genuinely added, and the guard assertion above is what keeps it honest.
    assert sites == 8
