#!/usr/bin/env python3
"""Submit a purpose-built WhatsApp template for delivering a paid file.

Why a new template
------------------
The delivery path currently reuses ``01_wecare_doc``, which is APPROVED and works, but
was built for a different job:

* its BODY is fixed text with no variables, so the message cannot name the file or the
  customer - a paid delivery arrives as "Please find the attached document";
* it carries a leftover FLOW button labelled **"Subscribe"**, which on a paid file
  delivery is actively misleading.

``wd_file_delivery`` fixes both: BODY variables for the customer name and the file
name, and no buttons at all.

The payment template is deliberately NOT recreated. ``wecare_whatapp_native_pay_template``'s only gap is that
its BODY has no variables, and the amount already reaches the customer through the
ORDER_DETAILS payload rather than the text - so the gap is cosmetic. Its button is an
ORDER_DETAILS button, which is coupled to the account's payment configuration; hand-
rolling a replacement risks breaking a working checkout to fix wording.

The DOCUMENT header sample
--------------------------
Meta requires an ``example.header_handle`` for a media header, obtained by uploading a
sample through the resumable upload endpoint. That is what the three
``/wa-business/media/resumable/*`` routes do, so this script drives them rather than
reimplementing the flow.

Approval is Meta's, not ours. This submits and reports status; it does not wait.

    python scripts/provision_file_delivery_template.py --dry-run
    python scripts/provision_file_delivery_template.py
    python scripts/provision_file_delivery_template.py --verify
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
WABA_ID = "2094615664435155"
TEMPLATES_FUNCTION = "wecare-whatsapp-templates:live"
MEDIA_FUNCTION = "wecare-whatsapp-business-api:live"

TEMPLATE_NAME = "wd_file_delivery"
LANGUAGE = "en"

ROOT = Path(__file__).resolve().parents[1]
# A tiny valid PDF, assembled at runtime. Meta only needs a representative sample of
# the header's media type; it is never sent to anyone.
SAMPLE_NAME = "sample-delivery.pdf"


def _sample_pdf() -> bytes:
    text = "WECARE.DIGITAL sample document"
    content = f"BT /F1 14 Tf 60 760 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


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


def header_handle() -> tuple[str, str]:
    """Upload a sample PDF and return (handle, detail)."""
    sample = _sample_pdf()

    status, body = _invoke(
        MEDIA_FUNCTION,
        {
            "httpMethod": "POST",
            "path": "/wa-business/media/resumable/session",
            "body": json.dumps(
                {
                    "fileName": SAMPLE_NAME,
                    "fileType": "application/pdf",
                    "fileLength": len(sample),
                }
            ),
        },
    )
    if status >= 300:
        return "", f"session failed HTTP {status} {body}"
    session_id = str(body.get("sessionId") or "")
    if not session_id:
        return "", f"no sessionId returned: {body}"

    status, body = _invoke(
        MEDIA_FUNCTION,
        {
            "httpMethod": "POST",
            "path": f"/wa-business/media/resumable/{session_id}/chunk",
            "body": json.dumps(
                {"offset": 0, "data": base64.b64encode(sample).decode("ascii")}
            ),
        },
    )
    if status >= 300:
        return "", f"chunk failed HTTP {status} {body}"

    status, body = _invoke(
        MEDIA_FUNCTION,
        {
            "httpMethod": "POST",
            "path": f"/wa-business/media/resumable/{session_id}/finish",
            "body": json.dumps({"target": "handle"}),
        },
    )
    if status >= 300:
        return "", f"finish failed HTTP {status} {body}"
    handle = str(body.get("headerHandle") or "")
    return (handle, "uploaded") if handle else ("", f"no headerHandle: {body}")


def definition(handle: str) -> dict:
    return {
        "name": TEMPLATE_NAME,
        "language": LANGUAGE,
        # UTILITY, not MARKETING: this is the receipt for a transaction the customer
        # just paid for. Miscategorising it as marketing would make it subject to
        # marketing opt-outs and per-user caps.
        "category": "UTILITY",
        "components": [
            {
                "type": "HEADER",
                "format": "DOCUMENT",
                "example": {"header_handle": [handle]},
            },
            {
                "type": "BODY",
                # {{1}} customer name, {{2}} file name. Both are things the reused
                # template could not say, which is the whole reason this exists.
                "text": (
                    "Hi {{1}}, thank you for your payment. "
                    "Your file {{2}} is attached above.\n\n"
                    "You can download it any time from this chat."
                ),
                "example": {"body_text": [["Ramesh", "Invoice WD-2026-001.pdf"]]},
            },
            {"type": "FOOTER", "text": "WECARE.DIGITAL"},
            # No BUTTONS, deliberately. The template this replaces carried a FLOW
            # button labelled "Subscribe" from an unrelated use, which on a paid
            # delivery reads like an upsell attached to something already bought.
        ],
    }


def existing() -> dict | None:
    status, body = _invoke(
        TEMPLATES_FUNCTION,
        {
            "requestContext": {"http": {"method": "GET", "path": "/templates"}},
            "rawPath": "/templates",
            "queryStringParameters": {"wabaId": WABA_ID, "maxResults": "200"},
        },
    )
    if status >= 300:
        return None
    for template in body.get("templates") or body.get("data") or []:
        if template.get("name") == TEMPLATE_NAME:
            return template
    return None


def verify() -> int:
    template = existing()
    if not template:
        print(f"FAIL {TEMPLATE_NAME} not found in WABA {WABA_ID}")
        return 1

    status = template.get("status", "?")
    print(f"PASS {TEMPLATE_NAME} exists  status={status}  category={template.get('category')}")

    components = {c.get("type"): c for c in template.get("components") or []}
    if components.get("HEADER", {}).get("format") == "DOCUMENT":
        print("PASS DOCUMENT header")
    else:
        print(f"FAIL header is {components.get('HEADER', {}).get('format')}, expected DOCUMENT")
        return 1

    body_text = components.get("BODY", {}).get("text", "")
    if "{{1}}" in body_text and "{{2}}" in body_text:
        print("PASS BODY has both variables (customer name, file name)")
    else:
        print("FAIL BODY is missing variables - the whole point of this template")
        return 1

    if "BUTTONS" in components:
        print("FAIL BUTTONS present; this template is meant to have none")
        return 1
    print("PASS no buttons")

    if status != "APPROVED":
        print(f"\n{TEMPLATE_NAME} is {status}. Approval is Meta's; re-run --verify later.")
        print("Until it is APPROVED, delivery keeps using 01_wecare_doc.")
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
        print(f"would upload a {len(_sample_pdf())}-byte sample PDF for the DOCUMENT header")
        print(f"would submit {TEMPLATE_NAME} / {LANGUAGE} / UTILITY")
        print(json.dumps(definition("<handle>"), indent=2))
        print("\ndry run: nothing submitted")
        return 0

    handle, detail = header_handle()
    if not handle:
        print(f"ABORT could not obtain a header handle: {detail}")
        return 1
    print(f"header handle obtained ({len(handle)} chars)")

    status, body = _invoke(
        TEMPLATES_FUNCTION,
        {
            "requestContext": {"http": {"method": "POST", "path": "/templates"}},
            "rawPath": "/templates",
            "queryStringParameters": {"wabaId": WABA_ID},
            "body": json.dumps({"templateDefinition": definition(handle)}),
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
