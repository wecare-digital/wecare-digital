"""`_handle_cart_order` writes a hand-off and sends a link. It computes no money, and sends nothing
at all while the gate is off.

This file is half additive and half a REMOVAL TEST, and the removal half is the important one. The
replaced implementation read Meta's `item_price` as a `float`, added 18% GST to goods Wix had
already taxed, logged a 2% convenience fee, rewrote every retailer id to `ITEM_n`, and then called
`_send_payment_request` to build an `order_details` / Review-and-Pay message against a Meta payment
configuration this account does not have. The AST assertions at the bottom are what stop any of
that coming back by accident.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
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
from lambda_utils.ecommerce import whatsapp_basket as wb  # noqa: E402

KEYS = "stack-wecare-digital-WixOrderIds"
CONTACTS = "stack-wecare-digital-ContactsTable"
SYSTEM_CONFIG = "stack-wecare-digital-SystemConfigTable"

PRODUCT_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
VARIANT_A = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
PRODUCT_B = "cccccccc-3333-4333-8333-cccccccccccc"
VARIANT_B = "dddddddd-4444-4444-8444-dddddddddddd"

#: A plain fixture subscriber. NOT one of the three business numbers, and not the QA recipient
#: either - no test in this file can reach a live send, but the fixtures stay honest about it.
CUSTOMER = "919876543210"
CONTACT_ID = "wa919876543210"
WAMID = "wamid.HBgMOTE5ODc2NTQzMjEwFQIAEhggQkJDMTIz"


def retailer(product_id: str, variant_id: str) -> str:
    return f"wix:{product_id}:{variant_id}"


def order_message(items=None, *, message_id=WAMID, catalog_id="catalog-1"):
    if items is None:
        items = [{"product_retailer_id": retailer(PRODUCT_A, VARIANT_A), "quantity": 2,
                  "item_price": 499, "currency": "INR"},
                 {"product_retailer_id": retailer(PRODUCT_B, VARIANT_B), "quantity": 1,
                  "item_price": 1299, "currency": "INR"}]
    return {"id": message_id, "from": CUSTOMER, "type": "order",
            "order": {"catalog_id": catalog_id, "product_items": list(items)}}


class _Recorder:
    """Stands in for the Lambda client, so an outbound send is a recorded fact rather than a call."""

    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        payload = kwargs.get("Payload") or "{}"
        body = json.loads(payload)
        inner = body.get("body")
        self.invocations.append({
            "function": kwargs.get("FunctionName"),
            "type": kwargs.get("InvocationType"),
            "message": json.loads(inner) if isinstance(inner, str) else (inner or {}),
        })
        return {"StatusCode": 202}

    def sent(self, interactive_type=None):
        return [call for call in self.invocations
                if interactive_type is None
                or call["message"].get("interactiveType") == interactive_type]


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
    """Turn the gate on for ONE test, at the module constant the SystemConfig default falls back to.

    Never by writing an env var on the real function and never by touching a live-send flag: this
    is a unit-level flip of a default, and nothing in this file can reach Meta.
    """
    monkeypatch.setattr(module, "WA_CATALOG_ORDERS_ENABLED", True)


def run(module, message=None, *, sender=CUSTOMER, contact_id=CONTACT_ID):
    module._handle_cart_order(message or order_message(), contact_id, sender,
                              "phone-number-id-waba1", "request-fixture")


def handoffs(fake):
    return [row for row in fake.all_rows(KEYS)
            if str(row.get("orderId", "")).startswith(wb.TOKEN_PREFIX)]


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


# ── the write ─────────────────────────────────────────────────────────────────


def test_two_wix_lines_write_exactly_one_handoff_row(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)

    rows = handoffs(fake)
    assert len(rows) == 1
    row = rows[0]
    assert row["phone"] == "+" + CUSTOMER
    assert row["channel"] == "whatsapp"
    assert row["sourceMessageId"] == WAMID
    assert row["lineCount"] == 2
    assert [line["quantity"] for line in row["lines"]] == [2, 1]
    assert row["expiresAt"] > row["createdAt"]
    # No money field under any spelling. `item_price` was 499 and 1299 on the message.
    assert not [key for key in row if "paise" in key.lower() or "amount" in key.lower()
                or "price" in key.lower() or "total" in key.lower() or "gst" in key.lower()]
    # Match the structured payload contract. A timestamp or opaque identifier can
    # contain the digits of a price without carrying that price as a money field.
    assert all(set(line) == {"productId", "variantId", "quantity"}
               for line in row["lines"])


def test_the_reply_is_a_cta_link_to_the_cart_and_carries_no_price(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)

    cta = recorder.sent("cta_url")
    assert len(cta) == 1
    data = cta[0]["message"]["interactiveData"]
    token = handoffs(fake)[0]["token"]
    assert data["url"] == f"https://wecare.digital/cart/?basket={token}"
    assert "\u20b9" not in data["body"] and "INR" not in data["body"]
    for amount in ("499", "1299", "1798", "2.5", "2%", "18"):
        assert amount not in data["body"]


def test_the_same_wamid_twice_yields_one_row(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    run(module)

    assert len(handoffs(fake)) == 1
    # And the customer is messaged once: Meta redelivers when OUR ack was lost, not when the
    # reply was, so a second link for one cart would be a duplicate message.
    assert len(recorder.sent("cta_url")) == 1


def test_a_different_cart_from_the_same_customer_gets_its_own_handoff(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    run(module, order_message(message_id="wamid.SECOND"))
    assert len(handoffs(fake)) == 2
    assert len({row["token"] for row in handoffs(fake)}) == 2


def test_a_message_with_no_wamid_still_writes_rather_than_refusing(handler):
    """There is nothing to be idempotent ON without a message id, and refusing a real order over a
    missing field would be the wrong trade. Meta also cannot redeliver under an id it did not send.
    """
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module, order_message(message_id=""))
    assert len(handoffs(fake)) == 1


# ── the refusals ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("business", ["918031830030", "919330994400", "919903300044"])
def test_a_business_number_sender_is_refused_before_any_write(handler, business):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    # Armed so the test fails loudly if the code reaches the table at all, rather than relying on
    # the row count alone.
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


def test_an_all_foreign_cart_writes_nothing_and_sends_nothing(handler):
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


# ── the address prompt, retained ──────────────────────────────────────────────


def test_an_address_is_requested_only_when_none_is_on_file(handler):
    module, fake, recorder, monkeypatch = handler
    enable(module, monkeypatch)
    run(module)
    assert len(recorder.sent("address_message")) == 1

    recorder.invocations.clear()
    fake.Table(CONTACTS).put_item(Item={"id": CONTACT_ID, "shippingAddress": "12 Dalhousie Square"})
    run(module, order_message(message_id="wamid.WITHADDRESS"))
    assert recorder.sent("address_message") == []
    assert len(recorder.sent("cta_url")) == 1


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
    assert "cart_order_handoff_written" in text
    assert "cart_order_handoff_replayed" in text
    assert "cart_order_business_sender_refused" in text
    # `reference_id`-class ids are loggable in full: a wamid is a correlation id, not a secret.
    assert WAMID in text


def test_with_the_gate_off_the_disabled_line_still_masks_the_phone(handler, caplog):
    module, _fake, _recorder, _monkeypatch = handler
    with caplog.at_level("INFO"):
        run(module)
    assert "cart_order_handoff_disabled" in caplog.text
    assert CUSTOMER not in caplog.text


# ── the removal, proved over the AST ──────────────────────────────────────────


def _cart_order_tree() -> ast.FunctionDef:
    tree = ast.parse(HANDLER_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_handle_cart_order":
            return node
    raise AssertionError("_handle_cart_order must keep its name - the dispatch calls it")


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
    replaced, not the entry point."""
    source = HANDLER_PATH.read_text()
    assert "if msg_type == 'order':" in source
    assert "_handle_cart_order(message, contact_id, sender_phone" in source


def test_no_float_and_no_two_percent_fee_survives_in_the_cart_order_path():
    node = _cart_order_tree()
    floats = [child for child in ast.walk(node)
              if isinstance(child, ast.Constant) and isinstance(child.value, float)]
    assert floats == [], "a float literal is back in the cart-order path"
    assert "float" not in _called_names(node)
    assert "round" not in _called_names(node)
    # The old fee and GST constants, in every spelling they appeared in.
    numbers = {child.value for child in ast.walk(node)
               if isinstance(child, ast.Constant) and isinstance(child.value, (int, float))}
    assert not ({0.02, 2.0, 2, 18, 18.0, 0.18} & numbers), \
        "a fee or GST rate constant is back in the cart-order path"


def test_send_payment_request_is_not_reachable_from_a_cart_order():
    """The function stays for its other callers. What is gone is this path's call to it, so no
    `order_details` / Review-and-Pay message is built for a catalogue order and no Meta payment
    configuration is read."""
    called = _called_names(_cart_order_tree())
    assert "_send_payment_request" not in called
    assert "_fetch_catalog_product_names" not in called
    assert "_send_order_status_message" not in called
    # Nor indirectly, through the one helper this path does delegate to.
    source = HANDLER_PATH.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "_request_shipping_address", "_catalog_orders_enabled", "_handoff_url",
                "_phone_suffix"):
            assert "_send_payment_request" not in _called_names(node)


def test_item_price_is_not_read_anywhere_on_this_path():
    node = _cart_order_tree()
    strings = {child.value for child in ast.walk(node)
               if isinstance(child, ast.Constant) and isinstance(child.value, str)}
    assert "item_price" not in strings
    assert "product_items" not in strings, "parsing belongs to whatsapp_basket, not the handler"


def test_the_payment_status_vocabulary_import_survives():
    """This file is in `CONSULTING_FILES` in `tests/test_payment_vocabulary_at_decision_points.py`.
    The import has to stay, and no raw `captured` literal may be introduced by this diff."""
    source = HANDLER_PATH.read_text()
    assert "from lambda_utils import payment_status as pay_status" in source
    node = _cart_order_tree()
    strings = {child.value for child in ast.walk(node)
               if isinstance(child, ast.Constant) and isinstance(child.value, str)}
    assert "captured" not in strings and "paid" not in strings
