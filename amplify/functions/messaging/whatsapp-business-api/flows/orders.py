"""
Order-centric helpers — central order lookup and dropdown formatting.
Used by Submit Request, Track Request, and all order-linked flows.

OrderTable is the single source of truth for every order, whatever channel created it:
website checkout, WhatsApp catalog orders and staff-entered orders all live there, in the
shape `lambda_utils.ecommerce.order_record` describes. These helpers read through that
module so a customer's website orders appear in their WhatsApp Flow order picker exactly
like orders placed in chat.
"""
import os
import json
import logging
from typing import Dict, List

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_store, shared_tables
from lambda_utils.ecommerce import order_record

# `lambda_utils.privacy` has no intra-package dependencies (only `re` and `typing`), so unlike
# the deferred `flow_completion` imports elsewhere in this package it cannot introduce a cycle
# and is imported at module scope - above its first use, so a masked log site can never raise
# NameError on the path that was leaking.
#
# The fallback masks rather than passing the value through. An ImportError here must not be
# able to turn a redaction back into a disclosure, which is what `return phone` would do.
try:
    from lambda_utils.privacy import mask_phone
except ImportError:  # pragma: no cover - lambda_utils is always present in the deployed package
    def mask_phone(phone: str) -> str:
        return '***'

logger = logging.getLogger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


ORDERS_TABLE = order_record.table_name()
FLOW_SUBMISSIONS_TABLE = shared_tables.flow_submissions_table_name()

#: How many orders the Flow picker offers. A WhatsApp dropdown is a short list, newest first.
PICKER_LIMIT = 20


def extract_short_id(wd_order_number: str) -> str:
    """Extract the short ID from a WD-ORD number, in either shape.

    'WD-ORD - A1B2C3D4 - ...' → 'A1B2C3D4'   (legacy spaced)
    'WD-ORD-K4M7PQR9'        → 'K4M7PQR9'   (current)

    One implementation, shared with every other order reader: `order_record.short_id`.
    """
    return order_record.short_id(wd_order_number)


def format_order_dropdown(wd_id: str, created_date: str = '', total: str = '',
                          first_item: str = '', order_date_ist: str = '') -> str:
    """Build readable dropdown title: 'A1B2C3D4 — 22 Feb 2026, 6:00 PM'"""
    short = extract_short_id(wd_id)
    if order_date_ist:
        return f'{short} — {order_date_ist}'
    if created_date:
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
            ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
            return f'{short} — {ist.strftime("%-d %b %Y, %-I:%M %p")}'
        except Exception:
            pass
    # Fallback: parse date/time from the WD-ORD string itself
    parts = wd_id.split(' - ')
    if len(parts) >= 4:
        try:
            date_part = parts[2].strip()  # "22-02-2026"
            time_part = parts[3].strip()  # "17:43:01"
            dd, mm, yyyy = date_part.split('-')
            hh_str, mi_str = time_part.split(':')[:2]
            months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
            month_name = months[int(mm) - 1]
            h = int(hh_str)
            ampm = 'PM' if h >= 12 else 'AM'
            h12 = 12 if h == 0 else (h - 12 if h > 12 else h)
            return f'{short} — {int(dd)} {month_name} {yyyy}, {h12}:{mi_str} {ampm}'
        except Exception:
            pass
    return short


# `create_manual_order` was removed here (2026-10-15). It had zero callers and wrote a second
# order shape (spaced WD-ORD id, rupee float, no channel). Staff orders are created by the
# workspace order form through `order_record.staff_order`, in the shared shape.


def get_order(order_id: str) -> Dict:
    """Get a single order from the one order table by orderId, in the shared view."""
    try:
        table = dynamodb.Table(ORDERS_TABLE)
        resp = table.get_item(Key={'orderId': order_id})
        item = resp.get('Item')
        return order_record.view(item) if item else {}
    except Exception as e:
        logger.warning(f'Order lookup failed: {type(e).__name__}')
        return {}


def order_label(order_id: str) -> str:
    """The short order number to show a customer for a stored orderId, from either channel.

    A WD-ORD id carries its number; a website or WhatsApp-catalog order's id is a UUIDv7, so
    its number is read off the row (one `get_item`) rather than cut out of the UUID.
    """
    if not order_id or order_id == 'none':
        return ''
    if str(order_id).startswith('WD-ORD'):
        return extract_short_id(order_id)
    order = get_order(order_id)
    return (order or {}).get('shortId') or extract_short_id(order_id)


def get_submissions_for_order(order_id: str) -> List[Dict]:
    """Get all FlowSubmissions linked to an orderId."""
    try:
        table = dynamodb.Table(FLOW_SUBMISSIONS_TABLE)
        resp = table.query(
            IndexName='orderId',
            KeyConditionExpression='orderId = :oid',
            ExpressionAttributeValues={':oid': order_id},
            ScanIndexForward=False,
        )
        return resp.get('Items', [])
    except Exception as e:
        logger.warning(f'Submissions lookup for order failed: {type(e).__name__}')
        return []


def _phone_variants(phone: str) -> List[str]:
    """Every spelling an order's `customerPhone` may carry for this customer.

    Website orders carry the session's E.164 phone; older rows carry what was typed. A bare
    10-digit Indian mobile is also tried with `+91`, as this lookup always did.
    """
    variants = contact_store.phone_variants(phone)
    digits = contact_store.digits(phone)
    local = digits[2:] if len(digits) > 10 and digits.startswith('91') else digits
    if len(local) == 10 and f'+91{local}' not in variants:
        variants.append(f'+91{local}')
    return variants


def fetch_orders_for_flow(phone: str, email: str) -> list:
    """
    Fetch a customer's orders for a WhatsApp Flow dropdown, from every channel.

    Queries the one order table on its customerPhone GSI. Website checkout orders, WhatsApp
    catalog orders and staff-entered orders are all offered: this used to keep only ids that
    start with 'WD-ORD', which silently dropped every website and WhatsApp-catalog order
    (their orderId is a UUIDv7; the WD-ORD number is `orderNumber`).

    Returns list of {id, title}: `id` is the stored orderId every later Flow step reads the
    order back by, `title` is "A1B2C3D4 — 22 Feb 2026, 6:00 PM".
    """
    if not phone:
        return []
    rows: Dict[str, Dict] = {}
    try:
        orders_table = dynamodb.Table(ORDERS_TABLE)
        for pv in _phone_variants(phone):
            try:
                resp = orders_table.query(
                    IndexName='customerPhone',
                    KeyConditionExpression=Key('customerPhone').eq(pv),
                    ScanIndexForward=False, Limit=PICKER_LIMIT,
                )
                for item in resp.get('Items', []):
                    order_id = item.get('orderId', '')
                    if order_id and order_id not in rows:
                        rows[order_id] = item
            except Exception as e:
                logger.debug(f'Order query variant failed: {type(e).__name__}')
    except Exception as e:
        logger.debug(f'Order table query skipped: {type(e).__name__}')

    ordered = sorted(rows.values(), key=order_record.created_at, reverse=True)[:PICKER_LIMIT]
    results = [order_record.picker_choice(item) for item in ordered]
    if results:
        logger.info(json.dumps({'action': 'fetch_orders', 'source': 'orders_table',
                                'count': len(results), 'phone': mask_phone(phone)}))
    return results
