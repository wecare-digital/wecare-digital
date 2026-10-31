"""Native catalog service boundaries: product identity, verified owner and message claims.

Inbound catalog amounts are deliberately discarded. Native checkout must still obtain a
ProductsTable-priced snapshot and pass live payment readiness before sending a payable message.
"""
from __future__ import annotations
import re
from typing import Any
from lambda_utils import customer_auth, template_status, template_media
from . import service_requests, whatsapp_basket

# Customer-readable Vault item label. Only the WORDING is staff-editable for
# an explicit file-bound send; no client can change the SKU, quantity or amount.
# This exact label is frozen into PaymentAttempt.invoiceLines and rendered on
# the paid GST invoice PNG, so later edits cannot rewrite issued documents.
VAULT_ITEM_DESCRIPTION_DEFAULT = 'Secure document download (24-hour access)'
_VAULT_ITEM_DESCRIPTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'()&/-]{11,59}\\Z")


def valid_vault_item_description(raw: Any) -> bool:
    return (type(raw) is str and 12 <= len(raw) <= 60
            and raw == raw.strip() and '  ' not in raw
            and bool(_VAULT_ITEM_DESCRIPTION.fullmatch(raw))
            and 'http' not in raw.lower())


def vault_item_description(raw: Any) -> str:
    return raw if valid_vault_item_description(raw) else VAULT_ITEM_DESCRIPTION_DEFAULT


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


def payment_details(row: dict, quote: Any, reference_id: str, configuration: str, now: int,
                    *, invoice_lines: dict | None = None) -> dict:
    """Meta Review & Pay from the same canonical breakdown stored on the attempt."""
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,35}', reference_id or '') or not configuration:
        raise ValueError('verified payment configuration and canonical reference required')
    labels = {'SUBMIT_REQUEST': 'Submit Request', 'DROP_DOCS': 'Drop Docs', 'VAULT': 'Vault'}
    label = labels.get(row['kind'], 'Service')

    spec = invoice_lines if isinstance(invoice_lines, dict) else {}
    lines = spec.get('lines') if isinstance(spec.get('lines'), list) else []
    service_line = lines[0] if len(lines) == 1 and isinstance(lines[0], dict) else {}
    unit_paise = int(service_line.get('unitPricePaise') or 0)
    quantity = int(service_line.get('quantity') or 0)
    if unit_paise <= 0 or quantity != 1:
        # Backward-compatible fallback for tests/legacy callers; current checkout always passes
        # invoiceLines. It intentionally cannot invent discount/Express from a quote alone.
        unit_paise = int(quote.collection_before_convenience_paise)
        quantity = 1

    # Meta rejects retailer_id together with an item image in a Review & Pay
    # ORDER_DETAILS action (131009). Keep the approved shared thumbnail used by
    # the successful staff Pay Flow, and omit retailer_id from the Meta payment
    # wire only. Product/variant identity remains bound in the server-owned
    # catalogue session, priced service intent, and payment attempt.
    # Same frozen description as PaymentAttempt.invoiceLines -> paid invoice PNG.
    # Never accept a description from the inbound WhatsApp event or price quote.
    if row['kind'] == service_requests.VAULT:
        label = vault_item_description(service_line.get('name'))
    items = [{
        'name': label, 'quantity': quantity,
        'amount': {'value': unit_paise, 'offset': 100},
        'image': {'link': template_media.DEFAULT_ORDER_ITEM_THUMBNAIL},
    }]
    if quote.convenience_fee_paise:
        # Non-catalog line: no synthetic retailer_id.
        items.append({'name': 'Convenience fee', 'quantity': 1,
                      'amount': {'value': int(quote.convenience_fee_paise), 'offset': 100}})

    supply_gst_paise = int(spec.get('supplyGstPaise') or 0)
    discount_paise = int(spec.get('discountPaise') or 0)
    express_paise = int(spec.get('deliveryPaise') or 0)
    order = {
        'status': 'pending',
        # Meta's subtotal includes the catalog items plus non-catalog fee line. Shipping,
        # discount and fee GST are separate fields and reconcile to total_amount.
        'items': items,
        'subtotal': {'value': unit_paise + int(quote.convenience_fee_paise), 'offset': 100},
        'shipping': {'value': express_paise, 'offset': 100, 'description': 'Express'},
        'tax': {'value': supply_gst_paise + int(quote.convenience_gst_paise), 'offset': 100,
                'description': 'GST'},
        'expiration': {'timestamp': str(now + 900),
                       'description': 'Complete payment within 15 minutes'},
    }
    if discount_paise:
        order['discount'] = {'value': discount_paise, 'offset': 100, 'description': 'Delight'}
        order['couponCode'] = 'DELIGHT'

    reconciled = (
        unit_paise + supply_gst_paise + express_paise - discount_paise
        + int(quote.convenience_fee_paise) + int(quote.convenience_gst_paise)
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
        launch = templates.get('_dropdoc_flow') or {}
        if (launch.get('name') != '_dropdoc_flow'
                or not template_status.is_sendable(launch.get('status'))
                or launch.get('language') != 'en'):
            return False
        buttons = [b for comp in launch.get('components') or [] if comp.get('type') == 'BUTTONS'
                   for b in comp.get('buttons') or []]
        return bool(buttons and buttons[0].get('type') == 'FLOW'
                    and str(buttons[0].get('flow_id') or '') == '39581903361452878')
    return False
