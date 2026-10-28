"""Native catalog service boundaries: product identity, verified owner and message claims.

Inbound catalog amounts are deliberately discarded. Native checkout must still obtain a
ProductsTable-priced snapshot and pass live payment readiness before sending a payable message.
"""
from __future__ import annotations
import re
from typing import Any
from lambda_utils import customer_auth, template_status, template_media
from . import meta_catalog_sync, service_requests, whatsapp_basket

SESSION_PREFIX = 'CATALOGSERVICE#'
# Vault and Drop Docs use the one native WhatsApp service-payment rail. Submit Request was sold
# here too, but every dependency of a paid WhatsApp Submit
# Request is gone: its continuation Flow 1107164111921876 reads DEPRECATED on Meta (2026-10-25),
# `paid_submit_request.VARIANT_ID` was wiped with the retired catalogue identities (#712), and
# `service_request_store.request_intent` now requires the original order, which this leg never
# had. A Submit Request session therefore failed only AFTER its customer lock and intent were
# written. The customer is now told up front to start it on the website instead.
ALLOWED = frozenset({'VAULT', 'DROP_DOCS'})


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
        raise ValueError('Choose one supported service item, quantity 1.')
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


def payment_details(row: dict, snapshot: Any, reference_id: str,
                    configuration: str, now: int) -> dict:
    """Build the Vault/Drop Docs ORDER_DETAILS from the frozen checkout snapshot.

    The item price, supply GST, Delight, Express and checkout fee figures are all server-owned
    facts already frozen by checkout. The normal service item explicitly carries the owner-
    approved 2048 WECARE thumbnail; outbound-whatsapp enforces the same image again at send time.
    """
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,35}', reference_id or '') or not configuration:
        raise ValueError('verified payment configuration and canonical reference required')
    quote = snapshot.quote
    frozen = snapshot.frozen_data if isinstance(snapshot.frozen_data, dict) else {}
    frozen_items = frozen.get('items') if isinstance(frozen.get('items'), list) else []
    if len(frozen_items) != 1 or not isinstance(frozen_items[0], dict):
        raise ValueError('catalog service quote must contain one frozen item')
    line = frozen_items[0]
    item_paise = int(line.get('unitPricePaise') or 0) * int(line.get('quantity') or 0)
    if item_paise <= 0:
        raise ValueError('catalog service item price unavailable')

    pricing = frozen.get('pricingMetadata') if isinstance(frozen.get('pricingMetadata'), dict) else {}
    supply_gst_paise = int(pricing.get('supplyGstPaise') or 0)
    discount_paise = int(pricing.get('discountPaise') or 0)
    delivery = frozen.get('delivery') if isinstance(frozen.get('delivery'), dict) else {}
    express_paise = int(delivery.get('paise') or 0)

    labels = {'DROP_DOCS': 'Drop Docs', 'VAULT': 'Vault'}
    label = labels.get(row['kind'], 'Service')
    items = [{
        'retailer_id': meta_catalog_sync.retailer_id(row['productId'], row['variantId']),
        'name': label,
        'quantity': 1,
        'amount': {'value': item_paise, 'offset': 100},
        'image': {'link': template_media.DEFAULT_ORDER_ITEM_THUMBNAIL},
    }]
    if quote.convenience_fee_paise:
        items.append({
            'name': 'Convenience fee',
            'quantity': 1,
            'amount': {'value': int(quote.convenience_fee_paise), 'offset': 100},
        })

    subtotal_paise = item_paise + int(quote.convenience_fee_paise)
    order = {
        'status': 'pending',
        'items': items,
        'subtotal': {'value': subtotal_paise, 'offset': 100},
        'shipping': {'value': express_paise, 'offset': 100, 'description': 'Express'},
        'tax': {
            'value': supply_gst_paise + int(quote.convenience_gst_paise),
            'offset': 100,
            'description': 'GST',
        },
        'expiration': {
            'timestamp': str(now + 900),
            'description': 'Complete payment within 15 minutes',
        },
    }
    if discount_paise:
        order['discount'] = {
            'value': discount_paise,
            'offset': 100,
            'description': 'Delight',
        }
        order['couponCode'] = 'DELIGHT'

    # Prove the sheet closes exactly before it is allowed to leave this process.
    reconciled = (
        subtotal_paise + express_paise
        + supply_gst_paise + int(quote.convenience_gst_paise)
        - discount_paise
    )
    if reconciled != int(quote.total_payable_paise):
        raise ValueError('catalog service ORDER_DETAILS does not reconcile to payable total')

    return {
        'reference_id': reference_id,
        'type': 'digital-goods',
        'currency': 'INR',
        'payment_configuration': configuration,
        'total_amount': {'value': int(quote.total_payable_paise), 'offset': 100},
        'order': order,
    }


def meta_ready(readiness: dict, kind: str) -> bool:
    templates = readiness.get('templates') or {}
    pay = templates.get('wecare_whatapp_native_pay_template') or {}
    if (pay.get('name') != 'wecare_whatapp_native_pay_template'
            or not template_status.is_sendable(pay.get('status')) or pay.get('language') != 'en'):
        return False
    if kind == 'VAULT':
        download = templates.get('wecare_default_download') or {}
        if (download.get('name') != 'wecare_default_download'
                or not template_status.is_sendable(download.get('status'))
                or download.get('language') != 'en'):
            return False
        buttons = [b for comp in download.get('components') or [] if comp.get('type') == 'BUTTONS'
                   for b in comp.get('buttons') or []]
        return bool(buttons and buttons[0].get('type') == 'URL'
                    and buttons[0].get('url') == 'https://wecare.digital/vault/?file={{1}}')
    if kind == 'DROP_DOCS':
        launch = templates.get('drop_docs_flow') or {}
        if (launch.get('name') != 'drop_docs_flow'
                or not template_status.is_sendable(launch.get('status'))
                or launch.get('language') != 'en'):
            return False
        buttons = [b for comp in launch.get('components') or [] if comp.get('type') == 'BUTTONS'
                   for b in comp.get('buttons') or []]
        return bool(buttons and buttons[0].get('type') == 'FLOW'
                    and str(buttons[0].get('flow_id') or '') == '39581903361452878')
    return False
