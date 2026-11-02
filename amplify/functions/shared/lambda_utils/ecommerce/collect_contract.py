"""Collect identity/preview contracts; no pricing or rendering decisions."""
import hashlib
import json
from decimal import Decimal


def is_collect(invoice):
    return (invoice.get('entryPoint') == 'pay_flow'
            and not invoice.get('fixedPresetId') and not invoice.get('serviceKind'))


def preview_fingerprint(body, quote):
    def number(value):
        return str(Decimal(str(value or 0)).normalize())
    fields = ('contactId', 'customerName', 'customerPhone', 'customerEmail',
              'buyerGstin', 'shippingAddress', 'billingAddress', 'addressLine1',
              'addressLine2', 'city', 'state', 'postalCode', 'countryCode', 'goodsType')
    context = {key: str(body.get(key) or '').strip() for key in fields}
    context['items'] = [{
        'name': str(item.get('name') or '').strip(),
        'amount': number(item.get('amount')), 'quantity': number(item.get('quantity', 1)),
        'gstRate': number(item.get('gstRate', body.get('gstRate', 18))),
        'hsnSac': str(item.get('hsnSac') or '').strip(),
    } for item in body.get('items', [])]
    context['quote'] = {key: number(quote.get(key)) for key in (
        'subtotal', 'discount', 'shipping', 'tax', 'convenienceFeeNet',
        'convenienceFeeGst', 'total')}
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def address_snapshot(contact):
    """Compare stored source fields, avoiding duplicate address-formatting rules."""
    def clean(value):
        if isinstance(value, dict):
            return {key: normalized for key, child in value.items()
                    if (normalized := clean(child)) not in ('', None, {})}
        return str(value or '').strip()
    canonical = contact.get('checkoutDeliveryAddress')
    if isinstance(canonical, dict) and canonical:
        return {'checkoutDeliveryAddress': clean(canonical)}
    fields = ('shippingAddressJson', 'addressLine1', 'addressLine2', 'landmark',
              'city', 'state', 'postalCode', 'country', 'countryCode',
              'houseNumber', 'buildingName', 'towerNumber', 'floorNumber')
    return clean({key: contact.get(key) for key in fields})
