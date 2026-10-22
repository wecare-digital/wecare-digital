#!/usr/bin/env python3
"""Submit the WhatsApp Order Status template used for out-of-window fulfilment updates.

Why this template exists
------------------------
Staff can drive a paid order forward from the workspace (Pay Flow → "Mark Shipped" /
"Mark Completed"), and a capture auto-sends ``processing``. INSIDE the 24-hour customer
service window those updates travel as a free-form interactive ``order_status`` message
and need NO template. OUTSIDE that window Meta allows an order_status update only through
an APPROVED template whose ``sub_category`` is ``ORDER_STATUS`` — without it, a shipment
or completion notice to a customer who last messaged days ago is silently dropped
(``outbound-whatsapp._approved_order_status_template`` logs
``order_status_template_not_configured`` and returns '').

This provisions that template so the out-of-window path can send.

Shape Meta requires
--------------------
An Order Status template is a UTILITY template with ``sub_category: ORDER_STATUS`` and
ordinary BODY (+ optional FOOTER) components — no media header, no buttons. The live
status, reference id and description are carried by the SEND payload's ``order_status``
component (see ``outbound-whatsapp._handle_order_status_send``), NOT by template
variables, so the BODY here is fixed text and intentionally has no ``{{n}}`` placeholders.

The name and language MUST match the outbound function's environment
(``WA_ORDER_STATUS_TEMPLATE`` / ``WA_ORDER_STATUS_TEMPLATE_LANGUAGE`` in
``config/lambda-env-manifest.json``): both the send path and
``scripts/commerce_release_audit.py`` prove the template APPROVED by that exact name,
category, sub_category and language, so a mismatch reads as "not configured".

Approval is Meta's, not ours. This submits and reports status; it does not wait.

    python scripts/provision_order_status_template.py --dry-run
    python scripts/provision_order_status_template.py
    python scripts/provision_order_status_template.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
WABA_ID = "2094615664435155"
TEMPLATES_FUNCTION = "wecare-whatsapp-templates:live"
# The UNFILTERED, sub_category-bearing readback the payment/order-status gate itself
# trusts. Deliberately the SAME route the outbound handler and the release audit use, so
# --verify proves exactly what production proves — not a laxer view that lists templates
# without sub_category and would pass a wrongly-categorised template.
BUSINESS_API_FUNCTION = "wecare-whatsapp-business-api:live"

# MUST equal config/lambda-env-manifest.json → wecare-outbound-whatsapp →
# WA_ORDER_STATUS_TEMPLATE / WA_ORDER_STATUS_TEMPLATE_LANGUAGE.
TEMPLATE_NAME = "wecare_order_status"
LANGUAGE = "en"


def lam():
    return boto3.client("lambda", region_name=REGION)


def _invoke(function_name: str, payload: dict) -> tuple[int, dict]:
    response = lam().invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    raw = response["Payload"].read()
    result = json.loads(raw.decode()) if raw else {}
    if response.get("FunctionError"):
        return 500, {"error": "invoked function raised", "detail": str(result)[:300]}
    body = result.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"raw": body[:300]}
    return int(result.get("statusCode") or 0), (body if isinstance(body, dict) else {})


def definition() -> dict:
    return {
        "name": TEMPLATE_NAME,
        "language": LANGUAGE,
        # UTILITY + ORDER_STATUS: this is a transactional fulfilment update, not
        # marketing. Miscategorising it as marketing would subject shipment/completion
        # notices to marketing opt-outs and per-user caps; omitting the sub_category
        # makes it an ordinary utility template Meta will not accept an order_status
        # component against on send.
        "category": "UTILITY",
        "sub_category": "ORDER_STATUS",
        "components": [
            {
                "type": "BODY",
                # Fixed text, no {{n}} variables on purpose: the live status, order
                # reference and per-status description ride in the SEND payload's
                # order_status component, not in template variables.
                "text": (
                    "There is an update on your order. "
                    "Open this chat to see the latest status and details."
                ),
            },
            {"type": "FOOTER", "text": "WECARE.DIGITAL"},
            # No HEADER and no BUTTONS. An order_status template carries its
            # call-to-action through the order_status component at send time.
        ],
    }


def _approved_rows() -> list:
    """The sub_category-bearing template rows, via the gate's own readback route."""
    status, body = _invoke(
        BUSINESS_API_FUNCTION,
        {
            "httpMethod": "GET",
            "path": "/wa-business/payment-templates/list",
            "queryStringParameters": {"wabaId": WABA_ID},
        },
    )
    if status >= 300:
        return []
    rows = body.get("data")
    return rows if isinstance(rows, list) else []


def existing() -> dict | None:
    for row in _approved_rows():
        if isinstance(row, dict) and row.get("name") == TEMPLATE_NAME:
            return row
    return None


def verify() -> int:
    template = existing()
    if not template:
        print(f"FAIL {TEMPLATE_NAME} not found in WABA {WABA_ID}")
        print("     Submit it first: python scripts/provision_order_status_template.py")
        return 1

    # Exactly the four conditions outbound._approved_order_status_template and
    # commerce_release_audit.audit_release check, reported one by one so a
    # near-miss (right name, wrong sub_category) is named rather than lumped in.
    checks = {
        "status == APPROVED": template.get("status") == "APPROVED",
        "category == UTILITY": template.get("category") == "UTILITY",
        "sub_category == ORDER_STATUS": template.get("sub_category") == "ORDER_STATUS",
        f"language == {LANGUAGE}": template.get("language") == LANGUAGE,
    }
    ok = True
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {label}")
        ok = ok and passed

    if not ok:
        status = template.get("status", "?")
        if status != "APPROVED":
            print(f"\n{TEMPLATE_NAME} is {status}. Approval is Meta's; re-run --verify later.")
            print("Until it is APPROVED, out-of-window order_status updates are not sent.")
        return 1

    print(f"\n{TEMPLATE_NAME} is ready. Ensure the outbound function env matches:")
    print(f"  WA_ORDER_STATUS_TEMPLATE={TEMPLATE_NAME}")
    print(f"  WA_ORDER_STATUS_TEMPLATE_LANGUAGE={LANGUAGE}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)

    if args.verify:
        return verify()

    found = existing()
    if found:
        print(f"{TEMPLATE_NAME} already exists, status={found.get('status')}")
        print("nothing submitted; re-run --verify to check approval")
        return 0

    if args.dry_run:
        print(f"would submit {TEMPLATE_NAME} / {LANGUAGE} / UTILITY / ORDER_STATUS")
        print(json.dumps(definition(), indent=2))
        print("\ndry run: nothing submitted")
        return 0

    status, body = _invoke(
        TEMPLATES_FUNCTION,
        {
            "requestContext": {"http": {"method": "POST", "path": "/templates"}},
            "rawPath": "/templates",
            "queryStringParameters": {"wabaId": WABA_ID},
            "body": json.dumps({"templateDefinition": definition()}),
        },
    )
    if status >= 300:
        print(f"ABORT template submission failed HTTP {status}: {body}")
        return 1

    print(f"submitted: id={body.get('metaTemplateId')} status={body.get('templateStatus')}")
    print("\nread-back verification:")
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
