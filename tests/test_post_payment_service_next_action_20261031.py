"""Template-only payment rail: no standalone interactive CTA after an invoice.

Executes the ACTUAL invoice-engine compatibility function with synthetic inputs.
The native Review & Pay payment itself remains an approved ORDER_DETAILS
*template* with a button, as required by Meta's India payment documentation.
Neither payments nor WhatsApp messages are sent by these tests.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVOICE = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
TEMPLATES = ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py"
VAULT = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py"
DROP_DOCS = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_drop_docs.py"


def retired_orders_link():
    tree = ast.parse(INVOICE.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "_send_order_page_link"]
    assert len(nodes) == 1
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(INVOICE), "exec"), namespace)
    return namespace["_send_order_page_link"], nodes[0]


def test_no_standalone_interactive_cta_for_any_paid_service_or_regular_cart():
    invoke, _ = retired_orders_link()
    # A paid Vault, Drop Docs, amendment, other service, regular cart and even
    # an unknown historical reference all pass this compatibility boundary.
    # The helper cannot send, claim, look up a customer or charge anything.
    for case in range(9):
        assert invoke(f"invoice-{case}", f"contact-{case}", "+919000000000",
                      "sender", object(), "synthetic") == "template_only_policy"
    assert invoke("", "", "", "", None, "") == "template_only_policy"


def test_disabled_cta_is_side_effect_free_and_cannot_reappear_in_a_chat_window():
    _, function = retired_orders_link()
    assert not any(isinstance(node, ast.Call) for node in ast.walk(function))
    assert not any(isinstance(node, ast.Await) for node in ast.walk(function))
    source = ast.get_source_segment(INVOICE.read_text(encoding="utf-8"), function)
    assert source is not None
    for disallowed in ("isInteractive", "interactiveType", "cta_url",
                       "lambda_client.invoke(", "claim_invoice_delivery(",
                       "recipientPhone", "templateName", "send_whatsapp"):
        # The explanation in the docstring may mention 'cta_url', but it must
        # never form a payload or call a sender.
        if disallowed == "cta_url":
            assert "'interactiveType': 'cta_url'" not in source
        else:
            assert disallowed not in source.split('"""')[-1]


def test_payment_status_receipt_and_service_templates_stay_separate():
    invoice = INVOICE.read_text(encoding="utf-8")
    templates = TEMPLATES.read_text(encoding="utf-8")
    vault = VAULT.read_text(encoding="utf-8")
    drop_docs = DROP_DOCS.read_text(encoding="utf-8")

    assert "if delivered and not force:" in invoice
    assert "link_outcome = _send_order_page_link(" in invoice
    assert "wa_status in ('accepted', 'sent', 'delivered', 'read')" in invoice
    assert "'isTemplate': True" in invoice
    assert "'templateName': WA_INVOICE_TEMPLATE" in invoice
    assert "'templateFlowButton': {'index': 0, 'flowToken': review_flow_token}" in invoice

    # Meta India template payments use wire type=template with the approved
    # ORDER_DETAILS button. ORDER_STATUS transitions remain template-only.
    assert 'wecare_whatapp_native_pay_template' in templates
    assert 'wecare_order_status_v3' in templates
    assert 'wecare_default_invoice_image_template' in templates
    assert 'wecare_default_download' in templates

    # Vault is download URL, Drop Docs is an upload Flow.
    assert "whatsapp_templates.download_send_fields(file['fileId'])" in vault
    assert "vaultNotificationStatus" in vault
    assert "vaultDocumentStatus" not in vault
    assert "whatsapp_templates.DROP_DOCS_FLOW" in drop_docs
