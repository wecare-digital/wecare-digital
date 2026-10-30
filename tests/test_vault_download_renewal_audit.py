"""Offline security contracts for exact-file cart renewal and paid Vault downloads.

No customer identity, S3 bytes, WhatsApp messages, or Razorpay charges needed.
"""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
VAULT_WINDOW = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/vault_window.py"
SECURE_FILES = ROOT / "amplify/functions/core/secure-files/handler.py"
CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
INTENT = ROOT / "amplify/functions/ecommerce/service-requests/handler.py"
WORKSPACE = ROOT / "src/components/workspace/service/SecureFiles.tsx"
GET_PAGE = ROOT / "src/components/get/GetPage.tsx"
STATUS = ROOT / "src/pages/checkout/status.tsx"
IAM = ROOT / "amplify/infra/checkout.json"

def isolated_function(path, function_name, context):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name == function_name]
    assert len(functions) == 1, function_name
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), context)
    return context[function_name]

def test_strict_24_hour_boundary_no_free_grace():
    ctx = {"Optional": __import__("typing").Optional, "Dict": Dict, "Any": Any,
           "window_ends_at": lambda ent: ent["accessWindowEndsAt"]}
    check = isolated_function(VAULT_WINDOW, "window_open", ctx)
    ent = {"accessWindowEndsAt": 86400}
    assert check(ent, 86399)
    assert not check(ent, 86400)
    assert not check(ent, 86401)
    assert check(ent, 86399, grace=0)

def test_download_transport_expires_by_entitlement_window():
    state = {"now": 40000, "calls": [], "sessions": []}
    class Table:
        def put_item(self, **kw):
            state["sessions"].append(kw["Item"])
    ctx = {
        "Dict": Dict, "Any": Any, "time": SimpleNamespace(time=lambda: state["now"]),
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="a"*32)),
        "SESSION_PREFIX": "vault-session#",
        "DOWNLOAD_URL_TTL": 60,
        "vault_window": SimpleNamespace(window_ends_at=lambda ent: ent["end"]),
        "_table": lambda name: Table(), "GRANTS_TABLE": "grants",
        "_download_url": lambda row, ttl: state["calls"].append(ttl) or "https://example.invalid/signed",
    }
    issue = isolated_function(SECURE_FILES, "_issue_download_session", ctx)
    entitlement = {"grantId":"g","customerId":"c","fileId":"f","ownerPhone":"verified","end":40013}
    payload = issue(entitlement, {"s3Key":"secure/x"})
    assert payload["expiresInSeconds"] == 13
    assert state["calls"] == [13]
    assert state["sessions"][-1]["expiresAt"] == 40013
    entitlement["end"] = 40000
    with pytest.raises(ValueError):
        issue(entitlement, {"s3Key":"secure/x"})
    assert len(state["sessions"]) == 1
    entitlement["end"] = 50000
    assert issue(entitlement, {"s3Key":"secure/x"})["expiresInSeconds"] == 60

def test_storage_presence_checked_before_paid_window_open():
    source = SECURE_FILES.read_text(encoding="utf-8")
    for function in ("def _redeem_after_reconcile(", "def _redeem("):
        body = source.split(function, 1)[1].split("\n\ndef ", 1)[0]
        assert "if not _vault_file_storage_ready(item):" in body
        assert body.index("if not _vault_file_storage_ready(item):") < body.index("_open_access_window(entitlement")
        assert "return _vault_storage_unavailable(origin)" in body
        assert "if vault_window.window_ends_at(entitlement) <= int(time.time()):" in body
        assert "except ValueError:" in body
    assert 'result = _s3_client().head_object(Bucket=BUCKET, Key=key)' in source
    assert 'return int(result.get("ContentLength") or 0) > 0' in source
    assert 'key.startswith(SECURE_PREFIX)' in source
    assert '"error": "VAULT_STORAGE_UNAVAILABLE"' in source
    assert 'ResponseContentDisposition' in source
    assert '"_safe_download_filename' not in source # assigned via plain function name
    assert 'f\'attachment; filename="{_safe_download_filename(item)}"\'' in source

def test_website_cart_file_binding_current_owner_and_expired_window():
    rows = {
        "intent": {"requestId": "INTENT#intent-1", "status": "OPEN", "kind": "VAULT",
                   "variantId": "RVT", "vaultFileId": "file-1",
                   "ownerCustomerId": "customer-1", "targetRequestId": "FILE#file-1",
                   "vaultOwnerPhone": "verified"},
        "file": {"fileId": "file-1", "status": "active",
                 "ownerCustomerId": "customer-1", "ownerPhone": "verified"},
        "entitlement": {"recordType": "VAULT_ENTITLEMENT", "entitlementState": "ACTIVE",
                        "customerId": "customer-1", "fileId": "file-1",
                        "ownerPhone": "verified", "state": "EXPIRED"},
    }
    class Table:
        def __init__(self, name):
            self.name = name
        def get_item(self, **kw):
            if "ServiceRequestsTable" in self.name:return {"Item": dict(rows["intent"])}
            if "SecureFilesTable" in self.name:return {"Item": dict(rows["file"])}
            return {"Item": dict(rows["entitlement"])}
    class CheckoutRejected(Exception):
        def __init__(self, reason):
            self.reason = reason
    service_requests = SimpleNamespace(
        VAULT="VAULT",
        service_line=lambda lines: SimpleNamespace(kind="VAULT",variant_id="RVT"),
        INTENT_ID_RE=re.compile(r"^intent-1$"))
    ctx = {
        "customer_auth": SimpleNamespace(CustomerIdentity=object),
        "Dict": Dict, "Any": Any,
        "service_requests": service_requests,
        "website_checkout": SimpleNamespace(CheckoutRejected=CheckoutRejected),
        "_table": lambda name: Table(name),
        "time": SimpleNamespace(time=lambda: 40000),
        "vault_window": SimpleNamespace(access_state=lambda ent, now: ent["state"]),
    }
    # Import is inside helper, use function-only extraction with filtered import replaced by
    # a no-op so all security predicates still execute with the stub module.
    source = CHECKOUT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_verify_vault_website_renewal")
    fn.body = [n for n in fn.body
               if not (isinstance(n, ast.ImportFrom) and
                       n.module == "lambda_utils.ecommerce")]
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(CHECKOUT), "exec"), ctx)
    check = ctx["_verify_vault_website_renewal"]
    params = (SimpleNamespace(customer_id="customer-1"), {"serviceIntentId": "intent-1"}, [{}])
    assert check(*params) is None
    rows["entitlement"]["state"] = "OPEN"
    with pytest.raises(CheckoutRejected, match="VAULT_ACCESS_ACTIVE"):
        check(*params)
    rows["entitlement"]["state"] = "READY"
    with pytest.raises(CheckoutRejected, match="VAULT_ACCESS_ACTIVE"):
        check(*params)
    rows["entitlement"]["state"] = "EXPIRED"
    rows["file"]["ownerCustomerId"] = "different-customer"
    with pytest.raises(CheckoutRejected, match="VAULT_FILE_UNAVAILABLE"):
        check(*params)
    rows["file"]["ownerCustomerId"] = "customer-1"
    rows["entitlement"]["customerId"] = "different-customer"
    with pytest.raises(CheckoutRejected, match="VAULT_ENTITLEMENT_UNVERIFIED"):
        check(*params)

def test_website_and_whatsapp_rails_share_same_file_and_entitlement():
    src = GET_PAGE.read_text(encoding="utf-8")
    svc = INTENT.read_text(encoding="utf-8")
    checkout = CHECKOUT.read_text(encoding="utf-8")
    iam = json.loads(IAM.read_text(encoding="utf-8"))
    assert "handleWebsiteCheckout" in src and "Add 24-hour renewal to cart" in src
    assert "postRequestIntent(" in src and "file.fileId" in src
    assert "setServiceLine( service.variantId, response.intent.intentId, vaultLinePrice )" in src
    assert "serviceIntentFor( lineItems ) === response.intent.intentId" in src
    assert "requestMySecureFilePayment( file.fileId )" in src
    assert "VAULT_WEBSITE_RETURN_FILE_KEY" in src
    assert "vault_entitlement=vault_entitlement" in svc
    assert "ConsistentRead=True" in svc
    assert "_verify_vault_website_renewal(identity, body, line_items)" in checkout
    assert "VAULT_ACCESS_ACTIVE" in checkout
    assert "DownloadGrantsTable" in json.dumps(iam)
    assert "SecureFilesTable" in json.dumps(iam)
    page = STATUS.read_text(encoding="utf-8")
    assert "Return to Vault · Download" in page
    assert "vaultReturnFile" in page and "view !== 'paid'" in page

def test_no_insecure_redirect_or_filename_restore():
    src = GET_PAGE.read_text(encoding="utf-8")
    backend = SECURE_FILES.read_text(encoding="utf-8")
    assert "'wecare-digital-get.s3.us-east-1.amazonaws.com'" in src
    assert "'wecare-digital-get.s3.amazonaws.com'" in src
    assert "destination.protocol !== 'https:'" in src
    assert "destination.username" in src and "destination.password" in src
    assert "window.location.assign( destination.href )" in src
    assert "wecare-digital-" in backend
    assert "re.sub(r\"[^a-zA-Z0-9._-]\"" in backend
    assert "Download" in src
