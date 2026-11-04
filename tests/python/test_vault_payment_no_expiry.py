"""Staff Vault payment cards never expire (like Collect); checkout cards keep 15 minutes.

Staff Vault sends have no resend limit. No AWS or messages.
"""
from pathlib import Path
from types import SimpleNamespace

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


CATALOG_SERVICES = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py'


def test_staff_vault_send_has_no_resend_limit_or_customer_lock():
    source = CATALOG_SERVICES.read_text()
    # The one-card-per-file 24-hour rule is gone (owner decision 2026-11-04).
    assert 'VAULTPAYLIVE#' not in source
    assert 'VAULT_PAYMENT_REQUEST_LIVE' not in source
    # The customer-wide lock is skipped for staff Vault sends, kept for customer purchases.
    prepare = source[source.index('def _prepare_payment('):]
    gate = prepare.index("if row.get('origin') != 'STAFF_VAULT':")
    assert gate < prepare.index("'NATIVESERVICEACTIVE#'")
    drop_docs = source[source.index('def _prepare_drop_docs_payment('):source.index('def _prepare_payment(')]
    assert "'NATIVESERVICEACTIVE#'" in drop_docs and 'STAFF_VAULT_ORIGIN' not in drop_docs
