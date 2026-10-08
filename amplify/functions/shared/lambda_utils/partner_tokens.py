"""
Partner (Embedded Signup) tenant + token resolution.

Multi-tenant helper: onboarded businesses each have
  - a tenant record in SystemConfigTable  (id = partner_tenant_<wabaId>)
  - a per-tenant secret  wecare/partners/<wabaId>  holding their access_token

Use `resolve_token(waba_id=..., phone_id=...)` in inbound/outbound WhatsApp
handlers to send/receive on a partner's behalf. It returns the partner token
when the WABA/phone belongs to an onboarded partner, else None (caller falls
back to the platform's own MetaGraphClient token for owned numbers).

This keeps existing single-tenant behavior intact — partner routing only
kicks in for known partner assets.
"""
import os
import json
import time
from typing import Optional, List, Dict

import boto3

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
PARTNER_PREFIX = 'wecare/partners/'
TENANT_PREFIX = 'partner_tenant_'

_secrets = boto3.client('secretsmanager', region_name=REGION)
_ddb = boto3.resource('dynamodb', region_name=REGION)

# warm-lambda caches
_token_cache: Dict[str, str] = {}
_token_cached_at: Dict[str, float] = {}
_CACHE_SECONDS = 300
_phone_index: Dict[str, str] = {}   # phone_number_id -> waba_id
_index_loaded = False
_index_loaded_at = 0.0


def list_tenants() -> List[dict]:
    """Return all connected partner tenant records (from SystemConfigTable)."""
    tenants: List[dict] = []
    table = _ddb.Table(SYSTEM_CONFIG_TABLE)
    kwargs = {
        'FilterExpression': 'begins_with(id, :p)',
        'ExpressionAttributeValues': {':p': TENANT_PREFIX},
    }
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get('Items', []):
            try:
                tenants.append(json.loads(item.get('configValue', '{}')))
            except json.JSONDecodeError:
                continue
        lek = resp.get('LastEvaluatedKey')
        if not lek:
            break
        kwargs['ExclusiveStartKey'] = lek
    return tenants


def _load_phone_index() -> None:
    global _index_loaded, _index_loaded_at
    now = time.monotonic()
    if _index_loaded and now - _index_loaded_at < _CACHE_SECONDS:
        return
    refreshed = {}
    for t in list_tenants():
        waba = t.get('wabaId')
        phone = t.get('phoneNumberId')
        if waba and phone:
            refreshed[phone] = waba
    _phone_index.clear()
    _phone_index.update(refreshed)
    _index_loaded = True
    _index_loaded_at = now


def get_partner_token(waba_id: str) -> Optional[str]:
    """Return the stored access token for a partner WABA, or None."""
    if not waba_id:
        return None
    now = time.monotonic()
    if waba_id in _token_cache and now - _token_cached_at.get(waba_id, 0) < _CACHE_SECONDS:
        return _token_cache[waba_id]
    _token_cache.pop(waba_id, None)
    _token_cached_at.pop(waba_id, None)
    try:
        raw = _secrets.get_secret_value(SecretId=f'{PARTNER_PREFIX}{waba_id}').get('SecretString', '') or '{}'
        token = (json.loads(raw).get('access_token') or '').strip()
        if token:
            _token_cache[waba_id] = token
            _token_cached_at[waba_id] = now
            return token
    except _secrets.exceptions.ResourceNotFoundException:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({'event': 'partner_token_read_error', 'wabaId': waba_id, 'error': str(e)}))
    return None


def resolve_token(waba_id: Optional[str] = None, phone_id: Optional[str] = None) -> Optional[str]:
    """Resolve a partner access token by WABA id or phone-number id.

    Returns None when the asset is not a known partner (caller should then use
    the platform's own token). Never raises.
    """
    if waba_id:
        tok = get_partner_token(waba_id)
        if tok:
            return tok
    if phone_id:
        _load_phone_index()
        mapped = _phone_index.get(phone_id)
        if mapped:
            return get_partner_token(mapped)
    return None


def is_partner_asset(waba_id: Optional[str] = None, phone_id: Optional[str] = None) -> bool:
    return resolve_token(waba_id=waba_id, phone_id=phone_id) is not None
