"""The Wix Coupons V2 adapter contract: the paths, the JSON types, and what is never read back.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/coupons-20261001.md` sections 1.1,
1.1.1, 1.1.2, 4.2 and 5.3.1, and the test list in section 7 (tests 22-41).

The three assertions worth reading twice
---------------------------------------
* **Test 25** serialises the outgoing body with the same `json.dumps` call `wix_ecom._request`
  makes, and asserts `type(parsed[...]) is int`. Wix's coupon money fields are JSON `number`,
  every documented example sends a bare integer, and `wix_ecom._request` has no custom encoder -
  so a `Decimal` would raise `TypeError` before the request left the process and a `Money.to_wix()`
  string would be the wrong type. Asserting the JSON type, not the Python type, is what pins it.
* **Tests 24a/24b** are MEDIUM-15. `json.loads` with no `parse_float` turns Wix's
  `"moneyOffAmount": 10` into `10.0` before any of our logic runs, and `wix_ecom.py` is read-only,
  so the fix cannot be at the parser. The rule is stated positively instead: nothing numeric is
  ever read.
* **Test 37c** is an AST ban on parsing a status out of an exception's prose. `Create Coupon`
  documents `errors: []` - no failure of any kind - and `wix_ecom._request` collapses every non-2xx
  into one message string. So branching on a parsed substring would make a money decision depend
  on an exception's wording, and prose alone would not stop someone writing it.
"""

from __future__ import annotations

import ast
import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeTable  # noqa: E402
from lambda_utils.ecommerce import coupon_store as cs  # noqa: E402
from lambda_utils.ecommerce import wix_coupons as wc  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
ADAPTER = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/wix_coupons.py"
HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"
SOURCE = ADAPTER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(ADAPTER))

NOW = 1_700_000_000
START_MS = 1_719_390_501_000


class Wix:
    """A spy request callable with the same signature `wix_ecom._request` has."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {"id": "wix-coupon-1"}
        self.error = error
        self.calls = []

    def __call__(self, endpoint, method="POST", body=None):
        self.calls.append((method.upper(), endpoint, copy.deepcopy(body)))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.response)


def clock(value: int = NOW):
    return lambda: value


def definition(**overrides):
    base = {
        "code": "SAVE10",
        "name": "Ten rupees off",
        "discountKind": cs.MONEY_OFF,
        "moneyOffPaise": 123400,
        "startTimeMs": START_MS,
        "minimumSubtotalPaise": 500000,
        "usageLimit": 10,
        "limitPerCustomer": 1,
    }
    base.update(overrides)
    return cs.validate_definition({k: v for k, v in base.items() if v is not None},
                                  clock=clock())


def get_fixture():
    return json.loads((FIXTURES / "wix_coupon_get_response.json").read_text())


# ── 22-24: the path, the wrapper and the id-only response ─────────────────────

def test_create_coupon_posts_to_the_documented_stores_v2_path():
    """`/stores/v2/coupons`, NOT `/ecom/`. The service's own server mapping."""
    wix = Wix()
    wc.WixCoupons(wix).create(definition())
    assert wix.calls[0][0] == "POST"
    assert wix.calls[0][1] == "/stores/v2/coupons"
    assert wc.BASE == "/stores/v2/coupons"
    assert "/ecom/" not in wc.BASE


def test_the_create_request_body_is_wrapped_in_specification():
    wix = Wix()
    wc.WixCoupons(wix).create(definition())
    body = wix.calls[0][2]
    assert set(body) == {"specification"}


def test_the_create_response_is_read_as_an_id_only():
    """`CreateCouponResponse` is documented as `{"id": "..."}` - not the created coupon - so
    relying on an echoed body would be relying on something Wix does not send."""
    wix = Wix(response={"id": "wix-coupon-1"})
    assert wc.WixCoupons(wix).create(definition()) == "wix-coupon-1"

    missing = Wix(response={})
    with pytest.raises(wc.WixCouponError):
        wc.WixCoupons(missing).create(definition())


def test_the_adapter_reads_only_id_active_type_and_code_from_a_wix_response():
    """24a, closing MEDIUM-15's first half.

    Walks the adapter's AST for every constant string key it subscripts or `.get()`s, and
    asserts each one is either a key it is allowed to read off a Wix response or one of OUR
    OWN stored attribute names. The discrimination is what makes the assertion meaningful:
    `moneyOffPaise` is ours, `moneyOffAmount` is Wix's, and they are different words.

    `code` is in the readable set for exactly one reason, recorded rather than assumed:
    `WIX_CODE_CONFLICT` is defined in terms of `specification.code` (section 5.3.1) and is
    otherwise undetectable. It is a string, so the no-numeric rule below is untouched.
    """
    read: set[str] = set()
    for node in ast.walk(TREE):
        # `Load` only. A `Store` subscript is the adapter WRITING a key into the outgoing body,
        # which is the opposite of reading one off a response.
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            read.add(node.slice.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            read.add(node.args[0].value)

    ours = set(cs.DEFINITION_ATTRIBUTES)
    unexplained = sorted(read - wc.READABLE_RESPONSE_KEYS - ours)
    assert not unexplained, f"the adapter reads keys that are neither ours nor readable: " \
                            f"{unexplained}"
    assert not read & wc.NUMERIC_RESPONSE_KEYS, \
        "the adapter reads a NUMERIC Wix field; json.loads has no parse_float here, so it " \
        "would arrive as a float"
    assert wc.READABLE_RESPONSE_KEYS == {"coupon", "id", "specification", "active", "type",
                                         "code"}


def test_a_wix_response_carrying_money_is_ignored_rather_than_stored():
    """24b, closing MEDIUM-15's second half. The fixture's `moneyOffAmount: 10` arrives as a
    float and must not reach our row."""
    response = get_fixture()
    assert isinstance(json.loads(json.dumps(response))["coupon"]["specification"]
                      ["moneyOffAmount"], (int, float))

    view = wc.WixCoupons(Wix(response=response)).get(
        "abeb638b-f9f4-4bb8-8fe7-2319504df6d9")
    assert set(view) == {"id", "active", "type", "code"}
    for value in view.values():
        assert not isinstance(value, float)

    store = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                      indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    cs.claim(store, definition())
    cs.mark_mirrored(store, "SAVE10", view["id"], clock=clock())
    row = store.rows["COUPON#SAVE10"]
    assert row["moneyOffPaise"] == 123400          # OUR number, unchanged
    assert "moneyOffAmount" not in row
    for value in row.values():
        assert not isinstance(value, float)


# ── 25-28: the JSON types at the boundary ─────────────────────────────────────

def _serialised(body):
    """The body as `wix_ecom._request` would serialise it: `json.dumps`, no custom encoder."""
    return json.loads(json.dumps(body or {}).decode("utf-8")
                      if isinstance(json.dumps(body or {}), bytes)
                      else json.dumps(body or {}))


@pytest.mark.parametrize("overrides,field,expected", [
    ({}, "moneyOffAmount", 1234),
    ({"discountKind": cs.PERCENT_OFF, "moneyOffPaise": None, "percentOffBps": 500},
     "percentOffRate", 5),
    ({"discountKind": cs.FIXED_PRICE, "moneyOffPaise": None, "fixedPricePaise": 50000},
     "fixedPriceAmount", 500),
    ({}, "minimumSubtotal", 5000),
])
def test_every_money_field_leaves_as_a_json_integer(overrides, field, expected):
    """Pins HIGH-5's resolution at the exact JSON type, through the real encoder."""
    wix = Wix()
    wc.WixCoupons(wix).create(definition(**overrides))
    parsed = _serialised(wix.calls[0][2])
    assert type(parsed["specification"][field]) is int
    assert parsed["specification"][field] == expected


def test_the_outgoing_body_survives_the_read_only_request_encoder():
    """`wix_ecom._request` does `json.dumps(body or {})` with no encoder, so a `Decimal`
    anywhere in the body raises `TypeError`. `wix_ecom.py` is read-only, so the body is what
    has to be right."""
    for overrides in ({},
                      {"discountKind": cs.PERCENT_OFF, "moneyOffPaise": None,
                       "percentOffBps": 2500},
                      {"discountKind": cs.FREE_SHIPPING, "moneyOffPaise": None},
                      {"discountKind": cs.BUY_X_GET_Y, "moneyOffPaise": None,
                       "buyX": 2, "buyY": 1}):
        body = {"specification": wc.specification(definition(**overrides))}
        json.dumps(body)  # must not raise


def test_no_float_is_ever_constructed_on_the_wix_conversion_path(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("a float was constructed on the Wix conversion path")

    builtins = wc.__builtins__
    monkeypatch.setitem(builtins if isinstance(builtins, dict) else builtins.__dict__,
                        "float", explode)
    wix = Wix()
    wc.WixCoupons(wix).create(definition())
    assert wix.calls[0][2]["specification"]["moneyOffAmount"] == 1234


def test_paise_convert_by_integer_division_only():
    """`123400 -> 1234`. `123450` never reaches conversion because validation refused it."""
    assert wc.specification(definition())["moneyOffAmount"] == 1234
    with pytest.raises(cs.CouponValidationError) as refusal:
        definition(moneyOffPaise=123450)
    assert refusal.value.code == "SUB_RUPEE_DISCOUNT_NOT_SUPPORTED"

    # And the adapter refuses it too, so the guarantee does not rest on one layer.
    row = dict(definition())
    row["moneyOffPaise"] = 123450
    with pytest.raises(wc.WixCouponError):
        wc.specification(row)


def test_times_are_sent_as_epoch_millisecond_strings():
    """The one place a string IS documented: `startTime` is `format: int64` with
    `minimum: 1000000000000`, and every documented example quotes it."""
    body = wc.specification(definition(expirationTimeMs=START_MS + 86_400_000))
    assert body["startTime"] == str(START_MS)
    assert type(body["startTime"]) is str
    assert body["expirationTime"] == str(START_MS + 86_400_000)


# ── 30-31: the scope and the read-only type ───────────────────────────────────

def test_a_scope_group_requires_an_entity_id():
    with pytest.raises(cs.CouponValidationError):
        definition(scopeNamespace="stores", scopeGroupName="product", scopeEntityId=None)

    scoped = wc.specification(definition(
        scopeNamespace="stores", scopeGroupName="collection",
        scopeEntityId="11111111-1111-4111-8111-111111111111"))
    assert scoped["scope"] == {"namespace": "stores", "group": {
        "name": "collection", "entityId": "11111111-1111-4111-8111-111111111111"}}


def test_the_read_only_type_field_is_never_sent():
    """The schema marks `type` read-only and derives it from whichever discount field was set."""
    for overrides in ({}, {"discountKind": cs.FREE_SHIPPING, "moneyOffPaise": None},
                      {"discountKind": cs.PERCENT_OFF, "moneyOffPaise": None,
                       "percentOffBps": 500}):
        assert "type" not in wc.specification(definition(**overrides))


# ── 34-36: deactivate and get ─────────────────────────────────────────────────

def test_deactivate_sends_only_specification_active_false():
    """Closes HIGH-6 for Update. PATCH is documented as patch semantics, so the NARROW body is
    the safe one: a full re-send would re-assert fields whose Wix-side values we may not be the
    last writer of."""
    wix = Wix(response={})
    wc.WixCoupons(wix).deactivate("wix-coupon-1")
    method, endpoint, body = wix.calls[0]
    assert body == {"specification": {"active": False}}
    assert "fieldMask" not in body
    assert set(body["specification"]) == {"active"}


def test_deactivate_uses_patch_on_the_coupon_id_path():
    wix = Wix(response={})
    wc.WixCoupons(wix).deactivate("wix-coupon-1")
    assert wix.calls[0][0] == "PATCH"
    assert wix.calls[0][1] == "/stores/v2/coupons/wix-coupon-1"


def test_get_coupon_is_a_get_by_id_with_no_body():
    """Closes HIGH-6 for Get. One path parameter, no request body."""
    wix = Wix(response=get_fixture())
    wc.WixCoupons(wix).get("abeb638b-f9f4-4bb8-8fe7-2319504df6d9")
    method, endpoint, body = wix.calls[0]
    assert method == "GET"
    assert endpoint == "/stores/v2/coupons/abeb638b-f9f4-4bb8-8fe7-2319504df6d9"
    assert body is None


def test_deactivate_never_calls_delete_a_coupon():
    """`DELETE /stores/v2/coupons/{id}` exists and is deliberately not wired. The guarantee is
    that the code is ABSENT, which a test can enumerate, not that it is guarded."""
    methods = {node.value for node in ast.walk(TREE)
               if isinstance(node, ast.Constant) and isinstance(node.value, str)
               and node.value in ("GET", "POST", "PATCH", "PUT", "DELETE")}
    assert methods == {"GET", "POST", "PATCH"}
    assert not [node for node in ast.walk(TREE)
                if isinstance(node, ast.FunctionDef) and "delete" in node.name.lower()]


# ── 37-37c: failure handling ──────────────────────────────────────────────────

def test_a_wix_failure_leaves_the_coupon_pending_and_not_applicable():
    """Fail-closed. A coupon Wix does not know about would be accepted by us and refused by
    `Add Coupon`, and the customer would watch a discount appear and then vanish."""
    store = FakeTable(key_attr=cs.KEY_ATTRIBUTE,
                      indexes={cs.STATUS_INDEX: (cs.STATUS_ATTRIBUTE, "createdAt")})
    row = cs.create(store, {"code": "SAVE10", "name": "Ten off",
                            "discountKind": cs.MONEY_OFF, "moneyOffPaise": 100000,
                            "startTimeMs": START_MS, "minimumSubtotalPaise": 500000},
                    clock=clock())
    assert row["wixMirrorState"] == cs.MIRROR_PENDING

    wix = Wix(error=RuntimeError("Wix eCom POST /stores/v2/coupons returned HTTP 500"))
    with pytest.raises(RuntimeError):
        wc.WixCoupons(wix).create(row)
    assert store.rows["COUPON#SAVE10"]["wixMirrorState"] == cs.MIRROR_PENDING
    assert cs.evaluate(store.rows["COUPON#SAVE10"],
                       clock=clock(START_MS // 1000 + 10)) == cs.WIX_MIRROR_INCOMPLETE


@pytest.mark.parametrize("status", [400, 403, 409, 428, 500, 502])
def test_a_create_failure_of_any_status_leaves_the_row_pending_not_conflicted(status):
    """MEDIUM-9's first branch. `Create Coupon` declares `errors: []`, so NO status may be
    special-cased, and a duplicate code is indistinguishable from a network timeout."""
    wix = Wix(error=RuntimeError(
        f"Wix eCom POST /stores/v2/coupons returned HTTP {status}"))
    with pytest.raises(RuntimeError) as raised:
        wc.WixCoupons(wix).create(definition())
    assert not isinstance(raised.value, wc.WixCouponConflict)


def test_a_get_coupon_probe_finding_a_foreign_code_raises_wix_code_conflict():
    """MEDIUM-9's second branch, and the ONLY path to that state.

    Reachable only from a coupon created in the Wix dashboard outside this system, because our
    own conditional put on `COUPON#<codeUpper>` has already refused every duplicate we could
    have created.
    """
    foreign = get_fixture()
    foreign["coupon"]["specification"]["code"] = "SOMEONEELSES"
    with pytest.raises(wc.WixCouponConflict) as conflict:
        wc.WixCoupons(Wix(response=foreign)).assert_mirrors(
            wix_coupon_id="abeb638b-f9f4-4bb8-8fe7-2319504df6d9", code="SAVE10")
    assert conflict.value.code == "WIX_CODE_CONFLICT"

    # Our own code, case-insensitively, is NOT a conflict: Wix does not document its code
    # uniqueness as case-sensitive and a case-only difference is not a different coupon.
    ours = get_fixture()
    ours["coupon"]["specification"]["code"] = "save10"
    assert wc.WixCoupons(Wix(response=ours)).assert_mirrors(
        wix_coupon_id="abeb638b-f9f4-4bb8-8fe7-2319504df6d9", code="SAVE10")["active"] is True


def test_no_branch_parses_a_status_out_of_an_exception_message():
    """37c. The shortcut MEDIUM-9 exists to forbid, banned on the AST in the adapter AND the
    handler, because prose alone would not stop someone writing it."""
    offenders = []
    for path in (ADAPTER, HANDLER):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "str" and node.args:
                argument = ast.unparse(node.args[0])
                if "exc" in argument or "error" in argument:
                    offenders.append(f"{path.name}:{node.lineno} str() of an exception")
            if isinstance(node, ast.Attribute) and node.attr == "args" \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id in ("exc", "error", "exception"):
                offenders.append(f"{path.name}:{node.lineno} reads exception .args")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docstrings and "HTTP " in node.value:
                offenders.append(f"{path.name}:{node.lineno} carries an 'HTTP ' literal")
    assert not offenders, "\n  ".join(offenders)


def _docstring_ids(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = (node.body or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def test_a_pending_mirror_is_refused_by_validate():
    """38. Fail-closed, asserted from the verdict side."""
    row = dict(definition())
    row["wixMirrorState"] = cs.MIRROR_PENDING
    assert cs.evaluate(row, clock=clock(START_MS // 1000 + 10)) == cs.WIX_MIRROR_INCOMPLETE
    row["wixMirrorState"] = cs.MIRROR_DONE
    assert cs.evaluate(row, clock=clock(START_MS // 1000 + 10)) == cs.ELIGIBLE


def test_no_wix_error_body_is_logged_or_surfaced():
    """39. `wix_ecom._request` already reduces an `HTTPError` to a status-only message, and that
    behaviour is relied on rather than reimplemented - so the adapter must not log at all."""
    assert "logger" not in SOURCE
    assert "logging" not in SOURCE
    assert "print(" not in SOURCE

    handler_source = HANDLER.read_text(encoding="utf-8")
    tree = ast.parse(handler_source, filename=str(HANDLER))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        rendered = ast.unparse(node)
        # The only thing an exception may contribute to a log line is its TYPE NAME. The
        # message can carry a status, and a status in a log is one grep away from a branch.
        assert "str(exc" not in rendered
        assert ".args" not in rendered
        if "exc" in rendered:
            assert "type(exc).__name__" in rendered, \
                f"line {node.lineno} logs an exception other than by type name"


def test_the_adapter_holds_no_boto3_client_and_reads_no_secret():
    """41. An injected request callable only, exactly like `cart_v2`."""
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    for forbidden in ("boto3", "botocore", "urllib", "os"):
        assert not any(name == forbidden or name.startswith(forbidden + ".")
                       for name in imported), f"wix_coupons imports {forbidden}"
    for marker in ("get_secret_value", "SecretId", "secretsmanager", "Authorization",
                   "api_key", "apiKey"):
        assert marker not in SOURCE, f"wix_coupons mentions {marker}"

    # The request callable really is injected: the constructor takes it and stores it.
    adapter = wc.WixCoupons(Wix())
    assert callable(adapter.request)


# ── the no-parallel-system proof ──────────────────────────────────────────────

#: Which `specification` field each priced kind emits. Declared here and asserted against
#: `coupon_store.KIND_AMOUNT_ATTRIBUTE` below, so this map cannot silently fall behind the kinds.
_SPECIFICATION_FIELD = {
    cs.MONEY_OFF: "moneyOffAmount",
    cs.PERCENT_OFF: "percentOffRate",
    cs.FIXED_PRICE: "fixedPriceAmount",
}

#: Two values per kind, both legal at issuance (whole rupees, whole percent), so moving one
#: stored attribute is observable on BOTH sides without tripping a validation rule.
_BASE_VALUE = {cs.MONEY_OFF: 123400, cs.PERCENT_OFF: 500, cs.FIXED_PRICE: 50000}
_MOVED_VALUE = {cs.MONEY_OFF: 246800, cs.PERCENT_OFF: 1000, cs.FIXED_PRICE: 100000}

#: Comfortably above the fixture's `minimumSubtotalPaise`, so the floor is never the reason a
#: probe refuses.
_COLLECTION_PAISE = 1_000_000


def _priced_row(kind, value):
    """A validated definition row of `kind` carrying exactly its own amount attribute."""
    return definition(**{"discountKind": kind, "moneyOffPaise": None, "percentOffBps": None,
                         "fixedPricePaise": None, cs.KIND_AMOUNT_ATTRIBUTE[kind]: value})


def test_the_discount_amount_and_the_wix_specification_read_the_same_attributes():
    """One coupon definition, two renderings - not two discount engines.

    This is the assertion behind the whole "one coupon system" claim, and it is written as a
    property rather than as a list of expected numbers. Two things are pinned:

    * the set of kinds `coupon_store.discount_paise` will price is EXACTLY
      `coupon_store.KIND_AMOUNT_ATTRIBUTE` - the same three kinds that have a stored magnitude
      for `specification` to send. A fourth kind gaining an amount function, or losing one, fails
      here rather than drifting into production;
    * for each of those kinds, moving the ONE stored attribute named by
      `KIND_AMOUNT_ATTRIBUTE` moves both the Wix-bound field and our computed discount, and
      REMOVING it makes both refuse. Two readers of one attribute cannot disagree about what the
      coupon was; two readers of two attributes eventually do, and the customer sees one number
      in the cart and a different one on the invoice.
    """
    assert set(_SPECIFICATION_FIELD) == set(cs.KIND_AMOUNT_ATTRIBUTE)

    # Every amount attribute is populated on the probe, so the only thing selecting which one is
    # read is `discountKind` itself.
    probe = {"moneyOffPaise": 123400, "percentOffBps": 500, "fixedPricePaise": 50000,
             "buyX": 2, "buyY": 1}
    priced = set()
    for kind in cs.DISCOUNT_KINDS:
        try:
            amount = cs.discount_paise({**probe, "discountKind": kind},
                                       collection_paise=_COLLECTION_PAISE)
        except cs.CouponValidationError as refusal:
            assert refusal.code == "COUPON_KIND_UNSUPPORTED", kind
            continue
        assert type(amount) is int
        priced.add(kind)
    assert priced == set(cs.KIND_AMOUNT_ATTRIBUTE)

    for kind in sorted(priced):
        attribute = cs.KIND_AMOUNT_ATTRIBUTE[kind]
        field = _SPECIFICATION_FIELD[kind]
        base, moved = _priced_row(kind, _BASE_VALUE[kind]), _priced_row(kind, _MOVED_VALUE[kind])

        assert wc.specification(base)[field] != wc.specification(moved)[field], kind
        assert (cs.discount_paise(base, collection_paise=_COLLECTION_PAISE)
                != cs.discount_paise(moved, collection_paise=_COLLECTION_PAISE)), kind

        stripped = {key: value for key, value in base.items() if key != attribute}
        with pytest.raises(wc.WixCouponError):
            wc.specification(stripped)
        with pytest.raises(cs.CouponValidationError):
            cs.discount_paise(stripped, collection_paise=_COLLECTION_PAISE)
