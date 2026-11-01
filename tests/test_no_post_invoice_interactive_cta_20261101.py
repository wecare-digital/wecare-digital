"""Guard against reintroducing the retired free-form post-invoice WhatsApp CTA.

The invoice renderer may send only the approved paid-invoice template. Dedicated
post-payment service actions (e.g. Access Vault) have separate guarded senders.
Historical order-page-link delivery rows remain audit data, never send triggers.
"""

import ast
from pathlib import Path

INVOICE_ENGINE = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/payments/invoice-engine/handler.py"
)


def test_invoice_engine_has_no_retired_order_page_sender():
    source = INVOICE_ENGINE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_send_order_page_link" not in functions
    assert "_ORDER_PAGE_LINK_CHECKOUT_MODES" not in source
    assert "_ORDER_PAGE_LINK_CHANNEL" not in source
    assert "_ORDER_PAGE_URL" not in source
    assert "order_page_link" not in source
    assert "order-page-link" not in source
    assert "cta_url" not in source


def test_paid_invoice_template_delivery_still_exists():
    source = INVOICE_ENGINE.read_text(encoding="utf-8")

    assert "WA_INVOICE_TEMPLATE" in source
    assert "invoice_whatsapp_sent" in source
    assert "send_invoice_whatsapp" in source
    assert "wa_order_status" in source
