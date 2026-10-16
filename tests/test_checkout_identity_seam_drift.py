"""The checkout-identity seam: the server's reply and the page's parser must be one shape.

Why this gate exists
--------------------
Phase 1 landed as four features that never share a file. Three of them agree on a contract by
restating it:

* ``ecommerce/checkout``'s ``action:"profile"`` reply (FEAT-002) is what ``src/components/cart/CartPage.tsx``
  parses as ``ProfileReply`` and projects onto ``CheckoutProfileValue`` (FEAT-003/FEAT-004);
* ``auth/customer-profile``'s save reply (FEAT-001) is projected onto the SAME
  ``CheckoutProfileValue`` by ``CheckoutProfile.tsx``, so a returning customer and a
  just-saved one must be describable by one type;
* ``contact_address.normalize_for_storage``'s return (FEAT-001) is what
  ``AddressFields.StoredAddress`` (FEAT-003) declares.

Every one of those is a copy across a language boundary, and each failure mode is SILENT. A
renamed server key does not break a build: ``String( reply.contactId || '' )`` yields ``''``, and
the identity card renders an empty row. A refusal string that drifts by one character stops
matching ``if ( status === ... )`` and falls through to the honest-but-useless UNRECOGNISED arm,
so a customer who needs the address editor is told the checkout could not be confirmed.

The four features each verified their own half. This holds the halves equal to each other.

Parsing
-------
The Python side is read from the **AST**, not with a regex: the keys are wanted as a closed set,
and only a parse can say that a dict literal has exactly these keys and no others. The TypeScript
side is read by brace-matching one named declaration, which is narrower than the repo's usual
``re.findall(r"'([^']+)'", source)`` because these blocks declare field names rather than string
literals.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import contact_address  # noqa: E402

CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
CUSTOMER_PROFILE = ROOT / "amplify/functions/auth/customer-profile/handler.py"
CART = ROOT / "src/components/cart/CartPage.tsx"
PROFILE_COMPONENT = ROOT / "src/components/CheckoutProfile.tsx"
ADDRESS_FIELDS = ROOT / "src/components/AddressFields.tsx"

#: The three refusal strings the page branches on BY NAME. Byte-identical on both sides or the
#: arm is dead. Kept as a literal tuple rather than derived from either side, so a rename has to
#: be made here too and cannot be "agreed" by both sides drifting together.
REFUSALS = (
    "PROFILE_REQUIRED",
    "DELIVERY_DETAILS_REQUIRED",
    "DELIVERY_METHOD_UNAVAILABLE",
)

#: Plausible misspellings of the three. None may appear on either side: a near miss is the
#: failure this test exists to catch, and it is invisible to every other gate.
NEAR_MISSES = (
    "DELIVERY_ADDRESS_REQUIRED",
    "DELIVERY_DETAILS_MISSING",
    "DELIVERY_DETAILS_UNAVAILABLE",
    "DELIVERY_METHOD_REQUIRED",
    "DELIVERY_METHODS_UNAVAILABLE",
    "PROFILE_INCOMPLETE",
    "PROFILE_NOT_FOUND",
)


def _profile_ready_bodies(path: Path, function: str = "") -> list:
    """Every dict literal in `path` whose `status` is the constant `PROFILE_READY`, as key sets."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = [tree]
    if function:
        scopes = [node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == function]
        assert scopes, f"{path.name} no longer defines {function}()"
    found = []
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Dict):
                continue
            pairs = {key.value: value for key, value in zip(node.keys, node.values)
                     if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            status = pairs.get("status")
            if isinstance(status, ast.Constant) and status.value == "PROFILE_READY":
                found.append(set(pairs))
    return found


def _one_profile_ready_body(path: Path, function: str = "") -> set:
    bodies = _profile_ready_bodies(path, function)
    assert len(bodies) == 1, (
        f"{path.name} builds {len(bodies)} PROFILE_READY bodies; this seam assumes exactly one")
    return bodies[0]


def _emitted_codes(path: Path) -> set:
    """Every string a dict literal sends as `status` or `error` -- what the browser can receive.

    From the AST, so a code that survives only in a comment or a docblock does not count. That
    distinction is the whole point: a refusal arm can be deleted while every prose mention of it
    stays behind, and a text search would still find it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value in ("status", "error")
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                codes.add(value.value)
    return codes


def _ts_fields(path: Path, header: str) -> list:
    """The field names of one brace-delimited TS declaration, in source order."""
    source = path.read_text(encoding="utf-8")
    assert source.count(header) == 1, f"{path.name} does not declare exactly one `{header}`"
    start = source.index(header) + len(header)
    depth, end = 1, start
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return re.findall(r"^\s*(\w+)\??\s*:", source[start:end - 1], re.M)


# ── the readiness reply ─────────────────────────────────────────────────────────

def test_the_page_parses_exactly_the_keys_the_readiness_reply_sends():
    """Equality, not a subset, and in both directions for a reason.

    A server key the page does not declare is a field nothing can read. A declared key the
    server never sends is an arm that silently reads `undefined` -- which `profileFrom` turns
    into `''` rather than an error, so it renders as a blank row on the identity card.
    """
    assert set(_ts_fields(CART, "type ProfileReply = {")) == _one_profile_ready_body(
        CHECKOUT, "_profile_status")


def test_the_editor_value_asks_for_nothing_the_readiness_reply_lacks():
    """`profileFrom` projects the reply onto `CheckoutProfileValue`; every field must exist.

    A subset, not equality: `status` is the envelope and `emailVerified` is always true on this
    shape, so neither belongs on the value the editor hands back.
    """
    value = set(_ts_fields(PROFILE_COMPONENT, "export interface CheckoutProfileValue {"))
    assert value <= _one_profile_ready_body(CHECKOUT, "_profile_status")


def test_the_save_reply_describes_the_same_customer_as_the_readiness_reply():
    """One type, two producers.

    `CheckoutProfile.tsx` projects the SAVE reply onto `CheckoutProfileValue` and `cart.tsx`
    projects the READINESS reply onto the same type, so a field present on only one of them
    would make a just-saved customer and a returning customer different shapes.
    """
    saved = _one_profile_ready_body(CUSTOMER_PROFILE)
    read = _one_profile_ready_body(CHECKOUT, "_profile_status")
    value = set(_ts_fields(PROFILE_COMPONENT, "export interface CheckoutProfileValue {"))
    assert value <= saved
    assert saved <= read, f"the save reply promises {saved - read}, which the read side never sends"


# ── the stored address ──────────────────────────────────────────────────────────

def test_the_stored_address_type_is_the_wire_shape():
    declared = _ts_fields(ADDRESS_FIELDS, "export interface StoredAddress {")
    stored = contact_address.normalize_for_storage({
        "addressLine1": "12 MG Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postalCode": "560001",
    })
    assert set(declared) == set(stored)
    assert len(declared) == len(set(declared)) == 9


def test_every_stored_address_field_is_a_string_on_both_sides():
    """The India money rule, at the one place a float could enter DynamoDB.

    `normalize_for_storage` omits `latitude`/`longitude`/`googlePlaceId` structurally, so this
    asserts the consequence rather than the omission: nine strings, and a TS declaration that
    says so. A number arriving here would be stored as a DynamoDB `N` and read back as a
    `Decimal`, and the TS type would be a lie about it.
    """
    stored = contact_address.normalize_for_storage({
        "addressLine1": "12 MG Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postalCode": "560001",
    })
    assert all(isinstance(value, str) for value in stored.values()), stored
    source = ADDRESS_FIELDS.read_text(encoding="utf-8")
    start = source.index("export interface StoredAddress {")
    block = source[start:source.index("}", start)]
    assert re.findall(r":\s*(\w+);", block) == ["string"] * 9


def test_the_stored_address_type_is_declared_once_and_imported_everywhere_else():
    """One declaration, or the nine keys are a copy that can drift inside the frontend too."""
    declarations = [
        path for path in sorted((ROOT / "src").rglob("*.ts*"))
        if re.search(r"^\s*(export\s+)?(interface|type)\s+StoredAddress\b",
                     path.read_text(encoding="utf-8"), re.M)
    ]
    assert declarations == [ADDRESS_FIELDS]
    for path in sorted((ROOT / "src").rglob("*.ts*")):
        source = path.read_text(encoding="utf-8")
        if path == ADDRESS_FIELDS or "StoredAddress" not in source:
            continue
        assert re.search(r"import[^;]*StoredAddress[^;]*from\s*'[^']*AddressFields'",
                         source, re.S), f"{path.relative_to(ROOT)} names StoredAddress but imports it from nowhere"


# ── the refusal strings ─────────────────────────────────────────────────────────

def test_the_refusal_strings_are_byte_identical_on_both_sides():
    """The EMITTED value against the BRANCHED value, which is narrower than "both files say it".

    Neither half may be satisfied by a mention. On the server the code has to be the value of a
    `status` or `error` key in a real dict literal; on the page it has to appear as the
    comparison `status === '<CODE>'`. A declaration in the `Outcome` union, a docblock line or a
    test fixture proves nothing about whether the arm still exists.
    """
    emitted = _emitted_codes(CHECKOUT)
    page = CART.read_text(encoding="utf-8")
    for code in REFUSALS:
        assert code in emitted, f"{code} is not a code the handler sends"
        assert re.search(rf"status\s*===\s*'{code}'", page), \
            f"{code} is not a status the page branches on"


def test_no_near_miss_spelling_exists_on_either_side():
    both = CHECKOUT.read_text(encoding="utf-8") + CART.read_text(encoding="utf-8")
    for wrong in NEAR_MISSES:
        assert wrong not in both, f"{wrong} is a near miss for one of {REFUSALS}"


def test_the_method_only_refusal_stays_above_the_address_refusal():
    """`DeliveryMethodUnavailable` SUBCLASSES `DeliveryDetailsRequired`.

    Order decides which handler runs, so swapping the two `except` arms would collapse the
    distinction this phase added -- and it would still pass every shape test above.
    """
    tree = ast.parse(CHECKOUT.read_text(encoding="utf-8"))
    order = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        for code in ("DELIVERY_METHOD_UNAVAILABLE", "DELIVERY_DETAILS_REQUIRED"):
            if any(isinstance(inner, ast.Constant) and inner.value == code
                   for inner in ast.walk(node)):
                order.append((node.lineno, code))
    first = [code for _line, code in sorted(order)]
    assert first[:2] == ["DELIVERY_METHOD_UNAVAILABLE", "DELIVERY_DETAILS_REQUIRED"], first
