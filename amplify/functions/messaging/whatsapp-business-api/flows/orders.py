"""
Order-centric helpers — central order lookup, sync, and dropdown formatting.
Used by Submit Request, Track Request, and all order-linked flows.
OrdersTable is the single source of truth for all order sources (Wix, manual, Shopify, etc.).
"""
import os
import json
import time
import uuid
import logging
from decimal import Decimal
from typing import Dict, List

import boto3

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


ORDERS_TABLE = os.environ.get('ORDERS_TABLE', 'stack-wecare-digital-OrderTable')
FLOW_SUBMISSIONS_TABLE = os.environ.get('FLOW_SUBMISSIONS_TABLE', 'stack-wecare-digital-FlowSubmissionTable')


def extract_short_id(wd_order_number: str) -> str:
    """Extract the short ID from a WD-ORD number, in either shape.

    'WD-ORD - A1B2C3D4 - ...' → 'A1B2C3D4'   (legacy spaced)
    'WD-ORD-K4M7PQR9'        → 'K4M7PQR9'   (current)

    The current form has no ' - ' to split on, so it used to fall through to the first 12
    characters and come out as 'WD-ORD-K4M7' - a truncated prefix with the distinguishing
    part cut off. This value is what the Flow dropdown shows and what the Wix sync stores as
    `shortId`, so the prefix strip is not cosmetic here.
    """
    if not wd_order_number:
        return ''
    parts = wd_order_number.split(' - ')
    if len(parts) >= 2:
        return parts[1]
    prefix = 'WD-ORD-'
    if wd_order_number.startswith(prefix) and len(wd_order_number) > len(prefix):
        return wd_order_number[len(prefix):]
    return wd_order_number[:12]


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


def create_manual_order(customer_phone: str, customer_name: str = '',
                        items_summary: str = '', total_amount: float = 0,
                        notes: str = '') -> Dict:
    """Create a manual order in OrdersTable. Returns the order dict."""
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    ist = now_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    short = uuid.uuid4().hex[:8].upper()
    wd_id = f'WD-ORD - {short} - {ist.strftime("%d-%m-%Y")} - {ist.strftime("%H:%M:%S")} - IST'
    order_date_ist = ist.strftime('%d %b %Y, %I:%M %p')
    now_ts = int(time.time())
    item = {
        'orderId': wd_id,
        'shortId': short,
        'source': 'manual',
        'sourceOrderId': '',
        'sourceOrderNumber': '',
        'customerPhone': customer_phone,
        'customerName': customer_name,
        'orderDate': ist.strftime('%Y-%m-%d'),
        'orderTime': ist.strftime('%H:%M:%S'),
        'orderDateIST': order_date_ist,
        'itemsSummary': items_summary or 'Manual order',
        'totalAmount': Decimal(str(total_amount)) if total_amount else Decimal('0'),
        'currency': 'INR',
        'orderStatus': 'active',
        'paymentStatus': 'pending',
        'adminNotes': notes,
        'createdAt': now_ts,
        'updatedAt': now_ts,
    }
    table = dynamodb.Table(ORDERS_TABLE)
    table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
    logger.info(json.dumps({'event': 'manual_order_created', 'orderId': wd_id, 'shortId': short}))
    return item


def get_order(order_id: str) -> Dict:
    """Get a single order from OrdersTable by orderId."""
    try:
        table = dynamodb.Table(ORDERS_TABLE)
        resp = table.get_item(Key={'orderId': order_id})
        return resp.get('Item', {})
    except Exception as e:
        logger.warning(f'Order lookup failed: {e}')
        return {}


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
        logger.warning(f'Submissions lookup for order {order_id} failed: {e}')
        return []


def fetch_orders_for_flow(phone: str, email: str) -> list:
    """
    Fetch orders for a user by phone or email.
    ORDER-CENTRIC: queries OrdersTable first (all sources), then the API-only
    Wix Store Lambda as the commerce fallback.
    Returns list of {id, title} for WhatsApp Flow dropdown.
    Dropdown format: "A1B2C3D4 — 22 Feb 2026, 6:00 PM"
    Internal id: full "WD-ORD - A1B2C3D4 - 22-02-2026 - 18:00:00 - IST"
    """
    results = []
    seen = set()

    def _add(wd_id: str, title: str):
        if wd_id and wd_id not in seen:
            seen.add(wd_id)
            results.append({'id': wd_id, 'title': title})

    clean_phone = ''
    clean_phone_short = ''
    if phone:
        clean_phone = phone.replace('+', '').replace(' ', '').replace('-', '')
        clean_phone_short = clean_phone[2:] if len(clean_phone) > 10 and clean_phone.startswith('91') else clean_phone

    # ── Source 1: OrdersTable (all sources) ──
    try:
        orders_table = dynamodb.Table(ORDERS_TABLE)
        for pv in [f'+{clean_phone}', clean_phone, f'+91{clean_phone_short}']:
            try:
                resp = orders_table.query(
                    IndexName='customerPhone',
                    KeyConditionExpression='customerPhone = :p',
                    ExpressionAttributeValues={':p': pv},
                    ScanIndexForward=False, Limit=20,
                )
                for item in resp.get('Items', []):
                    wd_id = item.get('orderId', '')
                    if not wd_id.startswith('WD-ORD'):
                        continue
                    title = format_order_dropdown(
                        wd_id, order_date_ist=item.get('orderDateIST', ''),
                        total=str(item.get('totalAmount', '')),
                        first_item=(item.get('itemsSummary', '') or '').split(',')[0].strip(),
                    )
                    _add(wd_id, title)
                if results:
                    break
            except Exception:
                pass
        if results:
            logger.info(json.dumps({'action': 'fetch_orders', 'source': 'orders_table', 'count': len(results)}))
            return results
    except Exception as e:
        logger.debug(f'OrdersTable query skipped: {e}')

    # Wix Store fallback removed in the Wix exit: OrdersTable (AWS-native checkout)
    # is the sole source of truth. The `wecare-wix-store` Lambda this used to invoke
    # as "Source 2" was deleted, so there is nothing to fall back to — a miss remains
    # a miss rather than reviving the retired Wix store integration.
    return results
