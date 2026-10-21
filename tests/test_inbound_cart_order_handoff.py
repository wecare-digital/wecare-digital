"""`_handle_cart_order` parses a catalogue cart and drives the NATIVE ORDER_DETAILS money leg.

THE AUTHORIZED CONTRACT (owner-authorised, FEAT-002). With the gate on and a verified customer, a
product cart reaches a PRICED native payment send through the unified checkout machinery: the
inbound handler invokes `wecare-checkout:live` with `internalAction == 'prepareNativeCart'`,
passing variants and integer quantities ONLY. The amount, the single `PAYREF#` reservation and the
approved-template send all live in `ecommerce/checkout`, never here.

This file is HALF a behaviour test and HALF a removal test, and the removal half is the important
one. The deleted sender read Meta's `item_price` as a `float`, added 18% GST, logged a 2%
convenience fee, rewrote retailer ids to `ITEM_n`, and minted a `WD-PAY` reference reserved
nowhere. The AST assertions at the bottom keep every one of those from coming back: the inbound
cart path contains no float money arithmetic, no 2%/18% fee-or-GST constant, does not read
`item_price` as a price, and mints no hand-built `WD-PAY` reference. Pricing and reservation are
proven server-side in `tests/test_checkout_handler.py` (the `prepareNativeCart` / `_create` leg).
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"
for extra in (ROOT / "amplify/functions/shared",
              HANDLER_PATH.parent,
              HANDLER_PATH.parent / "modules",
              Path(__file__).parent):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils.ecommerce import meta_catalog_sync  # noqa: E402
from lambda_utils.ecommerce import whatsapp_basket as wb  # noqa: E402

KEYS = "stack-wecare-digital-CommerceKeys"
CONTACTS = "stack-wecare-digital-ContactsTable"
SYSTEM_CONFIG = "stack-wecare-digital-SystemConfigTable"

PRODUCT_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
VARIANT_A = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
PRODUCT_B = "cccccccc-3333-4333-8333-cccccccccccc"
VARIANT_B = "dddddddd-4444-4444-8444-dddddddddddd"

#: A plain fixture subscriber. NOT one of the three business numbers, and not the QA recipient
#: either.
CUSTOMER = "919876543210"
CONTACT_ID = "wa919876543210"
WAMID = "wamid.HBgMOTE5ODc2NTQzMjEwFQIAEhggQkJDMTIz"

#: The AWS-style WABA1 phone id — the only sender `wa_payment_request.PAYMENT_SENDERS` permits,
#: and what the inbound handler passes through to `prepareNativeCart`.
WABA1_PHONE_ID = "phone-number-id-waba1-direct-1016149501586345"

CHECKOUT_FUNCTION = "wecare-checkout:live"


def retailer(product_id: str, variant_id: str) -> str:
    """The Meta catalogue retailer id for one ProductsTable line, from its one owner."""
    return meta_catalog_sync.retailer_id(product_id, variant_id)


def order_message(items=None, *, message_id=WAMID, catalog_id="catalog-1"):
    if items is None:
        items = [{"product_retailer_id": retailer(PRODUCT_A, VARIANT_A), "quantity": 2,
                  "item_price": 499, "currency": "INR"},
                 {"product_retailer_id": retailer(PRODUCT_B, VARIANT_B), "quantity": 1,
                  "item_price": 1299, "currency": "INR"}]
    return {"id": message_id, "from": CUSTOMER, "type": "order",
            "order": {"catalog_id": catalog_id, "product_items": list(items)}}


class _Recorder:
    """Stands in for the Lambda client. Records every invoke and answers a `RequestResponse`
    checkout `prepareNativeCart` with a 200 `NATIVE_CART_PREPARED` outcome, so the inbound leg
    exercises its success path without reaching the real checkout Lambda."""

    def __init__(self):
        self.invocations = []
        self.outcome = {"outcome": "NATIVE_CART_PREPARED", "statusCode": 200,
                        "status": "PAYMENT_REQUEST_SENT", "paymentAttemptId": "pa-fixture"}

    def invoke(self, **kwargs):
        payload = kwargs.get("Payload") or "{}"
        body = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        inner = body.get("body")
        self.invocations.append({
            "function": kwargs.get("FunctionName"),
            "type": kwargs.get("InvocationType"),
            "internalAction": body.get("internalAction"),
            "payload": body,
            "message": json.loads(inner) if isinstance(inner, str) else (inner or {}),
        })
        return {"StatusCode": 202, "Payload": _Blob(json.dumps(self.outcome).encode("utf-8"))}

    def checkout_calls(self):
        return [c for c in self.invocations
                if c["internalAction"] == "prepareNativeCart"]

    def sent(self, interactive_type=None):
        return [call for call in self.invocations
                if interactive_type is None
                or call["message"].get("interactiveType") == interactive_type]


class _Blob:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("COMMERCE_KEYS_TABLE", KEYS)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS)
    monkeypatch.setenv("SYSTEM_CONFIG_TABLE", SYSTEM_CONFIG)
    monkeypatch.delenv("WA_CATALOG_ORDERS_ENABLED", raising=False)
    spec = importlib.util.spec_from_file_location("inbound_cart_handoff_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fake = FakeDynamo(keys={KEYS: "orderId", CONTACTS: "id", SYSTEM_CONFIG: "id"})
    recorder = _Recorder()
    monkeypatch.setattr(module, "dynamodb", fake)
    monkeypatch.setattr(module, "lambda_client", recorder)
    return module, fake, recorder, monkeypatch


def enable(module, monkeypatch):
    """Turn the gate on for ONE test, at the module constant the SystemConfig default falls back to."""
    monkeypatch.setattr(module, "WA_CATALOG_ORDERS_ENABLED", True)


def run(module, message=None, *, sender=CUSTOMER, contact_id=CONTACT_ID,
        phone_number_id=WABA1_PHONE_ID):
    module._handle_cart_order(message or order_message(), contact_id, sender,
                              phone_number_id, "request-fixture")


def indexes(fake):
    return [row for row in fake.all_rows(KEYS)
            if str(row.get("orderId", "")).startswith(
                (wb.MESSAGE_INDEX_PREFIX, wb.CONTENT_INDEX_PREFIX))]


# ── the gate ──────────────────────────────────────────────────────────────────


def test_with_the_gate_off_nothing_is_written_and_nothing_is_sent(handler):
    module, fake, recorder, _ = handler
    assert module.WA_CATALOG_ORDERS_ENABLED is False, "the default must be off"
    run(module)
    assert fake.count(KEYS) == 0
    assert recorder.invocations == []


def test_a_system_config_read_failure_does_not_turn_the_gate_on(handler):
    module, fake, recorder, monkeypatch = handler
    monkeypatch.setattr(module.dynamodb, "Table",
                        lambda name: (_ for _ in ()).throw(RuntimeError("config unavailable")))
    assert module._catalog_orders_enabled() is False


def test_system_config_can_turn_the_gate_on_without_a_deploy(handler):
    module, fake, _recorder, _ = handler
    fake.Table(SYSTEM_CONFIG).put_item(
        Item={"id": "whatsapp_catalog_orders", "configValue": "true"})
    assert module._catalog_orders_enabled() is True
    fake.Table(SYSTEM_CONFIG).put_item(
        Item={"id": "whatsapp_catalog_orders", "configValue": "false"})
    assert module._catalog_orders_enabled() is False


# ── the money leg ───────────────────────────────────────────────────────────


def test_a_product_cart_invokes_the_checkout_native_cart_action_with_variants_only(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)

    calls = recorder.checkout_calls()
    assert len(calls) == 1
    call = calls[0]
    # The seam is the unified checkout, request/response, the general-cart twin of the service leg.
    assert call["function"] == CHECKOUT_FUNCTION
    assert call["type"] == "RequestResponse"
    payload = call["payload"]
    assert payload["contactId"] == CONTACT_ID
    assert payload["phoneNumberId"] == WABA1_PHONE_ID
    assert payload["senderPhone"] == CUSTOMER
    # Variants and integer quantities ONLY. No money field under any spelling, and NOT the Meta
    # `item_price` values 499 / 1299.
    lines = payload["lines"]
    assert [line["quantity"] for line in lines] == [2, 1]
    assert all(set(line) == {"productId", "variantId", "quantity"} for line in lines)
    blob = json.dumps(payload)
    for money in ("item_price", "499", "1299", "amount", "paise", "price", "gst"):
        assert money not in blob.lower()


def test_the_same_wamid_twice_invokes_checkout_once(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    run(module)

    # Exactly one index row, and the checkout native-cart action reached exactly once: a
    # redelivery cannot produce a second attempt or a second send.
    assert len(indexes(fake)) == 1
    assert len(recorder.checkout_calls()) == 1


def test_a_message_with_no_wamid_still_dedupes_on_its_content_key(handler):
    """No wamid to key on, so the deterministic content key is the dedup. The SAME cart from the
    SAME customer twice still invokes checkout once."""
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module, order_message(message_id=""))
    run(module, order_message(message_id=""))

    rows = indexes(fake)
    assert len(rows) == 1
    assert str(rows[0]["orderId"]).startswith(wb.CONTENT_INDEX_PREFIX)
    assert len(recorder.checkout_calls()) == 1


def test_a_different_cart_from_the_same_customer_gets_its_own_invoke(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    run(module, order_message(message_id="wamid.SECOND"))
    assert len(recorder.checkout_calls()) == 2


# ── rollback on a failed prepare, so a redelivery can retry ─────────────────


class _Raiser:
    """A Lambda client that raises only on the `prepareNativeCart` checkout invoke, standing in
    for a transient checkout outage. Other invokes (the in-chat address request) succeed, so the
    test isolates the checkout failure. Records the checkout attempts so we can prove a retry
    actually re-invokes."""

    def __init__(self):
        self.checkout_invocations = []

    def invoke(self, **kwargs):
        payload = kwargs.get("Payload") or b"{}"
        body = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        if body.get("internalAction") == "prepareNativeCart":
            self.checkout_invocations.append(kwargs.get("FunctionName"))
            raise RuntimeError("checkout momentarily unavailable")
        return {"StatusCode": 202, "Payload": _Blob(b"{}")}

    def checkout_calls(self):
        return list(self.checkout_invocations)


def test_a_raising_invoke_rolls_the_index_back_so_a_redelivery_retries(handler):
    """If the `prepareNativeCart` invoke raises, no attempt was reserved and no template went out.
    The resolve-before-generate index row must NOT survive, so Meta's redelivery of the SAME cart
    re-invokes checkout rather than being swallowed as a replay."""
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    raiser = _Raiser()
    monkeypatch.setattr(module, "lambda_client", raiser)

    run(module)
    # The failed prepare left no index behind.
    assert indexes(fake) == []
    assert len(raiser.checkout_calls()) == 1

    # A redelivery of the same cart is now free to retry.
    run(module)
    assert len(raiser.checkout_calls()) == 2
    assert indexes(fake) == []


def test_a_non_prepared_outcome_rolls_the_index_back_so_a_redelivery_retries(handler):
    """A reachable checkout that answers anything other than NATIVE_CART_PREPARED reserved no
    attempt. Same contract as a raising invoke: the index is cleared and a redelivery retries."""
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    recorder.outcome = {"outcome": "NATIVE_CART_NOT_PREPARED", "statusCode": 409}

    run(module)
    assert indexes(fake) == []
    assert len(recorder.checkout_calls()) == 1

    # The redelivery retries because nothing is holding the dedup key.
    run(module)
    assert len(recorder.checkout_calls()) == 2
    assert indexes(fake) == []

    # And once checkout recovers and prepares the cart, the index persists again.
    recorder.outcome = {"outcome": "NATIVE_CART_PREPARED", "statusCode": 200}
    run(module)
    assert len(recorder.checkout_calls()) == 3
    assert len(indexes(fake)) == 1


def test_a_successful_prepare_keeps_the_index_so_a_redelivery_invokes_once(handler):
    """The idempotency guarantee is intact on the SUCCESS path: a prepared cart leaves its index
    row in place, so a redelivery of the same wamid collapses to exactly one invoke and one send,
    and the rollback delete is never taken."""
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)

    run(module)
    assert len(recorder.checkout_calls()) == 1
    assert len(indexes(fake)) == 1

    run(module)                                   # the redelivery
    assert len(recorder.checkout_calls()) == 1    # still one: collapsed as a replay
    assert len(indexes(fake)) == 1
    # No rollback delete ran on the success path; the index row is load-bearing and untouched.
    assert (KEYS, "delete_item") not in fake.calls


def test_the_rollback_never_deletes_a_concurrent_winners_index(handler):
    """The rollback delete is conditional on the token WE wrote. If a concurrent winner already
    holds the index row under its own token (its prepare is the live one), a later loser whose
    invoke fails must NOT clear that row: the token-guarded delete misses, so the single-attempt
    invariant is never broken by a late loser's rollback."""
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    raiser = _Raiser()
    monkeypatch.setattr(module, "lambda_client", raiser)

    # Pre-seed the index row with a DIFFERENT token, as a concurrent winner would have left it.
    winner_token = "winner-token-not-ours"
    order_id = wb.message_key(WAMID)
    fake.Table(KEYS).put_item(Item={
        "orderId": order_id, "token": winner_token,
        "handoffId": wb.handoff_key(winner_token), "indexType": "wamid", "createdAt": 1})

    run(module)
    # Our conditional put loses (the winner's row exists), so this delivery is a replay and never
    # invokes; the winner's row stands untouched and its token is intact.
    rows = indexes(fake)
    assert len(rows) == 1
    assert rows[0]["token"] == winner_token
    assert raiser.checkout_calls() == []

    # Directly exercise the rollback helper with a losing token: it must leave the winner's row.
    module._rollback_cart_order_index(fake.Table(KEYS), order_id, "a-losers-token", "req")
    rows = indexes(fake)
    assert len(rows) == 1
    assert rows[0]["token"] == winner_token


# ── the refusals (all BEFORE the checkout invoke) ───────────────────────────


@pytest.mark.parametrize("business", ["918031830030", "919330994400", "919903300044"])
def test_a_business_number_sender_is_refused_before_any_write(handler, business):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    monkeypatch.setattr(module.dynamodb, "Table", _refuse_table(module, fake))
    run(module, sender=business)
    assert fake.count(KEYS) == 0
    assert recorder.invocations == []


def _refuse_table(module, fake):
    """A `Table` that answers SystemConfig and fails on anything else, so 'before any write' is
    proved by unreachability rather than by a count that a later cleanup could also produce."""
    def table(name):
        if name == SYSTEM_CONFIG:
            return fake.Table(name)
        raise AssertionError(f"a refused sender must not reach {name}")
    return table


def test_an_all_foreign_cart_writes_nothing_and_invokes_nothing(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module, order_message([{"product_retailer_id": "WD-PARTNER-UP", "quantity": 1},
                               {"product_retailer_id": "htlu35lrs1", "quantity": 2}]))
    assert fake.count(KEYS) == 0
    assert recorder.invocations == []


def test_a_sender_with_no_country_code_is_refused(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module, sender="12")
    assert fake.count(KEYS) == 0
    assert recorder.invocations == []


# ── the address prompt, retained for physical goods ─────────────────────────


def test_an_address_is_requested_for_a_product_cart(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    # The in-chat address collection is retained: the checkout refuses a physical basket with no
    # saved address, so the prompt is what lets the native leg become payable.
    assert len(recorder.sent("address_message")) == 1
    # And the money leg was still driven.
    assert len(recorder.checkout_calls()) == 1


# ── logs ──────────────────────────────────────────────────────────────────────


def test_every_log_line_on_this_path_carries_a_suffix_and_never_a_full_phone(handler, caplog):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    with caplog.at_level("INFO"):
        run(module)
        run(module)                                 # the replay line
        run(module, sender="918031830030")          # the business-number refusal
        run(module, order_message([{"product_retailer_id": "nope", "quantity": 1}],
                                  message_id="wamid.FOREIGN"))
    text = caplog.text
    assert CUSTOMER not in text and "+" + CUSTOMER not in text
    assert '"phone_suffix": "3210"' in text
    assert "cart_order_payment_prepared" in text
    assert "cart_order_payment_replayed" in text
    assert "cart_order_business_sender_refused" in text
    # A wamid is a correlation id, not a secret, so it is loggable in full.
    assert WAMID in text


def test_with_the_gate_off_the_disabled_line_still_masks_the_phone(handler, caplog):
    module, _fake, _recorder, _monkeypatch = handler
    with caplog.at_level("INFO"):
        run(module)
    assert "cart_order_handoff_disabled" in caplog.text
    assert CUSTOMER not in caplog.text


# ── the removal, proved over the AST ──────────────────────────────────────────


def _func_tree(name: str) -> ast.FunctionDef:
    tree = ast.parse(HANDLER_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} must keep its name")


def _cart_order_nodes() -> list:
    """Both halves of the inbound cart money path: the entry parser and the rebuilt sender.

    The safety invariants apply to the whole path, so the AST walks cover `_handle_cart_order`
    AND `_send_payment_request` together — repricing or a self-minted reference is forbidden in
    either one."""
    return [_func_tree("_handle_cart_order"), _func_tree("_send_payment_request")]


def _called_names(node: ast.AST) -> set:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def test_the_dispatch_still_routes_an_order_message_here():
    """The function name and the `msg_type == 'order'` dispatch are load-bearing: the body was
    rebuilt, not the entry point."""
    source = HANDLER_PATH.read_text()
    assert "if msg_type == 'order':" in source
    assert "_handle_cart_order(message, contact_id, sender_phone" in source


def test_the_cart_order_path_reaches_the_rebuilt_money_sender():
    """`_handle_cart_order` delegates the general cart to `_send_payment_request`, which drives the
    native `prepareNativeCart` leg on the unified checkout."""
    called = _called_names(_func_tree("_handle_cart_order"))
    assert "_send_payment_request" in called
    source = HANDLER_PATH.read_text()
    assert "'internalAction': 'prepareNativeCart'" in source


def test_no_float_and_no_fee_or_gst_constant_survives_in_the_cart_order_path():
    for node in _cart_order_nodes():
        floats = [child for child in ast.walk(node)
                  if isinstance(child, ast.Constant) and isinstance(child.value, float)]
        assert floats == [], "a float literal is back in the cart-order path"
        assert "float" not in _called_names(node)
        assert "round" not in _called_names(node)
        # The old fee and GST constants, in every spelling they appeared in.
        numbers = {child.value for child in ast.walk(node)
                   if isinstance(child, ast.Constant) and isinstance(child.value, (int, float))}
        assert not ({0.02, 2.0, 18, 18.0, 0.18} & numbers), \
            "a fee or GST rate constant is back in the cart-order path"


def test_no_hand_built_wd_pay_reference_in_the_cart_order_path():
    """The single `PAYREF#` is minted by the checkout reservation. This path mints no reference of
    its own — no `WD-PAY`, no `uuid` call, no reference-format string."""
    source = HANDLER_PATH.read_text()
    for node in _cart_order_nodes():
        strings = {child.value for child in ast.walk(node)
                   if isinstance(child, ast.Constant) and isinstance(child.value, str)}
        assert not any("WD-PAY" in s for s in strings)
        assert "uuid4" not in _called_names(node)
        assert "uuid" not in _called_names(node)


def test_item_price_is_not_read_anywhere_on_this_path():
    for node in _cart_order_nodes():
        strings = {child.value for child in ast.walk(node)
                   if isinstance(child, ast.Constant) and isinstance(child.value, str)}
        assert "item_price" not in strings
        assert "product_items" not in strings, "parsing belongs to whatsapp_basket, not the handler"


def test_the_payment_status_vocabulary_import_survives():
    """This file is in `CONSULTING_FILES` in `tests/test_payment_vocabulary_at_decision_points.py`.
    The import has to stay, and no raw `captured`/`paid` literal may be introduced by this diff."""
    source = HANDLER_PATH.read_text()
    assert "from lambda_utils import payment_status as pay_status" in source
    for node in _cart_order_nodes():
        strings = {child.value for child in ast.walk(node)
                   if isinstance(child, ast.Constant) and isinstance(child.value, str)}
        assert "captured" not in strings and "paid" not in strings
