"""A customer reads their OWN orders, and the proof is on the query rather than on the output.

The security cases come first on purpose, because they are the ones that must fail loudly. Most of
them assert on the CAPTURED `query` kwargs instead of on the returned list, and that distinction is
the whole value of this file: a handler that moved its scoping from the key condition into a
row-level filter would return an identical list while reading - and paying for - another customer's
rows. An assertion on the output cannot tell those two apart. An assertion on the query can.

`customer_auth.require_customer` is left REAL throughout. Only the Cognito client underneath it is
stubbed, so the issuer pin that separates the customer pool from the staff pool is exercised rather
than mocked past - which is what makes the staff-token case meaningful.
"""
from __future__ import annotations

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
HANDLER_PATH = ROOT / "amplify/functions/ecommerce/customer-orders/handler.py"

ORDERS_TABLE = "stack-wecare-digital-OrderTable"
ORDERS_INDEX = "customerId-createdAt-index"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"

#: The Cognito `sub` is the customer id - see `customer_auth.customer_id_from_attributes`.
SUBJECT = "11111111-2222-3333-4444-555555555555"
OTHER_SUBJECT = "99999999-8888-7777-6666-555555555555"
PHONE = "+919330994400"

CUSTOMER_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_46ULYuukt"
#: The STAFF pool. A token from it is perfectly valid, which is exactly why the issuer pin exists.
STAFF_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_cSx0RHCIR"


# ── fixtures ──────────────────────────────────────────────────────────────────

def _token(issuer: str) -> str:
    """A token whose unverified `iss` claim is `issuer`. The signature is never checked here -
    `customer_auth` proves liveness with `GetUser` and reads `iss` only to REJECT."""
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer}).encode("utf-8")).decode("ascii").rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{payload}.not-a-signature"


def _key_condition(kwargs) -> tuple:
    """`(attribute_name, value)` out of a boto3 `Key(...).eq(...)` condition."""
    expression = kwargs["KeyConditionExpression"].get_expression()
    attribute, value = expression["values"]
    return attribute.name, value


class RecordingTable:
    """A DynamoDB table stub that RECORDS every `query` kwarg it is handed.

    It also implements just enough of a GSI query - partition filter, descending sort,
    `ExclusiveStartKey`, `Limit`, `LastEvaluatedKey` - that paging can be exercised end to end.
    """

    def __init__(self, name, items=None, *, sort_key="createdAt", error=None):
        self.name = name
        self.items = [dict(item) for item in (items or [])]
        self.sort_key = sort_key
        self.error = error
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.error is not None:
            raise self.error
        attribute, value = _key_condition(kwargs)
        matched = [item for item in self.items if item.get(attribute) == value]
        if self.sort_key and all(self.sort_key in item for item in matched):
            matched.sort(key=lambda item: item[self.sort_key],
                         reverse=not kwargs.get("ScanIndexForward", True))
        start = kwargs.get("ExclusiveStartKey")
        if start:
            keys = [item for item in matched
                    if str(item.get("orderId")) == str(start.get("orderId"))]
            if keys:
                matched = matched[matched.index(keys[0]) + 1:]
        limit = int(kwargs.get("Limit") or len(matched) or 1)
        page, remaining = matched[:limit], matched[limit:]
        result = {"Items": page}
        if remaining and page:
            last = page[-1]
            result["LastEvaluatedKey"] = {"customerId": last.get("customerId"),
                                          "createdAt": last.get("createdAt"),
                                          "orderId": last.get("orderId")}
        return result


class FakeResource:
    def __init__(self, tables):
        self.tables = tables

    def Table(self, name):
        return self.tables[name]


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


def order_row(**overrides):
    """A row as `finalization.accept_paid` writes it, with DynamoDB's own number type."""
    row = {
        "orderId": "WD-ORD-A1B2C3D4",
        "orderNumber": "WD-100042",
        "referenceId": "REF-ABCDEF",
        "customerId": SUBJECT,
        "createdAt": Decimal("1764700000"),
        "amountPaise": Decimal("121481"),
        "currency": "INR",
        "paymentStatus": "PAYMENT_PAID",
    }
    row.update(overrides)
    return row


def contact_row(**overrides):
    row = {
        "id": "contact-1",
        "phone": PHONE,
        "name": "Asha Sen",
        "firstName": "Asha",
        "lastName": "Sen",
        "email": "asha@example.com",
        "emailVerifiedAt": 1700000000,
        "checkoutCustomerId": SUBJECT,
        "checkoutDeliveryAddress": {
            "addressLine1": "12 MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "postalCode": "560001",
        },
        "deletedAt": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def ctx(monkeypatch):
    """`(handler_module, orders_table, contacts_table, rate_limit_calls)` with no AWS at all."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    spec = importlib.util.spec_from_file_location("customer_orders_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["customer_orders_under_test"] = module
    spec.loader.exec_module(module)

    orders = RecordingTable(ORDERS_TABLE)
    contacts = RecordingTable(CONTACTS_TABLE, sort_key=None)
    monkeypatch.setattr(module, "_dynamodb", FakeResource({
        ORDERS_TABLE: orders, CONTACTS_TABLE: contacts}))

    rate_calls = []
    monkeypatch.setattr(module.rate_limit, "check_rate_limit",
                        lambda *a, **k: rate_calls.append((a, k)) or True)
    monkeypatch.setattr(module.customer_auth, "_client", lambda: FakeCognito())
    yield module, orders, contacts, rate_calls
    sys.modules.pop("customer_orders_under_test", None)


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


def call(module, **kwargs):
    response = module.handler(event(**kwargs), None)
    return response, json.loads(response["body"])


# ── security: the boundary, asserted on the query ─────────────────────────────

def test_an_unauthenticated_request_is_401_and_reads_nothing(ctx):
    module, orders, contacts, rate_calls = ctx
    response, body = call(module, token="")
    assert response["statusCode"] == 401
    assert body["error"] == "VERIFICATION_REQUIRED"
    # Auth precedes everything that costs anything: no Query, and not even a rate-limit write.
    assert orders.queries == []
    assert contacts.queries == []
    assert rate_calls == []


def test_the_401_is_not_cacheable(ctx):
    """`cors_headers` sets no cache directive at all, so an unwrapped 401 would be a cacheable
    per-customer denial. `_no_store` covers the denial as well as the 200."""
    module, _, _, _ = ctx
    response, _ = call(module, token="")
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["Pragma"] == "no-cache"


def test_a_staff_pool_token_gets_a_byte_identical_401(ctx):
    """A staff token is VALID - `GetUser` succeeds - so only the issuer pin rejects it. The body
    must match the unauthenticated one exactly, or the response becomes an oracle for which pool
    a token came from."""
    module, orders, contacts, _ = ctx
    anonymous, _ = call(module, token="")
    staff, _ = call(module, issuer=STAFF_ISSUER)
    assert staff["statusCode"] == anonymous["statusCode"] == 401
    assert staff["body"] == anonymous["body"]
    assert orders.queries == []
    assert contacts.queries == []


def test_the_query_is_scoped_by_the_index_and_the_authenticated_subject(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    response, _ = call(module, body={})
    assert response["statusCode"] == 200
    assert len(orders.queries) == 1
    kwargs = orders.queries[0]
    assert kwargs["IndexName"] == ORDERS_INDEX
    assert _key_condition(kwargs) == ("customerId", SUBJECT)
    assert kwargs["ScanIndexForward"] is False
    assert kwargs["Limit"] == 20


def test_the_query_carries_no_row_level_filter(ctx):
    """A filter naming `customerId` would not be harmless redundancy. It runs AFTER DynamoDB has
    read and charged for the other customer's item, so its bytes have already reached this
    process's memory - and it would signal that the key condition is not trusted."""
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    call(module, body={})
    assert "FilterExpression" not in orders.queries[0]
    assert "ConditionExpression" not in orders.queries[0]


def test_a_customer_id_planted_in_the_body_is_refused_and_changes_no_query(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    response, body = call(module, body={"customerId": OTHER_SUBJECT})
    assert response["statusCode"] == 400
    assert body["error"] == "UNEXPECTED_FIELD"
    assert orders.queries == []


def test_a_tampered_cursor_still_queries_the_callers_own_partition(ctx):
    """The one place a round-tripped value could become an authorisation input. The partition
    component is overwritten from the proven identity, so the worst a forged cursor can do is name
    a position inside the caller's own partition - which is why it needs no signature."""
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    forged = base64.urlsafe_b64encode(json.dumps({
        "orderId": "WD-ORD-SOMEONEELSE",
        "createdAt": 1764700000,
        "customerId": OTHER_SUBJECT,          # ignored by construction
    }).encode("utf-8")).decode("ascii").rstrip("=")

    response, _ = call(module, body={"cursor": forged})
    assert response["statusCode"] == 200
    kwargs = orders.queries[0]
    assert _key_condition(kwargs) == ("customerId", SUBJECT)
    assert kwargs["ExclusiveStartKey"]["customerId"] == SUBJECT
    assert kwargs["ExclusiveStartKey"]["orderId"] == "WD-ORD-SOMEONEELSE"


def test_two_customers_orders_in_one_table_and_the_proof_is_the_query(ctx):
    """THE CROSS-CUSTOMER ISOLATION CASE.

    The returned list would look identical if the scoping lived in a row-level filter, so the
    assertion is on the QUERY: one key condition on the authenticated subject, no filter. The
    output check below is the corroboration, not the proof.
    """
    module, orders, _, _ = ctx
    orders.items = [
        order_row(orderId="mine-1", orderNumber="WD-1", createdAt=Decimal("100")),
        order_row(orderId="theirs-1", orderNumber="WD-2", customerId=OTHER_SUBJECT,
                  createdAt=Decimal("200")),
        order_row(orderId="mine-2", orderNumber="WD-3", createdAt=Decimal("300")),
    ]
    response, body = call(module, body={})
    assert response["statusCode"] == 200

    kwargs = orders.queries[0]
    assert _key_condition(kwargs) == ("customerId", SUBJECT)
    assert "FilterExpression" not in kwargs

    assert [row["orderNumber"] for row in body["orders"]] == ["WD-3", "WD-1"]   # newest first


def test_the_handler_does_not_reach_for_the_staff_pool_guard():
    """`middleware.require_auth` is hardcoded to the staff pool and falls through to `Viewer` for
    a customer token, so importing it here would silently grant staff-intended access."""
    source = HANDLER_PATH.read_text(encoding="utf-8")
    assert "middleware" not in source
    assert "require_auth" not in source
    # And it calls the customer guard with the exact text scripts/audit_route_auth.py matches on.
    assert "customer_auth.require_customer(" in source


# ── method, body and cursor validation ────────────────────────────────────────

def test_the_preflight_is_answered_and_is_not_cacheable(ctx):
    module, orders, _, _ = ctx
    response = module.handler(event(method="OPTIONS", token=""), None)
    assert response["statusCode"] == 200
    assert response["headers"]["Cache-Control"] == "no-store"
    assert orders.queries == []


def test_a_get_is_refused(ctx):
    module, _, _, _ = ctx
    response, body = call(module, method="GET")
    assert response["statusCode"] == 405
    assert body["error"] == "METHOD_NOT_ALLOWED"
    assert response["headers"]["Cache-Control"] == "no-store"


def test_a_body_that_is_not_an_object_is_refused(ctx):
    module, orders, _, _ = ctx
    request = event()
    request["body"] = "[1, 2, 3]"
    response = module.handler(request, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "INVALID_BODY"
    assert orders.queries == []


def test_an_absent_body_is_the_first_page(ctx):
    module, orders, contacts, _ = ctx
    orders.items = [order_row()]
    contacts.items = [contact_row()]
    response, body = call(module)
    assert response["statusCode"] == 200
    assert len(body["orders"]) == 1
    assert body["profile"]["email"] == "asha@example.com"


@pytest.mark.parametrize("cursor", ["", "not-base64url-json", "e30",
                                    base64.urlsafe_b64encode(b'{"orderId": ""}').decode(),
                                    "A" * 600])
def test_a_malformed_cursor_is_a_400_rather_than_a_silent_page_one(ctx, cursor):
    """A client that believes it is paginating while actually re-reading page one will loop."""
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    response, body = call(module, body={"cursor": cursor})
    assert response["statusCode"] == 400
    assert body["error"] == "INVALID_CURSOR"
    assert orders.queries == []


def test_the_cursor_round_trips_and_carries_no_customer_id(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row(orderId=f"o-{n}", orderNumber=f"WD-{n}",
                              createdAt=Decimal(str(1000 + n))) for n in range(3)]
    first_response, first = call(module, body={"limit": 2})
    assert first_response["statusCode"] == 200
    assert len(first["orders"]) == 2
    decoded = json.loads(base64.urlsafe_b64decode(
        first["cursor"] + "=" * (-len(first["cursor"]) % 4)))
    assert set(decoded) == {"orderId", "createdAt"}
    assert "customerId" not in decoded

    _, second = call(module, body={"cursor": first["cursor"]})
    assert [row["orderNumber"] for row in second["orders"]] == ["WD-0"]


def test_the_last_page_carries_no_cursor(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    _, body = call(module, body={})
    assert "cursor" not in body


# ── limits ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("requested,expected", [(0, 20), ("abc", 20), (500, 50),
                                                (None, 20), (7, 7), (-3, 20)])
def test_the_limit_is_clamped_and_never_raises(ctx, requested, expected):
    """`int(params.get('limit','50'))` is a 500 waiting for `?limit=abc`, which is why the clamp
    is a shared helper. The maximum is 50 rather than the module's 100: a 100-order page is a
    payload nobody reads."""
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    response, _ = call(module, body={"limit": requested})
    assert response["statusCode"] == 200
    assert orders.queries[0]["Limit"] == expected


# ── status, through the vocabulary ────────────────────────────────────────────

def test_the_word_an_order_row_actually_holds_reads_as_a_capture(ctx):
    """`finalization.accept_paid` writes the attempt vocabulary's paid spelling onto every order,
    and before the alias `canonical()` answered '' and rank 0 for a confirmed capture."""
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    _, body = call(module, body={})
    assert body["orders"][0]["status"] == "captured"
    assert body["orders"][0]["statusRank"] == 50


@pytest.mark.parametrize("stored", ["PAYMENT_CANCELLED", "PAYMENT_EXPIRED", "on hold", "", None])
def test_an_unmappable_status_degrades_honestly(ctx, stored):
    """Distinguishable from "not paid": the page says "status unavailable". This is a LIVE path -
    `core/service-api` copies a staff-supplied word onto an order row from an allowlist - so it is
    the handler's normal behaviour for a staff-touched row."""
    module, orders, _, _ = ctx
    orders.items = [order_row(paymentStatus=stored)]
    _, body = call(module, body={})
    assert body["orders"][0]["status"] == ""
    assert body["orders"][0]["statusRank"] == 0


def test_a_whatsapp_order_says_so_on_the_wire(ctx):
    """The order-source tag `/orders` renders. `channel` is ATTRIBUTION - it says where the order
    was placed - and it is a separate field from `checkoutMode`, which says how it settled."""
    module, orders, _, _ = ctx
    orders.items = [order_row(channel="whatsapp")]
    _, body = call(module, body={})
    assert body["orders"][0]["channel"] == "whatsapp"


def test_an_order_row_with_no_channel_reads_as_the_website(ctx):
    """Every row written before the channel landed, and every row the SERVING index's projection
    does not carry it on - the repoint to `customerId-createdAt-v2-index` is a separate step. Both
    are honestly `website`: no WhatsApp order can exist, because the hand-off that would create
    one is gated off."""
    module, orders, _, _ = ctx
    assert "channel" not in order_row()
    orders.items = [order_row()]
    _, body = call(module, body={})
    assert body["orders"][0]["channel"] == "website"


@pytest.mark.parametrize("stored,expected", [
    ("WhatsApp", "whatsapp"), ("whatsapp ", "whatsapp"), ("WHATSAPP", "whatsapp"),
    ("", "website"), (None, "website"), ("telegram", "website"), (Decimal("1"), "website"),
    ({"channel": "whatsapp"}, "website"),
])
def test_the_channel_is_canonical_on_the_wire_whatever_the_row_holds(ctx, stored, expected):
    """One spelling reaches the browser whatever was stored, and nothing in this list raises -
    `_project`'s degrade-never-raise contract covers this field like every other one."""
    module, orders, _, _ = ctx
    orders.items = [order_row(channel=stored)]
    _, body = call(module, body={})
    assert body["orders"][0]["channel"] == expected


def test_the_handler_compares_no_channel_word_raw(ctx):
    """For the same reason it compares no payment word: a second reading of a vocabulary is a
    second answer waiting to disagree with the first."""
    source = HANDLER_PATH.read_text(encoding="utf-8")
    for spelling in ('== "whatsapp"', "== 'whatsapp'", '== "website"', "== 'website'"):
        assert spelling not in source
    assert "order_channel.canonical(" in source


def test_the_handler_compares_no_payment_word_at_all(ctx):
    """It reports; the sentence is chosen in the browser. A comparison here would be a sixth
    place the vocabulary lives."""
    source = HANDLER_PATH.read_text(encoding="utf-8")
    for spelling in ('== "captured"', "== 'captured'", '== "paid"', "== 'paid'"):
        assert spelling not in source


# ── money: integer paise, currency compared explicitly ───────────────────────

def test_a_decimal_amount_arrives_as_an_integer_not_a_string(ctx):
    """`cors_response` serialises with `json.dumps(body, default=str)`, so a Decimal would reach
    the browser as the STRING "121481" while an int arrives as the number."""
    module, orders, _, _ = ctx
    orders.items = [order_row(amountPaise=Decimal("121481"))]
    _, body = call(module, body={})
    assert body["orders"][0]["amountPaise"] == 121481
    assert isinstance(body["orders"][0]["amountPaise"], int)
    assert '"121481"' not in json.dumps(body)


def test_a_non_integral_amount_fails_closed_rather_than_truncating(ctx):
    """`payment_status.paise` coerces with `int()`, so `paise(Decimal('1.5'))` returns 1
    SILENTLY. A number smaller than the customer paid is the failure the money rule exists to
    stop, which is why the integrality guard is not redundant."""
    module, orders, _, _ = ctx
    orders.items = [order_row(amountPaise=Decimal("1.5"))]
    _, body = call(module, body={})
    assert body["orders"][0]["amountPaise"] is None
    assert body["orders"][0]["currencyUnexpected"] is False


@pytest.mark.parametrize("raw", ["121481", "  42  ", None, True, -1, 12.9])
def test_an_amount_that_is_not_trusted_integer_paise_is_null(ctx, raw):
    """The `(int, Decimal)` allowlist excludes `float` BY CONSTRUCTION, so no separate float arm
    exists to go stale. A string that happens to parse is still not a trusted amount, and `bool`
    is an `int` subclass so it passes the allowlist and is caught by `paise`."""
    module, orders, _, _ = ctx
    orders.items = [order_row(amountPaise=raw)]
    _, body = call(module, body={})
    assert body["orders"][0]["amountPaise"] is None


def test_a_foreign_currency_yields_no_amount_and_says_so(ctx):
    """Compared to the literal INR, never inferred from the magnitude of the amount, so foreign
    minor units are never rendered behind a rupee sign."""
    module, orders, _, _ = ctx
    orders.items = [order_row(currency="USD", amountPaise=Decimal("5000"))]
    _, body = call(module, body={})
    row = body["orders"][0]
    assert row["amountPaise"] is None
    assert row["currency"] == "USD"
    assert row["currencyUnexpected"] is True


def test_currency_unexpected_is_always_present_and_type_stable(ctx):
    """Emitted ALWAYS, defaulting to false, so a browser reading `row.currencyUnexpected === true`
    never has to handle `undefined` as a third state."""
    module, orders, _, _ = ctx
    orders.items = [order_row(), order_row(orderId="o2", currency="USD")]
    _, body = call(module, body={})
    for row in body["orders"]:
        assert "currencyUnexpected" in row
        assert isinstance(row["currencyUnexpected"], bool)


def test_no_rupee_value_is_put_on_the_wire(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row()]
    _, body = call(module, body={})
    row = body["orders"][0]
    assert "amount" not in row
    assert "amountInRupees" not in row
    assert "rupees" not in json.dumps(row).lower()


# ── per-row degradation: a bad ROW degrades, a bad TABLE refuses ─────────────

def test_an_uncoercible_date_is_null_and_keeps_the_rest_of_the_row(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row(createdAt="not-a-number")]
    _, body = call(module, body={})
    assert body["orders"][0]["createdAt"] is None
    assert body["orders"][0]["orderNumber"] == "WD-100042"


def test_a_missing_order_number_leaves_the_reference_id_as_the_identifier(ctx):
    module, orders, _, _ = ctx
    orders.items = [order_row(orderNumber="")]
    _, body = call(module, body={})
    assert body["orders"][0]["orderNumber"] == ""
    assert body["orders"][0]["referenceId"] == "REF-ABCDEF"


def test_one_unreadable_row_does_not_blank_the_history(ctx):
    module, orders, _, _ = ctx
    orders.items = [
        order_row(orderId="good", orderNumber="WD-GOOD", createdAt=Decimal("200")),
        order_row(orderId="bad", orderNumber="WD-BAD", createdAt=Decimal("100"),
                  amountPaise="junk", paymentStatus="who knows"),
    ]
    _, body = call(module, body={})
    assert [row["orderNumber"] for row in body["orders"]] == ["WD-GOOD", "WD-BAD"]
    assert body["orders"][0]["amountPaise"] == 121481
    assert body["orders"][1]["amountPaise"] is None
    assert body["orders"][1]["status"] == ""


def test_the_snapshot_is_never_on_the_wire(ctx):
    """Unreachable twice over - the index projection does not carry it and the role grants no
    GetItem - but asserted so a later projection change does not quietly surface it."""
    module, orders, _, _ = ctx
    orders.items = [order_row(purchasedSnapshot={"cart": {"secret": "x"}},
                              snapshotHash="deadbeef",
                              providerPaymentId="pay_123",
                              paymentAttemptId="att_123")]
    _, body = call(module, body={})
    rendered = json.dumps(body)
    for leaked in ("purchasedSnapshot", "snapshotHash", "providerPaymentId",
                   "paymentAttemptId", "finalizationStage", "customerId"):
        assert leaked not in rendered


def test_an_empty_history_is_a_200_and_not_a_404(ctx):
    """Nothing is missing; the answer is "none"."""
    module, orders, contacts, _ = ctx
    contacts.items = [contact_row()]
    response, body = call(module, body={})
    assert response["statusCode"] == 200
    assert body["orders"] == []
    assert body["profile"]["name"] == "Asha Sen"


def test_a_failed_query_is_a_503_because_there_is_no_partial_answer(ctx):
    module, orders, contacts, _ = ctx
    orders.error = RuntimeError("ResourceNotFoundException")
    response, body = call(module, body={})
    assert response["statusCode"] == 503
    assert body["error"] == "ORDERS_UNAVAILABLE"
    assert response["headers"]["Cache-Control"] == "no-store"
    # The profile is never consulted: a 503 has no body to decorate.
    assert contacts.queries == []


def test_the_rate_limit_is_keyed_on_the_proven_subject(ctx):
    module, orders, _, rate_calls = ctx
    orders.items = [order_row()]
    call(module, body={})
    assert rate_calls[0][0][:3] == ("my-orders", SUBJECT, 10)


def test_being_over_the_rate_limit_refuses_before_any_read(ctx, monkeypatch):
    module, orders, contacts, _ = ctx
    monkeypatch.setattr(module.rate_limit, "check_rate_limit", lambda *a, **k: False)
    response, body = call(module, body={})
    assert response["statusCode"] == 429
    assert body["error"] == "TOO_MANY_REQUESTS"
    assert orders.queries == []
    assert contacts.queries == []


# ── the profile card ──────────────────────────────────────────────────────────

def test_the_profile_comes_off_the_row_this_session_owns(ctx):
    module, orders, contacts, _ = ctx
    contacts.items = [contact_row()]
    _, body = call(module, body={})
    profile = body["profile"]
    assert profile["name"] == "Asha Sen"
    assert profile["firstName"] == "Asha"
    assert profile["lastName"] == "Sen"
    assert profile["email"] == "asha@example.com"
    assert profile["emailVerified"] is True
    assert profile["phone"] == PHONE
    assert profile["addressComplete"] is True
    assert profile["address"]["fullAddress"]
    # Keyed on the NORMALISED phone, which is the string the row was written under.
    assert _key_condition(contacts.queries[0]) == ("phone", PHONE)
    assert contacts.queries[0]["IndexName"] == "phone-index"
    assert contacts.queries[0]["Limit"] == 5


def test_first_and_last_name_travel_separately(ctx):
    """They pre-fill two inputs. Splitting one `name` string in the browser is lossy and would
    rewrite a two-word surname on save, because `customer-profile` recomposes `name` from both."""
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(firstName="Asha", lastName="Sen Gupta",
                                  name="Asha Sen Gupta")]
    _, body = call(module, body={})
    assert body["profile"]["firstName"] == "Asha"
    assert body["profile"]["lastName"] == "Sen Gupta"


def test_a_crm_created_unowned_row_is_not_a_customer_profile(ctx):
    """A matching phone never authorizes an ownerless contact disclosure."""
    module, _, contacts, _ = ctx
    row = contact_row()
    row.pop("checkoutCustomerId")
    contacts.items = [row]
    _, body = call(module, body={})
    profile = body["profile"]
    assert profile is None


def test_an_empty_string_owner_counts_as_unowned(ctx):
    """A matching phone never authorizes an ownerless contact disclosure."""
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(checkoutCustomerId="   ")]
    _, body = call(module, body={})
    assert body["profile"] is None


def test_an_owned_row_wins_over_an_unowned_one_on_the_same_number(ctx):
    """Otherwise a session with its own row could adopt a stray unowned duplicate and render
    somebody else's name on the identity card."""
    module, _, contacts, _ = ctx
    stray = contact_row(id="stray", email="stray@example.com")
    stray.pop("checkoutCustomerId")
    contacts.items = [stray, contact_row(id="mine", email="mine@example.com")]
    _, body = call(module, body={})
    assert body["profile"]["email"] == "mine@example.com"


def test_a_soft_deleted_unowned_row_is_not_adopted(ctx):
    module, _, contacts, _ = ctx
    row = contact_row(deletedAt=1700000001)
    row.pop("checkoutCustomerId")
    contacts.items = [row]
    _, body = call(module, body={})
    assert body["profile"] is None


def test_a_row_owned_by_another_customer_is_not_the_profile(ctx):
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(checkoutCustomerId=OTHER_SUBJECT)]
    _, body = call(module, body={})
    assert body["profile"] is None


def test_adopting_an_unowned_row_does_not_open_a_cross_customer_read(ctx):
    """THE BOUNDARY, restated the way it would actually be breached: a row with ANOTHER owner
    must stay refused even when an unowned fallback exists on the same number, and the fallback
    must never be reached by relaxing the owner comparison itself."""
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(id="theirs", email="theirs@example.com",
                                  checkoutCustomerId=OTHER_SUBJECT)]
    _, body = call(module, body={})
    assert body["profile"] is None


def test_the_profile_never_writes_to_the_contacts_table():
    """Read-only adoption. This role holds `dynamodb:Query` on `phone-index` and nothing else, so
    a stamp from here would fail with AccessDenied at runtime where no test would see it - and
    `tests/test_customer_orders_iam.py` asserts that grant by equality, so widening the role to
    allow one would fail there instead. The claim is written by `auth/customer-profile`.
    """
    import ast

    tree = ast.parse(HANDLER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"_profile", "_unowned"}:
            rendered = ast.unparse(node)
            for writer in ("update_item", "put_item", "delete_item"):
                assert writer not in rendered, \
                    f"{node.name} calls {writer}; this role has no write grant on ContactsTable"


def test_a_soft_deleted_row_is_not_the_profile(ctx):
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(deletedAt=1700000001)]
    _, body = call(module, body={})
    assert body["profile"] is None


def test_an_owned_row_wins_over_a_deleted_duplicate_on_the_same_number(ctx):
    """`phone-index` is hash-only and two rows can share a number - a soft-deleted one and its
    replacement - which is why both existing copies of this predicate take `Limit=5` and scan."""
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(id="old", deletedAt=1, email="old@example.com"),
                      contact_row(id="new", email="new@example.com")]
    _, body = call(module, body={})
    assert body["profile"]["email"] == "new@example.com"


def test_an_unverified_email_is_reported_as_unverified(ctx):
    """The predicate here is deliberately WEAKER than checkout's - a customer with real order
    history and an unverified email must still see their own name and address - so the flag has to
    travel, or the identity card asserts an unverified email is verified."""
    module, _, contacts, _ = ctx
    row = contact_row()
    row.pop("emailVerifiedAt")
    contacts.items = [row]
    _, body = call(module, body={})
    assert body["profile"]["emailVerified"] is False
    assert body["profile"]["email"] == "asha@example.com"
    assert body["profile"]["name"] == "Asha Sen"
    assert body["profile"]["addressComplete"] is True


def test_an_unusable_stored_address_degrades_to_no_address_on_file(ctx):
    """`contact_address.from_contact` never raises, so an address written before a rule tightened
    is `null` rather than a 500 - and it is never a re-composition of the six address fields."""
    module, _, contacts, _ = ctx
    contacts.items = [contact_row(checkoutDeliveryAddress={"city": "Bengaluru"})]
    _, body = call(module, body={})
    assert body["profile"]["address"] is None
    assert body["profile"]["addressComplete"] is False
    assert body["profile"]["email"] == "asha@example.com"


def test_a_blank_session_phone_performs_no_contacts_query_at_all(ctx, monkeypatch):
    """`dynamo_reads.query_index` raises BEFORE `table.query` on a blank key, so saying so costs
    less than catching it - and the order list is unaffected either way."""
    module, orders, contacts, _ = ctx
    orders.items = [order_row()]
    monkeypatch.setattr(module.customer_auth, "_client",
                        lambda: FakeCognito(phone=""))
    response, body = call(module, body={})
    assert response["statusCode"] == 200
    assert len(body["orders"]) == 1
    assert body["profile"] is None
    assert contacts.queries == []


def test_an_unparseable_session_phone_falls_back_to_the_raw_value(ctx, monkeypatch):
    """`MissingCountryCode` subclasses `InvalidPhoneNumber`, so one arm covers both. It degrades
    rather than returning a 400, because here the phone only decides whether a card renders beside
    an order list that is already correct."""
    module, orders, contacts, _ = ctx
    orders.items = [order_row()]
    monkeypatch.setattr(module.customer_auth, "_client",
                        lambda: FakeCognito(phone="9330994400"))
    response, body = call(module, body={})
    assert response["statusCode"] == 200
    assert len(body["orders"]) == 1
    assert _key_condition(contacts.queries[0]) == ("phone", "9330994400")
    assert body["profile"] is None


def test_a_contacts_failure_still_returns_the_orders(ctx):
    """The WHOLE profile step is inside one `try`. A narrower one would let the order list - which
    was already correct - be lost to the catch-all 500."""
    module, orders, contacts, _ = ctx
    orders.items = [order_row()]
    contacts.error = RuntimeError("ProvisionedThroughputExceededException")
    response, body = call(module, body={})
    assert response["statusCode"] == 200
    assert len(body["orders"]) == 1
    assert body["profile"] is None


def test_a_cursored_request_omits_the_profile_entirely(ctx):
    """OMITTED, not null. `null` is a meaningful value here ("no contact row, or a degraded
    read"), so returning it on page two would let one transient contacts failure remove a card the
    customer is already looking at - and it would pay for a Query per page for a value the page
    discards."""
    module, orders, contacts, _ = ctx
    contacts.items = [contact_row()]
    orders.items = [order_row(orderId=f"o-{n}", orderNumber=f"WD-{n}",
                              createdAt=Decimal(str(1000 + n))) for n in range(3)]
    _, first = call(module, body={"limit": 2})
    assert first["profile"]["email"] == "asha@example.com"
    assert len(contacts.queries) == 1

    _, second = call(module, body={"cursor": first["cursor"]})
    assert "profile" not in second
    assert len(contacts.queries) == 1          # no second contacts read


# ── nothing here reads a credential ──────────────────────────────────────────

def test_the_module_reads_no_secret_in_any_spelling(ctx):
    source = HANDLER_PATH.read_text(encoding="utf-8").lower()
    for spelling in ("get_secret_value", "secretsmanager", "batch_get_secret",
                     "asm-exec", "resolve:secrets"):
        assert spelling not in source


def test_no_float_arithmetic_appears_on_the_money_path(ctx):
    source = HANDLER_PATH.read_text(encoding="utf-8")
    for operator in (" / ", " // ", "round(", "float("):
        assert operator not in source


def test_an_unexpected_failure_is_a_500_with_cors_headers(ctx, monkeypatch):
    """An unhandled exception escaping a handler reaches the browser as a network-class failure
    with no body and no CORS headers, which a client cannot read a message out of."""
    module, _, _, _ = ctx
    monkeypatch.setattr(module, "_body", lambda event: (_ for _ in ()).throw(
        RuntimeError("boom")))
    response, body = call(module, body={})
    assert response["statusCode"] == 500
    assert body["error"] == "INTERNAL_ERROR"
    assert response["headers"]["Access-Control-Allow-Origin"]
    assert response["headers"]["Cache-Control"] == "no-store"
