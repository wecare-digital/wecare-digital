"""Architecture guard: one customer/commerce backbone across website + WhatsApp.

The four customer surfaces must not grow separate sources of truth:
- Website checkout
- WhatsApp Inbox
- WhatsApp Catalog
- WhatsApp Flows

Orders are one OrderTable; people are one ContactsTable; Flow responses are one
FlowSubmissionTable; payment identity is CommerceKeys + PaymentAttemptsTable; invoices and
receipts are one invoice-engine domain. This test is intentionally structural so a future
provider/UI feature cannot quietly fork one of those stores.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
sys.path.insert(0, str(SHARED))

from lambda_utils import shared_tables  # noqa: E402


def _src(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_table_names_are_single_home():
    assert shared_tables.contacts_table_name() == "stack-wecare-digital-ContactsTable"
    assert shared_tables.orders_table_name() == "stack-wecare-digital-OrderTable"
    assert shared_tables.flow_submissions_table_name() == "stack-wecare-digital-FlowSubmissionTable"
    assert shared_tables.invoices_table_name() == "stack-wecare-digital-InvoicesTable"
    assert shared_tables.invoice_items_table_name() == "stack-wecare-digital-InvoiceItemsTable"
    assert shared_tables.invoice_assets_table_name() == "stack-wecare-digital-InvoiceAssetsTable"
    assert shared_tables.invoice_sequence_table_name() == "stack-wecare-digital-InvoiceSequenceTable"
    assert shared_tables.invoice_delivery_table_name() == "stack-wecare-digital-InvoiceDeliveryLogTable"
    assert shared_tables.payment_attempts_table_name() == "stack-wecare-digital-PaymentAttemptsTable"
    assert shared_tables.commerce_keys_table_name() == "stack-wecare-digital-CommerceKeys"
    assert shared_tables.products_table_name() == "stack-wecare-digital-ProductsTable"
    assert shared_tables.carts_table_name() == "stack-wecare-digital-CartTable"


def test_website_checkout_uses_shared_customer_order_and_payment_stores():
    source = _src("amplify/functions/ecommerce/checkout/handler.py")
    assert "CONTACTS_TABLE = shared_tables.contacts_table_name()" in source
    assert "ORDERS_TABLE = shared_tables.orders_table_name()" in source
    assert "PAYMENT_ATTEMPTS_TABLE = shared_tables.payment_attempts_table_name()" in source
    assert "COMMERCE_KEYS_TABLE = shared_tables.commerce_keys_table_name()" in source
    assert "PRODUCTS_TABLE = shared_tables.products_table_name()" in source
    assert "CART_TABLE = shared_tables.carts_table_name()" in source


def test_whatsapp_inbox_uses_same_contact_and_flow_response_stores():
    source = _src("amplify/functions/messaging/inbound-whatsapp-handler/handler.py")
    assert "CONTACTS_TABLE = shared_tables.contacts_table_name()" in source
    assert "FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()" in source
    assert "os.environ.get('FLOW_SUBMISSIONS_TABLE'" not in source


def test_whatsapp_flows_use_same_contact_order_and_response_stores():
    common = _src("amplify/functions/messaging/whatsapp-business-api/flows/common.py")
    orders = _src("amplify/functions/messaging/whatsapp-business-api/flows/orders.py")
    assert "CONTACTS_TABLE = shared_tables.contacts_table_name()" in common
    assert "FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()" in common
    assert "ORDERS_TABLE = order_record.table_name()" in orders


def test_website_order_history_reads_the_same_contact_and_order_stores():
    source = _src("amplify/functions/ecommerce/customer-orders/handler.py")
    assert "CONTACTS_TABLE = shared_tables.contacts_table_name()" in source
    assert "ORDERS_TABLE = shared_tables.orders_table_name()" in source


def test_whatsapp_catalog_is_a_projection_of_the_native_products_table():
    source = _src("amplify/functions/ecommerce/meta-catalog-sync/handler.py")
    assert "project the AWS ProductsTable onto the Meta Commerce catalog" in source
    assert "from lambda_utils import shared_tables" in source
    assert "PRODUCTS_TABLE = shared_tables.products_table_name()" in source
    assert "ProductsTable is the sole catalogue authority" in source


def test_invoice_and_receipt_management_have_one_engine_and_shared_stores():
    source = _src("amplify/functions/payments/invoice-engine/handler.py")
    assert "INVOICES_TABLE = shared_tables.invoices_table_name()" in source
    assert "INVOICE_ITEMS_TABLE = shared_tables.invoice_items_table_name()" in source
    assert "INVOICE_ASSETS_TABLE = shared_tables.invoice_assets_table_name()" in source
    assert "INVOICE_SEQ_TABLE = shared_tables.invoice_sequence_table_name()" in source
    assert "INVOICE_DELIVERY_TABLE = shared_tables.invoice_delivery_table_name()" in source
    assert "CONTACTS_TABLE = shared_tables.contacts_table_name()" in source
    assert "PAYMENT_ATTEMPTS_TABLE = shared_tables.payment_attempts_table_name()" in source
    assert "COMMERCE_KEYS_TABLE = shared_tables.commerce_keys_table_name()" in source


def test_order_record_declares_one_order_table_for_every_channel():
    source = _src("amplify/functions/shared/lambda_utils/ecommerce/order_record.py")
    assert "`OrderTable` holds every order, whatever surface it came from" in source
    assert "return shared_tables.ORDERS.name()" in source


def test_payment_identity_has_one_commerce_keys_resolver():
    source = _src("amplify/functions/shared/lambda_utils/ecommerce/order_keys.py")
    assert "from lambda_utils import shared_tables" in source
    assert "return shared_tables.commerce_keys_table_name()" in source
    assert 'os.environ.get("COMMERCE_KEYS_TABLE"' not in source
