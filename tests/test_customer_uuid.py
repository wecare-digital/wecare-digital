"""The public customer id must be a uuid4, and must refuse the one format that leaks a clock.

WHY THE uuid7 CASE IS THE HEADLINE TEST
---------------------------------------
This repo already mints time-ordered identifiers, and `identifiers.py`'s own docstring says why
they must never be public: "the creation time is *visible* in the id". The customer uuid is
printed on a tax invoice the customer keeps and forwards, so a uuid7 in this attribute would
disclose, to anyone holding that document, the millisecond the customer's record was created.

`uuid.UUID(...)` parses a uuid7 without complaint, so a validator written as "does it parse"
would accept exactly the value that must not be accepted. Hence `is_customer_uuid` tests the
version field, and hence `identifiers.new_uuid7()` is run for real here rather than a
hand-written string being asserted against - a fixture could drift away from what the minter
actually produces, and then this test would stop testing anything.

THE SECOND PROPERTY: `from_contact` NEVER RAISES
------------------------------------------------
Its callers are a checkout preparing a payment and renderers that run after the money has moved.
So every bad input - `None`, a non-dict, a missing key, junk, a uuid7, a non-canonical spelling -
must become `''`, which renders no customer-id row. The same contract
`ecommerce.contact_address.from_contact` carries, for the same reason.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import identifiers  # noqa: E402
from lambda_utils.identity import customer_uuid  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# 1. what we mint
# ══════════════════════════════════════════════════════════════════════════════

def test_a_minted_value_satisfies_the_validator():
    """The round trip, which is the only property that keeps the two functions honest about
    each other. A minter whose output its own validator rejects would store nothing anywhere."""
    minted = customer_uuid.new_customer_uuid()
    assert customer_uuid.is_customer_uuid(minted)


def test_what_we_mint_is_version_four():
    assert uuid.UUID(customer_uuid.new_customer_uuid()).version == customer_uuid.VERSION == 4


def test_two_mints_differ():
    """Not a statistical claim - a guard against a constant or a cached value being returned,
    which would make every customer share one id on their invoices."""
    assert len({customer_uuid.new_customer_uuid() for _ in range(64)}) == 64


def test_the_attribute_name_is_fixed():
    """A rename trip-wire. This string is the join key on the contact row, the order row, the
    invoice row and both wire shapes, so renaming it without the rest is a silent blank column."""
    assert customer_uuid.ATTRIBUTE == "customerUuid"


# ══════════════════════════════════════════════════════════════════════════════
# 2. what the validator refuses
# ══════════════════════════════════════════════════════════════════════════════

def test_a_uuid7_is_REFUSED():
    """THE rule this module exists to enforce. Run against the real minter, not a fixture."""
    seven = identifiers.new_uuid7()
    assert uuid.UUID(seven).version == 7, "the fixture itself must really be a uuid7"
    assert customer_uuid.is_customer_uuid(seven) is False


def test_a_uuid5_is_refused_too():
    """`auth/customer-profile` mints the CONTACT ROW ID as uuid5 of the Cognito sub. If that
    value were ever copied into this attribute, publishing it would publish a hash of the Cognito
    subject - so the validator refuses it rather than printing it."""
    five = str(uuid.uuid5(uuid.NAMESPACE_URL, "wecare:checkout-customer:CUS_TEST"))
    assert customer_uuid.is_customer_uuid(five) is False


@pytest.mark.parametrize("spelling", [
    "{%s}" % uuid.uuid4(),                       # braces
    "urn:uuid:%s" % uuid.uuid4(),                # urn form
    uuid.uuid4().hex,                            # 32 hex chars, no hyphens
    str(uuid.uuid4()).upper(),                   # upper case
    " %s " % uuid.uuid4(),                       # surrounding whitespace
])
def test_a_non_canonical_spelling_is_refused(spelling):
    """All five of these PARSE in Python and are a different STRING from what we stored. This id
    is compared, joined on and printed verbatim, so two spellings of one id would let an invoice
    and an order page disagree character for character."""
    assert customer_uuid.is_customer_uuid(spelling) is False


@pytest.mark.parametrize("junk", [
    None, "", "   ", "not-a-uuid", 12345, 0, True, [], {}, object(),
    identifiers.new_ulid(),
])
def test_junk_is_refused(junk):
    assert customer_uuid.is_customer_uuid(junk) is False


# ══════════════════════════════════════════════════════════════════════════════
# 3. from_contact: total, and never raises
# ══════════════════════════════════════════════════════════════════════════════

def test_from_contact_returns_the_value_for_a_valid_row():
    minted = customer_uuid.new_customer_uuid()
    assert customer_uuid.from_contact({customer_uuid.ATTRIBUTE: minted}) == minted


@pytest.mark.parametrize("row", [
    None,
    {},
    "a string, not a row",
    42,
    {customer_uuid.ATTRIBUTE: None},
    {customer_uuid.ATTRIBUTE: ""},
    {customer_uuid.ATTRIBUTE: "junk"},
    {customer_uuid.ATTRIBUTE: identifiers.new_uuid7()},
    {"id": str(uuid.uuid4())},            # the CONTACT row id is not this attribute
])
def test_from_contact_degrades_to_empty_string(row):
    assert customer_uuid.from_contact(row) == ""


def test_from_contact_never_raises_on_a_hostile_row():
    """A dict whose `.get` raises is not a contact. The guarantee is the contract, so the answer
    here is the same empty string as for every other unusable input."""
    class Hostile(dict):
        def get(self, *_args, **_kwargs):
            raise RuntimeError("no")

    with pytest.raises(RuntimeError):
        Hostile().get(customer_uuid.ATTRIBUTE)     # the fixture really is hostile
    # ... and the module still answers rather than propagating.
    try:
        answer = customer_uuid.from_contact(Hostile())
    except Exception as exc:  # noqa: BLE001 - the point of the test
        pytest.fail(f"from_contact raised {type(exc).__name__}; its contract says it cannot")
    assert answer == ""


# ══════════════════════════════════════════════════════════════════════════════
# 4. the boundary: this module is pure
# ══════════════════════════════════════════════════════════════════════════════

def test_the_module_touches_no_aws_and_no_clock():
    """It is read on the payment path and minted inside a DynamoDB expression, so it must hold no
    client, need no credential, and - decisively - import no clock, because a time source is how
    a timestamp gets back into an id that must not carry one."""
    source = (SHARED / "lambda_utils" / "identity" / "customer_uuid.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in ("boto3", "import time", "time.time", "new_uuid7", "new_ulid"):
        assert forbidden not in code.split('"""')[-1], forbidden


def test_it_imports_from_the_package_root():
    """`from lambda_utils.identity import customer_uuid` must resolve through the package, since
    that is the spelling every handler uses and `deploy_all_lambdas.py --dry-run` validates."""
    import lambda_utils.identity as identity_pkg
    assert identity_pkg.customer_uuid is customer_uuid
    assert os.path.basename(customer_uuid.__file__) == "customer_uuid.py"
