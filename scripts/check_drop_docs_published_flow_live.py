#!/usr/bin/env python3
"""Read-only release gate for paid Drop Docs: verify the ACTUAL published Meta FLOW_JSON.

The approved _dropdoc_flow button and FlowRegistry PUBLISHED badge are not enough:
the published F003 payload must match the reviewed source before paid completion
can be claimed. This script invokes two existing GET-only AWS Lambda endpoints
and downloads Meta's temporary HTTPS Flow asset. Never sends messages, opens a
payment, publishes an asset, or reads customer/order records.

    python scripts/check_drop_docs_published_flow_live.py

Exit codes: 0 = verified; 1 = wrong template/Flow JSON; 2 = unreadable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
FLOW_SOURCE = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/published/f003-drop-docs.json"
FLOW_READER = "wecare-whatsapp-business-api:live"
MAX_FLOW_BYTES = 512 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def trusted_meta_asset_url(url: str) -> bool:
    """Do not follow arbitrary CDN URLs or redirect away from the expected host."""
    if not isinstance(url, str) or len(url) > 4096:
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "mmg.whatsapp.net"
                and parts.port in (None, 443) and not parts.username
                and not parts.password and parts.path.endswith(".json")
                and not parts.fragment)
    except ValueError:
        return False


def read_meta_flow_asset_url(lambda_client, flow_id: str) -> str:
    """The existing GET /wa-business/flows/assets readback is staff-data-free."""
    if not (flow_id.isascii() and flow_id.isdigit()):
        raise ValueError("canonical Flow ID is not numeric")
    response = lambda_client.invoke(
        FunctionName=FLOW_READER, InvocationType="RequestResponse",
        Payload=json.dumps({"httpMethod": "GET", "path": "/wa-business/flows/assets",
                            "queryStringParameters": {"flowId": flow_id}}).encode("utf-8"))
    if response.get("FunctionError"):
        raise RuntimeError("Meta Flow assets read failed")
    payload = response["Payload"].read()
    envelope = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    if envelope.get("statusCode") != 200:
        raise RuntimeError("Meta Flow assets read not authorized or unavailable")
    body = envelope.get("body")
    document = json.loads(body) if isinstance(body, str) else body
    if not isinstance(document, dict) or str(document.get("flowId")) != flow_id:
        raise RuntimeError("wrong Flow returned by provider")
    assets = document.get("assets")
    matches = [a for a in assets if isinstance(a, dict) and
               a.get("assetType") == "FLOW_JSON"] if isinstance(assets, list) else []
    if len(matches) != 1 or matches[0].get("name") != "flow.json":
        raise RuntimeError("no unique published FLOW_JSON")
    url = matches[0].get("downloadUrl")
    if not trusted_meta_asset_url(url):
        raise RuntimeError("Meta Flow asset link is absent or unsafe")
    return url


def load_published_flow_json(url: str, *, opener=None) -> dict:
    """Bounded one-hop GET of the temporary Meta CDN asset, never other hosts."""
    if not trusted_meta_asset_url(url):
        raise ValueError("not an allowed Meta asset URL")
    http = opener or build_opener(NoRedirect())
    with http.open(Request(url, headers={"Accept": "application/json"}), timeout=15) as res:
        if not trusted_meta_asset_url(res.geturl()):
            raise RuntimeError("Meta CDN response redirected to another host")
        raw = res.read(MAX_FLOW_BYTES + 1)
    if len(raw) > MAX_FLOW_BYTES:
        raise RuntimeError("Meta asset exceeds audited size limit")
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("Meta FLOW_JSON is not an object")
    return decoded


def compare_published_to_source(actual: dict, expected: dict) -> dict:
    """Strict semantic comparison, ignoring only JSON formatting/key order."""
    required_screens = ["SELECT_TARGET", "NOTE", "UPLOAD", "CONFIRMATION"]
    screens = actual.get("screens", []) if isinstance(actual, dict) else []
    screen_ids = [s.get("id") for s in screens if isinstance(s, dict)] if isinstance(screens, list) else []
    completion = screens[-1] if isinstance(screens, list) and screens else {}
    completion_payload = json.dumps(completion, sort_keys=True)
    valid = (screen_ids == required_screens
             and isinstance(completion, dict) and completion.get("terminal") is True
             and '"flow_key": "wd_f003_drop_docs"' in completion_payload
             and '"name": "DocumentPicker"' in json.dumps(actual, sort_keys=True)
             and actual == expected)
    def digest(document):
        return hashlib.sha256(json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
    return {"ok": bool(valid), "screens": screen_ids,
            "semanticSha256": digest(actual),
            "sourceSemanticSha256": digest(expected)}


def main() -> int:
    try:
        import boto3
        sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
        from lambda_utils import canonical_flows, whatsapp_templates
        import check_whatsapp_templates_live as templates_audit

        canonical = canonical_flows.published_flow("drop_docs")
        flow_id = str((canonical or {}).get("flowId") or "")
        if not flow_id:
            raise RuntimeError("no canonical published Drop Docs Flow")

        # Existing approved-template audit validates exact template identity,
        # approved copy, IMAGE header, FLOW button and DATA_EXCHANGE target.
        binding_issues = templates_audit.flow_binding_issues(
            whatsapp_templates.DROP_DOCS_FLOW, templates_audit.live_flow_definitions())
        if binding_issues:
            print(json.dumps({"ok": False, "stage": "template_binding",
                              "issues": binding_issues}))
            return 1

        client = boto3.client("lambda", region_name="us-east-1")
        url = read_meta_flow_asset_url(client, flow_id)
        actual = load_published_flow_json(url)
        expected = json.loads(FLOW_SOURCE.read_text(encoding="utf-8"))
        comparison = compare_published_to_source(actual, expected)
        print(json.dumps({"flowId": flow_id, "template": "_dropdoc_flow",
                          "verifiedProviderAsset": True, **comparison}, indent=2))
        return 0 if comparison["ok"] else 1
    except Exception as exc:  # noqa: BLE001 - redact provider URL and all payloads
        print(json.dumps({"ok": False, "stage": "live_provider_read",
                          "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
