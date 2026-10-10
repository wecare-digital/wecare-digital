"""Native catalog service boundaries: product identity, verified owner and message claims.

Inbound catalog amounts are deliberately discarded. Native checkout must still obtain a
Wix-priced snapshot and pass live payment readiness before sending a payable message.
"""
from __future__ import annotations
import re
from typing import Any
from lambda_utils import customer_auth
from . import service_requests, whatsapp_basket

SESSION_PREFIX = 'CATALOGSERVICE#'
ALLOWED = frozenset({'SUBMIT_REQUEST', 'VAULT'})


def finalization_complete(attempt: dict) -> bool:
    return bool(attempt.get('status') == 'PAYMENT_PAID'
                and attempt.get('wixOrderId')
                and attempt.get('finalizationStage') == 'WIX_CART_COMPLETED')


def service_from_lines(lines: list[dict]) -> dict | None:
    relevant = [x for x in lines if service_requests.is_service_product(x.get('productId'))]
    if not relevant:
        return None
    if len(lines) != 1 or len(relevant) != 1:
        raise ValueError('Buy one service at a time in WhatsApp.')
    item = relevant[0]
    kind = service_requests.SERVICE_KIND_BY_VARIANT.get(item.get('variantId'))
    if kind not in ALLOWED or type(item.get('quantity')) is not int or item['quantity'] != 1:
        raise ValueError('Choose one Submit Request or Vault item, quantity 1.')
    return {'kind': kind, 'variantId': item['variantId'], 'productId': item['productId']}


def verified_identity(contact: dict, users: list[dict], phone: str):
    number = whatsapp_basket.e164(phone)
    owner = contact.get('checkoutCustomerId')
    if (not number or whatsapp_basket.is_business_sender(phone) or not owner
            or contact.get('deletedAt') is not None or contact.get('isDeleted')
            or whatsapp_basket.e164(contact.get('phone')) != number or len(users) != 1
            or not users[0].get('Enabled', True)):
        raise customer_auth.CustomerNotAuthorized('verified customer required')
    attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}
    if attrs.get('sub') != owner or attrs.get('phone_number') != number or attrs.get('phone_number_verified') != 'true':
        raise customer_auth.CustomerNotAuthorized('verified customer required')
    # The line above already refused anything but 'true', so the flag is proven rather than
    # assumed and the identity may carry it honestly.
    return customer_auth.CustomerIdentity(customer_id=owner, subject=owner, phone=number,
                                          phone_verified=True)


def selected_session(keys: Any, token: str, contact_id: str, phone: str, now: int) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,80}', token or ''):
        raise customer_auth.CustomerNotAuthorized('session unavailable')
    row = keys.get_item(Key={'orderId': SESSION_PREFIX + token}, ConsistentRead=True).get('Item') or {}
    if (row.get('contactId') != contact_id or row.get('phone') != whatsapp_basket.e164(phone)
            or int(row.get('expiresAt') or 0) <= now or row.get('kind') not in ALLOWED):
        raise customer_auth.CustomerNotAuthorized('session unavailable')
    return row


def url_button_component(button: dict) -> dict:
    suffix, index = button.get('suffix'), button.get('index', 0)
    # This contract is intentionally file identifiers only, not arbitrary URLs or credentials.
    if (not isinstance(suffix, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', suffix)
            or type(index) is not int or not 0 <= index <= 9):
        raise ValueError('invalid dynamic file button')
    return {'type': 'button', 'sub_type': 'url', 'index': str(index),
            'parameters': [{'type': 'text', 'text': suffix}]}


def payment_details(row: dict, quote: Any, reference_id: str, configuration: str, now: int) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,35}', reference_id or '') or not configuration:
        raise ValueError('verified payment configuration and canonical reference required')
    label = 'Submit Request' if row['kind'] == 'SUBMIT_REQUEST' else 'Vault'
    items = [{'retailer_id': 'wix:' + row['productId'] + ':' + row['variantId'],
              'name': label, 'quantity': 1,
              'amount': {'value': quote.collection_before_convenience_paise, 'offset': 100}}]
    if quote.convenience_fee_paise:
        items.append({'retailer_id': 'wecare-convenience-fee', 'name': 'Convenience fee', 'quantity': 1,
                      'amount': {'value': quote.convenience_fee_paise, 'offset': 100}})
    return {'reference_id': reference_id, 'type': 'digital-goods', 'currency': 'INR',
        # The RESOLVER owns `payment_settings` (Mode 3). The inline block that used to be here
        # reached Meta WITHOUT passing `outbound-whatsapp._build_payment_settings` at all, so the
        # WABA1-only refusal, the raw-link refusals and the VALID_PAYMENT_CONFIGS membership
        # check did not apply to this leg. Removing it is a correctness fix, not a cleanup.
        #
        # The NAME still travels, and it has to. `configuration` was used ONLY by that block, so
        # dropping the block alone would make this argument dead, the resolver would fall back to
        # the sender's phone map, and the system could prove one configuration against Meta while
        # telling Meta to use another — with no refusal anywhere. Mirrors the invoice engine,
        # where the reserved string and the sent string are the same string by construction.
        'payment_configuration': configuration,
        'total_amount': {'value': quote.total_payable_paise, 'offset': 100},
        'order': {'status': 'pending', 'items': items,
                  'subtotal': {'value': quote.collection_before_convenience_paise + quote.convenience_fee_paise, 'offset': 100},
                  'tax': {'value': quote.convenience_gst_paise, 'offset': 100, 'description': 'GST on convenience fee'},
                  'expiration': {'timestamp': str(now + 900), 'description': 'Complete payment within 15 minutes'}}}


def meta_ready(readiness: dict, kind: str) -> bool:
    templates = readiness.get('templates') or {}
    for name in ('wecarepay_wa', 'wecare_leave_review', 'wecare_default_download'):
        template = templates.get(name) or {}
        if template.get('name') != name or template.get('status') != 'APPROVED' or template.get('language') != 'en':
            return False
    download = templates['wecare_default_download']
    buttons = [b for c in download.get('components') or [] if c.get('type') == 'BUTTONS'
               for b in c.get('buttons') or []]
    if not buttons or buttons[0].get('type') != 'URL' or buttons[0].get('url') != 'https://wecare.digital/vault/?file={{1}}':
        return False
    if kind == 'SUBMIT_REQUEST':
        flow = readiness.get('flow') or {}
        if flow.get('id') != '1728231914933139' or flow.get('status') != 'PUBLISHED' or flow.get('validation_errors'):
            return False
    return kind in ALLOWED
