"""One order record for both channels, and one way to read it back.

`OrderTable` holds every order, whatever surface it came from:

    website checkout            finalization.accept_paid    channel website
    WhatsApp catalog basket     finalization.accept_paid    channel whatsapp (website leg)
    WhatsApp catalog service    finalization.accept_paid    channel whatsapp (in-chat leg)
    staff-entered order         `staff_order` below         channel from the form, source manual

Every writer stamps the same identity and attribution fields: `orderId`, `orderNumber`
(`WD-ORD-...`), `shortId`, `channel`, `source`, `customerPhone`, `contactId` when the
ContactsTable row is known, integer `amountPaise` beside the legacy rupee `totalAmount`,
`currency`, `paymentStatus`, `orderStatus`/`status`, `createdAt`.

Readers go through `view`, which also understands rows written before this module existed:
the spaced `WD-ORD - XXXXXXXX - dd-mm-yyyy - HH:MM:SS - IST` ids, rows with only a rupee
`totalAmount`, and rows whose payment word is the attempt vocabulary's `PAYMENT_PAID`. That
is what lets the WhatsApp Flow order picker, the staff workspace and order tracking all list
website and WhatsApp orders from one query.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional

from lambda_utils import shared_tables

from . import order_channel

ORDER_NUMBER_PREFIX = 'WD-ORD-'

#: The order source a staff-entered order carries when the form does not name one.
SOURCE_MANUAL = 'manual'

#: Statuses as stored. `PAYMENT_PAID` is what `accept_paid` writes (the attempt vocabulary);
#: readers that speak the staff vocabulary see it as `paid`.
PAYMENT_PAID_ATTEMPT_WORD = 'PAYMENT_PAID'
PAYMENT_PAID = 'paid'
PAYMENT_PENDING = 'pending'

_IST = timezone(timedelta(hours=5, minutes=30))


def table_name() -> str:
    """The one order table for this execution environment."""
    return shared_tables.ORDERS.name()


def short_id(order_number: Any) -> str:
    """The distinguishing part of an order number, in either shape.

    'WD-ORD-K4M7PQR9'                       -> 'K4M7PQR9'
    'WD-ORD - A1B2C3D4 - 22-02-2026 - ...'  -> 'A1B2C3D4'
    """
    text = str(order_number or '').strip()
    if not text:
        return ''
    parts = text.split(' - ')
    if len(parts) >= 2:
        return parts[1].strip()
    if text.startswith(ORDER_NUMBER_PREFIX) and len(text) > len(ORDER_NUMBER_PREFIX):
        return text[len(ORDER_NUMBER_PREFIX):]
    return text[:12]


def order_number(item: Mapping[str, Any]) -> str:
    """The customer-facing order number for any stored row."""
    explicit = str(item.get('orderNumber') or '').strip()
    if explicit:
        return explicit
    order_id = str(item.get('orderId') or '').strip()
    short = str(item.get('shortId') or '').strip() or short_id(order_id)
    if order_id.startswith('WD-ORD') and short:
        return f'{ORDER_NUMBER_PREFIX}{short}'
    return order_id


def _integer(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        try:
            if value.is_finite() and value == value.to_integral_value():
                return int(value)
        except (InvalidOperation, ValueError):
            return None
    return None


def paise_from_rupees(value: Any) -> Optional[int]:
    """Exact integer paise for a rupee amount, or None when it is not a whole number of paise."""
    if value is None or isinstance(value, bool) or value == '':
        return None
    try:
        amount = Decimal(str(value)) * 100
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        return None
    return int(amount)


def amount_paise(item: Mapping[str, Any]) -> Optional[int]:
    """Integer paise for the order: `amountPaise` when stored, else derived from `totalAmount`."""
    stored = _integer(item.get('amountPaise'))
    if stored is not None:
        return stored
    return paise_from_rupees(item.get('totalAmount'))


def payment_status(item: Mapping[str, Any]) -> str:
    """The payment word staff and Flow readers speak (`paid`, `pending`, ...)."""
    word = str(item.get('paymentStatus') or '').strip()
    if word == PAYMENT_PAID_ATTEMPT_WORD:
        return PAYMENT_PAID
    return word or PAYMENT_PENDING


def created_at(item: Mapping[str, Any]) -> int:
    value = _integer(item.get('createdAt'))
    return value if value is not None else 0


def view(item: Mapping[str, Any]) -> Dict[str, Any]:
    """The row with every shared field present, in one vocabulary. Never raises.

    A copy: the stored row is not modified, and every original attribute is kept so existing
    consumers that read a writer-specific field still find it.
    """
    out: Dict[str, Any] = dict(item or {})
    number = order_number(out)
    out['orderNumber'] = number
    out['shortId'] = str(out.get('shortId') or '').strip() or short_id(number)
    out['channel'] = order_channel.canonical(out.get('channel'))
    paise = amount_paise(out)
    if paise is not None:
        out['amountPaise'] = paise
    out['paymentStatus'] = payment_status(out)
    # `orderStatus` first: it is the field status updates write (and the GSI is on it), so on
    # an older row whose `status` copy went stale it is the one that is current.
    out['status'] = str(out.get('orderStatus') or out.get('status') or 'active')
    out['createdAt'] = created_at(out)
    return out


def display_date(item: Mapping[str, Any]) -> str:
    """'22 Feb 2026, 6:00 PM' in IST, from the stored IST label or `createdAt`."""
    label = str(item.get('orderDateIST') or '').strip()
    if label:
        return label
    seconds = created_at(item)
    if not seconds:
        return ''
    moment = datetime.fromtimestamp(seconds, tz=_IST)
    hour = moment.hour % 12 or 12
    return f'{moment.day} {moment.strftime("%b %Y")}, {hour}:{moment.strftime("%M %p")}'


def picker_choice(item: Mapping[str, Any]) -> Dict[str, str]:
    """`{id, title}` for a WhatsApp Flow order dropdown.

    `id` is the stored `orderId`, which is what every downstream Flow step reads the order
    back by; `title` is the short number and the date, so website and WhatsApp orders look
    the same to the customer.
    """
    row = view(item)
    title = row['shortId'] or row['orderNumber']
    when = display_date(row)
    return {'id': str(row.get('orderId') or ''), 'title': f'{title} — {when}' if when else title}


def staff_order(body: Mapping[str, Any], *, short: str, now: int,
                contact_id: str = '', customer_phone: str = '') -> Dict[str, Any]:
    """A staff-entered order in the shared shape. Empty values are dropped.

    `customer_phone` is the canonical spelling the caller resolved; the body's own text is
    kept when the caller could not canonicalise it.
    """
    order_id = f'{ORDER_NUMBER_PREFIX}{short}'
    total = body.get('totalAmount')
    paise = paise_from_rupees(total)
    item: Dict[str, Any] = {
        'orderId': order_id,
        'orderNumber': order_id,
        'shortId': short,
        'channel': order_channel.canonical(body.get('channel')),
        'source': str(body.get('source') or SOURCE_MANUAL),
        'customerPhone': customer_phone or str(body.get('customerPhone') or ''),
        'customerName': body.get('customerName', ''),
        'customerEmail': body.get('customerEmail', ''),
        'contactId': contact_id,
        'itemsSummary': body.get('itemsSummary', ''),
        'totalAmount': Decimal(paise) / Decimal(100) if paise is not None else None,
        'amountPaise': paise,
        'currency': body.get('currency', 'INR'),
        'orderStatus': body.get('status', 'active'),
        'status': body.get('status', 'active'),
        'paymentStatus': body.get('paymentStatus', PAYMENT_PENDING),
        'adminNotes': body.get('notes', ''),
        'createdAt': now,
        'updatedAt': now,
    }
    return {key: value for key, value in item.items() if value is not None and value != ''}
