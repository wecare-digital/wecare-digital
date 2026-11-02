"""One table per shared concept, so every channel reads and writes the same rows.

Four channels touch a customer: the WhatsApp inbox, WhatsApp catalog orders, WhatsApp Flows
and the website checkout. They share exactly these stores, and this module is the only
place their names are decided:

    concept          physical table               one row per          env override
    ---------------  ---------------------------  -------------------  ----------------------
    contacts         ContactsTable                person               CONTACTS_TABLE
    orders           OrderTable                   order (both          ORDERS_TABLE
                                                  channels)
    flow responses   FlowSubmissionTable          submitted form       FLOW_SUBMISSIONS_TABLE
                                                  (every channel)
    flow logs        FlowLogTable                 Flow interaction     FLOW_LOGS_TABLE
    status history   RequestStatusHistoryTable    status change        STATUS_HISTORY_TABLE
    flow drafts      FlowDraftTable               resumable Flow       DRAFTS_TABLE
    invoices         InvoicesTable                 financial document   INVOICES_TABLE
    invoice items    InvoiceItemsTable             invoice line         INVOICE_ITEMS_TABLE
    invoice assets   InvoiceAssetsTable            private receipt      INVOICE_ASSETS_TABLE
    invoice sequence InvoiceSequenceTable          statutory sequence   INVOICE_SEQ_TABLE
    invoice delivery InvoiceDeliveryLogTable        receipt delivery      INVOICE_DELIVERY_TABLE
    payment attempts PaymentAttemptsTable          payment attempt      PAYMENT_ATTEMPTS_TABLE
    commerce keys    CommerceKeys                   idempotency/binding  COMMERCE_KEYS_TABLE
    products         ProductsTable                  catalog authority     PRODUCTS_TABLE
    carts            CartTable                      working cart          CART_TABLE

The env names are the ones the live Lambdas already carry, so resolving through here changes
no deployed value. When an env var is absent the name is built from `TABLE_PREFIX` (what
`wecare-service-api` and `wecare-sla-engine` set) and otherwise from the account default, so
the f-string convention and the explicit-env convention give the same answer.

Folded tables
-------------
These held copies of rows that belong to one of the stores above. No runtime writer may use
them; `RETIRED` maps each to where its rows belong now. The historical consolidation
helper is no longer tracked. Verify existing rows have been migrated before considering
physical table deletion, which remains a separate, owner-approved step.

    CustomersTable         -> ContactsTable        never existed live; a second person store
    ReviewTable            -> FlowSubmissionTable  flowCode WD_REV (rating) / WD_IDEA (idea)
    AppointmentTable       -> FlowSubmissionTable  flowCode WD_APPT
    RxSlotTable            -> FlowSubmissionTable  flowCode WD_RX
    EnterpriseAssistTable  -> FlowSubmissionTable  flowCode WD_ENT
    AmendmentHistoryTable  -> FlowSubmissionTable  flowCode WD_AMEND
    SubmitRequestsTable    -> FlowLogTable         its only live rows were flow_log events
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple

#: The prefix every live table carries. `TABLE_PREFIX` overrides it per Lambda.
DEFAULT_PREFIX = 'stack-wecare-digital'


@dataclass(frozen=True)
class SharedTable:
    """A shared store: its logical name, env override, physical suffix and partition key."""

    concept: str
    env: str
    physical: str
    partition_key: str

    def name(self) -> str:
        """The table name for this execution environment.

        Read on every call rather than frozen at import, so a test or a Lambda that sets the
        env var after import still gets the value it set.
        """
        explicit = (os.environ.get(self.env) or '').strip()
        if explicit:
            return explicit
        prefix = (os.environ.get('TABLE_PREFIX') or '').strip() or DEFAULT_PREFIX
        return f'{prefix}-{self.physical}'

    @property
    def default_name(self) -> str:
        """The live name with no env override. For scripts and tests."""
        return f'{DEFAULT_PREFIX}-{self.physical}'


CONTACTS = SharedTable('contacts', 'CONTACTS_TABLE', 'ContactsTable', 'id')
ORDERS = SharedTable('orders', 'ORDERS_TABLE', 'OrderTable', 'orderId')
FLOW_SUBMISSIONS = SharedTable('flow_submissions', 'FLOW_SUBMISSIONS_TABLE',
                               'FlowSubmissionTable', 'submissionId')
FLOW_LOGS = SharedTable('flow_logs', 'FLOW_LOGS_TABLE', 'FlowLogTable', 'logId')
STATUS_HISTORY = SharedTable('status_history', 'STATUS_HISTORY_TABLE',
                             'RequestStatusHistoryTable', 'historyId')
FLOW_DRAFTS = SharedTable('flow_drafts', 'DRAFTS_TABLE', 'FlowDraftTable', 'draftKey')
INVOICES = SharedTable('invoices', 'INVOICES_TABLE', 'InvoicesTable', 'invoiceId')
INVOICE_ITEMS = SharedTable('invoice_items', 'INVOICE_ITEMS_TABLE', 'InvoiceItemsTable', 'itemId')
INVOICE_ASSETS = SharedTable('invoice_assets', 'INVOICE_ASSETS_TABLE', 'InvoiceAssetsTable', 'assetId')
INVOICE_SEQUENCE = SharedTable('invoice_sequence', 'INVOICE_SEQ_TABLE', 'InvoiceSequenceTable', 'sequenceId')
INVOICE_DELIVERY = SharedTable('invoice_delivery', 'INVOICE_DELIVERY_TABLE',
                               'InvoiceDeliveryLogTable', 'invoiceId')
PAYMENT_ATTEMPTS = SharedTable('payment_attempts', 'PAYMENT_ATTEMPTS_TABLE',
                               'PaymentAttemptsTable', 'paymentAttemptId')
COMMERCE_KEYS = SharedTable('commerce_keys', 'COMMERCE_KEYS_TABLE', 'CommerceKeys', 'orderId')
PRODUCTS = SharedTable('products', 'PRODUCTS_TABLE', 'ProductsTable', 'id')
CARTS = SharedTable('carts', 'CART_TABLE', 'CartTable', 'cartId')

#: Every shared store, in the order the module docstring lists them.
SHARED: Tuple[SharedTable, ...] = (
    CONTACTS, ORDERS, FLOW_SUBMISSIONS, FLOW_LOGS, STATUS_HISTORY, FLOW_DRAFTS,
    INVOICES, INVOICE_ITEMS, INVOICE_ASSETS, INVOICE_SEQUENCE, INVOICE_DELIVERY,
    PAYMENT_ATTEMPTS, COMMERCE_KEYS, PRODUCTS, CARTS)

#: Folded table -> the table its rows live in now. A test asserts no runtime module names a
#: key of this map, so a writer cannot quietly reopen a second store.
RETIRED: Dict[str, str] = {
    'CustomersTable': CONTACTS.physical,
    'ReviewTable': FLOW_SUBMISSIONS.physical,
    'AppointmentTable': FLOW_SUBMISSIONS.physical,
    'RxSlotTable': FLOW_SUBMISSIONS.physical,
    'EnterpriseAssistTable': FLOW_SUBMISSIONS.physical,
    'AmendmentHistoryTable': FLOW_SUBMISSIONS.physical,
    'SubmitRequestsTable': FLOW_LOGS.physical,
}


def contacts_table_name() -> str:
    return CONTACTS.name()


def orders_table_name() -> str:
    return ORDERS.name()


def flow_submissions_table_name() -> str:
    return FLOW_SUBMISSIONS.name()


def flow_logs_table_name() -> str:
    return FLOW_LOGS.name()


def status_history_table_name() -> str:
    return STATUS_HISTORY.name()


def flow_drafts_table_name() -> str:
    return FLOW_DRAFTS.name()

def invoices_table_name() -> str:
    return INVOICES.name()


def invoice_items_table_name() -> str:
    return INVOICE_ITEMS.name()


def invoice_assets_table_name() -> str:
    return INVOICE_ASSETS.name()


def invoice_sequence_table_name() -> str:
    return INVOICE_SEQUENCE.name()


def invoice_delivery_table_name() -> str:
    return INVOICE_DELIVERY.name()


def payment_attempts_table_name() -> str:
    return PAYMENT_ATTEMPTS.name()


def commerce_keys_table_name() -> str:
    return COMMERCE_KEYS.name()


def products_table_name() -> str:
    return PRODUCTS.name()


def carts_table_name() -> str:
    return CARTS.name()
