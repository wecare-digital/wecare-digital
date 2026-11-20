"""
Partner (Embedded Signup) prepaid billing / metering.

Model
-----
Each onboarded tenant (WABA) has a PREPAID WALLET. Usage is metered per tenant
from WhatsApp message-status webhooks (which carry a `pricing.category`), priced
via a configurable rate card, and deducted from the wallet. A ledger records
every top-up and charge. Sending is blocked when the wallet is empty/suspended.

Tables (DynamoDB, created by scripts/_setup_partner_billing.py)
  PartnerWallet  PK wabaId            -> balance, currency, status, threshold, updatedAt
  PartnerLedger  PK wabaId, SK ts     -> type(topup|charge), amount, category, balanceAfter, note, ttl

Who-used-what: every charge row is attributed to a wabaId + category + messageId,
so per-customer usage is fully auditable from the ledger.

Restriction: `is_sufficient()` gates outbound sends; `charge()` auto-suspends a
wallet that drops to/below its low-balance threshold.
"""
import os
import json
import time
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

import boto3

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
WALLET_TABLE = os.environ.get('PARTNER_WALLET_TABLE', 'stack-wecare-digital-PartnerWallet')
LEDGER_TABLE = os.environ.get('PARTNER_LEDGER_TABLE', 'stack-wecare-digital-PartnerLedger')
ALERT_SNS_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:us-east-1:775261844268:stack-wecare-digital')
DEFAULT_CURRENCY = os.environ.get('PARTNER_DEFAULT_CURRENCY', 'INR')
LEDGER_TTL_DAYS = int(os.environ.get('PARTNER_LEDGER_TTL_DAYS', '400'))

# Per-message rate card by WhatsApp category, in wallet currency. Includes any
# markup over Meta's cost. Override the flat default with RATE_CARD env (JSON).
DEFAULT_RATE_CARD = {'MARKETING': 0.90, 'UTILITY': 0.15, 'AUTHENTICATION': 0.12, 'SERVICE': 0.0}
try:
    RATE_CARD = {**DEFAULT_RATE_CARD, **json.loads(os.environ.get('RATE_CARD', '{}') or '{}')}
except json.JSONDecodeError:
    RATE_CARD = DEFAULT_RATE_CARD

# Optional per-country override. RATE_CARD_BY_COUNTRY env (JSON), keyed by ISO
# dial-code prefix or country code, each mapping category->rate. Falls back to
# the flat RATE_CARD when a country/category isn't listed. Example:
#   {"91": {"MARKETING": 0.73, "UTILITY": 0.12}, "1": {"MARKETING": 1.10}}
try:
    RATE_CARD_BY_COUNTRY = json.loads(os.environ.get('RATE_CARD_BY_COUNTRY', '{}') or '{}')
except json.JSONDecodeError:
    RATE_CARD_BY_COUNTRY = {}

_ddb = boto3.resource('dynamodb', region_name=REGION)
_sns = boto3.client('sns', region_name=REGION)


def _alert(subject: str, message: str) -> None:
    try:
        _sns.publish(TopicArn=ALERT_SNS_ARN, Subject=subject[:100], Message=message)
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'partner_alert_error', 'error': str(e)}))


def _wallet_tbl():
    return _ddb.Table(WALLET_TABLE)


def _ledger_tbl():
    return _ddb.Table(LEDGER_TABLE)


def _dec(x) -> Decimal:
    return Decimal(str(x))


def _country_prefix(to_number: str) -> str:
    """Best-effort dial-code prefix from an E.164 number (no +). Tries 2- then
    1-digit country codes present in the per-country card."""
    n = (to_number or '').lstrip('+')
    for length in (3, 2, 1):
        if n[:length] in RATE_CARD_BY_COUNTRY:
            return n[:length]
    return ''


def rate_for(category: str, country: str = '', to_number: str = '') -> float:
    cat = (category or '').upper()
    key = country or _country_prefix(to_number)
    if key and key in RATE_CARD_BY_COUNTRY and cat in RATE_CARD_BY_COUNTRY[key]:
        return float(RATE_CARD_BY_COUNTRY[key][cat])
    return float(RATE_CARD.get(cat, 0.0))


def get_wallet(waba_id: str) -> dict:
    if not waba_id:
        return {}
    item = _wallet_tbl().get_item(Key={'wabaId': waba_id}).get('Item') or {}
    if item:
        item['balance'] = float(item.get('balance', 0))
        item['threshold'] = float(item.get('threshold', 0))
        item['markupPct'] = float(item.get('markupPct', 0))
    return item


def set_settings(waba_id: str, currency: str = None, markup_pct: float = None,
                 threshold: float = None) -> dict:
    """Admin: configure a tenant wallet's currency, markup %, and low-balance threshold."""
    ensure_wallet(waba_id, currency)
    expr, vals, names = ['updatedAt = :t'], {':t': datetime.now(timezone.utc).isoformat()}, {}
    if currency:
        expr.append('currency = :c'); vals[':c'] = currency
    if markup_pct is not None:
        expr.append('markupPct = :m'); vals[':m'] = _dec(markup_pct)
    if threshold is not None:
        expr.append('threshold = :th'); vals[':th'] = _dec(threshold)
    _wallet_tbl().update_item(Key={'wabaId': waba_id},
                              UpdateExpression='SET ' + ', '.join(expr),
                              ExpressionAttributeValues=vals)
    return get_wallet(waba_id)


def ensure_wallet(waba_id: str, currency: str = None) -> dict:
    w = get_wallet(waba_id)
    if w:
        return w
    now = datetime.now(timezone.utc).isoformat()
    _wallet_tbl().put_item(Item={
        'wabaId': waba_id, 'balance': _dec(0), 'currency': currency or DEFAULT_CURRENCY,
        'status': 'ACTIVE', 'threshold': _dec(0), 'updatedAt': now,
    })
    return get_wallet(waba_id)


def _ledger(waba_id: str, kind: str, amount: float, balance_after: float,
            category: str = '', note: str = '', message_id: str = '') -> None:
    ts = datetime.now(timezone.utc).isoformat()
    try:
        _ledger_tbl().put_item(Item={
            'wabaId': waba_id, 'ts': ts, 'type': kind, 'amount': _dec(amount),
            'balanceAfter': _dec(balance_after), 'category': category or '',
            'note': note or '', 'messageId': message_id or '',
            'ttl': int(time.time()) + LEDGER_TTL_DAYS * 86400,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'partner_ledger_error', 'wabaId': waba_id, 'error': str(e)}))


def topup(waba_id: str, amount: float, note: str = '', actor: str = 'admin', currency: str = None) -> dict:
    ensure_wallet(waba_id, currency)
    resp = _wallet_tbl().update_item(
        Key={'wabaId': waba_id},
        UpdateExpression='SET balance = balance + :a, #s = :active, updatedAt = :t',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={':a': _dec(amount), ':active': 'ACTIVE',
                                   ':t': datetime.now(timezone.utc).isoformat()},
        ReturnValues='UPDATED_NEW')
    bal = float(resp['Attributes']['balance'])
    _ledger(waba_id, 'topup', amount, bal, note=note or f'top-up by {actor}')
    logger.info(json.dumps({'event': 'partner_topup', 'wabaId': waba_id, 'amount': amount, 'balance': bal}))
    return {'wabaId': waba_id, 'balance': bal, 'status': 'ACTIVE'}


def is_sufficient(waba_id: str, estimate: float = 0.0) -> bool:
    """Gate for outbound sends on a partner WABA. Non-partner WABAs (no wallet)
    return True so platform-owned numbers are never blocked."""
    w = get_wallet(waba_id)
    if not w:
        return True  # not a metered partner wallet
    if w.get('status') != 'ACTIVE':
        return False
    return float(w.get('balance', 0)) >= float(estimate)


def charge(waba_id: str, amount: float = None, category: str = '', message_id: str = '',
           note: str = '', to_number: str = '') -> dict:
    """Deduct usage from a partner wallet. If amount is None it is derived from
    the (country-aware) category rate card. Auto-suspends at the threshold."""
    w = get_wallet(waba_id)
    if not w:
        return {'charged': False, 'reason': 'no wallet'}
    amt = amount if amount is not None else rate_for(category, to_number=to_number)
    # Apply per-tenant markup on top of the base rate (0 by default).
    markup = float(w.get('markupPct', 0) or 0)
    if amount is None and markup:
        amt = round(amt * (1 + markup / 100.0), 4)
    if amt <= 0:
        return {'charged': False, 'reason': 'zero cost', 'category': category}
    resp = _wallet_tbl().update_item(
        Key={'wabaId': waba_id},
        UpdateExpression='SET balance = balance - :a, updatedAt = :t',
        ExpressionAttributeValues={':a': _dec(amt), ':t': datetime.now(timezone.utc).isoformat()},
        ReturnValues='UPDATED_NEW')
    bal = float(resp['Attributes']['balance'])
    _ledger(waba_id, 'charge', amt, bal, category=category, note=note, message_id=message_id)
    # auto-suspend at/below threshold
    threshold = float(w.get('threshold', 0))
    if bal <= threshold:
        _wallet_tbl().update_item(
            Key={'wabaId': waba_id}, UpdateExpression='SET #s = :s',
            ExpressionAttributeNames={'#s': 'status'}, ExpressionAttributeValues={':s': 'SUSPENDED'})
        logger.warning(json.dumps({'event': 'partner_wallet_suspended', 'wabaId': waba_id, 'balance': bal}))
        _alert('WECARE partner wallet suspended',
               f'Partner WABA {waba_id} wallet dropped to {bal} {w.get("currency", "")} and was suspended. Top up to resume messaging.')
    return {'charged': True, 'amount': amt, 'balance': bal, 'category': category}


def list_wallets() -> list:
    wallets = []
    kwargs = {}
    while True:
        resp = _wallet_tbl().scan(**kwargs)
        for it in resp.get('Items', []):
            wallets.append({'wabaId': it.get('wabaId'), 'balance': float(it.get('balance', 0)),
                            'currency': it.get('currency', DEFAULT_CURRENCY), 'status': it.get('status', 'ACTIVE'),
                            'threshold': float(it.get('threshold', 0)), 'updatedAt': it.get('updatedAt', '')})
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
        kwargs['ExclusiveStartKey'] = lek
    return wallets


def analytics(waba_id: str, days: int = 30) -> dict:
    """Aggregate a tenant's usage from the ledger: total spend, spend + count by
    category, top-ups, and current balance — over the last `days`."""
    from datetime import timedelta
    if not waba_id:
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    spend_by_cat, count_by_cat = {}, {}
    total_spend = total_topup = charge_count = 0.0
    kwargs = {'KeyConditionExpression': 'wabaId = :w AND ts >= :s',
              'ExpressionAttributeValues': {':w': waba_id, ':s': since},
              'ScanIndexForward': False}
    while True:
        resp = _ledger_tbl().query(**kwargs)
        for it in resp.get('Items', []):
            amt = float(it.get('amount', 0))
            if it.get('type') == 'charge':
                cat = it.get('category', '') or 'OTHER'
                spend_by_cat[cat] = round(spend_by_cat.get(cat, 0) + amt, 4)
                count_by_cat[cat] = count_by_cat.get(cat, 0) + 1
                total_spend = round(total_spend + amt, 4)
                charge_count += 1
            elif it.get('type') == 'topup':
                total_topup = round(total_topup + amt, 4)
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
        kwargs['ExclusiveStartKey'] = lek
    w = get_wallet(waba_id)
    return {
        'wabaId': waba_id, 'days': days, 'balance': float(w.get('balance', 0)) if w else 0,
        'currency': w.get('currency', DEFAULT_CURRENCY) if w else DEFAULT_CURRENCY,
        'totalSpend': total_spend, 'totalTopup': total_topup, 'messageCount': int(charge_count),
        'spendByCategory': spend_by_cat, 'countByCategory': count_by_cat,
    }


def recent_ledger(waba_id: str, limit: int = 20) -> list:
    resp = _ledger_tbl().query(
        KeyConditionExpression='wabaId = :w', ExpressionAttributeValues={':w': waba_id},
        ScanIndexForward=False, Limit=limit)
    out = []
    for it in resp.get('Items', []):
        out.append({'ts': it.get('ts'), 'type': it.get('type'), 'amount': float(it.get('amount', 0)),
                    'balanceAfter': float(it.get('balanceAfter', 0)), 'category': it.get('category', ''),
                    'note': it.get('note', ''), 'messageId': it.get('messageId', '')})
    return out
