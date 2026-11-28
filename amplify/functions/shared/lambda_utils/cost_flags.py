"""
Cost-control feature flags. All default FALSE. Read from env first, then SystemConfig.

Usage:
    from lambda_utils.cost_flags import is_enabled
    if is_enabled('ENABLE_CLOUDFRONT'): ...

`ENABLE_WAF` was removed on 2026-09-28. WAF itself was deleted from the account as a
cost decision, and the CDK resource the flag gated is gone, so the flag could only
have misreported a capability that no longer exists.
"""
import os
import json
import time
from typing import Dict

import boto3

FLAGS = [
    'ENABLE_CLOUDFRONT', 'ENABLE_STEP_FUNCTIONS', 'ENABLE_ATHENA_ANALYTICS',
    'ENABLE_GLUE', 'ENABLE_TEXTRACT_IMPORT', 'ENABLE_XRAY',
    'ENABLE_ADVANCED_CLOUDWATCH_DASHBOARD', 'ENABLE_RAW_WEBHOOK_ARCHIVE',
]

SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
_CACHE: Dict[str, object] = {}
_CACHE_TTL = 300
_TRUTHY = {'1', 'true', 'yes', 'on', 'enabled'}

_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


def _config_flags() -> Dict[str, bool]:
    now = time.time()
    if _CACHE.get('ts', 0) + _CACHE_TTL > now and 'flags' in _CACHE:
        return _CACHE['flags']  # type: ignore
    flags: Dict[str, bool] = {}
    try:
        item = _dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': 'cost_flags'}).get('Item')
        if item:
            raw = item.get('configValue', '{}')
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            for k, v in data.items():
                flags[k.upper()] = (str(v).lower() in _TRUTHY) if not isinstance(v, bool) else v
    except Exception:
        pass
    _CACHE['flags'] = flags
    _CACHE['ts'] = now
    return flags


def is_enabled(flag: str) -> bool:
    """True only if explicitly enabled via env or SystemConfig. Defaults FALSE."""
    flag = flag.upper()
    env_val = os.environ.get(flag)
    if env_val is not None:
        return env_val.strip().lower() in _TRUTHY
    return bool(_config_flags().get(flag, False))


def all_flags() -> Dict[str, bool]:
    return {f: is_enabled(f) for f in FLAGS}
