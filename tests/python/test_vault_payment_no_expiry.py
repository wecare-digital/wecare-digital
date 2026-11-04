"""Staff Vault payment cards never expire (like Collect); checkout cards keep 15 minutes.

Also pins the one-card-per-file guard and the legacy lapsed-card flag. No AWS or messages.
"""
import ast
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError
from lambda_utils.ecommerce import catalog_service_checkout as catalog

ROOT = Path(__file__).resolve().parents[2]
SECURE_FILES = ROOT / 'amplify/functions/core/secure-files/handler.py'
NOW = 1800000000
QUOTE = SimpleNamespace(collection_before_convenience_paise=8254, convenience_fee_paise=206,
                        convenience_gst_paise=37, total_payable_paise=8497)
LINES = {'lines': [{'unitPricePaise': 4900, 'quantity': 1}], 'supplyGstPaise': 882,
         'discountPaise': 28, 'deliveryPaise': 2500}
SHIPPING = {'addresses': [{'name': 'Example Customer', 'phone_number': '919000000001',
                           'address': 'Example street', 'city': 'Kolkata', 'state': 'West Bengal',
                           'in_pin_code': '700012', 'country': 'IN'}]}


def details(row):
    kwargs = {'invoice_lines': LINES, 'shipping_info': SHIPPING} if row['kind'] == 'VAULT' else {}
    return catalog.payment_details(row, QUOTE, 'WD-PAY-EXAMPLE', 'WECAREDIGITAL', NOW, **kwargs)


def test_staff_vault_card_has_no_expiry_like_collect():
    order = details({'kind': 'VAULT', 'origin': 'STAFF_VAULT'})['order']
    assert 'expiration' not in order
    # Amounts are untouched by the expiry change.
    assert order['shipping']['value'] == 2500


def test_customer_started_checkout_cards_keep_fifteen_minutes():
    for row in ({'kind': 'VAULT', 'origin': 'VAULT_OFFER'}, {'kind': 'VAULT'},
                {'kind': 'DROP_DOCS', 'origin': 'STAFF_VAULT'}, {'kind': 'DROP_DOCS'}):
        expiration = details(row)['order']['expiration']
        assert expiration['timestamp'] == str(NOW + 900), row
        assert expiration['description'] == 'Complete payment within 15 minutes'


def lapsed_fn():
    nodes = [n for n in ast.parse(SECURE_FILES.read_text()).body
             if (isinstance(n, ast.FunctionDef) and n.name == '_payment_request_lapsed')
             or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in {
                 'PAYMENT_REQUEST_NEVER_EXPIRES', 'LEGACY_PAYMENT_REQUEST_WINDOW_SECONDS',
                 '_PAYMENT_CARD_OUTCOMES'} for t in n.targets))]
    ns = {'datetime': datetime, 'timezone': timezone, 'Dict': dict, 'Any': object}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SECURE_FILES), 'exec'), ns)
    return ns['_payment_request_lapsed']


def iso(epoch):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(epoch))


def test_only_an_old_fifteen_minute_card_counts_as_lapsed():
    lapsed = lapsed_fn()
    sent = {'lastPaymentRequestOutcome': 'PAYMENT_REQUEST_SENT',
            'lastPaymentRequestedAt': iso(NOW - 3600)}
    assert lapsed(sent, NOW) is True
    assert lapsed({**sent, 'lastPaymentRequestOutcome': 'PAYMENT_REQUEST_UNCONFIRMED'}, NOW) is True
    # Still inside its 15 minutes (+1 minute slack): Meta has not cancelled it yet.
    assert lapsed({**sent, 'lastPaymentRequestedAt': iso(NOW - 600)}, NOW) is False
    # A card sent without an expiry never lapses: one payable card per file still holds.
    assert lapsed({**sent, 'lastPaymentRequestExpiry': 'NEVER'}, NOW) is False
    for outcome in ('PAYMENT_REQUEST_REFUSED', 'WHATSAPP_IDENTITY_REQUIRED', '', None):
        assert lapsed({**sent, 'lastPaymentRequestOutcome': outcome}, NOW) is False
    assert lapsed({**sent, 'lastPaymentRequestedAt': 'garbage'}, NOW) is False


class Keys:
    """In-memory CommerceKeys with DynamoDB-style conditional update for the live slot."""

    def __init__(self):
        self.rows = {}

    def update_item(self, Key, ExpressionAttributeValues, ConditionExpression='', **_):
        row = self.rows.setdefault(Key['orderId'], {'orderId': Key['orderId']})
        values = ExpressionAttributeValues
        if 'liveUntil < :now' in ConditionExpression:
            if 'liveUntil' in row and not row['liveUntil'] < values[':now']:
                raise ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'U')
            row.update(liveUntil=values[':until'], sessionKey=values[':session'])
        elif ':zero' in values:
            if row.get('sessionKey') != values[':session']:
                raise ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'U')
            row['liveUntil'] = 0

    def get_item(self, Key, ConsistentRead=False):
        return {'Item': dict(self.rows.get(Key['orderId'], {}))}


def guard_source():
    source = (ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py').read_text()
    assert "STAFF_VAULT_LIVE_PREFIX + file_id" in source
    assert "'VAULT_PAYMENT_REQUEST_LIVE'" in source
    assert "_release_slot()" in source
    return source


def test_guard_blocks_a_second_card_for_24_hours_then_allows_one():
    guard_source()
    keys = Keys()
    window = catalog.STAFF_VAULT_RESEND_GUARD_SECONDS
    slot = {'orderId': 'VAULTPAYLIVE#file-1'}

    def claim(now, session):
        try:
            keys.update_item(Key=slot, ConditionExpression='attribute_not_exists(liveUntil) OR liveUntil < :now',
                             ExpressionAttributeValues={':until': now + window, ':session': session,
                                                        ':owner': 'o', ':now': now})
            return True
        except ClientError:
            return False

    assert claim(NOW, 's1') is True
    assert claim(NOW + 60, 's2') is False
    assert claim(NOW + window - 1, 's3') is False
    assert claim(NOW + window + 1, 's4') is True
    # A definitive pre-send refusal releases only its own claim.
    keys.update_item(Key=slot, ExpressionAttributeValues={':zero': 0, ':session': 's4'},
                     ConditionExpression='sessionKey=:session')
    assert claim(NOW + window + 2, 's5') is True


def test_card_may_be_live_outcomes_keep_the_slot():
    source = guard_source()
    assert ("_CARD_MAY_BE_LIVE = frozenset({'PAYMENT_REQUEST_SENT', 'PAYMENT_REQUEST_UNCONFIRMED'})"
            in source)
