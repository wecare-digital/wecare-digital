#!/usr/bin/env python3
"""Read-only: compare the template registry with the live WABA1 template list.

`amplify/functions/shared/lambda_utils/whatsapp_templates.py` is the one place the platform names
the templates it sends. Meta is the authority on whether each one is APPROVED. This script reads
the live list through `wecare-whatsapp-business-api:live` `/wa-business/payment-templates/list`,
the same sub_category-bearing readback the send gates trust, and checks every registered
template:

  * it exists on WABA1 and is APPROVED;
  * its category and language match the registry;
  * its sub_category matches when the registry names one (ORDER_STATUS);
  * all nine registered Flow buttons target their canonical PUBLISHED Flow ID and
    retain DATA_EXCHANGE; the paid Drop Docs template retains its approved shape.

It prints template names and verdicts only, never message content or customer data, and writes
nothing. The provider readback checks button bindings, not published Flow JSON or handset completion. Exit 0 when every registered template matches, 1 on any mismatch, 2 when the live list
cannot be read.

    python scripts/check_whatsapp_templates_live.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))

from lambda_utils import canonical_flows, whatsapp_templates  # noqa: E402

REGION = "us-east-1"
WABA_ID = "2094615664435155"
READ_FUNCTION = "wecare-whatsapp-business-api:live"
DEFINITIONS_FUNCTION = "wecare-whatsapp-template-management:live"

# Every registered template that opens a canonical Flow. Keep this mapping
# explicit: a Flow button's Meta target is NOT controlled by sender payloads.
FLOW_TARGETS = {
    whatsapp_templates.INVOICE.name: "leave_review",
    whatsapp_templates.LEAVE_REVIEW.name: "leave_review",
    whatsapp_templates.PDF_DOWNLOAD.name: "subscribe",
    whatsapp_templates.PROFILE_DETAILS.name: "subscribe",
    whatsapp_templates.SUBMIT_REQUEST_FLOW.name: "submit_request",
    whatsapp_templates.REQUEST_AMENDMENT_FLOW.name: "amend_request",
    whatsapp_templates.DROP_DOCS_FLOW.name: "drop_docs",
    whatsapp_templates.REQUEST_PICKUP_FLOW.name: "request_pickup",
    whatsapp_templates.TRACK_SHIPPING_FLOW.name: "shipments",
}



def _invoke_get(function: str, path: str, query: dict) -> dict:
    """Only read live, published provider definitions; never invoke a send or write."""
    import boto3

    response = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=function, InvocationType="RequestResponse",
        Payload=json.dumps({"httpMethod": "GET", "path": path,
                            "queryStringParameters": query}).encode())
    payload = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError") or payload.get("statusCode") != 200:
        raise RuntimeError(f"live read unavailable: {function}")
    body = payload.get("body")
    data = json.loads(body) if isinstance(body, str) else body
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid live response: {function}")
    return data


def live_templates() -> list:
    rows = _invoke_get(READ_FUNCTION, "/wa-business/payment-templates/list",
                       {"wabaId": WABA_ID}).get("data")
    if not isinstance(rows, list):
        raise RuntimeError("approval inventory unavailable")
    return rows


def live_flow_definitions() -> list:
    # The approval list intentionally omits 'components'. Read them through
    # Meta template management, whose own list endpoint follows provider
    # pagination and returns HTTP 502 rather than a partial inventory.
    data = _invoke_get(DEFINITIONS_FUNCTION, "/whatsapp/templates",
                       {"wabaId": WABA_ID, "maxResults": "200"})
    # Reject an unexpected cursor if the endpoint ever changes its response
    # contract: do not accept a first-page-only result as authoritative.
    paging = data.get("paging")
    if (data.get("next_cursor") or data.get("next")
            or (isinstance(paging, dict) and paging.get("next"))):
        raise RuntimeError("template button inventory is incomplete")
    rows = data.get("templates")
    if not isinstance(rows, list):
        raise RuntimeError("template button definitions unavailable")
    return rows


def flow_binding_issues(template, definitions: list) -> list[str]:
    """Fail closed on mismatched/missing LIVE Flow targets, not source-only IDs."""
    capability = FLOW_TARGETS.get(template.name)
    if not capability:
        return []
    target = canonical_flows.published_flow(capability)
    if not target or not str(target.get("flowId") or "").isdigit():
        return [f"canonical {capability} Flow is not published"]

    matching = [row for row in definitions if isinstance(row, dict)
                and row.get("name") == template.name
                and row.get("language") == template.language]
    if len(matching) != 1:
        return [f"expected one live component definition, got {len(matching)}"]
    live = matching[0]
    issues = []
    expected_template_id = whatsapp_templates.APPROVED_TEMPLATE_IDS.get(template.name)
    if expected_template_id and str(live.get("id") or "") != str(expected_template_id):
        issues.append("live template ID changed; review the existing version")
    if live.get("status") != "APPROVED":
        issues.append("component definition is not APPROVED")
    if live.get("category") != template.category:
        issues.append("component definition category changed")

    components = live.get("components")
    if not isinstance(components, list):
        return issues + ["live components absent"]
    button_sections = [c for c in components if isinstance(c, dict)
                       and c.get("type") == "BUTTONS"]
    if len(button_sections) != 1:
        return issues + [f"expected one BUTTONS component, got {len(button_sections)}"]
    buttons = button_sections[0].get("buttons")
    if not isinstance(buttons, list):
        return issues + ["live BUTTONS payload absent"]
    flow_buttons = [b for b in buttons if isinstance(b, dict)
                    and b.get("type") == "FLOW"]
    if len(flow_buttons) != 1:
        return issues + [f"expected one FLOW button, got {len(flow_buttons)}"]
    button = flow_buttons[0]
    actual_id = str(button.get("flow_id") or "")
    if actual_id != str(target["flowId"]):
        issues.append(f"FLOW target {actual_id or 'missing'} != canonical {target['flowId']}")
    if button.get("flow_action") != "DATA_EXCHANGE":
        issues.append("FLOW action must be DATA_EXCHANGE")

    # The paid Drop Docs sender supplies a dynamic IMAGE header and a Flow token.
    # Check that a future template edit cannot silently alter this approved shape.
    if template.name == whatsapp_templates.DROP_DOCS_FLOW.name:
        header = [c for c in components if isinstance(c, dict) and c.get("type") == "HEADER"]
        body = [c for c in components if isinstance(c, dict) and c.get("type") == "BODY"]
        footer = [c for c in components if isinstance(c, dict) and c.get("type") == "FOOTER"]
        if len(header) != 1 or header[0].get("format") != "IMAGE":
            issues.append("Drop Docs IMAGE header missing")
        if len(body) != 1 or body[0].get("text") != "✅ Your service is ready. Tap below to continue.":
            issues.append("Drop Docs approved body copy changed")
        if len(footer) != 1 or footer[0].get("text") != "WECARE.DIGITAL":
            issues.append("Drop Docs approved footer changed")
        if button.get("text") != "Drop Docs":
            issues.append("Drop Docs button label changed")
    return issues


def main() -> int:
    try:
        rows = live_templates()
        definitions = live_flow_definitions()
    except Exception as error:  # noqa: BLE001 - a read failure is its own exit code
        print(f"ERROR could not read live template approval/buttons: {type(error).__name__}")
        return 2
    by_name = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            by_name.setdefault(row["name"], []).append(row)

    problems = 0
    for template in whatsapp_templates.ALL:
        candidates = by_name.get(template.name, [])
        live = next((r for r in candidates if r.get("language") == template.language), None)
        issues = []
        if not candidates:
            issues.append("not on WABA1")
        elif live is None:
            issues.append(f"no '{template.language}' language variant")
        else:
            if live.get("status") != "APPROVED":
                issues.append(f"status {live.get('status')}")
            if live.get("category") != template.category:
                issues.append(f"category {live.get('category')} != {template.category}")
            if template.sub_category and live.get("sub_category") != template.sub_category:
                issues.append(f"sub_category {live.get('sub_category')} != {template.sub_category}")
        issues.extend(flow_binding_issues(template, definitions))
        verdict = "OK  " if not issues else "FAIL"
        role = "automated" if template.automated else "manual"
        print(f"{verdict} {template.name:42} {role:9} " + ("; ".join(issues) if issues else "APPROVED" + ("; FLOW ID verified" if template.name in FLOW_TARGETS else "")))
        problems += bool(issues)

    unregistered = sorted(set(by_name) - {t.name for t in whatsapp_templates.ALL})
    if unregistered:
        print("live but not in the registry (informational): " + ", ".join(unregistered))
    print(f"\n{len(whatsapp_templates.ALL) - problems}/{len(whatsapp_templates.ALL)} registered "
          "templates match WABA1")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
