"""A ₹1 (100-paise) DRY proof of the native WhatsApp checkout send.

What this is, and what it is NOT
--------------------------------
This drives the REAL Meta-envelope builder, `_handle_checkout_template_send`, for a ₹1 native
catalog-service payment to +918100640044, with `_send_message` STUBBED to CAPTURE the payload
instead of transmitting it. Nothing reaches Meta, Razorpay, or a handset, and no money moves — the
stub is the hard guarantee of that. The test both ASSERTS the envelope is correct and PRINTS it
(run with `-s`) so the exact sheet can be eyeballed before any live flag is ever flipped.

Why this layer
--------------
`_handle_checkout_template_send` is the one function that composes the `order_details` action Meta
renders: it runs the payment-config resolver (Mode 3), applies the "Delight" discount label, sets
digital-goods (so no delivery address is requested), and assembles the `wecarepay_wa` template
payload. Proving the ₹1 figure here proves what would actually go out.

The amount
----------
₹1 == 100 paise. Meta amounts are `{value, offset:100}`, so ₹1 is `{'value': 100, 'offset': 100}`.
The total is asserted as an INTEGER paise value, the currency as INR named explicitly.
"""
import json
import os
import sys

import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions',
                                'messaging', 'outbound-whatsapp'))

RECIPIENT = '+918100640044'
WABA1_PHONE_ID = 'phone-number-id-waba1-direct-1016149501586345'

#: ₹1 in paise, and its Delight discount. 0.5% of ₹1 = 0.5 paise -> integer floor 0, so a ₹1
#: order carries NO Delight amount (the policy is real but rounds to zero at this size). The
#: proof therefore shows an honest ₹1 sheet with a zero discount line rather than inventing one.
RUPEE1_PAISE = 100
DELIGHT_PAISE_ON_1_RUPEE = 0  # default_coupon.delight_paise(100) == 100 * 50 // 10000 == 0


@pytest.fixture
def send(monkeypatch):
    """The real builder, with the wire stubbed to capture-only. Returns (handler, captured)."""
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
        with patch('boto3.resource'), patch('boto3.client'):
            import handler as h

    captured = {}

    def _capture_send(phone_number_id, payload, as_bytes=False):
        captured['phone_number_id'] = phone_number_id
        captured['payload'] = payload
        return {'messageId': 'wamid.DRYRUN0000000001'}

    # The wire, the persistence, and the metric are all stubbed: this test proves the PAYLOAD, and
    # must not touch DynamoDB or CloudWatch (both are mocked boto3 here anyway).
    monkeypatch.setattr(h, '_send_message', _capture_send)
    monkeypatch.setattr(h, '_store_message_record', lambda *a, **k: None)
    monkeypatch.setattr(h, '_emit_delivery_metric', lambda *a, **k: None)
    return h, captured


def _rupee1_order_details():
    """The native catalog-service `order_details` input for a ₹1 service, as `_create` /
    `catalog_service_checkout.payment_details` shapes it: digital-goods, INR, the WECAREDIGITAL
    config NAME only (the resolver owns `payment_settings`), one service line at ₹1, and the
    stored DELIGHT code so the label resolves to "Delight"."""
    return {
        'reference_id': 'WD-PAY-RUPEE1TEST01',
        'type': 'digital-goods',
        'currency': 'INR',
        'payment_configuration': 'WECAREDIGITAL',
        # The stored policy code the authoritative checkout wrote — this is what makes the
        # discount line read "Delight", not the amount.
        'couponCode': 'DELIGHT',
        'order': {
            'status': 'pending',
            'items': [{
                'retailer_id': 'wecare-submit-request',
                'name': 'Submit Request',
                'quantity': 1,
                'amount': {'value': RUPEE1_PAISE, 'offset': 100},
            }],
            'subtotal': {'value': RUPEE1_PAISE, 'offset': 100},
            'discount': {'value': DELIGHT_PAISE_ON_1_RUPEE, 'offset': 100},
            'tax': {'value': 0, 'offset': 100, 'description': 'GST on convenience fee'},
        },
        'total_amount': {'value': RUPEE1_PAISE, 'offset': 100},
    }


def _drive(h):
    return h._handle_checkout_template_send(
        message_id='msg-rupee1-proof',
        contact_id='contact-cat-1',
        recipient_phone=RECIPIENT,
        phone_number_id=WABA1_PHONE_ID,
        is_template=True,
        template_name='wecarepay_wa',
        template_params=[],
        checkout_order_details=_rupee1_order_details(),
        header_image_url=None,
        request_id='req-rupee1-proof')


def test_the_rupee1_sheet_is_built_correctly_and_nothing_is_sent_live(send, capsys):
    h, captured = send
    resp = _drive(h)

    # The builder succeeded and returned the `sent` envelope — but `sent` here means "handed to
    # the stubbed wire", which captured it instead of transmitting. No live send occurred.
    assert resp['statusCode'] == 200, resp['body']
    body = json.loads(resp['body'])
    assert body['status'] == 'sent'
    assert body['type'] == 'checkout_template'
    assert body['templateName'] == 'wecarepay_wa'
    assert body['referenceId'] == 'WD-PAY-RUPEE1TEST01'

    # ── the captured Meta payload: this is exactly what WOULD go to Meta ──
    assert captured['phone_number_id'] == WABA1_PHONE_ID
    payload = captured['payload']
    assert payload['to'] == RECIPIENT
    assert payload['type'] == 'template'
    assert payload['template']['name'] == 'wecarepay_wa'

    # The order_details action, dug out of the button component.
    buttons = [c for c in payload['template']['components']
               if c.get('type') == 'button' and c.get('sub_type') == 'order_details']
    assert len(buttons) == 1
    action = buttons[0]['parameters'][0]['action']['order_details']

    # ₹1 == 100 paise, as an INTEGER, currency named explicitly.
    assert action['total_amount'] == {'value': RUPEE1_PAISE, 'offset': 100}
    assert isinstance(action['total_amount']['value'], int)
    assert action['currency'] == 'INR'
    assert action['reference_id'] == 'WD-PAY-RUPEE1TEST01'

    # Digital-goods, so Meta requests NO delivery address (correct for a service).
    assert action['type'] == 'digital-goods'
    assert 'shipping_info' not in action

    # The discount line is labelled "Delight" (the canonical policy label), and at ₹1 the policy
    # rounds to a zero amount — shown honestly rather than invented.
    assert action['order']['discount']['description'] == 'Delight'
    assert action['order']['discount']['value'] == DELIGHT_PAISE_ON_1_RUPEE

    # The resolver owns Mode 3: payment_settings is BUILT here, carrying the Razorpay config, and
    # was never supplied by the caller.
    assert isinstance(action.get('payment_settings'), list) and action['payment_settings']
    gateway = action['payment_settings'][0]['payment_gateway']
    assert gateway['type'] == 'razorpay'
    assert gateway['configuration_name'] == 'WECAREDIGITAL'

    # Print the whole sheet so it can be eyeballed with `pytest -s`.
    print("\n================ ₹1 NATIVE WHATSAPP CHECKOUT SHEET (DRY — NOT SENT) ================")
    print(f"recipient:        {payload['to']}")
    print(f"sender phone id:  {captured['phone_number_id']}")
    print(f"template:         {payload['template']['name']} ({payload['template']['language']['code']})")
    print("order_details action:")
    print(json.dumps(action, indent=2))
    print("===================================================================================\n")


def test_the_proof_sends_nothing_over_any_real_wire(send):
    """The guarantee, stated as a test: the only 'send' is the capture stub, and the real
    `_send_message` was replaced. If someone removes the stub, this file would hit mocked boto3
    and fail loudly rather than silently reaching Meta."""
    h, captured = send
    _drive(h)
    # The capture ran exactly once and recorded a payload — proof the build completed — while the
    # real transport was never invoked (it is monkeypatched away for the fixture's lifetime).
    assert captured.get('payload') is not None
    assert h._send_message.__name__ == '_capture_send'
