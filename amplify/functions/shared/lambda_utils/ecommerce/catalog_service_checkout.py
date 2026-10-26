"""Native catalog service boundaries: product identity, verified owner and message claims.

Inbound catalog amounts are deliberately discarded. Native checkout must still obtain a
ProductsTable-priced snapshot and pass live payment readiness before sending a payable message.
"""
from __future__ import annotations
import re
from typing import Any
from lambda_utils import customer_auth, template_status
from . import meta_catalog_sync, service_requests, whatsapp_basket

SESSION_PREFIX = 'CATALOGSERVICE#'
# Vault only. Submit Request was sold here too, but every dependency of a paid WhatsApp Submit
# Request is gone: its continuation Flow 1107164111921876 reads DEPRECATED on Meta (2026-10-25),
# `paid_submit_request.VARIANT_ID` was wiped with the retired catalogue identities (#712), and
# `service_request_store.request_intent` now requires the original order, which this leg never
# had. A Submit Request session therefore failed only AFTER its customer lock and intent were
# written. The customer is now told up front to start it on the website instead.
ALLOWED = frozenset({'VAULT'})


def finalization_complete(attempt: dict) -> bool:
    """True once the native finalizer committed the order and reconciled its tenders.

    `finalization.finalize` stages INTERNAL_ORDER_CREATED (with the orderId) and then
    ORDER_FINALIZED on the attempt row; ORDER_FINALIZED is its only terminal success stage.
    """
    return bool(attempt.get('status') == 'PAYMENT_PAID'
                and attempt.get('orderId')
                and attempt.get('finalizationStage') == 'ORDER_FINALIZED')


def service_from_lines(lines: list[dict]) -> dict | None:
    relevant = [x for x in lines if service_requests.is_service_product(x.get('productId'))]
    if not relevant:
        return None
    if len(lines) != 1 or len(relevant) != 1:
        raise ValueError('Buy one service at a time in WhatsApp.')
    item = relevant[0]
    kind = service_requests.SERVICE_KIND_BY_VARIANT.get(item.get('variantId'))
    if kind not in ALLOWED or type(item.get('quantity')) is not int or item['quantity'] != 1:
        raise ValueError('Choose one Vault item, quantity 1.')
    return {'kind': kind, 'variantId': item['variantId'], 'productId': item['productId']}


def service_refusal(lines: list[dict]) -> str:
    """Why `service_from_lines` refused `lines`, as the reply the customer should get.

    'unsupported' when a service line is one this leg does not sell, so the answer is the website;
    otherwise 'alone': the service was mixed with other lines, sent more than once, or with a
    quantity other than 1, and sending it again on its own would work.
    """
    for line in lines:
        if (service_requests.is_service_product(line.get('productId'))
                and service_requests.SERVICE_KIND_BY_VARIANT.get(line.get('variantId')) not in ALLOWED):
            return 'unsupported'
    return 'alone'


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


#: An offer token: what `catalogService.sendOffer` mints (`secrets.token_urlsafe(24)`).
OFFER_TOKEN_RE = re.compile(r'[A-Za-z0-9_-]{20,80}')


def quick_reply_component(button: dict) -> dict:
    """The send-time payload of the Vault offer's QUICK_REPLY button.

    Meta returns the payload with the customer's tap. It is only ever `vaultoffer:` and an
    opaque offer token, never a file id, phone number or amount: the token is looked up
    server-side and the tap is then re-proven against the verified sender.
    """
    payload, index = button.get('payload'), button.get('index', 0)
    prefix = 'vaultoffer:'
    if (not isinstance(payload, str) or not payload.startswith(prefix)
            or not OFFER_TOKEN_RE.fullmatch(payload[len(prefix):])
            or type(index) is not int or not 0 <= index <= 9):
        raise ValueError('invalid quick reply button')
    return {'type': 'button', 'sub_type': 'quick_reply', 'index': str(index),
            'parameters': [{'type': 'payload', 'payload': payload}]}


def payment_details(row: dict, quote: Any, reference_id: str, configuration: str, now: int) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,35}', reference_id or '') or not configuration:
        raise ValueError('verified payment configuration and canonical reference required')
    label = 'Submit Request' if row['kind'] == 'SUBMIT_REQUEST' else 'Vault'
    items = [{'retailer_id': meta_catalog_sync.retailer_id(row['productId'], row['variantId']),
              'name': label, 'quantity': 1,
              'amount': {'value': quote.collection_before_convenience_paise, 'offset': 100}}]
    if quote.convenience_fee_paise:
        # Non-catalog line: no synthetic retailer_id (Vault is fee-exempt; kept for safety).
        items.append({'name': 'Convenience fee', 'quantity': 1,
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
    for name in ('wecare_whatapp_native_pay_template', 'wecare_default_download'):
        template = templates.get(name) or {}
        if template.get('name') != name or not template_status.is_sendable(template.get('status')) or template.get('language') != 'en':
            return False
    download = templates['wecare_default_download']
    buttons = [b for c in download.get('components') or [] if c.get('type') == 'BUTTONS'
               for b in c.get('buttons') or []]
    if not buttons or buttons[0].get('type') != 'URL' or buttons[0].get('url') != 'https://wecare.digital/vault/?file={{1}}':
        return False
    return kind in ALLOWED
