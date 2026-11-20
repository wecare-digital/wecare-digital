"""
System event helper — writes to the existing SystemEvent model
(table `stack-wecare-digital-SystemEventTable`).

Usage:
    from lambda_utils.system_events import record_system_event
    record_system_event('template_rejected', waba_id=wid, severity='warning',
                        data={'template': name, 'reason': reason})

Fails open. eventData is secret-masked JSON.
"""
import os
import json
import time
import uuid
from typing import Any, Dict, Optional

import boto3

from lambda_utils.logging import get_logger
from lambda_utils.masking import mask_secrets

logger = get_logger(__name__)

SYSTEM_EVENT_TABLE = os.environ.get('SYSTEM_EVENT_TABLE', 'stack-wecare-digital-SystemEventTable')
TTL_DAYS = int(os.environ.get('SYSTEM_EVENT_TTL_DAYS', '180'))

_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Recognized event types (per Part 2)
EVENT_TYPES = {
    'meta_api_failure_spike', 'template_rejected', 'template_ttl_cleared',
    'flow_validation_error', 'flow_health_blocked', 'webhook_signature_failure',
    'dlq_depth_alert', 'general_purpose_ai_pricing_seen', 'token_rotation_reminder',
    'waba_quality_warning', 'phone_quality_update', 'account_update', 'user_id_update',
    # Flow lifecycle (Part 4 A)
    'flow_published', 'flow_publish_failed', 'flow_deprecated', 'flow_migrated', 'flow_cloned',
}
SEVERITIES = {'info', 'warning', 'error', 'critical'}


def record_system_event(event_type: str, waba_id: Optional[str] = None,
                        phone_number_id: Optional[str] = None, severity: str = 'info',
                        data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Persist a system event. Returns id on success, None on failure (never raises)."""
    event_id = str(uuid.uuid4())
    now = int(time.time())
    if severity not in SEVERITIES:
        severity = 'info'
    try:
        item = {
            'id': event_id,
            'eventType': event_type,
            'wabaId': waba_id or '',
            'phoneNumberId': phone_number_id or '',
            'eventData': json.dumps(mask_secrets(data or {}), default=str)[:8000],
            'severity': severity,
            'acknowledged': False,
            'createdAt': now,
            'ttl': now + TTL_DAYS * 24 * 60 * 60,
        }
        _dynamodb.Table(SYSTEM_EVENT_TABLE).put_item(Item={k: v for k, v in item.items() if v != ''})
        return event_id
    except Exception as e:  # noqa: BLE001
        logger.warning('{"event":"system_event_write_failed","type":"%s","error":"%s"}' % (event_type, str(e)[:160]))
        return None
