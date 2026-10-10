"""An issued invoice is a document of record, not a row.

H3. Before this, `update_invoice`'s `allowed` list carried `status` and `paymentStatus`
alongside every amount field, and its only guard refused AMOUNT changes on a row that was
already `paid`/`cancelled`. Two consequences, both measurable here:

  * An issued, unpaid invoice could be PUT to `status: paid` / `paymentStatus: captured`.
    No payment, no capture, no webhook - and every downstream reader (the dues list, the
    revenue totals, the balance-due notifier) then treated it as money received.
  * A successful update re-rendered the PNG over the SAME S3 key and overwrote the same
    `InvoiceAssets` row, so the document the customer was sent stopped existing.

And `add_remark` took its author from the request body (defaulting to `'admin'`), so the
record of who refunded money was whatever the browser said, while `type='refund'` moved
`paymentStatus` to `refunded` on the strength of that same body.

These tests pin the refusals, the version keys and the two identity facts. They assert on
the STORED ROW as well as the status code, because "answered 409" and "wrote nothing" are
different claims and only the second one is the invariant.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import types
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import boto3.dynamodb.conditions  # the real resource loads this; the fixture mocks construction

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "amplify/functions/payments/invoice-engine/handler.py"
FLOW_PAGE = ROOT / "src/pages/workspace/pay/flow/index.tsx"
API_CLIENT = ROOT / "src/api/client.ts"

INVOICE_ID = "inv-fixture"
REFERENCE_ID = "WD-PAY-FIXTURE01"
PAYMENT_ID = "pay_fixture0000001"
REFUND_ID = "rfnd_fixture000001"
# A placeholder, never a real person: these rows are written into assertions.
CUSTOMER = "Placeholder Customer"
STAFF = "staff-user-placeholder"


# ══════════════════════════════════════════════════════════════════════════════
# In-memory tables. Purpose-built, because the assets table is the SUBJECT here
# ══════════════════════════════════════════════════════════════════════════════
#
# `crm_fake_dynamo.FakeTable` keys its rows on ONE attribute, and `InvoiceAssets` is keyed
# `(invoiceId HASH, assetType RANGE)`. A single-attribute fake would collapse `image` and
# `image#v2` onto one row and the versioning test would pass while the engine overwrote the
# document of record - the exact defect under test. So the composite key is modelled.


def _apply_set(expression: str, row: dict, names: dict, values: dict) -> dict:
    """The engine's `SET a = :a, #b = :b` expressions, and nothing else.

    Narrow on purpose: an expression shape this does not understand must fail loudly rather
    than leave the row untouched and let a "wrote nothing" assertion pass for the wrong reason.
    """
    if "SET" not in expression:
        raise AssertionError(f"unexpected update expression {expression!r}")
    for assignment in expression.split("SET", 1)[1].split(","):
        target, _, source = (part.strip() for part in assignment.partition("="))
        if not target:
            continue
        row[names.get(target, target)] = values[source]
    return row


class _InvoicesTable:
    """Key `invoiceId`, with `arm_get_failure` so the fail-closed guard is measurable."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.writes = 0
        self._get_failure: Exception | None = None

    def seed(self, item: dict) -> None:
        self.rows[item["invoiceId"]] = dict(item)

    def arm_get_failure(self, error: Exception) -> None:
        self._get_failure = error

    def get_item(self, Key=None, **_):
        if self._get_failure is not None:
            raise self._get_failure
        row = self.rows.get((Key or {})["invoiceId"])
        return {"Item": copy.deepcopy(row)} if row else {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None,
                    ExpressionAttributeValues=None, **_):
        self.writes += 1
        key = (Key or {})["invoiceId"]
        row = self.rows.setdefault(key, {"invoiceId": key})
        _apply_set(UpdateExpression, row, ExpressionAttributeNames or {},
                   ExpressionAttributeValues or {})
        return {"Attributes": dict(row)}

    def put_item(self, Item=None, **_):
        self.writes += 1
        self.rows[dict(Item or {})["invoiceId"]] = dict(Item or {})
        return {}


class _ItemsTable:
    """Composite `(invoiceId, itemIndex)`, queried with a real boto3 `Key(...).eq(...)`."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        self.rows[(item["invoiceId"], int(item["itemIndex"]))] = item
        return {}

    def query(self, KeyConditionExpression=None, **_):
        attribute, value = KeyConditionExpression.get_expression()["values"]
        if attribute.name != "invoiceId":
            raise AssertionError(f"unexpected query on {attribute.name!r}")
        return {"Items": [dict(row) for (invoice_id, _), row in sorted(self.rows.items())
                          if invoice_id == value]}


class _AssetsTable:
    """Composite `(invoiceId, assetType)`. A new version must be a new ROW, not an overwrite."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self.overwrites: list = []
        self._query_failure: Exception | None = None

    def arm_query_failure(self, error: Exception) -> None:
        self._query_failure = error

    def put_item(self, Item=None, **_):
        item = dict(Item or {})
        key = (item["invoiceId"], item["assetType"])
        if key in self.rows:
            # Recorded rather than refused: DynamoDB would accept it. The assertion that it
            # never happens for an issued invoice belongs in the test, not in the fake.
            self.overwrites.append(key)
        self.rows[key] = item
        return {}

    def get_item(self, Key=None, **_):
        key = (Key or {})
        row = self.rows.get((key["invoiceId"], key["assetType"]))
        return {"Item": dict(row)} if row else {}

    def query(self, KeyConditionExpression=None, **_):
        if self._query_failure is not None:
            raise self._query_failure
        attribute, value = KeyConditionExpression.get_expression()["values"]
        if attribute.name != "invoiceId":
            raise AssertionError(f"unexpected query on {attribute.name!r}")
        return {"Items": [dict(row) for (invoice_id, _), row in sorted(self.rows.items())
                          if invoice_id == value]}


class _PaymentsTable:
    """Key `id`, which is what `razorpay-webhook` writes the payment id as."""

    def __init__(self) -> None:
        self.rows: dict = {}
        self._get_failure: Exception | None = None

    def seed(self, item: dict) -> None:
        self.rows[item["id"]] = dict(item)

    def arm_get_failure(self, error: Exception) -> None:
        self._get_failure = error

    def get_item(self, Key=None, **_):
        if self._get_failure is not None:
            raise self._get_failure
        row = self.rows.get((Key or {})["id"])
        return {"Item": dict(row)} if row else {}


class _InertTable:
    """Contacts, the delivery log, the keys table: read or written incidentally, never asserted."""

    def put_item(self, **_):
        return {}

    def update_item(self, **_):
        return {}

    def get_item(self, **_):
        return {}

    def query(self, **_):
        return {"Items": []}

    def scan(self, **_):
        return {"Items": []}


class _Tables:
    """A `boto3.resource('dynamodb')` stand-in: one named fake per table the engine opens."""

    def __init__(self, module) -> None:
        self.invoices = _InvoicesTable()
        self.items = _ItemsTable()
        self.assets = _AssetsTable()
        self.payments = _PaymentsTable()
        self._by_name = {
            module.INVOICES_TABLE: self.invoices,
            module.INVOICE_ITEMS_TABLE: self.items,
            module.INVOICE_ASSETS_TABLE: self.assets,
            module.PAYMENTS_TABLE: self.payments,
            module.CONTACTS_TABLE: _InertTable(),
            module.INVOICE_DELIVERY_TABLE: _InertTable(),
            module.COMMERCE_KEYS_TABLE: _InertTable(),
        }

    def Table(self, name):  # noqa: N802 - the boto3 resource spelling
        try:
            return self._by_name[name]
        except KeyError:
            raise AssertionError(f"the engine opened an unexpected table {name!r}") from None


class _FakeS3:
    """Records every object, so "the previous rendition is still there" is an assertion."""

    def __init__(self) -> None:
        self.objects: dict = {}
        self.puts: list = []

    def put_object(self, Bucket=None, Key=None, Body=None, **_):
        self.objects[Key] = Body
        self.puts.append(Key)
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

def _draft_row() -> dict:
    """An UNISSUED row: no number has left the GST series, so there is no document yet."""
    return {
        "invoiceId": INVOICE_ID, "invoiceNumber": "", "status": "created",
        "paymentStatus": "pending", "referenceId": REFERENCE_ID,
        "customerName": CUSTOMER, "total": Decimal("1180"), "subtotal": Decimal("1000"),
        "tax": Decimal("180"), "gstRate": Decimal("18"),
    }


def _issued_row(**overrides) -> dict:
    row = _draft_row()
    row.update({"invoiceNumber": "WD/2627/00001", "status": "pending_payment"})
    row.update(overrides)
    return row


def _paid_row() -> dict:
    return _issued_row(status="paid", paymentStatus="captured", paymentId=PAYMENT_ID)


@pytest.fixture
def engine(monkeypatch):
    """The real handler, loaded by path under a unique name, pointed at the fakes above."""
    monkeypatch.syspath_prepend(str(ROOT / "amplify/functions/shared"))
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    name = "_issued_invoice_immutability_engine"
    spec = importlib.util.spec_from_file_location(name, FUNCTION)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    with patch("boto3.resource"), patch("boto3.client"):
        spec.loader.exec_module(module)

    tables = _Tables(module)
    module.dynamodb = tables
    module.s3 = _FakeS3()
    module.logger = MagicMock()
    # The renderer itself is not the subject: its bytes are a fixture so the version KEY is
    # what the test reads. `_signed_invoice_url` is stubbed for the same reason.
    module._generate_receipt_png = MagicMock(return_value=b"receipt bytes")
    module._signed_invoice_url = MagicMock(return_value="https://example.test/signed")

    from lambda_utils import middleware

    def _require_auth(event, required_role=None):
        """What `require_auth` does on a signed API Gateway request: attach, then allow."""
        event["_auth"] = {"username": STAFF, "email": f"{STAFF}@example.test",
                          "role": "Admin", "groups": ["Admin"], "attributes": {}}
        return None

    monkeypatch.setattr(middleware, "require_auth", _require_auth)
    module.tables = tables
    return module


@pytest.fixture
def pdf_engine(engine, monkeypatch):
    """`engine` plus the PIL transport fakes, so `generate_invoice_pdf` runs without Pillow."""
    image = MagicMock()
    image.save.side_effect = lambda target, **kwargs: target.write(b"%PDF-1.4\nfixture\n%%EOF")
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")
    pil_image.open = MagicMock(return_value=image)
    pil.Image = pil_image
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image)
    engine._flatten_onto_white = MagicMock(return_value=image)
    return engine


def _put(body: dict) -> dict:
    return {
        "rawPath": f"/invoices/{INVOICE_ID}",
        "requestContext": {"http": {"method": "PUT", "path": f"/invoices/{INVOICE_ID}"}},
        "pathParameters": {"invoiceId": INVOICE_ID},
        "body": json.dumps(body, default=str),
    }


def _post(suffix: str, body: dict) -> dict:
    path = f"/invoices/{INVOICE_ID}{suffix}"
    return {
        "rawPath": path,
        "requestContext": {"http": {"method": "POST", "path": path}},
        "pathParameters": {"invoiceId": INVOICE_ID},
        "body": json.dumps(body, default=str),
    }


def _body(response: dict) -> dict:
    return json.loads(response["body"])


# ══════════════════════════════════════════════════════════════════════════════
# D5 — `status` / `paymentStatus` are not client-writable on ANY row state
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("row_name", ["draft", "issued", "paid"])
@pytest.mark.parametrize("payload", [
    {"status": "paid"},
    {"paymentStatus": "captured"},
    {"status": "paid", "paymentStatus": "captured"},
    # Mixed with a field that WOULD be allowed: the refusal must not be bypassable by
    # hiding the state field among legitimate ones.
    {"customerName": "Someone Else", "paymentStatus": "refunded"},
])
def test_payment_state_is_refused_on_every_row_state(engine, row_name, payload):
    row = {"draft": _draft_row, "issued": _issued_row, "paid": _paid_row}[row_name]()
    engine.tables.invoices.seed(row)
    before = copy.deepcopy(engine.tables.invoices.rows[INVOICE_ID])

    response = engine.handler(_put(payload), None)

    assert response["statusCode"] == 400, response
    body = _body(response)
    assert body["errorCode"] == "STATUS_NOT_CLIENT_WRITABLE"
    # The refusal names the writers, so an operator is not left looking for a button.
    assert "cancel_invoice" in body["ownedBy"]
    assert engine.tables.invoices.rows[INVOICE_ID] == before
    assert engine.tables.invoices.writes == 0


def test_an_issued_unpaid_invoice_cannot_be_marked_paid(engine):
    """The named defect. A PUT was all it took to turn an unpaid invoice into revenue."""
    engine.tables.invoices.seed(_issued_row())

    response = engine.handler(_put({"status": "paid", "paymentStatus": "captured",
                                    "paidAt": 1700000000}), None)

    assert response["statusCode"] == 400
    assert _body(response)["errorCode"] == "STATUS_NOT_CLIENT_WRITABLE"
    stored = engine.tables.invoices.rows[INVOICE_ID]
    assert stored["status"] == "pending_payment"
    assert stored["paymentStatus"] == "pending"
    assert "paidAt" not in stored


def test_the_allowed_list_no_longer_mentions_payment_state(engine):
    """Removed from the set, not conditioned inside it (D5).

    A field that is only sometimes client-writable is a field whose guard can be bypassed by
    finding the state where it is permitted, so the absence is the property - not the refusal
    above, which is only how the absence is reported.
    """
    source = FUNCTION.read_text(encoding="utf-8")
    allowed = source.split("allowed = [", 1)[1].split("]", 1)[0]
    assert "'status'" not in allowed
    assert "'paymentStatus'" not in allowed
    assert engine._INVOICE_SERVER_OWNED_FIELDS == frozenset({"status", "paymentStatus"})


# ══════════════════════════════════════════════════════════════════════════════
# D4 — the financial content of an issued invoice is immutable
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("payload", [
    {"total": 999},
    {"subtotal": 500},
    {"gstRate": 5},
    {"referenceId": "WD-PAY-SOMETHINGELSE"},
    {"discount": 100},
    {"orderId": "ORD-0000"},
])
def test_a_financial_edit_on_an_issued_invoice_is_refused_and_writes_nothing(engine, payload):
    engine.tables.invoices.seed(_issued_row())
    before = copy.deepcopy(engine.tables.invoices.rows[INVOICE_ID])

    response = engine.handler(_put(payload), None)

    assert response["statusCode"] == 409, response
    body = _body(response)
    assert body["errorCode"] == "INVOICE_ISSUED_IMMUTABLE"
    assert body["useInstead"] == "cancel+reissue"
    assert body["fields"] == sorted(payload)
    assert engine.tables.invoices.rows[INVOICE_ID] == before
    assert engine.tables.invoices.writes == 0
    assert engine.s3.puts == []


def test_a_paid_invoice_is_pointed_at_a_credit_note_instead(engine):
    """Same refusal, different route out: a paid document cannot be cancelled and reissued."""
    engine.tables.invoices.seed(_paid_row())

    response = engine.handler(_put({"total": 1}), None)

    assert response["statusCode"] == 409
    body = _body(response)
    assert body["errorCode"] == "INVOICE_ISSUED_IMMUTABLE"
    assert body["useInstead"] == "remark"
    assert "credit note" in body["error"]


def test_a_row_with_a_number_is_issued_whatever_its_status_says(engine):
    """`_is_issued` reads the NUMBER first. A `created` row that carries one is still a document."""
    engine.tables.invoices.seed(_issued_row(status="created"))

    response = engine.handler(_put({"total": 1}), None)

    assert response["statusCode"] == 409
    assert _body(response)["errorCode"] == "INVOICE_ISSUED_IMMUTABLE"


def test_an_unissued_draft_still_takes_a_financial_edit(engine):
    """The other half of D4. Immutability after issue is only safe if drafts stay editable."""
    engine.tables.invoices.seed(_draft_row())

    response = engine.handler(_put({"total": 2360, "subtotal": 2000, "tax": 360}), None)

    assert response["statusCode"] == 200, response
    assert _body(response)["updated"] is True
    stored = engine.tables.invoices.rows[INVOICE_ID]
    assert stored["total"] == Decimal("2360")
    assert stored["subtotal"] == Decimal("2000")


def test_contact_fields_stay_editable_after_issue(engine):
    """A corrected spelling is not a change to what was charged.

    Refusing it would push staff toward cancel-and-reissue for a typo, which burns a GST
    number for no reason - so the refusal is scoped to the financial set deliberately.
    """
    engine.tables.invoices.seed(_issued_row())

    response = engine.handler(_put({
        "customerName": "Corrected Placeholder", "customerPhone": "+910000000000",
        "shippingAddress": "Placeholder address, Kolkata", "notes": "left with security",
    }), None)

    assert response["statusCode"] == 200, response
    stored = engine.tables.invoices.rows[INVOICE_ID]
    assert stored["customerName"] == "Corrected Placeholder"
    assert stored["notes"] == "left with security"
    # Untouched by a contact edit.
    assert stored["total"] == Decimal("1180")
    assert stored["invoiceNumber"] == "WD/2627/00001"


def test_an_unreadable_row_refuses_rather_than_writing(engine):
    """The guard fails CLOSED, replacing a warn-and-continue.

    One throttled GetItem used to be all it took to rewrite the totals on a paid tax invoice:
    the old guard logged a warning and fell through to the update.
    """
    engine.tables.invoices.seed(_paid_row())
    before = copy.deepcopy(engine.tables.invoices.rows[INVOICE_ID])
    engine.tables.invoices.arm_get_failure(RuntimeError("throttled"))

    response = engine.handler(_put({"total": 1}), None)

    assert response["statusCode"] == 503, response
    body = _body(response)
    assert body["errorCode"] == "INVOICE_STATE_UNREADABLE"
    assert body["retryable"] is True
    assert engine.tables.invoices.rows[INVOICE_ID] == before
    assert engine.tables.invoices.writes == 0


# ══════════════════════════════════════════════════════════════════════════════
# D4 — a re-render never writes over an issued rendition
# ══════════════════════════════════════════════════════════════════════════════

def test_rerendering_an_issued_invoice_writes_a_new_key(engine):
    engine.tables.invoices.seed(_issued_row())

    first = engine.handler(_post("/generate-image", {}), None)
    assert first["statusCode"] == 200, first
    first_key = _body(first)["s3Key"]
    engine.s3.objects[first_key] = b"the rendition the customer received"

    second = engine.handler(_post("/generate-image", {}), None)
    assert second["statusCode"] == 200, second
    second_key = _body(second)["s3Key"]

    # A NEW key, under the same gated prefix and off the same reference stem.
    assert second_key != first_key
    assert second_key == first_key.replace(".png", "-v2.png")
    assert second_key.startswith(engine.INVOICE_PREFIX)
    # The previous object is still there, with its original bytes.
    assert engine.s3.objects[first_key] == b"the rendition the customer received"
    # And so is its asset row, which is what every reader point-reads by `assetType`.
    assert engine.tables.assets.rows[(INVOICE_ID, "image")]["s3Key"] == first_key
    assert engine.tables.assets.rows[(INVOICE_ID, "image#v2")]["s3Key"] == second_key
    assert engine.tables.assets.overwrites == []

    third = engine.handler(_post("/generate-image", {}), None)
    assert _body(third)["s3Key"] == first_key.replace(".png", "-v3.png")
    assert engine.tables.assets.overwrites == []


def test_rerendering_a_draft_still_overwrites_in_place(engine):
    """There is no document of record yet, so a version history of a draft is noise."""
    engine.tables.invoices.seed(_draft_row())

    first_key = _body(engine.handler(_post("/generate-image", {}), None))["s3Key"]
    second_key = _body(engine.handler(_post("/generate-image", {}), None))["s3Key"]

    assert first_key == second_key == f"{engine.INVOICE_PREFIX}wecare-digital-{REFERENCE_ID}.png"
    assert list(engine.tables.assets.rows) == [(INVOICE_ID, "image")]
    assert engine.tables.assets.overwrites == [(INVOICE_ID, "image")]


def test_a_pdf_rerender_is_versioned_on_the_same_terms(pdf_engine):
    pdf_engine.tables.invoices.seed(_issued_row())

    first = _body(pdf_engine.handler(_post("/generate-pdf", {}), None))["s3Key"]
    second = _body(pdf_engine.handler(_post("/generate-pdf", {}), None))["s3Key"]

    assert first.endswith(".pdf") and second == first.replace(".pdf", "-v2.pdf")
    assert pdf_engine.tables.assets.rows[(INVOICE_ID, "pdf")]["s3Key"] == first
    assert pdf_engine.tables.assets.rows[(INVOICE_ID, "pdf#v2")]["s3Key"] == second


def test_an_unreadable_asset_history_never_falls_back_to_the_base_key(engine):
    """The fallback is the clock, not version 1.

    Answering 1 on a failed read would hand back the un-suffixed key and overwrite the issued
    document of record - the one thing the version scheme exists to prevent.
    """
    engine.tables.invoices.seed(_issued_row())
    base_key = f"{engine.INVOICE_PREFIX}wecare-digital-{REFERENCE_ID}.png"
    engine.s3.objects[base_key] = b"the rendition the customer received"
    engine.tables.assets.rows[(INVOICE_ID, "image")] = {
        "invoiceId": INVOICE_ID, "assetType": "image", "s3Key": base_key}
    engine.tables.assets.arm_query_failure(RuntimeError("throttled"))

    key = _body(engine.handler(_post("/generate-image", {}), None))["s3Key"]

    assert key != base_key
    assert engine.s3.objects[base_key] == b"the rendition the customer received"
    assert engine.tables.assets.overwrites == []


# ══════════════════════════════════════════════════════════════════════════════
# The remark author comes from the token
# ══════════════════════════════════════════════════════════════════════════════

def _stored_remarks(engine) -> list:
    raw = engine.tables.invoices.rows[INVOICE_ID]["remarks"]
    return json.loads(raw) if isinstance(raw, str) else raw


def test_a_forged_remark_author_is_ignored(engine):
    engine.tables.invoices.seed(_issued_row())

    response = engine.handler(_post("/remark", {
        "type": "remark", "text": "customer called", "author": "someone-else"}), None)

    assert response["statusCode"] == 200, response
    assert _body(response)["remark"]["author"] == STAFF
    remarks = _stored_remarks(engine)
    assert [r["author"] for r in remarks] == [STAFF]
    assert "someone-else" not in json.dumps(remarks)


def test_an_internal_invoke_gets_a_server_side_author(engine, monkeypatch):
    """`require_auth` SKIPS a Lambda-to-Lambda invoke, so there is no token to read.

    The label names the function that performed the write. A caller-supplied name is exactly
    what this change removes, and an internal path must not get it back.
    """
    from lambda_utils import middleware
    monkeypatch.setattr(middleware, "require_auth", lambda event, required_role=None: None)
    engine.tables.invoices.seed(_issued_row())

    response = engine.handler(_post("/remark", {
        "type": "remark", "text": "balance due reminder sent", "author": "admin"}), None)

    assert response["statusCode"] == 200, response
    assert _body(response)["remark"]["author"] == "system:invoice-engine"


# ══════════════════════════════════════════════════════════════════════════════
# A refund needs provider evidence
# ══════════════════════════════════════════════════════════════════════════════

def _refund(**overrides) -> dict:
    payload = {"type": "refund", "text": "customer asked for a refund", "amount": 1180}
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("payload, payment_row", [
    # No refund id at all - the old behaviour, which wrote `refunded` on this alone.
    (_refund(), {"id": PAYMENT_ID, "status": "captured"}),
    # A refund id the provider has never reported.
    (_refund(refundId=REFUND_ID), {"id": PAYMENT_ID, "status": "captured"}),
    # A refund id that does not match the one on record.
    (_refund(refundId=REFUND_ID),
     {"id": PAYMENT_ID, "status": "refunded", "refundId": "rfnd_somethingelse"}),
    # The right refund id, but the payment row has not reached `refunded`.
    (_refund(refundId=REFUND_ID),
     {"id": PAYMENT_ID, "status": "captured", "refundId": REFUND_ID}),
])
def test_a_refund_without_evidence_leaves_the_payment_state_alone(engine, payload, payment_row):
    engine.tables.invoices.seed(_paid_row())
    engine.tables.payments.seed(payment_row)

    response = engine.handler(_post("/remark", payload), None)

    assert response["statusCode"] == 400, response
    body = _body(response)
    assert body["errorCode"] == "REFUND_EVIDENCE_REQUIRED"
    assert "Nothing has been refunded." in body["error"]
    stored = engine.tables.invoices.rows[INVOICE_ID]
    # The payment state is EXACTLY as it was, and no refund figure was persisted.
    assert stored["paymentStatus"] == "captured"
    assert not {"refundAmount", "refundAmountPaise", "refundAt", "refundId"} & stored.keys()
    # The remark itself IS recorded: discarding the operator's note would push them to write
    # it somewhere we cannot see.
    remarks = _stored_remarks(engine)
    assert [r["type"] for r in remarks] == ["refund"]
    assert remarks[0]["providerRefundId"] == ""


def test_an_unreadable_payment_row_is_not_evidence(engine):
    engine.tables.invoices.seed(_paid_row())
    engine.tables.payments.seed({"id": PAYMENT_ID, "status": "refunded", "refundId": REFUND_ID})
    engine.tables.payments.arm_get_failure(RuntimeError("throttled"))

    response = engine.handler(_post("/remark", _refund(refundId=REFUND_ID)), None)

    assert response["statusCode"] == 400
    assert _body(response)["errorCode"] == "REFUND_EVIDENCE_REQUIRED"
    assert engine.tables.invoices.rows[INVOICE_ID]["paymentStatus"] == "captured"


def test_a_proven_refund_is_recorded(engine):
    """The bar is "the webhook has seen this refund" - the same fact a human would check."""
    engine.tables.invoices.seed(_paid_row())
    engine.tables.payments.seed({
        "id": PAYMENT_ID, "paymentId": PAYMENT_ID, "status": "refunded",
        "refundId": REFUND_ID, "refundAmountPaise": Decimal("118000")})

    response = engine.handler(_post("/remark", _refund(refundId=REFUND_ID)), None)

    assert response["statusCode"] == 200, response
    stored = engine.tables.invoices.rows[INVOICE_ID]
    assert stored["paymentStatus"] == "refunded"
    assert stored["refundAmountPaise"] == 118000
    assert stored["refundId"] == REFUND_ID
    assert _stored_remarks(engine)[0]["providerRefundId"] == REFUND_ID


def test_the_payment_id_may_come_from_the_body_when_the_invoice_carries_none(engine):
    """A legacy invoice row with no `paymentId` is still refundable, with the id supplied."""
    engine.tables.invoices.seed(_issued_row(status="paid", paymentStatus="captured"))
    engine.tables.payments.seed({"id": PAYMENT_ID, "status": "refunded", "refundId": REFUND_ID})

    response = engine.handler(_post("/remark", _refund(
        refundId=REFUND_ID, paymentId=PAYMENT_ID)), None)

    assert response["statusCode"] == 200, response
    assert engine.tables.invoices.rows[INVOICE_ID]["paymentStatus"] == "refunded"


def test_a_credit_note_never_touches_the_payment_state(engine):
    """Unchanged behaviour, pinned: a credit note is an accounting record, not a refund."""
    engine.tables.invoices.seed(_paid_row())

    response = engine.handler(_post("/remark", {
        "type": "credit_note", "text": "goodwill", "amount": 100}), None)

    assert response["statusCode"] == 200, response
    stored = engine.tables.invoices.rows[INVOICE_ID]
    assert stored["paymentStatus"] == "captured"
    assert stored["creditNoteAmountPaise"] == 10000


# ══════════════════════════════════════════════════════════════════════════════
# D6 — the UI no longer offers what the server refuses (source-pinned)
# ══════════════════════════════════════════════════════════════════════════════

def test_the_browser_cannot_supply_a_remark_author():
    """Dropped from the signature AND the body, so there is nothing for the server to ignore."""
    source = API_CLIENT.read_text(encoding="utf-8")
    declaration = [line for line in source.splitlines()
                   if "export async function addInvoiceRemark" in line]
    assert len(declaration) == 1, declaration
    assert "author" not in declaration[0].split("):")[0]
    assert "{ type: remarkType, text, amount }" in source


def test_the_edit_payload_carries_no_financial_field():
    """`shipping` and `discount` are gone from `submitEdit`, and the button is gated on issue."""
    source = FLOW_PAGE.read_text(encoding="utf-8")
    payload = source.split("const submitEdit", 1)[1].split("};", 1)[0]
    for field in ("shipping:", "discount:", "total:", "gstRate:"):
        assert field not in payload, field
    # The gate IMMEDIATELY above the Edit button, read by position rather than by presence
    # anywhere in the file: `isIssued` appearing somewhere is not the same claim as the Edit
    # button being the thing it gates. The old gate was `status !== 'paid' && !== 'cancelled'`,
    # which offered an edit on every issued unpaid invoice - that is, on all of them.
    lines = source.splitlines()
    edit_buttons = [i for i, line in enumerate(lines) if "openEditModal( selInvoice )" in line]
    assert len(edit_buttons) == 1, edit_buttons
    assert "!isIssued( selInvoice )" in lines[edit_buttons[0] - 1]
