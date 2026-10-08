"""The gift-card ledger: bearer value, conditional writes, and nothing that deletes a liability.

Design reference: `.agents/tasks/wix-coupons-giftcards-20261001/gift-cards-service-plugin-20261001.md`
sections 3.4, 6 and 7.5, and the test list in section 9.1 (tests 42-64).

MEDIUM-7's renames are applied. Tests 49, 50 and 53 were named for `reference`, which revision 3
re-keyed: the claim is `GCORDER#<codeHash>#<paymentAttemptId>`, and `referenceId` is two different
things depending on which producer built the attempt (a `WD-PAY-` reference on the in-WhatsApp path,
the RAZORPAY ORDER ID on the website path). A test named for the old key would describe a guarantee
the code does not make.

Three tests here are not in the design's list, and they are the reason the HIGH findings stay closed
rather than merely answered in prose:

* `test_every_dynamodb_access_is_an_exact_key_operation_or_the_status_index_query` enumerates the
  module's call sites, which is what pins HIGH-3 / DECISION 5. A sentence saying "no scan" is not a
  gate; an enumeration is.
* `test_a_void_carrying_only_a_transaction_id_resolves_both_the_card_and_the_attempt` pins HIGH-6 /
  DECISION 9. Without `paymentAttemptId` on the pointer row, `GC_VOIDED` is a stage with no
  reachable writer and the SPI role holds an `UpdateItem` grant for a call it cannot compose.
* `test_the_claim_row_is_settled_in_the_same_transaction_so_a_short_balance_is_recoverable` pins
  the ordering that makes an `InsufficientFunds` failure replayable rather than a permanent
  unsettled claim. Named for the transaction rather than for a `_decrement`, which no longer
  exists.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from decimal import Decimal

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from coupon_fake_dynamo import FakeClientError, FakeTable  # noqa: E402
from lambda_utils.ecommerce import gift_card_settlement as gcs  # noqa: E402
from lambda_utils.ecommerce import gift_card_store as gc  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_store.py"
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(MODULE))

GIFT_CARDS_HANDLER = ROOT / "amplify/functions/ecommerce/gift-cards/handler.py"
SPI_HANDLER = ROOT / "amplify/functions/ecommerce/wix-giftcard-spi/handler.py"
COUPON_HANDLER = ROOT / "amplify/functions/ecommerce/coupons/handler.py"

#: Not a credential: a test-only string that exists so the HMAC has a key. The real pepper lives in
#: Secrets Manager and is never on a command line, in a log, or in this file.
PEPPER = "pepper-for-tests-only"

NOW = 1_700_000_000
NOW_MS = NOW * 1000


def clock(value: int = NOW):
    return lambda: value


def table() -> FakeTable:
    return FakeTable(key_attr=gc.KEY_ATTRIBUTE,
                    indexes={gc.STATUS_INDEX: (gc.STATUS_ATTRIBUTE, "createdAt")})


def issue(store: FakeTable, *, value_paise: int = 500000, code: str = "WDGC0000TEST0001",
          **extra):
    issued = gc.issue(store, initial_value_paise=value_paise, pepper=PEPPER, code=code,
                      clock=clock(), **extra)
    store.calls.clear()
    return issued


def digest_of(code: str = "WDGC0000TEST0001") -> str:
    return gc.code_hash(code, pepper=PEPPER)


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _logging_calls(tree: ast.AST) -> list:
    return [call for call in ast.walk(tree)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "logger"]


# ── 42 / 43: the code is bearer value, so it is never the key and never stored ──

def test_the_partition_key_is_an_hmac_not_the_code():
    """The SPI bounds a code at 8-20 characters. An 8-character code over a small alphabet is
    inside brute-force range for a PLAIN hash, so a leaked table would expose live balances - which
    is why this is an HMAC with a pepper and not a bare SHA-256.

    This is the deliberate opposite of `coupon_store`, where the code IS the partition key.
    """
    store = table()
    issued = issue(store)
    key = issued["card"][gc.KEY_ATTRIBUTE]

    assert key.startswith(gc.PREFIX_CARD)
    assert key == gc.PREFIX_CARD + digest_of()
    assert len(digest_of()) == 64
    # The code appears in NO key of any row type.
    for row_key in store.rows:
        assert "WDGC0000TEST0001" not in row_key

    # And the pepper is load-bearing: the same code under a different pepper is a different key.
    assert gc.code_hash("WDGC0000TEST0001", pepper="a-different-pepper") != digest_of()


def test_the_code_is_never_stored_in_clear():
    """Only `codeLast4`. The code is returned ONCE, in the issuance response, and lives nowhere
    else - so a card whose code is lost is reissued rather than recovered, which is the correct
    property for bearer value."""
    store = table()
    issued = issue(store)
    card = issued["card"]

    assert card["codeLast4"] == "0001"
    assert issued["code"] == "WDGC0000TEST0001"
    for row in store.rows.values():
        for value in row.values():
            assert value != "WDGC0000TEST0001"
            if isinstance(value, str):
                assert "WDGC0000TEST0001" not in value
    # `code` is not among the attributes a card row may carry, by declaration.
    assert "code" not in gc.CARD_ATTRIBUTES
    assert "codeLast4" in gc.CARD_ATTRIBUTES


def test_a_pin_is_stored_as_an_hmac_and_compared_in_constant_time():
    """`hmac.compare_digest`, never `==`: a short-circuiting comparison leaks the matching prefix
    length through timing, and a PIN is short enough for that to matter."""
    store = table()
    issued = issue(store, pin="4321")
    card = issued["card"]
    assert card["pinHash"] != "4321"
    assert len(card["pinHash"]) == 64

    gc.verify_pin(card, "4321", pepper=PEPPER)
    with pytest.raises(gc.GiftCardNotFound):
        gc.verify_pin(card, "9999", pepper=PEPPER)

    # The comparison is `compare_digest`, asserted over the AST so the comment that explains why
    # cannot satisfy the test.
    body = next(node for node in ast.walk(TREE)
                if isinstance(node, ast.FunctionDef) and node.name == "verify_pin")
    compares = [node for node in ast.walk(body) if isinstance(node, ast.Compare)
                and any(isinstance(operand, ast.Call) for operand in node.comparators)]
    assert not compares, "a PIN is being compared with an operator rather than compare_digest"
    assert "compare_digest" in ast.unparse(body)


# ── 44 / 46: what may reach a log line, from this side of the asymmetry ─────────

def test_logs_carry_only_the_last_four_digits():
    """AST plus runtime. `masked()` takes `codeLast4` and REFUSES a longer string, so a caller
    cannot pass a full code and have it silently truncated inside a logging expression."""
    assert gc.masked("0001") == "****0001"
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.masked("WDGC0000TEST0001")
    assert refusal.value.code == "CODE_IN_LOG"

    for handler_path in (GIFT_CARDS_HANDLER, SPI_HANDLER):
        tree = ast.parse(handler_path.read_text(encoding="utf-8"), filename=str(handler_path))
        logged = [ast.unparse(call) for call in _logging_calls(tree)]
        assert logged, f"{handler_path.name} logs nothing, so the masking is untested"
        for rendered in logged:
            assert "'code'" not in rendered, f"a full code reaches a log line: {rendered}"
            assert '"code"' not in rendered
            if "codeLast4" in rendered:
                assert "store.masked(" in rendered or "masked(" in rendered, (
                    f"codeLast4 is logged unmasked: {rendered}")


def test_a_coupon_code_may_be_logged_but_a_gift_card_code_may_not():
    """The deliberate asymmetry, pinned from the gift-card side so neither design is
    "harmonised" into the other.

    A coupon code is broadcast marketing material - printed in campaigns, shared on purpose - so it
    is the partition key AND is loggable in full. A gift-card code is bearer value, so the same
    position holds an HMAC and only four digits ever reach a log. Making these the same would be a
    regression in one direction or the other, never an improvement in both.
    """
    from lambda_utils.ecommerce import coupon_store

    # Coupons: the code IS the key.
    assert coupon_store.definition_key("SAVE10") == "COUPON#SAVE10"
    # Gift cards: the code is never the key, and deriving one needs the pepper.
    with pytest.raises(TypeError):
        gc.card_key("WDGC0000TEST0001")        # type: ignore[call-arg]

    coupon_tree = ast.parse(COUPON_HANDLER.read_text(encoding="utf-8"))
    coupon_logged = " ".join(ast.unparse(call) for call in _logging_calls(coupon_tree))
    assert "'code'" in coupon_logged, "the coupon handler has stopped logging the code in full"

    gift_tree = ast.parse(GIFT_CARDS_HANDLER.read_text(encoding="utf-8"))
    gift_logged = " ".join(ast.unparse(call) for call in _logging_calls(gift_tree))
    assert "codeLast4" in gift_logged
    assert "'code'" not in gift_logged


# ── 45: no code in a path or a query ──────────────────────────────────────────

def test_no_route_accepts_a_code_in_a_path_or_query():
    """A bearer value in a URL lands in access logs, in `Referer` headers and in browser history.
    Enforced by SHAPE - no route template takes a code - rather than by convention.

    Also asserts the FIVE-route surface of MEDIUM-5: no hold and no release route exists, because a
    customer session has no `paymentAttemptId` and a hold taken outside the request that mints one
    skips `GC_HELD`, leaving `giftCardRequiredPaise` unwritten so `is_fully_settled` would settle a
    gift-card order on the Razorpay leg alone.
    """
    gift_tree = ast.parse(GIFT_CARDS_HANDLER.read_text(encoding="utf-8"))
    assignment = next(node for node in ast.walk(gift_tree)
                      if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                      and node.target.id == "ROUTE_HANDLERS")
    routes = ast.literal_eval(assignment.value)

    assert set(routes) == {
        "POST /gift-cards",
        "GET /gift-cards/{giftCardId}",
        "GET /gift-cards",
        "POST /gift-cards/{giftCardId}/disable",
        "POST /gift-cards/balance",
    }
    assert len(routes) == 5
    for route in routes:
        assert "{code}" not in route and "code" not in route.split("/")[-1].lower().replace(
            "gift-cards", "")
    for forbidden in ("POST /gift-cards/hold", "POST /gift-cards/release"):
        assert forbidden not in routes
    # No DELETE anywhere: a disabled card keeps its liability record.
    assert not [route for route in routes if route.startswith("DELETE ")]

    spi_tree = ast.parse(SPI_HANDLER.read_text(encoding="utf-8"))
    spi_assignment = next(node for node in ast.walk(spi_tree)
                          if isinstance(node, ast.AnnAssign)
                          and isinstance(node.target, ast.Name)
                          and node.target.id == "SPI_ROUTES")
    spi_routes = ast.literal_eval(spi_assignment.value)
    assert set(spi_routes) == {"POST /wix-giftcards/v1/balance",
                               "POST /wix-giftcards/v1/redeem",
                               "POST /wix-giftcards/v1/void"}
    for route in spi_routes:
        assert "{" not in route, "an SPI route carries a path parameter"


# ── 47 / 48: the balance floor ────────────────────────────────────────────────

def test_the_balance_cannot_go_negative_under_concurrency():
    """Two redemptions against one card. The second loses the CONDITION, not a comparison we made.

    This is the property a mock cannot fake and a read-then-write cannot hold: both readers would
    see a sufficient balance and both would proceed.
    """
    store = table()
    issue(store, value_paise=50000)
    first = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                      amount_paise=40000, clock=clock())
    assert first["remainingBalancePaise"] == 10000

    with pytest.raises(gc.InsufficientFunds):
        gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-2",
                  amount_paise=40000, clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000


def test_the_balance_floor_is_a_condition_expression_not_a_read_then_write():
    """The guard is inside the TRANSACTION's card item, and no `get_item` precedes it.

    Three assertions move with the money, not two. The floor is now found inside the
    `transact_write_items` card item; the read-ordering assertion is re-indexed onto the
    transaction, because the surviving `update_item` is the best-effort `balanceAfterPaise`
    follow-up and indexing on it would assert the wrong thing about the wrong write; and `:neg`
    is compared in its ATTRIBUTEVALUE form, `{"N": "-40000"}`, because that is what goes on the
    wire. That third assertion checks the marshalling - the `^-?[0-9]+$` rule owns the money
    property.
    """
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
              clock=clock())

    transactions = [kwargs for name, kwargs in store.calls if name == "transact_write_items"]
    assert len(transactions) == 1
    card_items = [item["Update"] for item in transactions[0]["TransactItems"]
                  if "ADD balancePaise" in str(item["Update"]["UpdateExpression"])]
    assert len(card_items) == 1
    assert "balancePaise >= :amount" in card_items[0]["ConditionExpression"]
    assert card_items[0]["ExpressionAttributeValues"][":neg"] == {"N": "-40000"}

    operations = store.operations()
    transaction_index = operations.index("transact_write_items")
    assert "get_item" not in operations[:transaction_index], (
        "a read precedes the balance move, which makes it a read-modify-write")
    assert operations[0] == "put_item", "the claim must be written before the balance moves"


# ── 49 / 50 / 53: idempotency, keyed on the PAYMENT ATTEMPT ────────────────────

def test_a_second_redeem_for_the_same_payment_attempt_returns_the_same_transaction_id():
    """The idempotency contract. `committed` is False on a replay, with the ORIGINAL id.

    Keyed on `paymentAttemptId` and not `referenceId`: section 3.4 measured that on the website
    path `attempt["referenceId"]` IS the Razorpay order id, which does not exist until after the
    gateway is addressed - and the hold has to precede the gateway.
    """
    store = table()
    issue(store, value_paise=50000)
    first = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                      amount_paise=40000, clock=clock())
    second = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                       amount_paise=40000, clock=clock())

    assert first["committed"] is True
    assert second["committed"] is False
    assert second["transactionId"] == first["transactionId"]


def test_a_second_redeem_for_the_same_payment_attempt_does_not_move_the_balance():
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
              clock=clock())
    before = store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"]

    # Shape-checked on the FIRST redemption, before the log is cleared - the helper refuses an
    # empty recording, which is what stops it passing vacuously over the replay below.
    seen = assert_transaction_items_are_exact_key_updates(store)
    assert seen >= 1
    assert _committers(store) == {"redeem"}

    store.calls.clear()
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
              clock=clock())

    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == before
    # In EITHER representation. Checking only `update_item` would stop checking anything the
    # moment the money moved into a transaction.
    assert not [call for call in store.calls if _is_balance_move(call)]


def test_two_different_payment_attempts_each_deduct_once():
    """A genuine second purchase SHOULD deduct again. The claim makes a REPLAY idempotent; it does
    not make two purchases one."""
    store = table()
    issue(store, value_paise=100000)
    first = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                      amount_paise=30000, clock=clock())
    second = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-2",
                       amount_paise=25000, clock=clock())

    assert first["transactionId"] != second["transactionId"]
    assert second["remainingBalancePaise"] == 45000
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 45000


def test_the_claim_is_written_before_the_balance_moves():
    """Call ordering, and it is what makes a replay safe. The claim is irreversible and the
    decrement is guarded; the reverse order would deduct and then discover it had already
    deducted."""
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
              clock=clock())

    claim_index = next(index for index, (name, kwargs) in enumerate(store.calls)
                       if name == "put_item"
                       and str(kwargs["Item"][gc.KEY_ATTRIBUTE]).startswith(gc.PREFIX_CLAIM))
    # The balance move is the TRANSACTION now, so the ordering is asserted against it.
    move_index = next(index for index, (name, _kwargs) in enumerate(store.calls)
                      if name == "transact_write_items")
    assert claim_index < move_index
    claim_call = store.calls[claim_index][1]
    assert claim_call["ConditionExpression"] == f"attribute_not_exists({gc.KEY_ATTRIBUTE})"


def test_the_claim_row_is_settled_in_the_same_transaction_so_a_short_balance_is_recoverable():
    """Not in the design's list, and it closes a real window.

    The claim is written UNSETTLED. If the balance move then fails for want of funds, a retry
    must re-drive it rather than report a redemption that never moved money - and it must
    re-drive it under the SAME transaction id, so a retry cannot mint a second one. Nothing here
    deletes the claim, so the window cannot be closed by removing evidence.

    Named for the TRANSACTION, not for a `_decrement`: the settle and the debit are now two
    `Update` items in one `TransactWriteItems`, so "settled by the decrement" named a function
    that no longer exists and an ordering that is no longer sequential.
    """
    store = table()
    issue(store, value_paise=10000)
    with pytest.raises(gc.InsufficientFunds):
        gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
                  clock=clock())
    claim = store.rows[gc.PREFIX_CLAIM + digest_of() + "#attempt-1"]
    assert claim["settled"] is False
    pending_id = claim["transactionId"]

    gc.credit(store, code_hash=digest_of(), amount_paise=40000, clock=clock())
    recovered = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                          amount_paise=40000, clock=clock())
    assert recovered["committed"] is True
    assert recovered["transactionId"] == pending_id
    assert store.rows[gc.PREFIX_CLAIM + digest_of() + "#attempt-1"]["settled"] is True


#: The two attribute-name prefixes the applied-move markers USED to carry. Kept as literals
#: rather than as module constants precisely because the constants are gone: the assertion below
#: is now "no such attribute is ever written", and reading the prefix off the module would make
#: the test unwritable the moment the constant was deleted.
RETIRED_MARKER_PREFIXES = ("appliedClaim#", "appliedVoid#")


def _markers_on(store: FakeTable, prefix: str) -> list:
    return sorted(key for key in store.rows[gc.PREFIX_CARD + digest_of()]
                  if key.startswith(prefix))


def assert_transaction_items_are_exact_key_updates(store: FakeTable) -> int:
    """Every recorded transaction is `Update` items on fully specified keys. Returns the count.

    Reads `calls`, NOT `applied`, deliberately: a CANCELLED attempt is still a request that went
    to the database in some shape, and it is exactly the attempt a shape regression would hide
    in. An empty recording is refused FIRST, because a helper that passes vacuously is worse
    than no helper - it reports a guarantee it never checked.

    Asserting each item's key set is exactly `{"Update"}` is what forbids a later `Put`,
    `Delete` or `ConditionCheck` arriving in this transaction without a design change.
    """
    transactions = [kwargs for name, kwargs in store.calls if name == "transact_write_items"]
    assert transactions, (
        "no transaction was recorded, so this helper would pass vacuously; the caller must "
        "drive a path that opens one")
    for kwargs in transactions:
        items = kwargs["TransactItems"]
        assert items, "a transaction with no items is not a transaction"
        for item in items:
            assert set(item) == {"Update"}, (
                f"only `Update` items belong in this transaction, got {sorted(item)}; a `Put`, "
                f"`Delete` or `ConditionCheck` here is a design change, not a refactor")
            update = item["Update"]
            assert update.get("TableName"), "every transaction item names its table"
            assert update.get("Key"), "every transaction item is an exact-key operation"
            assert "IndexName" not in update, "a transaction never addresses an index"
    return len(transactions)


def _is_balance_move(call: tuple) -> bool:
    """True for a balance move in EITHER representation.

    `ADD balancePaise` is a plain string in both the single-item `UpdateExpression` and inside a
    transaction item's, and `_marshal` never touches the expression text - so one predicate
    reads both logs. Matching only `update_item` would silently stop matching anything the
    moment the money moved into a transaction, which is the failure mode this exists to avoid.
    """
    name, kwargs = call
    if name == "update_item":
        return "ADD balancePaise" in str(kwargs.get("UpdateExpression") or "")
    if name == "transact_write_items":
        return any("ADD balancePaise" in str((item.get("Update") or {}).get("UpdateExpression")
                                             or "")
                   for item in kwargs.get("TransactItems") or [])
    return False


def _committer_of(kwargs: dict) -> str:
    """Which committer assembled this recorded transaction: `"redeem"` or `"void"`.

    Defined here because the design names it and the tree had no such symbol. The two are
    distinguishable without counting calls: `_commit_redemption` is `ADD balancePaise :neg` and
    `_commit_void` is `ADD balancePaise :amount`.

    RAISES rather than returning a sentinel for a transaction that moves no balance. A sentinel
    would be silently absorbed into a set comparison, so a third kind of transaction appearing
    on this path would pass unnoticed - which is the opposite of what a committer-set assertion
    is for.
    """
    expressions = [str((item.get("Update") or {}).get("UpdateExpression") or "")
                   for item in kwargs.get("TransactItems") or []]
    if any("ADD balancePaise :neg" in expression for expression in expressions):
        return "redeem"
    if any("ADD balancePaise :amount" in expression for expression in expressions):
        return "void"
    raise AssertionError(
        f"this transaction moves no balance, so no committer owns it: {expressions}")


def _committers(store: FakeTable) -> set:
    return {_committer_of(kwargs) for name, kwargs in store.calls
            if name == "transact_write_items"}


def test_the_settle_and_the_balance_move_are_one_commit():
    """Replaces `test_a_redemption_whose_settle_write_failed_debits_the_balance_exactly_once`.

    That test asserted a RECOVERY from a state this change makes unreachable: the money down and
    the claim unsettled, which existed because `settled` lived on a second item and could only be
    written after the balance had moved. The replacement therefore asserts the STRONGER property
    rather than nothing - **there is no interleaving in which the balance has moved and the claim
    is unsettled**, because the two are one `TransactWriteItems`.

    Retiring a test is the step most likely to be mistaken for making a build green, so the
    measurement is explicit: one transaction carries both the `ADD balancePaise` and the
    `SET settled = :true`, and no `update_item` carries either.
    """
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=20000,
              clock=clock())

    claim_key = gc.PREFIX_CLAIM + digest_of() + "#attempt-1"
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 30000
    assert store.rows[claim_key]["settled"] is True

    transactions = [kwargs for name, kwargs in store.calls if name == "transact_write_items"]
    seen = assert_transaction_items_are_exact_key_updates(store)
    assert seen >= 1
    assert _committers(store) == {"redeem"}
    expressions = [str(item["Update"]["UpdateExpression"]) for item in
                   transactions[0]["TransactItems"]]
    assert any("ADD balancePaise :neg" in text for text in expressions)
    assert any("SET settled = :true" in text for text in expressions), (
        "the settle must commit WITH the money, not after it")
    # And neither half survives as a separate single-item write.
    assert not [kwargs for name, kwargs in store.calls
                if name == "update_item"
                and "SET settled = :true" in str(kwargs.get("UpdateExpression") or "")]
    assert not [kwargs for name, kwargs in store.calls
                if name == "update_item"
                and "ADD balancePaise" in str(kwargs.get("UpdateExpression") or "")]


def test_a_stalled_redemption_still_debits_once_when_another_purchase_lands_between():
    """Why the guard is keyed on the CLAIM ROW and not on `activeClaimAttemptId`.

    `activeClaimAttemptId = :me` is written by the balance move, so `activeClaimAttemptId <>
    :me` looks like a cheap guard. It is not: the next attempt's move overwrites it, so a retry
    arriving after a second purchase would find its own id gone and deduct again. Narrower
    window, same loss.

    Driven post-fix by a SETTLED claim plus an intervening different purchase, which is the route
    to that state now that the money and the settle commit together.
    """
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=20000,
              clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 30000

    # A genuinely different purchase, which SHOULD deduct, and which moves activeClaimAttemptId.
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-2", amount_paise=5000,
              clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()][gc.CLAIM_ATTEMPT_ATTRIBUTE] == "attempt-2"
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 25000

    # attempt-1 arriving late, after its own id has been overwritten. It must NOT deduct again.
    replay = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                       amount_paise=20000, clock=clock())
    assert replay["committed"] is False
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 25000


def test_an_applied_move_marker_does_not_outlive_the_move_it_guards():
    """The stronger fact: NO applied-move marker is ever written at all.

    These markers existed to make the money its own idempotency record on one item, because the
    flag that recorded a move lived on a different item. With the move and the flag in one
    transaction there is nothing for a marker to guard - so the card row's size is bounded BY
    CONSTRUCTION rather than by a best-effort cleanup step, which is a stronger guarantee than
    the one this test used to make and is why the name is kept.
    """
    store = table()
    issue(store, value_paise=100000)
    for number in range(1, 6):
        gc.redeem(store, code_hash=digest_of(), attempt_id=f"attempt-{number}",
                  amount_paise=1000, clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 95000

    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-void",
                         amount_paise=1000, clock=clock())
    gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 95000

    for prefix in RETIRED_MARKER_PREFIXES:
        assert _markers_on(store, prefix) == [], (
            f"{prefix} is written nowhere now; the balance move and the flag that records it "
            f"are one transaction")
    # Nor on any other row, and nor transiently in any recorded write.
    for row in store.rows.values():
        for attribute in row:
            assert not str(attribute).startswith(RETIRED_MARKER_PREFIXES)
    for name, kwargs in store.calls:
        for prefix in RETIRED_MARKER_PREFIXES:
            assert prefix not in str(kwargs)

    # A replay never reaches the money move: `settled` short-circuits it at the pre-read.
    for number in range(1, 6):
        replay = gc.redeem(store, code_hash=digest_of(), attempt_id=f"attempt-{number}",
                           amount_paise=1000, clock=clock())
        assert replay["committed"] is False
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 95000


# ── 51 / 52: the ceiling is the SPI's, not money.py's ──────────────────────────

def test_the_issuance_ceiling_is_the_spi_maximum():
    """`99_999_999_999` paise == `999999999.99`, the documented `maximum` on both
    `GetBalanceResponse.balance` and `RedeemResponse.remainingBalance`. A card above it could not
    be REPORTED to Wix, and a balance we cannot report is a balance we cannot honour."""
    assert gc.MAX_VALUE_PAISE == 99_999_999_999
    assert gc.MAX_VALUE_PAISE < gc.MONEY_CEILING_PAISE
    store = table()
    issued = gc.issue(store, initial_value_paise=gc.MAX_VALUE_PAISE, pepper=PEPPER,
                      code="WDGC0000TEST0001", clock=clock())
    assert issued["card"]["balancePaise"] == gc.MAX_VALUE_PAISE


def test_a_value_above_the_spi_maximum_is_refused():
    """At issuance AND on a later credit - the ceiling is asserted on every credit, not only once,
    because a void returning money to a near-full card is a credit too."""
    store = table()
    with pytest.raises(gc.GiftCardValidationError):
        gc.issue(store, initial_value_paise=100_000_000_000, pepper=PEPPER,
                 code="WDGC0000TEST0001", clock=clock())

    issue(store, value_paise=gc.MAX_VALUE_PAISE)
    with pytest.raises(gc.GiftCardValidationError) as refusal:
        gc.credit(store, code_hash=digest_of(), amount_paise=100, clock=clock())
    assert refusal.value.code == "BALANCE_CEILING_EXCEEDED"
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == gc.MAX_VALUE_PAISE


# ── 55 / 56 / 57: void, resolved from the transaction id alone ──────────────────

def test_a_void_resolves_the_card_from_the_transaction_id_alone():
    """`VoidRequest` carries NO code, so a transaction has to be resolvable by its id without
    knowing which card it belongs to. A design that keyed transactions only under the card would be
    unable to serve a documented request."""
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())

    pointer = gc.resolve_transaction(store, transaction_id=redeemed["transactionId"])
    assert pointer["codeHash"] == digest_of()
    outcome = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert outcome["codeHash"] == digest_of()


def test_a_void_carrying_only_a_transaction_id_resolves_both_the_card_and_the_attempt():
    """HIGH-6 / DECISION 9, and the whole reason `GC_VOIDED` is reachable.

    Revision 2's `GCTXNID#` row pointed only at the card, so the SPI could credit a balance and had
    no `paymentAttemptId` to advance a stage against - `GC_VOIDED` was a rank with no writer, while
    `wecare-wix-giftcard-spi-role` held an `UpdateItem` grant on PaymentAttemptsTable for a call
    that could not be composed. The pointer now carries both.
    """
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-xyz",
                         amount_paise=40000, clock=clock())

    resolved = gc.resolve_transaction(store, transaction_id=redeemed["transactionId"])
    assert resolved == {"codeHash": digest_of(), "paymentAttemptId": "attempt-xyz"}

    outcome = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert outcome["paymentAttemptId"] == "attempt-xyz"
    assert outcome["codeHash"] == digest_of()
    # And the void's own pointer row carries the attempt too, so a void of a void resolves.
    assert store.rows[gc.PREFIX_TRANSACTION_ID + outcome["transactionId"]][
        "paymentAttemptId"] == "attempt-xyz"


def test_a_void_returns_the_balance_to_the_card():
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000

    outcome = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert outcome["remainingBalancePaise"] == 50000
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000
    original = store.rows[gc.PREFIX_TRANSACTION + digest_of() + "#" + redeemed["transactionId"]]
    assert original["voidedBy"] == outcome["transactionId"]


def test_a_second_void_is_already_voided():
    """409, and the balance moves once. The `voidedBy` guard is written BEFORE the credit, for the
    same reason the claim precedes the decrement: if the credit went first and the guard then lost
    its race, the card would be credited twice."""
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())

    with pytest.raises(gc.AlreadyVoided) as refusal:
        gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert refusal.value.status == 409
    assert refusal.value.spi_name == "AlreadyVoided"
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000


def test_a_void_whose_credit_failed_is_completed_by_a_retry_not_refused():
    """Not in the design's list, and it closes the void path's counterpart of the claim window.

    The `voidedBy` latch is written BEFORE the credit, which is correct - the reverse order could
    credit twice if the latch then lost its race. But a latch with no marker makes a transient
    failure PERMANENT and IRREVERSIBLE: every retry read `voidedBy` and raised `AlreadyVoided`, so
    the redemption stayed marked voided with the customer's balance never returned and no operator
    path back except a manual ledger edit.

    Same shape, same vocabulary and same recovery as `redeem`'s claim row one function earlier:
    the marker is written unset, only the money move sets it, and a retry re-drives the move. Two
    different recovery mechanisms in one liability ledger is how the next person gets one of them
    wrong.

    What this asserts is that the void COMPLETES, not merely that it is latched: the credit
    transaction fails strictly between the latch and the balance move, the retry completes it,
    and the balance lands correct EXACTLY ONCE - idempotent on replay, as `redeem` is.

    The fault is aimed at the TRANSACTION now, because that is where the credit lives. A bare
    throughput `FakeClientError` is NOT a cancellation, so `_is_transaction_cancellation` is
    `False`, `_transact_with_retry` re-raises without looping, and the test's own second
    `void()` call IS the retry. Every answer below is identical to the pre-fix one - that is
    the check that this rewrite preserved the property rather than replacing it.
    """
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    original_key = gc.PREFIX_TRANSACTION + digest_of() + "#" + redeemed["transactionId"]
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000

    store.arm_failure("transact_write_items",
                      FakeClientError("ProvisionedThroughputExceededException"))
    with pytest.raises(gc.GiftCardStoreUnavailable):
        gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())

    # The latch stands, and it says EXPLICITLY that the money has not come back yet.
    latched = store.rows[original_key]["voidedBy"]
    assert latched
    assert store.rows[original_key]["credited"] is False
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000

    # The retry COMPLETES the void rather than refusing it, under the SAME void id - so a retry
    # cannot mint a second void transaction - and the balance returns once.
    completed = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert completed["transactionId"] == latched
    assert completed["remainingBalancePaise"] == 50000
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000
    assert store.rows[original_key]["credited"] is True
    # One void transaction and one pointer for it, not two.
    assert [key for key in store.rows
            if key.startswith(gc.PREFIX_TRANSACTION) and store.rows[key].get(
                "kind") == gc.KIND_VOID] == [gc.PREFIX_TRANSACTION + digest_of() + "#" + latched]

    # And once the credit HAS landed the door re-closes: a third call refuses again rather than
    # leaving the void permanently re-drivable.
    with pytest.raises(gc.AlreadyVoided):
        gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000

    seen = assert_transaction_items_are_exact_key_updates(store)
    assert seen >= 2
    assert _committers(store) == {"redeem", "void"}


def test_a_void_credit_that_fails_twice_still_returns_the_balance_exactly_once():
    """Recovery that works once is not recovery. The latch is not consumed by an attempt.

    `times=2` is what makes the narrative literally true. A one-shot `arm_failure` cannot
    express "armed twice": `_fail_if_armed` consumed the arm with `pop`, so two arms before the
    two calls produced ONE failure and the second `pytest.raises` then failed against CORRECT
    code. The counter keeps the arming visible at the arming site instead of hiding a re-arm in
    the middle of the loop below.
    """
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())

    store.arm_failure("transact_write_items",
                      FakeClientError("ProvisionedThroughputExceededException"), times=2)
    for _ in range(2):
        with pytest.raises(gc.GiftCardStoreUnavailable):
            gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
        assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000

    completed = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert completed["remainingBalancePaise"] == 50000
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000

    seen = assert_transaction_items_are_exact_key_updates(store)
    assert seen >= 2
    assert _committers(store) == {"redeem", "void"}


def test_the_credit_and_the_credited_flag_are_one_commit():
    """Replaces `test_a_void_whose_credited_write_failed_returns_the_balance_exactly_once`.

    That test asserted a RECOVERY from a state this change makes unreachable: the money back and
    `credited` still `False`, which existed because the flag lived on the transaction row and
    could only follow the credit. Pre-fix, the retry branch read that state as "the credit never
    ran" and re-drove it - a card issued at 50000 and redeemed 40000 ended at 90000 paise, a
    silent business-side loss wearing the shape of a successful void.

    The replacement asserts the stronger property - the credit and the flag are ONE
    `TransactWriteItems`, so no interleaving leaves them disagreeing - and it ADDITIONALLY
    asserts that a second `void()` of the same transaction credits nothing. That second half is
    the property rehoused from the plain-credit test below, which lost its `once_key` half when
    `credit()` lost the parameter.
    """
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    original_key = gc.PREFIX_TRANSACTION + digest_of() + "#" + redeemed["transactionId"]
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000

    completed = gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert completed["remainingBalancePaise"] == 50000
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000
    assert store.rows[original_key]["credited"] is True

    void_transactions = [kwargs for name, kwargs in store.calls
                         if name == "transact_write_items" and _committer_of(kwargs) == "void"]
    assert len(void_transactions) == 1
    expressions = [str(item["Update"]["UpdateExpression"])
                   for item in void_transactions[0]["TransactItems"]]
    assert any("ADD balancePaise :amount" in text for text in expressions)
    assert any("SET credited = :true" in text for text in expressions), (
        "the flag must commit WITH the credit, not after it")
    assert not [kwargs for name, kwargs in store.calls
                if name == "update_item"
                and "SET credited = :true" in str(kwargs.get("UpdateExpression") or "")]

    # The same logical credit replayed moves the balance ONCE. 50000, not 90000.
    with pytest.raises(gc.AlreadyVoided):
        gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000
    # And one void transaction, not two.
    latched = store.rows[original_key]["voidedBy"]
    assert [key for key in store.rows
            if key.startswith(gc.PREFIX_TRANSACTION) and store.rows[key].get(
                "kind") == gc.KIND_VOID] == [gc.PREFIX_TRANSACTION + digest_of() + "#" + latched]

    seen = assert_transaction_items_are_exact_key_updates(store)
    assert seen >= 2
    assert _committers(store) == {"redeem", "void"}


def test_a_plain_credit_is_not_made_idempotent_because_two_top_ups_are_two_events():
    """A credit is a PLAIN ADDITION, and that asymmetry is deliberate rather than an oversight.

    Two credits of the same size are two different events, and de-duplicating them would
    silently swallow the second one. The void path's idempotency does not live here - it lives
    in `_commit_void`'s `credited = :false` condition, committed with the money, which is what
    `test_the_credit_and_the_credited_flag_are_one_commit` asserts.
    """
    store = table()
    issue(store, value_paise=1000)
    gc.credit(store, code_hash=digest_of(), amount_paise=500, clock=clock())
    gc.credit(store, code_hash=digest_of(), amount_paise=500, clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 2000


def test_a_void_latched_before_the_credited_flag_existed_is_never_re_credited():
    """`credited` ABSENT must read as COMPLETE, not as pending.

    A latch written by code that predates the flag is indistinguishable from one whose credit
    landed, and treating absence as pending would hand the balance back a second time. Only an
    explicit `False` - which only `void` itself writes - re-drives the credit.
    """
    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    original_key = gc.PREFIX_TRANSACTION + digest_of() + "#" + redeemed["transactionId"]
    legacy = dict(store.rows[original_key])
    legacy["voidedBy"] = "legacy-void-id"
    legacy["voidedAt"] = NOW
    legacy.pop("credited", None)
    store.seed(legacy)

    with pytest.raises(gc.AlreadyVoided):
        gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 10000


def test_an_unknown_transaction_id_is_transaction_not_found():
    store = table()
    issue(store)
    with pytest.raises(gc.TransactionNotFound) as refusal:
        gc.void(store, transaction_id="no-such-transaction", clock=clock())
    assert refusal.value.status == 404


# ── 58: hold expiry ───────────────────────────────────────────────────────────

def test_a_hold_past_its_expiry_does_not_block_another_purchase():
    """DECISION 5's third arm. An abandoned checkout must stop blocking the next one, and the only
    thing that can decide that is the stored expiry - not a sweeper, which would be a second
    writer racing the first."""
    store = table()
    issue(store, value_paise=50000)
    gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
            ttl_seconds=60, clock=clock())

    with pytest.raises(gc.GiftCardHeldByAnotherPurchase):
        gc.hold(store, code_hash=digest_of(), attempt_id="attempt-2", amount_paise=40000,
                ttl_seconds=60, clock=clock())

    later = gc.hold(store, code_hash=digest_of(), attempt_id="attempt-2", amount_paise=40000,
                    ttl_seconds=60, clock=clock(NOW + 3600))
    assert later["held"] is True
    assert store.rows[gc.PREFIX_CARD + digest_of()][gc.HOLD_ATTEMPT_ATTRIBUTE] == "attempt-2"


def test_retaking_your_own_hold_is_idempotent_rather_than_a_conflict():
    store = table()
    issue(store, value_paise=50000)
    gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
            clock=clock())
    again = gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
                    clock=clock())
    assert again["held"] is True


def test_the_hold_is_one_conditional_update_with_no_preceding_read():
    """A `get_item` in front would turn an atomic guard into a read-modify-write, and two attempts
    reading "free" in the same moment would both proceed."""
    store = table()
    issue(store, value_paise=50000)
    gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
            clock=clock())

    operations = store.operations()
    assert operations[0] == "update_item"
    condition = store.calls[0][1]["ConditionExpression"]
    for arm in ("attribute_not_exists(activeHoldAttemptId)",
                "activeHoldAttemptId = :me",
                "activeHoldExpiresAtMs < :now"):
        assert arm in condition
    assert "balancePaise >= :amount" in condition
    # The millisecond/second distinction: `:now` must be milliseconds or every live hold reads as
    # lapsed against a millisecond expiry.
    assert store.calls[0][1]["ExpressionAttributeValues"][":now"] == NOW_MS


def test_a_release_cannot_clear_another_live_holders_hold():
    store = table()
    issue(store, value_paise=50000)
    gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
            clock=clock())
    with pytest.raises(gc.GiftCardHeldByAnotherPurchase):
        gc.release(store, code_hash=digest_of(), attempt_id="attempt-2", clock=clock())

    gc.release(store, code_hash=digest_of(), attempt_id="attempt-1", clock=clock())
    assert gc.HOLD_ATTEMPT_ATTRIBUTE not in store.rows[gc.PREFIX_CARD + digest_of()]
    assert gc.PREFIX_HOLD + digest_of() + "#attempt-1" not in store.rows


def test_a_held_card_refuses_a_hold_for_a_different_attempt_but_the_balance_is_untouched():
    store = table()
    issue(store, value_paise=50000)
    gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
            clock=clock())
    with pytest.raises(gc.GiftCardHeldByAnotherPurchase):
        gc.hold(store, code_hash=digest_of(), attempt_id="attempt-2", amount_paise=1000,
                clock=clock())
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000


def test_a_hold_above_the_balance_is_insufficient_funds():
    store = table()
    issue(store, value_paise=5000)
    with pytest.raises(gc.InsufficientFunds):
        gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=40000,
                clock=clock())


# ── 59: a disabled or expired card ────────────────────────────────────────────

def test_a_disabled_card_cannot_be_redeemed():
    store = table()
    issue(store, value_paise=50000)
    gc.disable(store, code_hash=digest_of(), clock=clock())
    with pytest.raises(gc.GiftCardDisabled) as refusal:
        gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=1000,
                  clock=clock())
    assert refusal.value.status == 428
    assert store.rows[gc.PREFIX_CARD + digest_of()]["balancePaise"] == 50000


def test_an_expired_card_cannot_be_redeemed():
    store = table()
    issue(store, value_paise=50000, expires_at_ms=NOW_MS + 1000)
    card = gc.get_card(store, code_hash=digest_of())
    gc.assert_spendable(card, now_ms=NOW_MS)
    with pytest.raises(gc.GiftCardExpired):
        gc.assert_spendable(card, now_ms=NOW_MS + 2000)


def test_a_disabled_card_is_never_deleted():
    """`status = DISABLED`, and the row - with its balance - survives. A disabled card retains its
    liability record, because the debt is still owed."""
    store = table()
    issue(store, value_paise=50000)
    gc.disable(store, code_hash=digest_of(), clock=clock())
    row = store.rows[gc.PREFIX_CARD + digest_of()]
    assert row[gc.STATUS_ATTRIBUTE] == gc.STATUS_DISABLED
    assert row["balancePaise"] == 50000


# ── 60 / 61: nothing deletes a liability, and nothing expires one ──────────────

def test_nothing_in_the_store_deletes_a_card_a_transaction_or_a_pointer_row():
    """Enumerates the delete sites. There is exactly one, it is `_delete_hold`, and its key is a
    `GCHOLD#`. A card, a transaction, a claim and a pointer row have NO deleting function."""
    sites = [node for node in ast.walk(TREE)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "delete_item"]
    assert len(sites) == 1, f"{len(sites)} delete_item call sites, expected exactly one"

    owner = next(node for node in ast.walk(TREE)
                 if isinstance(node, ast.FunctionDef) and any(
                     call is sites[0] for call in ast.walk(node)))
    assert owner.name == "_delete_hold"
    assert "PREFIX_HOLD" in ast.unparse(sites[0])

    store = table()
    issue(store, value_paise=50000)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    gc.disable(store, code_hash=digest_of(), clock=clock())
    for prefix in (gc.PREFIX_CARD, gc.PREFIX_CLAIM, gc.PREFIX_TRANSACTION,
                   gc.PREFIX_TRANSACTION_ID, gc.PREFIX_CARD_ID):
        assert [key for key in store.rows if key.startswith(prefix)], \
            f"no {prefix} row survived"


def test_a_card_row_carries_no_ttl_attribute():
    """An expiring liability is a disappearing debt. `expiresAtMs` changes what is PERMITTED; it
    never removes what is OWED, and the table's TTL stays disabled."""
    store = table()
    issued = issue(store, value_paise=50000, expires_at_ms=NOW_MS + 86_400_000)
    for row in store.rows.values():
        for attribute in row:
            assert "ttl" not in attribute.lower(), f"{attribute} looks like a TTL attribute"
            assert "expiresAt" not in attribute or attribute in ("expiresAtMs",)
    assert issued["card"]["expiresAtMs"] == NOW_MS + 86_400_000

    # And no write ever names a TTL-shaped attribute. Over the AST, not the text, because the
    # paragraph explaining why TTL is disabled necessarily contains the word.
    for node in ast.walk(TREE):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("put_item", "update_item"):
            for keyword in node.keywords:
                rendered = ast.unparse(keyword.value)
                for shape in ("'ttl'", '"ttl"', "expireAt", "timeToLive", "TimeToLive"):
                    assert shape not in rendered, f"line {node.lineno} writes {shape}"


# ── 62 / 63: code generation ──────────────────────────────────────────────────

def test_the_code_is_generated_with_secrets_not_random():
    """AST, and the hazard is measured. `lambda-snapstart-deploy.md`: with SnapStart on, the
    snapshot freezes the `random` PRNG state and every restored environment produces the same
    sequence. SnapStart is off on all 65 functions today, but a gift-card code is exactly the class
    of value that must never repeat."""
    imports = {alias.name for node in ast.walk(TREE) if isinstance(node, ast.Import)
               for alias in node.names}
    imports |= {node.module for node in ast.walk(TREE) if isinstance(node, ast.ImportFrom)
                and node.module}
    assert "random" not in imports
    assert "secrets" in imports
    assert "_secrets.choice" in ast.unparse(
        next(node for node in ast.walk(TREE)
             if isinstance(node, ast.FunctionDef) and node.name == "generate_code"))


def test_the_generated_code_is_within_the_spi_length_bounds():
    """8 <= len <= 20, the documented `minLength`/`maxLength` on `code`."""
    assert gc.MIN_CODE_LENGTH == 8 and gc.MAX_CODE_LENGTH == 20
    assert gc.CODE_LENGTH == 16
    for _ in range(20):
        code = gc.generate_code()
        assert gc.MIN_CODE_LENGTH <= len(code) <= gc.MAX_CODE_LENGTH
        assert set(code) <= set(gc.CODE_ALPHABET)
    # Crockford: no I, L, O or U, so a handwritten code cannot be transcribed into another one.
    for ambiguous in "ILOU":
        assert ambiguous not in gc.CODE_ALPHABET
    with pytest.raises(gc.GiftCardValidationError):
        gc.generate_code(length=4)


def test_two_generated_codes_differ():
    assert len({gc.generate_code() for _ in range(50)}) == 50


# ── 64: integer paise only ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [1.0, 400.5, True, False, "4000", None, Decimal("40.5")])
def test_integer_paise_only(bad):
    """Floats and bools refused BY TYPE at every entry, never coerced and never rounded.

    `0.1 + 0.2` is not `0.3` in binary floating point, and a one-paise mismatch against the
    checkout total has to fail the payment CLOSED - so a rounding artefact would refuse a
    legitimate order. Rejecting the type at the boundary is cheaper than finding out later.
    """
    store = table()
    with pytest.raises(gc.GiftCardError):
        gc.issue(store, initial_value_paise=bad, pepper=PEPPER, code="WDGC0000TEST0001",
                 clock=clock())

    issue(store, value_paise=50000)
    with pytest.raises(gc.GiftCardError):
        gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=bad,
                  clock=clock())
    with pytest.raises(gc.GiftCardError):
        gc.hold(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=bad,
                clock=clock())
    with pytest.raises(gc.GiftCardError):
        gc.credit(store, code_hash=digest_of(), amount_paise=bad, clock=clock())


def test_no_float_is_constructed_anywhere_on_the_store_money_path(monkeypatch):
    """The strong version: `float` itself is made to raise, and a full redeem/void cycle runs."""
    import builtins

    def refuse(*_args, **_kwargs):
        raise AssertionError("a float was constructed on the gift-card money path")

    store = table()
    issue(store, value_paise=50000)
    monkeypatch.setattr(builtins, "float", refuse)
    redeemed = gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1",
                         amount_paise=40000, clock=clock())
    gc.void(store, transaction_id=redeemed["transactionId"], clock=clock())
    gc.split_payment(balance_paise=40000, wix_collection_paise=100000,
                     total_payable_paise=102950, requested_paise=40000)


def test_the_clock_must_return_integer_seconds():
    """`time.time()`'s float is refused, so no float reaches a stored timestamp that is later
    compared for exact equality."""
    store = table()
    with pytest.raises(gc.GiftCardStoreUnavailable):
        gc.issue(store, initial_value_paise=50000, pepper=PEPPER, code="WDGC0000TEST0001",
                 clock=lambda: 1700000000.5)


# ── the access-pattern enumeration (HIGH-3 / DECISION 5) ───────────────────────

def test_every_dynamodb_access_is_an_exact_key_operation_or_the_status_index_query():
    """Enumerates the call sites. A sentence saying "no scan" is not a gate.

    Every `get_item` / `put_item` / `update_item` / `delete_item` names a fully specified partition
    key, and the single `query` is on `status-index`. There is no prefix query and no second index,
    which is what DECISION 5 bought by moving the hold-existence fact onto the card row: a decision
    that gates money cannot be made from a scan, and it cannot be made from a GSI either, because a
    GSI is eventually consistent.
    """
    exact = {"get_item", "put_item", "update_item", "delete_item"}
    seen = {"query": 0, "scan": 0}
    for node in ast.walk(TREE):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        operation = node.func.attr
        if operation == "scan":
            seen["scan"] += 1
        elif operation == "query":
            seen["query"] += 1
        elif operation in exact:
            rendered = ast.unparse(node)
            assert "Key=" in rendered or "Item=" in rendered, (
                f"line {node.lineno}: {operation} without an explicit key")
            assert "IndexName" not in rendered
    assert seen["scan"] == 0, "the gift-card store must never scan"
    assert seen["query"] == 1, "exactly one query, on status-index"

    query = next(node for node in ast.walk(TREE)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "query")
    owner = next(node for node in ast.walk(TREE)
                 if isinstance(node, ast.FunctionDef)
                 and any(call is query for call in ast.walk(node)))
    assert owner.name == "list_by_status"
    assert "STATUS_INDEX" in ast.unparse(owner)

    # And at runtime: the fake raises on a scan and on a query against an undeclared index.
    store = table()
    with pytest.raises(AssertionError):
        store.scan()


def test_the_transaction_has_exactly_one_call_site_and_two_callers():
    """Presence and location only, and the location is the point.

    Three facts over one shared `FunctionDef`-owner walk:
      1. exactly ONE `transact_write_items` call exists in the module;
      2. its owning function is `_transact_with_retry`, so the bounded retry, the jitter and the
         injected sleeper exist once rather than per committer;
      3. `_transact_with_retry` is called from exactly `_commit_redemption` and `_commit_void`.

    Fact 3 needs its own predicate, because the gate above finds only ATTRIBUTE calls and
    `_transact_with_retry(...)` is a bare name. And nothing here `ast.unparse`s the transaction
    call looking for `TableName`/`Key`: the items are assembled in separate assignments, so that
    assertion would fail against correct code - the shape is measured at runtime by
    `assert_transaction_items_are_exact_key_updates` instead.
    """
    transaction_calls = [node for node in ast.walk(TREE)
                         if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute)
                         and node.func.attr == "transact_write_items"]
    assert len(transaction_calls) == 1, (
        "one call site, so the retry policy cannot diverge between the two committers")

    wrapper_calls = [node for node in ast.walk(TREE)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                     and node.func.id == "_transact_with_retry"]
    assert wrapper_calls, "the wrapper must actually be called"

    def owner_of(target):
        return next(node.name for node in ast.walk(TREE)
                    if isinstance(node, ast.FunctionDef)
                    and any(call is target for call in ast.walk(node)))

    assert owner_of(transaction_calls[0]) == "_transact_with_retry"
    assert {owner_of(call) for call in wrapper_calls} == {"_commit_redemption", "_commit_void"}


def test_marshal_is_byte_identical_to_boto3s_type_serializer():
    """The hand-written marshaller is PINNED, not asserted.

    `gift_card_store.py` may not import `boto3` at all - the gate above walks every
    `ast.Import`/`ast.ImportFrom`, so moving the import into a function body would not help
    either - so the AttributeValue shape is hand-written there and the equivalence is measured
    HERE, in `tests/`, where botocore is already a dependency. That keeps the module's
    import-free guarantee and still catches a divergence from boto3 in the one place that can
    see both.

    `_marshal` additionally refuses a `float` and a `Decimal` and a `bool`-as-amount, which is
    strictly stricter than `TypeSerializer` on this path rather than different.
    """
    from boto3.dynamodb.types import TypeSerializer

    serialise = TypeSerializer().serialize
    values = [0, 1, -1, 150000, -150000, gc.MAX_VALUE_PAISE, -gc.MAX_VALUE_PAISE,
              NOW, True, False,
              gc.PREFIX_CARD + digest_of(), gc.PREFIX_CLAIM + digest_of() + "#attempt-1",
              gc.STATUS_ACTIVE, "attempt-1"]
    for value in values:
        assert gc._marshal(value) == serialise(value), value

    # Measured, and the reason the exact-type check is not decoration.
    with pytest.raises(TypeError):
        serialise(1.5)
    for refused in (1.5, Decimal("150000"), None, [], {}):
        with pytest.raises(gc.GiftCardValidationError) as refusal:
            gc._marshal(refused)
        assert refusal.value.code == "UNMARSHALABLE_VALUE"


def test_no_branch_reads_the_post_commit_balance_observation():
    """`balanceAfterPaise` is an OBSERVATION, so it must never become an input to a decision.

    `TransactWriteItems` returns no `ALL_NEW`, so the figure is a separate read that may already
    include a later interleaved move. Every site that touches it is a WRITE; this asserts that
    structurally so a future `if row["balanceAfterPaise"] ...` cannot appear quietly.
    """
    observations = ("balanceAfterPaise", "voidBalanceAfterPaise")
    for node in ast.walk(TREE):
        # A subscript read, `row["balanceAfterPaise"]` or `.get("balanceAfterPaise")`.
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            assert node.slice.value not in observations, (
                f"line {node.lineno}: the post-commit balance is read, not written")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)):
            assert node.args[0].value not in observations, (
                f"line {node.lineno}: the post-commit balance is read, not written")


def test_the_status_index_is_sparse_so_only_cards_enter_it():
    """Transactions, claims, holds and pointer rows carry no `status`, so a staff list is bounded
    by the number of CARDS rather than by the size of the ledger."""
    store = table()
    issue(store, value_paise=50000)
    gc.redeem(store, code_hash=digest_of(), attempt_id="attempt-1", amount_paise=1000,
              clock=clock())
    page = gc.list_by_status(store, gc.STATUS_ACTIVE)
    assert len(page["Items"]) == 1
    assert page["Items"][0][gc.KEY_ATTRIBUTE].startswith(gc.PREFIX_CARD)

    for key, row in store.rows.items():
        if not key.startswith(gc.PREFIX_CARD) or key.startswith(gc.PREFIX_CARD_ID):
            assert gc.STATUS_ATTRIBUTE not in row, f"{key} would enter status-index"


def test_the_store_holds_no_boto3_client_and_reads_no_secret_itself():
    """Injected table resource, injected clock, injected secret reader. That is what makes every
    test above run offline - and it is also the structural form of the lazy-secret rule: this
    module cannot read a secret at import even by accident.

    Over the AST rather than the text, for the same reason the vocabulary gate walks the AST: the
    paragraph explaining why no boto3 client lives here necessarily contains the word `boto3`.
    """
    imports = {alias.name.split(".")[0] for node in ast.walk(TREE)
               if isinstance(node, ast.Import) for alias in node.names}
    imports |= {(node.module or "").split(".")[0] for node in ast.walk(TREE)
                if isinstance(node, ast.ImportFrom)}
    assert "boto3" not in imports
    assert "botocore" not in imports
    assert "os" not in imports, "an env-var read here would be ambient configuration"

    attributes = {node.func.attr for node in ast.walk(TREE)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("get_secret_value", "batch_get_secret_value", "client", "resource"):
        assert forbidden not in attributes

    # The pepper arrives through a reader called at the moment it is needed.
    calls = []

    def reader(secret_id):
        calls.append(secret_id)
        return {gc.PEPPER_FIELD: PEPPER}

    assert gc.read_pepper(reader) == PEPPER
    assert calls == [gc.SECRET_ID]


def test_a_storage_failure_is_never_reported_as_absence():
    """A throttle allowed to look like "no such card" would refuse a live card; worse, on the
    redeem path it would look like an unclaimed one and admit a second deduction."""
    store = table()
    issue(store, value_paise=50000)
    store.arm_failure("get_item", RuntimeError("ProvisionedThroughputExceededException"))
    with pytest.raises(gc.GiftCardStoreUnavailable):
        gc.get_card(store, code_hash=digest_of())


def test_a_code_hash_is_validated_so_a_raw_code_cannot_become_a_key():
    """The one mistake that would put bearer value into a key, refused by shape."""
    store = table()
    for bad in ("WDGC0000TEST0001", "", "zz", digest_of().upper(), None, 7):
        with pytest.raises(gc.GiftCardValidationError):
            gc.get_card(store, code_hash=bad)


def test_a_malformed_code_answers_exactly_as_an_unknown_one():
    """Three distinct answers for a malformed code, an unknown code and a wrong PIN would turn the
    endpoint into a code-validity oracle."""
    for bad in ("short", "has spaces here", "x" * 21, None, 7, True):
        with pytest.raises(gc.GiftCardNotFound) as refusal:
            gc.normalise_code(bad)
        assert refusal.value.code == "GIFT_CARD_NOT_FOUND"
        assert refusal.value.status == 404


def test_a_code_is_nfkc_normalised_and_upper_cased_before_it_is_hashed():
    """A fullwidth code must not become a second card that looks identical to a customer."""
    assert gc.normalise_code("wdgc0000test0001") == "WDGC0000TEST0001"
    assert gc.code_hash("ＷＤＧＣ０００ＴＥＳＴ０１", pepper=PEPPER) == \
        gc.code_hash("WDGC000TEST01", pepper=PEPPER)


def test_the_currency_is_compared_explicitly_and_never_inferred():
    assert gc.assert_currency("INR") == "INR"
    assert gc.assert_currency("inr") == "INR"
    with pytest.raises(gc.CurrencyNotSupported):
        gc.assert_currency("USD")
    with pytest.raises(gc.MissingCurrency):
        gc.assert_currency(None)
    assert gc.assert_currency(None, required=False) == "INR"


def test_a_wix_order_pointer_binds_one_attempt_and_reports_a_second_binding():
    """`GCWIXORDER#` is written at writeback time, when `wixOrderId` first exists (SEAM-G10). A
    second binding for the same Wix order is REPORTED rather than overwriting the first."""
    store = table()
    first = gc.bind_wix_order(store, wix_order_id="wix-order-1", attempt_id="attempt-1",
                              clock=clock())
    second = gc.bind_wix_order(store, wix_order_id="wix-order-1", attempt_id="attempt-2",
                               clock=clock())
    assert first == {"bound": True, "paymentAttemptId": "attempt-1"}
    assert second == {"bound": False, "paymentAttemptId": "attempt-1"}
    assert gc.resolve_attempt(store, wix_order_id="wix-order-1") == "attempt-1"


def test_a_card_resolves_by_our_own_id_through_a_pointer_row():
    """`GET /gift-cards/{giftCardId}` needs this, and the alternatives are a `Scan` or a GSI. A
    pointer row is the same device `GCTXNID#` already is, and it keeps every access exact-key."""
    store = table()
    issued = issue(store, value_paise=50000)
    resolved = gc.get_card_by_id(store, gift_card_id=issued["card"]["giftCardId"])
    assert resolved[gc.KEY_ATTRIBUTE] == gc.PREFIX_CARD + digest_of()
    assert gc.get_card_by_id(store, gift_card_id="00000000-0000-7000-8000-000000000000") is None


def test_an_invoice_create_reads_a_card_and_writes_no_evidence_onto_the_ledger():
    """DECISION 3, from the ledger's side: an invoice VERIFIES and records; it never debits.

    `invoice-engine.create_invoice` writes `giftCardRequiredPaise` / `giftCardCodeHash` /
    `giftCardRedeemedPaise` onto the INVOICE row, which is a different table. This asserts the
    consequence here, where the liability lives: everything that path does to a card is a read, so
    `balancePaise` is byte-for-byte unchanged, no hold attribute appears, and no transaction row is
    written.

    It matters because an invoice can sit unpaid for days. A hold or a debit taken at create would
    strand a customer's balance against a document nobody ever paid, and `is_fully_settled` would
    then read a `GC_HELD` stage that no producer ever advances - which is the same failure that
    keeps `POST /gift-cards/hold` from existing at all.
    """
    store = table()
    issued = issue(store, value_paise=50000)
    key = issued["card"][gc.KEY_ATTRIBUTE]
    before = dict(store.rows[key])

    # Exactly what the invoice path does: resolve the card by HMAC, check it is spendable, compare
    # the currency explicitly, read the balance.
    digest = gc.code_hash(issued["code"], pepper=PEPPER)
    card = gc.get_card(store, code_hash=digest)
    spendable = gc.assert_spendable(card, now_ms=NOW_MS)
    gc.assert_currency(spendable.get("currency"))
    assert int(spendable["balancePaise"]) == 50000

    # The evidence the invoice stores, built from the attribute names the settlement ladder owns.
    # It is a mapping destined for another table; nothing here writes it to the ledger.
    evidence = {
        gcs.CODE_HASH_ATTR: digest,
        gcs.REQUIRED_PAISE_ATTR: 30000,
        gcs.REDEEMED_PAISE_ATTR: 0,
    }
    assert set(evidence) <= gcs.EVIDENCE_KEYS
    assert evidence[gcs.REDEEMED_PAISE_ATTR] == 0, "nothing has been redeemed at create"

    assert store.rows[key] == before
    assert store.rows[key]["balancePaise"] == 50000
    assert gc.HOLD_ATTEMPT_ATTRIBUTE not in store.rows[key]
    assert gc.CLAIM_ATTEMPT_ATTRIBUTE not in store.rows[key]
    assert _markers_on(store, gc.PREFIX_TRANSACTION) == []
    assert _markers_on(store, gc.PREFIX_HOLD) == []
    # And every access was a read.
    assert {name for name, _ in store.calls} == {"get_item"}
