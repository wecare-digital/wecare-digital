"""A customer gets a short-lived link to their OWN invoice, and never anybody else's.

The security cases come first, because they are the ones that must fail loudly. Several of
them assert on the CAPTURED query kwargs rather than on the returned body, and that
distinction is the value of this file: a handler that moved its scoping out of the key
condition would return an identical answer while reading - and paying for - another
customer's rows. An assertion on the body cannot tell those two apart.

`customer_auth.require_customer` is left REAL throughout. Only the Cognito client underneath
it is stubbed, so the issuer pin that separates the customer pool from the staff pool is
exercised rather than mocked past - which is what makes the staff-token case meaningful.

No AWS is reached: DynamoDB, S3 and Cognito are all stubs.
"""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared')))

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "amplify/functions/ecommerce/customer-invoice/handler.py"

ORDERS_TABLE = "stack-wecare-digital-OrderTable"
ORDERS_INDEX = "customerId-createdAt-index"
INVOICES_TABLE = "stack-wecare-digital-InvoicesTable"
INVOICES_INDEX = "referenceId-index"
ASSETS_TABLE = "stack-wecare-digital-InvoiceAssetsTable"

SUBJECT = "11111111-2222-3333-4444-555555555555"
OTHER_SUBJECT = "99999999-8888-7777-6666-555555555555"
PHONE = "+919330994400"
CREATED_AT = 1764700000

CUSTOMER_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"
#: The STAFF pool. A token from it is perfectly valid, which is exactly why the pin exists.
STAFF_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_cSx0RHCIR"

#: The gated key the invoice engine actually writes.
GATED_KEY = "secure/stack/invoices/wecare-digital-REF-ABCDEF.png"
#: The same shape under the PUBLIC root - a legal string a row could still carry, because
#: the prefix only moved to `secure/` on 2026-09-30.
PUBLIC_KEY = "o/stack/invoices/wecare-digital-REF-ABCDEF.png"

SIGNED_URL = ("https://wecare-digital-get.s3.amazonaws.com/" + GATED_KEY
              + "?X-Amz-Signature=deadbeef&X-Amz-Credential=cred")


# ── fixtures ──────────────────────────────────────────────────────────────────

def _token(issuer: str) -> str:
    """A token whose unverified `iss` claim is `issuer`. The signature is never checked here -
    `customer_auth` proves liveness with `GetUser` and reads `iss` only to REJECT."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer}).encode("utf-8")).decode("ascii").rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{payload}.not-a-signature"


class RecordingTable:
    """A table stub that RECORDS every `query` and `get_item` kwarg it is handed."""

    def __init__(self, name, items=None, *, error=None):
        self.name = name
        self.items = [dict(item) for item in (items or [])]
        self.error = error
        self.queries = []
        self.gets = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.error is not None:
            raise self.error
        expression = kwargs["KeyConditionExpression"].get_expression()
        conditions = _flatten(expression)
        matched = [item for item in self.items
                   if all(item.get(name) == value for name, value in conditions)]
        limit = kwargs.get("Limit")
        return {"Items": matched[:limit] if limit else matched}

    def get_item(self, **kwargs):
        self.gets.append(kwargs)
        if self.error is not None:
            raise self.error
        key = kwargs["Key"]
        for item in self.items:
            if all(item.get(name) == value for name, value in key.items()):
                return {"Item": dict(item)}
        return {}


def _flatten(expression):
    """`[(attribute, value), ...]` out of one or more ANDed `Key(...).eq(...)` conditions."""
    if expression["operator"] == "AND":
        pairs = []
        for operand in expression["values"]:
            pairs.extend(_flatten(operand.get_expression()))
        return pairs
    attribute, value = expression["values"]
    return [(attribute.name, value)]


class FakeResource:
    def __init__(self, tables):
        self.tables = tables

    def Table(self, name):
        return self.tables[name]


class FakeS3:
    """`generate_presigned_url` only. Presigning is a local computation, so there is no
    network call to stub - and this function never fetches an object."""

    def __init__(self, url=SIGNED_URL):
        self.url = url
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
        self.calls.append({"operation": operation, "Params": dict(Params),
                           "ExpiresIn": ExpiresIn})
        return self.url


class FakeCognito:
    """`GetUser` for a live token. Returns the attributes `authenticate` actually reads."""

    def __init__(self, subject=SUBJECT, phone=PHONE):
        self.subject = subject
        self.phone = phone
        self.calls = 0

    def get_user(self, AccessToken):  # noqa: N803 - boto3's parameter name
        self.calls += 1
        return {"Username": self.phone,
                "UserAttributes": [{"Name": "sub", "Value": self.subject},
                                   {"Name": "phone_number", "Value": self.phone}]}


def _called_names(path: Path) -> set:
    """Every name this module CALLS, read off the AST rather than out of the text.

    A docstring that explains why a verb is not used necessarily contains that verb, so a
    substring sweep over the source fails on the explanation. The AST only sees code.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Attribute):
            names.add(target.attr)
        elif isinstance(target, ast.Name):
            names.add(target.id)
    return names


def order_row(**overrides):
    """A row as `finalization.accept_paid` writes it, with DynamoDB's own number type."""
    row = {
        "orderId": "WD-ORD-A1B2C3D4",
        "orderNumber": "WD-100042",
        "referenceId": "REF-ABCDEF",
        "customerId": SUBJECT,
        "createdAt": CREATED_AT,
        "amountPaise": Decimal("121481"),
        "currency": "INR",
        "paymentStatus": "PAYMENT_PAID",
    }
    row.update(overrides)
    return row


def invoice_row(**overrides):
    row = {"invoiceId": "INV-1", "referenceId": "REF-ABCDEF"}
    row.update(overrides)
    return row


def asset_row(**overrides):
    row = {"invoiceId": "INV-1", "assetType": "image", "s3Key": GATED_KEY,
           "contentType": "image/png"}
    row.update(overrides)
    return row


@pytest.fixture
def ctx(monkeypatch):
    """The handler plus its four stubs, with no AWS at all."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    spec = importlib.util.spec_from_file_location("customer_invoice_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["customer_invoice_under_test"] = module
    spec.loader.exec_module(module)

    orders = RecordingTable(ORDERS_TABLE, [order_row()])
    invoices = RecordingTable(INVOICES_TABLE, [invoice_row()])
    assets = RecordingTable(ASSETS_TABLE, [asset_row()])
    monkeypatch.setattr(module, "_dynamodb", FakeResource({
        ORDERS_TABLE: orders, INVOICES_TABLE: invoices, ASSETS_TABLE: assets}))
    s3 = FakeS3()
    monkeypatch.setattr(module, "_s3", s3)

    rate_calls = []
    monkeypatch.setattr(module.rate_limit, "check_rate_limit",
                        lambda *a, **k: rate_calls.append((a, k)) or True)
    monkeypatch.setattr(module.customer_auth, "_client", lambda: FakeCognito())

    class Ctx:
        pass

    bundle = Ctx()
    bundle.module = module
    bundle.orders = orders
    bundle.invoices = invoices
    bundle.assets = assets
    bundle.s3 = s3
    bundle.rate_calls = rate_calls
    yield bundle
    sys.modules.pop("customer_invoice_under_test", None)


def event(*, token=None, body=None, method="POST", issuer=CUSTOMER_ISSUER):
    headers = {"origin": "http://localhost:3000"}
    if token is None:
        token = _token(issuer)
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = {
        "requestContext": {"http": {"method": method}},
        "headers": headers,
    }
    if body is not None:
        request["body"] = json.dumps(body)
    return request


#: A sentinel, because `None` is a BODY A TEST NEEDS TO SEND - an absent body is one of the
#: INVALID_BODY cases. Defaulting on `None` would silently replace it with the valid body and
#: the test would pass for the wrong reason.
_DEFAULT = object()


def call(ctx, *, body=_DEFAULT, **kwargs):
    if body is _DEFAULT:
        body = {"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT}
    response = ctx.module.handler(event(body=body, **kwargs), None)
    return response, json.loads(response["body"])


# ── security: the boundary, asserted on the query ─────────────────────────────

def test_an_unauthenticated_request_is_401_and_reads_nothing(ctx):
    response, body = call(ctx, token="")
    assert response["statusCode"] == 401
    assert body["error"] == "VERIFICATION_REQUIRED"
    # Auth precedes everything that costs anything: no Query, no GetItem, no signature, and
    # not even a rate-limit write.
    assert ctx.orders.queries == []
    assert ctx.invoices.queries == []
    assert ctx.assets.gets == []
    assert ctx.s3.calls == []
    assert ctx.rate_calls == []


def test_a_staff_pool_token_gets_a_byte_identical_401(ctx):
    """A staff token is VALID - `GetUser` succeeds - so only the issuer pin rejects it, and
    the body must not say which of the two failure modes happened."""
    _, anonymous = call(ctx, token="")
    response, body = call(ctx, issuer=STAFF_ISSUER)
    assert response["statusCode"] == 401
    assert body == anonymous
    assert ctx.s3.calls == []


def test_the_401_is_not_cacheable(ctx):
    """`cors_headers` sets no cache directive at all, and the Amplify rewrite serves
    `/api/<*>` with status 200, so a shared cache sits in front of these responses."""
    response, _ = call(ctx, token="")
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["Pragma"] == "no-cache"


def test_every_success_response_is_also_no_store(ctx):
    """A cached presigned URL replayed to a second customer is the disclosure this route
    exists to avoid."""
    response, body = call(ctx)
    assert body["available"] is True
    assert response["headers"]["Cache-Control"] == "no-store"


def test_the_ownership_query_is_scoped_by_the_token_not_the_request(ctx):
    call(ctx)
    assert len(ctx.orders.queries) == 1
    query = ctx.orders.queries[0]
    assert query["IndexName"] == ORDERS_INDEX
    conditions = dict(_flatten(query["KeyConditionExpression"].get_expression()))
    # `customerId` comes from the Cognito `sub` and from nowhere else. DynamoDB will not
    # return an item from another partition, so another customer's order is UNREACHABLE
    # rather than read and then discarded.
    assert conditions["customerId"] == SUBJECT
    assert conditions["createdAt"] == CREATED_AT
    # No row-level filter: a filter runs AFTER the other row has been read, charged for and
    # brought into this process's memory.
    assert "FilterExpression" not in query


def test_no_limit_is_applied_to_the_ownership_query(ctx):
    """`createdAt` is the index RANGE key in whole seconds, not a unique key, so a Limit
    would silently truncate the caller's own rows at that second."""
    call(ctx)
    assert "Limit" not in ctx.orders.queries[0]


def test_another_customers_reference_at_the_same_timestamp_is_refused(ctx):
    """Scoped by partition, so this never even reaches the invoice lookup."""
    ctx.orders.items = [order_row(customerId=OTHER_SUBJECT)]
    response, body = call(ctx)
    assert response["statusCode"] == 200
    assert body == {"available": False}
    assert ctx.invoices.queries == []
    assert ctx.s3.calls == []


# ── ownership is a MEMBERSHIP test, not Items[0] ─────────────────────────────

def test_a_second_order_in_the_same_second_resolves_to_its_own_invoice(ctx):
    """THE CASE THAT KILLS THE OBVIOUS `Items[0]` IMPLEMENTATION.

    `createdAt` is the index RANGE key in whole SECONDS, so one customer can hold more than
    one row at one timestamp and `eq()` returns both. Taking the first row would refuse a
    legitimate second order with `available:false` - which this route makes
    indistinguishable from "not yours", so the customer would get a permanent, unexplainable
    "No invoice yet" and the log would say the ownership check failed.
    """
    ctx.orders.items = [
        order_row(orderId="WD-ORD-FIRST", orderNumber="WD-100042", referenceId="REF-FIRST"),
        order_row(orderId="WD-ORD-SECOND", orderNumber="WD-100043",
                  referenceId="REF-SECOND"),
    ]
    ctx.invoices.items = [invoice_row(invoiceId="INV-2", referenceId="REF-SECOND")]
    ctx.assets.items = [asset_row(invoiceId="INV-2")]
    response, body = call(ctx, body={"referenceId": "REF-SECOND", "createdAt": CREATED_AT})
    assert response["statusCode"] == 200
    assert body["available"] is True
    # And it is the SECOND row's invoice, not the first row's.
    assert ctx.invoices.queries[0]["IndexName"] == INVOICES_INDEX
    reference = dict(_flatten(
        ctx.invoices.queries[0]["KeyConditionExpression"].get_expression()))
    assert reference["referenceId"] == "REF-SECOND"
    assert ctx.assets.gets[0]["Key"]["invoiceId"] == "INV-2"


def test_order_number_is_read_off_the_matched_row_not_the_first(ctx):
    """The filename is derived from `orderNumber`, so reading it off the wrong row would
    bake another order's number into a signed Content-Disposition header."""
    ctx.orders.items = [
        order_row(orderId="WD-ORD-FIRST", orderNumber="WD-100042", referenceId="REF-FIRST"),
        order_row(orderId="WD-ORD-SECOND", orderNumber="WD-100043",
                  referenceId="REF-SECOND"),
    ]
    ctx.invoices.items = [invoice_row(invoiceId="INV-2", referenceId="REF-SECOND")]
    ctx.assets.items = [asset_row(invoiceId="INV-2")]
    call(ctx, body={"referenceId": "REF-SECOND", "createdAt": CREATED_AT})
    disposition = ctx.s3.calls[0]["Params"]["ResponseContentDisposition"]
    assert "WD-100043" in disposition
    assert "WD-100042" not in disposition


# ── one answer for three different facts ─────────────────────────────────────

def test_a_missing_invoice_answers_exactly_what_a_denied_one_does(ctx):
    """`available:false` is the SINGLE answer for "no invoice", "no asset" and "not your
    order", byte-identically, so the route is not an existence oracle."""
    _, denied = call(ctx)
    ctx.orders.items = [order_row(customerId=OTHER_SUBJECT)]
    _, not_yours = call(ctx)

    ctx.orders.items = [order_row()]
    ctx.invoices.items = []
    no_invoice_response, no_invoice = call(ctx)

    ctx.invoices.items = [invoice_row()]
    ctx.assets.items = []
    no_asset_response, no_asset = call(ctx)

    assert not_yours == no_invoice == no_asset == {"available": False}
    assert no_invoice_response["statusCode"] == no_asset_response["statusCode"] == 200
    assert denied["available"] is True   # the control: the happy path really does differ


def test_the_success_body_keys_equal_exactly_available_and_url(ctx):
    """EQUALITY, not containment - the property being protected IS the absence. An echoed
    `format`, a reinstated `expiresInSeconds` or a returned `filename` would otherwise ship
    unnoticed, and a field with no consumer is a field a later edit treats as load-bearing
    on the strength of its presence alone."""
    _, body = call(ctx)
    assert set(body) == {"available", "url"}
    assert body["url"] == SIGNED_URL


def test_the_refusal_body_keys_equal_exactly_available(ctx):
    ctx.invoices.items = []
    _, body = call(ctx)
    assert set(body) == {"available"}


def test_asset_type_never_appears_on_the_wire(ctx):
    """`format` and `assetType` are two different vocabularies. The request carries a FILE
    FORMAT; `assetType` is an internal table key and there is nothing on the wire to confuse
    it with."""
    response, body = call(ctx)
    assert "assetType" not in response["body"]
    assert "image" not in json.dumps(body)
    # It IS used as the table key, which is the only place it belongs.
    assert ctx.assets.gets[0]["Key"]["assetType"] == "image"


# ── the gated-key guard ──────────────────────────────────────────────────────

def test_a_public_root_key_is_refused_and_never_signed(ctx):
    """`s3Key` comes out of a DynamoDB row, so it is the one input on this path that is
    neither the caller's nor this code's - and a key shaped `o/stack/invoices/...` is a legal
    string a row could carry, because the prefix only moved to `secure/` on 2026-09-30.
    Presigning it SUCCEEDS and returns a signed URL for a world-readable object, so the
    client's signature check would pass while the artifact stayed public forever."""
    ctx.assets.items = [asset_row(s3Key=PUBLIC_KEY)]
    response, body = call(ctx)
    assert response["statusCode"] == 200
    assert body == {"available": False}
    # Refused BEFORE the signature, not after.
    assert ctx.s3.calls == []


def test_the_refused_key_appears_in_no_log_line(ctx, caplog):
    """`ReceiptError`'s message is built as f"refusing a receipt key outside the gated root:
    {key!r}..." - our own code composed it, but it EMBEDS THE S3 KEY. Logging an exception's
    text is permitted only when the message was built from known-safe parts; this one was
    not, so the handler logs `type(exc).__name__` and never `str(exc)`."""
    import logging
    ctx.assets.items = [asset_row(s3Key=PUBLIC_KEY)]
    with caplog.at_level(logging.DEBUG):
        call(ctx)
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert PUBLIC_KEY not in rendered
    assert "o/stack/invoices" not in rendered
    assert "refusing a receipt key" not in rendered
    # The type and the loggable correlation id are what it DOES carry.
    assert "ReceiptError" in rendered
    assert "REF-ABCDEF" in rendered


def test_the_signed_url_itself_appears_in_no_log_line(ctx, caplog):
    """The URL is a bearer grant."""
    import logging
    with caplog.at_level(logging.DEBUG):
        call(ctx)
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert SIGNED_URL not in rendered
    assert "X-Amz-Signature" not in rendered


def test_the_gated_key_is_what_gets_signed(ctx):
    call(ctx)
    assert ctx.s3.calls[0]["Params"]["Key"] == GATED_KEY
    assert ctx.s3.calls[0]["Params"]["Key"].startswith("secure/")
    assert ctx.s3.calls[0]["Params"]["Bucket"] == "wecare-digital-get"
    assert ctx.s3.calls[0]["operation"] == "get_object"


# ── the link itself ──────────────────────────────────────────────────────────

def test_the_link_carries_a_content_disposition_and_a_short_ttl(ctx):
    call(ctx)
    params = ctx.s3.calls[0]["Params"]
    # Baked INTO the signature, so it cannot be tampered with in transit - and it is why the
    # response carries no `filename` of its own.
    assert params["ResponseContentDisposition"].startswith("attachment; filename=")
    # 300s, not the module's 24h default: a day-long grant on a page is the forwarded-message
    # risk `receipt_links` exists to bound.
    assert ctx.s3.calls[0]["ExpiresIn"] <= 300
    assert ctx.module.LINK_TTL_SECONDS == 300


def test_an_unsanitised_order_number_cannot_reach_the_signed_header(ctx):
    """`orderNumber` is an unvalidated DynamoDB string and it is interpolated into a signed
    header, so it is sanitised to `[A-Za-z0-9._-]` first."""
    ctx.orders.items = [order_row(orderNumber='WD/../"; drop\n')]
    call(ctx)
    disposition = ctx.s3.calls[0]["Params"]["ResponseContentDisposition"]
    assert disposition == 'attachment; filename="invoice-WD..drop.png"'
    # The name itself, with the header's own closing quote stripped off.
    name = disposition.split('filename="')[1].rstrip('"')
    for forbidden in ('/', '"', ';', '\n', ' '):
        assert forbidden not in name


def test_the_filename_falls_back_to_the_reference_when_there_is_no_order_number(ctx):
    ctx.orders.items = [order_row(orderNumber="")]
    call(ctx)
    assert 'filename="invoice-REF-ABCDEF.png"' in (
        ctx.s3.calls[0]["Params"]["ResponseContentDisposition"])


def test_an_unsigned_url_from_the_signer_is_refused_rather_than_returned(ctx):
    """`assert_not_permanent` is applied to the PRODUCED url. A permanent CDN link arriving
    here would be a disclosure that works perfectly, forever, for everyone."""
    ctx.s3.url = "https://wecare.digital/get/o/stack/invoices/x.png"
    response, body = call(ctx)
    assert response["statusCode"] == 503
    assert body == {"error": "INVOICE_UNAVAILABLE"}


def test_a_signer_failure_is_a_503_and_not_a_partial_answer(ctx):
    def boom(*args, **kwargs):
        raise RuntimeError("no credentials")

    ctx.s3.generate_presigned_url = boom
    response, body = call(ctx)
    assert response["statusCode"] == 503
    assert body == {"error": "INVOICE_UNAVAILABLE"}


# ── it never generates ───────────────────────────────────────────────────────

def test_the_handler_never_generates_an_invoice(ctx):
    """Generation is `require_auth`-gated and ADVANCES THE GST SEQUENCE, so a customer
    -triggered render would mutate invoice state from a read path. Asserted on the CALLED
    NAMES as well as on the behaviour, because the property is an absence.

    IT WALKS THE AST, NOT THE TEXT, and that is required rather than fastidious: the
    handler's own docstrings necessarily NAME these verbs in the sentences explaining why it
    does not use them, so a substring sweep would fail on the explanation rather than on the
    code. Same reasoning as the frontend's comment-stripped source gates.
    """
    called = _called_names(HANDLER_PATH)
    for forbidden in ("generate_invoice_image", "put_item", "update_item", "delete_item",
                      "batch_write_item", "put_object", "delete_object",
                      "_build_invoice_html", "get_secret_value"):
        assert forbidden not in called, f"{forbidden} is called and must not be"
    # The only thing it does with S3 is sign, and it does not even do that itself - the
    # signature comes from `receipt_links.signed_url`, through `assert_not_permanent`.
    assert "signed_url" in called
    assert "assert_not_permanent" in called
    assert "assert_private_key" in called
    # It never fetches the object either, which is why its role has no bucket-level grant.
    assert "get_object" not in called
    assert "download_file" not in called
    # And no write reaches a stub when an asset is missing.
    ctx.assets.items = []
    call(ctx)
    assert ctx.s3.calls == []


def test_the_clients_are_built_lazily_and_never_at_import(ctx):
    """A module-scope `boto3.resource` reaches for AWS configuration at import time, and a
    module-scope READ is cached for the life of the execution environment."""
    source = HANDLER_PATH.read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith(("_dynamodb", "_s3")):
            assert line.split("=", 1)[1].strip() == "None", line
    assert "boto3.resource" in source
    assert "def _table(" in source
    assert "def _s3_client(" in source


# ── request validation, before any read ──────────────────────────────────────

def test_the_rate_limit_runs_before_validation_and_names_its_own_table(ctx):
    """`table_name=` is passed EXPLICITLY, never taken from the signature default of 80 or
    from the module's own env read: an unset variable would silently write to a different
    table than the one IAM grants, and `check_rate_limit` FAILS OPEN on the resulting
    AccessDeniedException."""
    call(ctx)
    assert len(ctx.rate_calls) == 1
    args, kwargs = ctx.rate_calls[0]
    assert args[0] == "my-invoice"
    # Keyed on the PROVEN subject, not on anything the request supplies.
    assert args[1] == SUBJECT
    assert args[2] == 5
    assert kwargs["table_name"] == "stack-wecare-digital-RateLimitTable"
    assert ctx.module.RATE_LIMIT_PER_SECOND == 5


def test_a_rate_limited_caller_gets_429_and_reads_nothing(ctx, monkeypatch):
    monkeypatch.setattr(ctx.module.rate_limit, "check_rate_limit", lambda *a, **k: False)
    response, body = call(ctx)
    assert response["statusCode"] == 429
    assert body == {"error": "TOO_MANY_REQUESTS"}
    assert ctx.orders.queries == []


@pytest.mark.parametrize("body,expected", [
    (None, "INVALID_BODY"),
    ({}, "INVALID_BODY"),
    ({"createdAt": CREATED_AT}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF"}, "INVALID_BODY"),
    ({"referenceId": "   ", "createdAt": CREATED_AT}, "INVALID_BODY"),
    ({"referenceId": "REF ABCDEF", "createdAt": CREATED_AT}, "INVALID_BODY"),
    ({"referenceId": "../../etc/passwd", "createdAt": CREATED_AT}, "INVALID_BODY"),
    ({"referenceId": "R" * 129, "createdAt": CREATED_AT}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": 0}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": -1}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": None}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": 1.5}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": "1764700000"}, "INVALID_BODY"),
    # `isinstance(True, int)` is TRUE, so bool has to be rejected EXPLICITLY - otherwise
    # `Key("createdAt").eq(True)` is a well-formed query for a nonsense timestamp.
    ({"referenceId": "REF-ABCDEF", "createdAt": True}, "INVALID_BODY"),
    ({"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT, "customerId": SUBJECT},
     "UNEXPECTED_FIELD"),
    ({"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT, "limit": 50},
     "UNEXPECTED_FIELD"),
    ({"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT, "format": "svg"},
     "UNSUPPORTED_FORMAT"),
    ({"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT, "format": "PNG"},
     "UNSUPPORTED_FORMAT"),
    ({"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT, "format": "image"},
     "UNSUPPORTED_FORMAT"),
])
def test_a_bad_body_is_refused_before_any_read(ctx, body, expected):
    response, answer = call(ctx, body=body)
    assert response["statusCode"] == 400
    assert answer == {"error": expected}
    # BEFORE any read, so a malformed request costs no DynamoDB call and no signature.
    assert ctx.orders.queries == []
    assert ctx.invoices.queries == []
    assert ctx.assets.gets == []
    assert ctx.s3.calls == []


def test_unparseable_json_is_invalid_body_rather_than_a_500(ctx):
    request = event(body={"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT})
    request["body"] = "{not json"
    response = ctx.module.handler(request, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"]) == {"error": "INVALID_BODY"}


def test_png_is_the_default_format_and_maps_to_the_image_asset(ctx):
    call(ctx, body={"referenceId": "REF-ABCDEF", "createdAt": CREATED_AT})
    assert ctx.assets.gets[0]["Key"]["assetType"] == "image"
    assert ctx.module.ASSET_TYPE == {"png": "image", "pdf": "pdf"}


def test_pdf_is_accepted_and_maps_to_the_pdf_asset(ctx):
    ctx.assets.items = [asset_row(assetType="pdf",
                                  s3Key="secure/stack/invoices/wecare-digital-x.pdf")]
    response, body = call(ctx, body={"referenceId": "REF-ABCDEF",
                                     "createdAt": CREATED_AT, "format": "pdf"})
    assert response["statusCode"] == 200
    assert body["available"] is True
    assert ctx.assets.gets[0]["Key"]["assetType"] == "pdf"


def test_a_non_post_method_is_refused(ctx):
    response, body = call(ctx, method="GET")
    assert response["statusCode"] == 405
    assert body == {"error": "METHOD_NOT_ALLOWED"}
    assert ctx.orders.queries == []


# ── degradation ──────────────────────────────────────────────────────────────

def test_a_failed_table_read_is_a_503_rather_than_a_false_negative(ctx):
    """A read failure has no partial answer. Answering `available:false` here would tell the
    customer their invoice does not exist when the truth is that we could not look."""
    ctx.orders.error = RuntimeError("ProvisionedThroughputExceededException")
    response, body = call(ctx)
    assert response["statusCode"] == 503
    assert body == {"error": "INVOICE_UNAVAILABLE"}


def test_no_error_message_echoes_an_input_back(ctx, caplog):
    import logging
    ctx.invoices.error = RuntimeError("table stack-wecare-digital-InvoicesTable is on fire")
    with caplog.at_level(logging.DEBUG):
        response, _ = call(ctx)
    assert response["statusCode"] == 503
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "is on fire" not in rendered
    assert "RuntimeError" in rendered


def test_an_unexpected_failure_is_a_500_with_a_type_and_no_text(ctx, caplog):
    import logging

    def boom(*args, **kwargs):
        raise KeyError("something structural")

    ctx.module._respond = boom
    with caplog.at_level(logging.DEBUG):
        response = ctx.module.handler(event(body={"referenceId": "REF-ABCDEF",
                                                  "createdAt": CREATED_AT}), None)
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "INTERNAL_ERROR"}
    assert response["headers"]["Cache-Control"] == "no-store"
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "KeyError" in rendered
    assert "something structural" not in rendered
