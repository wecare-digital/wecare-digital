"""Drop Docs and Vault cannot charge a second time. Enumerated, not asserted.

Why this is not paranoia
-----------------------
``core/secure-files`` carries its OWN Razorpay implementation - ``razorpay_orders.create_order``,
``POST /secure-files/{fileId}/order`` and ``/whatsapp-pay`` - priced at
``SECURE_FILE_PRICE_PAISE = 4900``, which is **the same Rs49 as Vault**. Two independent
payment paths at an identical price, one of which is reached by a route whose name
("whatsapp-pay") reads like the right thing to call, is exactly how a customer ends up
charged twice for one service.

The locker is reused by Phase O-2 for **storage and privacy only**. Drop Docs and Vault are
paid once, on the one checkout, through ``prepare-checkout`` -> ``cart_v2.calculate`` ->
Razorpay -> ``verify-callback``/``razorpay-webhook``. So the guarantee needed here is an
absence, and absences regress silently. This file makes it an enumeration at the HTTP seam
(``urllib.request.urlopen``, which is how BOTH ``razorpay_orders`` and ``razorpay_verify``
reach Razorpay) rather than a claim in a docstring, in the shape
``tests/test_one_service_money_path.py`` case (b) uses.

It also pins the posture the absence depends on: both flags ``false`` in the manifest, and
an IAM document that reads one public prefix and cannot delete anything anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
FUNC_DIR = ROOT / "amplify" / "functions" / "core" / "secure-files"
SHARED = ROOT / "amplify" / "functions" / "shared"
MANIFEST = ROOT / "config" / "lambda-env-manifest.json"
PROVISIONER = ROOT / "scripts" / "provision_secure_files_api.py"

for path in (str(ROOT / "tests"), str(FUNC_DIR), str(SHARED)):
    if path not in sys.path:
        sys.path.insert(0, path)

from service_requests_fake_dynamo import RequestTable  # noqa: E402
from test_dropdocs_document_privacy import (  # noqa: E402
    FakeS3, OWNER, PUBLIC_ID, REQUEST_INTERNAL, SOURCE_KEY, _attach_event, _identity,
    _seeded_table, _wire, handler)  # noqa: F401 - `handler` is a fixture, imported on purpose

from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402
from lambda_utils.ecommerce.service_requests import SUBMIT_REQUEST, VAULT  # noqa: E402

BUCKET = "wecare-digital-get"
INCOMING_RESOURCE = f"arn:aws:s3:::{BUCKET}/o/stack/whatsapp-media/incoming/*"
REQUESTS_TABLE_ARN_TAIL = "table/stack-wecare-digital-ServiceRequestsTable"


class RefusingProvider:
    """THE HTTP SEAM. Records every request and fails it.

    Nothing on the Drop Docs or Vault path may reach a provider at all, so unlike
    ``RecordingRazorpay`` in ``test_one_service_money_path.py`` this one answers nothing: a
    single call is already the defect. ``calls`` is kept so a failure says WHAT was reached
    rather than only that something was.
    """

    def __init__(self) -> None:
        self.calls: List[str] = []

    def __call__(self, request, timeout=None):
        url = getattr(request, "full_url", str(request))
        self.calls.append(f"{getattr(request, 'get_method', lambda: 'GET')()} {url}")
        raise AssertionError(f"the Drop Docs/Vault path reached a provider: {self.calls[-1]}")


def _exploding_razorpay_orders(monkeypatch):
    """A ``razorpay_orders`` whose every entry point is a tripwire.

    The locker imports it lazily, inside the two payment functions, precisely so that it is
    never even imported while the flag is off. Installing a module that detonates proves the
    laziness holds rather than assuming it.
    """
    module = type(sys)("razorpay_orders")

    def _never(*_args, **_kwargs):
        raise AssertionError("razorpay_orders must be unreachable on this path")

    module.create_order = _never
    module.order_is_paid = _never
    monkeypatch.setitem(sys.modules, "razorpay_orders", module)
    return module


# ── the attach path contacts no provider ──────────────────────────────────────

def test_a_drop_docs_attach_makes_zero_provider_calls(handler, monkeypatch):
    provider = RefusingProvider()
    _exploding_razorpay_orders(monkeypatch)
    table = _seeded_table()
    s3 = FakeS3()
    _wire(handler, monkeypatch, s3, table)

    with patch.object(urllib.request, "urlopen", provider):
        response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 201
    assert provider.calls == []
    # the document landed, so the 201 is not vacuous
    assert len([k for k in table.rows if str(k).startswith(store.DOC_PREFIX)]) == 1


def test_a_a_vault_request_makes_zero_provider_calls(monkeypatch):
    """A Vault intent is a row, not a charge. ``request_intent`` never moves money - the
    money is the ONE checkout, and the request only comes into existence afterwards."""
    provider = RefusingProvider()
    _exploding_razorpay_orders(monkeypatch)
    table = RequestTable()
    table.seed({"requestId": REQUEST_INTERNAL, "kind": SUBMIT_REQUEST,
                "publicRequestId": PUBLIC_ID, "customerId": OWNER, "status": "SUBMITTED",
                "statusRank": 10, "createdAt": 1, "updatedAt": 1})
    table.seed({"requestId": f"REQNO#{PUBLIC_ID}", "ownerCustomerId": OWNER,
                "targetRequestId": REQUEST_INTERNAL, "reservedAt": 1})

    with patch.object(urllib.request, "urlopen", provider):
        intent = store.request_intent(table, _identity(), VAULT, PUBLIC_ID)

    assert intent["kind"] == VAULT
    assert intent["amountPaise"] == 4900
    assert intent["currency"] == "INR"
    assert provider.calls == []
    assert not [k for k in table.rows if str(k).startswith("ORDER#")]
    assert not [k for k in table.rows if str(k).startswith("REQ#01")
                and k != REQUEST_INTERNAL]


def test_a_a_failed_attach_also_contacts_no_provider(handler, monkeypatch):
    """The failure path is the one that gets reached in production, so enumerate it too."""
    provider = RefusingProvider()
    _exploding_razorpay_orders(monkeypatch)
    table = _seeded_table()
    s3 = FakeS3()
    s3.fail_on["copy_object"] = RuntimeError("AccessDenied")
    _wire(handler, monkeypatch, s3, table)

    with patch.object(urllib.request, "urlopen", provider):
        response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 503
    assert provider.calls == []


# ── the locker's own payment path stays unreachable ───────────────────────────

def test_b_create_order_is_unreachable_while_the_payment_flag_is_unset(handler, monkeypatch):
    """``_create_order`` must refuse BEFORE importing ``razorpay_orders``.

    The tripwire module would raise on any call, so a 503 here means the import never
    happened - which is the property that keeps a credential unread while payments are off.
    """
    provider = RefusingProvider()
    _exploding_razorpay_orders(monkeypatch)
    monkeypatch.delenv("SECURE_FILES_PAYMENT_ENABLED", raising=False)
    monkeypatch.setattr(handler, "_owned_active_file",
                        lambda fid, ident: {"fileId": fid, "pricePaise": 4900,
                                            "s3Key": "secure/u/x"})

    with patch.object(urllib.request, "urlopen", provider):
        order = handler._create_order("f1", {"phone": "918100640044"},
                                      "https://wecare.digital")
        whatsapp = handler._send_whatsapp_payment("f1", {"phone": "918100640044"},
                                                  "https://wecare.digital")

    assert order["statusCode"] == 503
    assert json.loads(order["body"])["error"] == "PAYMENT_DISABLED"
    assert whatsapp["statusCode"] == 503
    assert json.loads(whatsapp["body"])["error"] == "PAYMENT_DISABLED"
    assert provider.calls == []


def test_b_the_attach_route_does_not_share_a_code_path_with_the_order_route():
    """Two payment implementations at the same Rs49 is the hazard. Keep them disjoint.

    The attach arm must not consult ``_payment_enabled``, create a grant, or name a price -
    reading the payment flag at all would be the first step towards the attach route
    acquiring an opinion about money.
    """
    source = (FUNC_DIR / "handler.py").read_text(encoding="utf-8")
    arm = source.split("def _dropdocs_attach(", 1)[1].split("\ndef ", 1)[0]
    for forbidden in ("_payment_enabled", "razorpay", "PRICE_PAISE", "GRANTS_TABLE",
                      "amountPaise", "pricePaise", "create_order"):
        assert forbidden not in arm, f"{forbidden} must not appear in the attach arm"


def test_b_the_existing_locker_routes_are_untouched():
    """Phase O-2 ADDS one route key. It must not retarget or rename an existing one."""
    provisioner = _load_provisioner()
    keys = [f"{method} {path}" for method, path in provisioner.ROUTES]
    assert keys.count("POST /secure-files/dropdocs/attach") == 1
    for existing in ("GET /secure-files",
                     "POST /secure-files/upload-init",
                     "POST /secure-files/{fileId}/confirm",
                     "POST /secure-files/{fileId}/revoke",
                     "GET /secure-files/mine",
                     "POST /secure-files/{fileId}/order",
                     "POST /secure-files/{fileId}/whatsapp-pay",
                     "GET /secure-files/{fileId}/download"):
        assert existing in keys
    assert len(keys) == len(set(keys)) == 9


# ── both flags ship off ───────────────────────────────────────────────────────

def _manifest_secure_files() -> Dict[str, Any]:
    # `_functions` is a COUNT, not the map. The map is `functions`. Easy to get wrong and
    # it fails as a TypeError rather than a KeyError, so it is named here deliberately.
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["functions"]["wecare-secure-files"]


def test_c_both_flags_are_false_in_the_manifest():
    """``SECURE_FILES_PAYMENT_ENABLED`` enabling is an owner action and nothing in Phase O-2
    touches it. ``DROPDOCS_ATTACH_ENABLED`` ships off because there is no upload UI yet."""
    env = _manifest_secure_files()
    assert env["SECURE_FILES_PAYMENT_ENABLED"] == "false"
    assert env["DROPDOCS_ATTACH_ENABLED"] == "false"
    # unchanged by this phase, and asserted so a drift in either direction is visible
    assert env["SECURE_FILE_PRICE_PAISE"] == "4900"
    assert env["SERVICE_REQUESTS_TABLE"] == "stack-wecare-digital-ServiceRequestsTable"


def test_c_the_provisioner_ships_both_flags_off_too():
    """The manifest records intent; the provisioner is what actually writes the variables."""
    provisioner = _load_provisioner()
    env = provisioner.environment()
    assert env["SECURE_FILES_PAYMENT_ENABLED"] == "false"
    assert env["DROPDOCS_ATTACH_ENABLED"] == "false"
    assert env["SERVICE_REQUESTS_TABLE"] == "stack-wecare-digital-ServiceRequestsTable"
    # --enable-payment must not also switch the attach route on
    assert provisioner.environment(payment_enabled=True)["DROPDOCS_ATTACH_ENABLED"] == "false"


def test_c_the_manifest_and_the_provisioner_agree_on_every_key():
    """A key in one and not the other is how a Lambda comes up missing a table name."""
    provisioner = _load_provisioner()
    assert set(provisioner.environment()) == set(_manifest_secure_files())


# ── the IAM delta ─────────────────────────────────────────────────────────────

def _load_provisioner():
    spec = importlib.util.spec_from_file_location("prov_secure_files_nsc", PROVISIONER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements() -> List[Dict[str, Any]]:
    return _load_provisioner().policy_document()["Statement"]


def _actions(statement: Dict[str, Any]) -> List[str]:
    action = statement.get("Action")
    return [action] if isinstance(action, str) else list(action or [])


def _resources(statement: Dict[str, Any]) -> List[str]:
    resource = statement.get("Resource")
    return [resource] if isinstance(resource, str) else list(resource or [])


def test_d_get_object_on_the_public_tree_is_exactly_one_prefix():
    """``CopyObject`` needs ``GetObject`` on its source, and that is the ONLY reason this
    role may read anything under ``o/``. One prefix, read-only, no write."""
    reading_public = [s for s in _statements()
                      if any(r.startswith(f"arn:aws:s3:::{BUCKET}/o/") for r in _resources(s))]
    assert len(reading_public) == 1
    statement = reading_public[0]
    assert statement["Effect"] == "Allow"
    assert _actions(statement) == ["s3:GetObject"]
    assert _resources(statement) == [INCOMING_RESOURCE]


def test_d_nothing_in_the_policy_can_write_anywhere_under_the_public_root():
    for statement in _statements():
        public = [r for r in _resources(statement)
                  if r.startswith(f"arn:aws:s3:::{BUCKET}/o/")]
        if not public:
            continue
        assert not {a for a in _actions(statement)
                    if a not in ("s3:GetObject", "s3:HeadObject")}, _actions(statement)


def test_d_the_policy_holds_no_delete_of_any_kind():
    """Deliberate, and load-bearing: the public original is NOT deleted. It expires under
    the existing ``s3_whatsapp_media_incoming`` TTL in ``operations/system-cleanup``. Adding
    a delete here to get a tidier story would also hand this role the ability to erase a
    customer's only copy."""
    everything = json.dumps(_load_provisioner().policy_document())
    for forbidden in ("s3:DeleteObject", "s3:DeleteObjectVersion", "s3:Delete",
                      "dynamodb:DeleteItem", "dynamodb:DeleteTable", "s3:*",
                      "dynamodb:*", '"Action": "*"'):
        assert forbidden not in everything, f"{forbidden} must not appear"


def test_d_the_request_table_grant_is_item_level_and_has_no_index():
    """Enough to resolve the caller's own REQ# row and write a DOC# row, and nothing more.
    No Query and no index ARN: `attach_document` and `list_documents` are GetItem-only on
    the read side, so a Query grant would be unused reach into other customers' rows."""
    grants = [s for s in _statements()
              if any(REQUESTS_TABLE_ARN_TAIL in r for r in _resources(s))]
    assert len(grants) == 1
    statement = grants[0]
    assert sorted(_actions(statement)) == ["dynamodb:GetItem", "dynamodb:PutItem",
                                           "dynamodb:UpdateItem"]
    assert all("/index/" not in r for r in _resources(statement))
    assert len(_resources(statement)) == 1


def test_d_the_pre_existing_statements_are_unchanged():
    """The delta must be additive. Widening `SecurePrefixOnly`, or loosening the Cognito
    scope, would be invisible in a diff of a long policy."""
    by_sid = {s.get("Sid"): s for s in _statements()}
    assert _resources(by_sid["SecurePrefixOnly"]) == [f"arn:aws:s3:::{BUCKET}/secure/*"]
    assert sorted(_actions(by_sid["SecurePrefixOnly"])) == ["s3:GetObject", "s3:HeadObject",
                                                            "s3:PutObject"]
    assert _resources(by_sid["CustomerPoolOnly"]) == [
        "arn:aws:cognito-idp:us-east-1:775261844268:userpool/us-east-1_46ULYuukt"]
    # the two new statements, and no others
    assert set(by_sid) == {"SecurePrefixOnly", "ReadWhatsAppIncomingToPromote",
                           "DropDocsRequestRows", "Catalogue", "CustomerPoolOnly",
                           "ValidateCallerToken", "AdminRoleLookup", "RazorpayKeyByArn",
                           "WhatsAppDelivery", "Logs"}


# ── the enumeration is not vacuous ────────────────────────────────────────────

def test_e_the_refusing_provider_would_actually_catch_a_call():
    """Without this, every ``provider.calls == []`` above could be passing for free."""
    provider = RefusingProvider()
    request = urllib.request.Request("https://api.razorpay.com/v1/orders", method="POST")
    with pytest.raises(AssertionError):
        provider(request)
    assert provider.calls == ["POST https://api.razorpay.com/v1/orders"]


def test_e_the_tripwire_module_would_actually_catch_an_import(monkeypatch):
    module = _exploding_razorpay_orders(monkeypatch)
    with pytest.raises(AssertionError):
        module.create_order(amount_paise=4900, receipt="r", notes={})


def test_e_a_foreign_request_still_refuses_rather_than_charging(handler, monkeypatch):
    """The refusal path must not be reachable by paying again. It is a 403, not a price."""
    provider = RefusingProvider()
    table = _seeded_table(owner="someone-else")
    _wire(handler, monkeypatch, FakeS3(), table)

    with patch.object(urllib.request, "urlopen", provider):
        response = handler.handler(_attach_event(), None)

    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error"] == "NOT_REGISTERED"
    assert "pricePaise" not in response["body"]
    assert provider.calls == []
    with pytest.raises(customer_auth.CustomerNotAuthorized):
        store.list_documents(table, _identity(), PUBLIC_ID)
