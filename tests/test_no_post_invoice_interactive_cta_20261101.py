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

OUTBOUND_WHATSAPP = (
    Path(__file__).resolve().parents[1]
    / "amplify/functions/messaging/outbound-whatsapp/handler.py"
)


def test_outbound_refuses_legacy_order_page_key_before_sending():
    source = OUTBOUND_WHATSAPP.read_text(encoding="utf-8")
    ast.parse(source)

    guard = source.index("if str(body.get('idempotencyKey') or '').startswith('order-page-link:'):")
    assert "'ORDER_PAGE_LINK_RETIRED'" in source
    assert "'retired_post_invoice_cta_refused'" in source

    # The fallback protects even an accidentally reactivated older
    # Commerce/Invoice engine version; refusal precedes any send-side effect.
    assert guard < source.index("phone_number_id = body.get", guard)
    assert guard < source.index("_refuse_unless_payment_ready(", guard)
    assert guard < source.index("_claim_keyed_outbound_send(", guard)
