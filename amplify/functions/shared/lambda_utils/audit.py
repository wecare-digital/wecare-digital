"""
Audit logging helper — writes to the existing AuditLog model
(table `stack-wecare-digital-AuditLogsTable`).

Usage:
    from lambda_utils.audit import record_audit
    record_audit(action='template.create', actor=user_id, resource_type='template',
                 resource_id=name, details={'category': cat})

Fails open (never raises) so auditing can't break a request. Details are secret-masked.

Fails open HERE. A caller may choose otherwise, and for an irreversible bulk delete it
must: `record_audit` returns the logId or `None`, so a caller that cannot afford an
unrecorded action checks the return value and refuses. `operations/system-cleanup`,
`core/messages-delete` and `payments/invoice-engine` all do. The reasoning is asymmetric
on purpose — an audit write that fails open loses a record, while deleting a table with no
record of who asked loses the only account of what happened.
"""
import os
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from lambda_utils.logging import get_logger
from lambda_utils.masking import mask_secrets

logger = get_logger(__name__)

AUDIT_TABLE = os.environ.get('AUDIT_LOG_TABLE', 'stack-wecare-digital-AuditLogsTable')
TTL_DAYS = int(os.environ.get('AUDIT_TTL_DAYS', '180'))

_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Canonical auditable actions (extend as needed)
ACTIONS = {
    'waba.sync', 'assigned_user.add', 'assigned_user.remove', 'webhook.subscribe',
    'webhook.unsubscribe', 'phone_setting.update', 'template.create', 'template.edit',
    'template.delete', 'template.send_test', 'flow.create', 'flow.update', 'flow.upload',
    'flow.publish', 'flow.deprecate', 'flow.clone', 'flow.migrate', 'qr.delete',
    'commerce.update', 'group.create', 'group.update', 'group.delete', 'payment.lookup',
    'payment.refund', 'dlq.replay', 'secret.update', 'feature_flag.update', 'username.claim',
    'username.delete', 'ai_policy.update',
    # WABA management (Part 3 Module 1)
    'event_destination.update', 'media.upload', 'media.delete', 'phone.register',
    'phone.migrate', 'phone.request_otp', 'phone.verify_otp', 'conversational.update',
    # Irreversible bulk deletes. These are the only callers that check the RETURN VALUE of
    # record_audit and refuse when it is None — see the fail-closed note in the docstring.
    'system.cleanup', 'messages.clear_all', 'invoice.delete', 'invoice.clear_all',
}


def record_audit(action: str, actor: Optional[str] = None, resource_type: Optional[str] = None,
                 resource_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Write an audit record. Returns logId on success, None on failure (never raises)."""
    log_id = str(uuid.uuid4())
    now = int(time.time())
    try:
        item = {
            # `id` is the LIVE table's partition key; `logId` is the alias that
            # `amplify/data/resource.ts` declares. Both are written from one value so
            # they cannot diverge - the same physical-key/alias pattern as
            # lambda_utils.contact_key.
            #
            # Until 2026-09-23 only `logId` was set, so every put_item raised
            # "ValidationException: One of the required keys was not given a value"
            # and the fail-open except below returned None. Measured: the table held
            # 0 items, so not one audit record from any of the 17 call sites had ever
            # been stored. The mismatch exists because resource.ts has never been
            # deployed - there is no AppSync API or Amplify data stack in the account
            # - so the live table was created by a script with an `id` key while this
            # helper was written against the declaration.
            'id': log_id,
            'logId': log_id,
            'action': action,
            'userId': actor or 'system',
            'resourceType': resource_type or '',
            'resourceId': resource_id or '',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'details': json.dumps(mask_secrets(details or {}), default=str)[:8000],
            'expiresAt': now + TTL_DAYS * 24 * 60 * 60,
        }
        # Empty values are stripped, but never the keys: a filter that can drop the
        # partition key is how a write becomes unconditionally invalid.
        written = {k: v for k, v in item.items() if v != '' or k in ('id', 'logId')}
        _dynamodb.Table(AUDIT_TABLE).put_item(Item=written)
        return log_id
    except Exception as e:  # noqa: BLE001
        logger.warning('{"event":"audit_write_failed","action":"%s","error":"%s"}' % (action, str(e)[:160]))
        return None
