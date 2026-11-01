"""Per-day WhatsApp Flow funnel counters: launch, INIT, validation, save, COMPLETE.

PURPOSE. Flow Hub showed submissions - the end of a Flow's funnel - and nothing about the
steps before it, so "customers type subscribe but nothing is saved" was invisible. Each stage
increments one atomic counter on a per-Flow, per-UTC-day row in FlowLogTable (the one
flow-log store Flow Hub already reads) and emits one structured CloudWatch line that a
metric filter or alarm can use.

AUTHORITY AND PRIVACY. Counters only: these rows hold no phone, name, address, token or free
text. The log line accepts only the allow-listed fields below, and callers pass masked
values. Recording is best effort and never raises, so telemetry cannot fail a customer
request. Reading is bounded: one GetItem per requested day, at most MAX_DAYS.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional

from lambda_utils import shared_tables

STAGES = (
    'launch_attempted', 'launch_blocked', 'launch_redirected', 'launch_sent', 'launch_failed',
    'init_received', 'init_success', 'init_rejected', 'init_failed',
    'review_rejected', 'validation_failed', 'stale_write_refused', 'save_refused',
    'save_success', 'completion_history_failed', 'complete_returned', 'error_notification',
)
ROW_TYPE = 'flow_funnel_daily'
MAX_DAYS = 31
RETENTION_SECONDS = 400 * 86400
_CODE_RE = re.compile(r'[A-Za-z0-9._-]{1,80}\Z')
#: The only fields a funnel log line may carry. Values are truncated, never parsed.
_LOG_FIELDS = frozenset({'reason', 'requestId', 'launchChannel', 'retry', 'created',
                         'contactId', 'phone', 'actor', 'role'})


def table_name() -> str:
    """FlowLogTable for this execution environment."""
    return shared_tables.flow_logs_table_name()


def valid_flow_code(flow_code: Any) -> bool:
    return bool(_CODE_RE.fullmatch(str(flow_code or '')))


def day_of(timestamp: int) -> str:
    return time.strftime('%Y-%m-%d', time.gmtime(int(timestamp)))


def row_id(flow_code: str, day: str) -> str:
    return f'funnel#{flow_code}#{day}'


def record(table: Any, flow_code: str, stage: str, *, logger: Any = None,
           now: Optional[int] = None, **fields: Any) -> bool:
    """Count one funnel event. Returns whether the counter was written; never raises."""
    if stage not in STAGES or not valid_flow_code(flow_code):
        return False
    stamp = int(time.time() if now is None else now)
    day = day_of(stamp)
    written = False
    error_type = ''
    try:
        table.update_item(
            Key={'logId': row_id(flow_code, day)},
            UpdateExpression=('SET #type = :type, #code = :code, #day = :day, #updated = :now, '
                              '#ttl = if_not_exists(#ttl, :ttl) ADD #count :one'),
            ExpressionAttributeNames={'#type': 'type', '#code': 'flowCode', '#day': 'day',
                                      '#updated': 'updatedAt', '#ttl': 'ttl',
                                      '#count': f'n_{stage}'},
            ExpressionAttributeValues={':type': ROW_TYPE, ':code': flow_code, ':day': day,
                                       ':now': stamp, ':ttl': stamp + RETENTION_SECONDS,
                                       ':one': 1},
        )
        written = True
    except Exception as exc:  # noqa: BLE001 - telemetry must never fail a request
        error_type = type(exc).__name__
    if logger is not None:
        payload: Dict[str, Any] = {'event': 'flow_funnel', 'flowCode': flow_code,
                                   'stage': stage, 'counted': written}
        if error_type:
            payload['counterError'] = error_type
        for key, value in fields.items():
            if key in _LOG_FIELDS and isinstance(value, (str, int, bool)) and value != '':
                payload[key] = value if not isinstance(value, str) else value[:120]
        try:
            logger.info(json.dumps(payload))
        except Exception:  # noqa: BLE001
            pass
    return written



def record_stages(table: Any, flow_code: str, stages: tuple[str, ...], *,
                  logger: Any = None, now: Optional[int] = None,
                  **fields: Any) -> bool:
    """Atomically count a small set of stages with ONE DynamoDB write.

    F001 INIT always increments 'init_received' and exactly one terminal INIT
    outcome. Grouping their writes removes a serial round-trip on the handset
    opening path while preserving the existing per-stage daily counters, TTL,
    CloudWatch events and the fail-open telemetry contract. Other Flow stages
    continue to use the original single-stage record() unchanged.
    """
    if (not isinstance(stages, tuple) or not 1 <= len(stages) <= 3
            or any(stage not in STAGES for stage in stages)
            or len(set(stages)) != len(stages)
            or not valid_flow_code(flow_code)):
        return False
    stamp = int(time.time() if now is None else now)
    day = day_of(stamp)
    written = False
    error_type = ''
    try:
        names = {'#type': 'type', '#code': 'flowCode', '#day': 'day',
                 '#updated': 'updatedAt', '#ttl': 'ttl'}
        names.update({f'#count_{i}': f'n_{stage}'
                      for i, stage in enumerate(stages)})
        table.update_item(
            Key={'logId': row_id(flow_code, day)},
            UpdateExpression=(
                'SET #type = :type, #code = :code, #day = :day, #updated = :now, '
                '#ttl = if_not_exists(#ttl, :ttl) ADD ' +
                ', '.join(f'#count_{i} :one' for i in range(len(stages)))
            ),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={
                ':type': ROW_TYPE, ':code': flow_code, ':day': day,
                ':now': stamp, ':ttl': stamp + RETENTION_SECONDS,
                ':one': 1,
            },
        )
        written = True
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a Flow
        error_type = type(exc).__name__
    if logger is not None:
        for stage in stages:
            payload: Dict[str, Any] = {'event': 'flow_funnel', 'flowCode': flow_code,
                                       'stage': stage, 'counted': written}
            if error_type:
                payload['counterError'] = error_type
            for key, value in fields.items():
                if key in _LOG_FIELDS and isinstance(value, (str, int, bool)) and value != '':
                    payload[key] = value if not isinstance(value, str) else value[:120]
            try:
                logger.info(json.dumps(payload))
            except Exception:  # noqa: BLE001
                pass
    return written


def read(table: Any, flow_code: str, *, days: int = 7, now: Optional[int] = None) -> Dict[str, Any]:
    """Daily counters for the last `days` UTC days, newest first. Read errors propagate."""
    if not valid_flow_code(flow_code):
        raise ValueError('invalid flow code')
    window = max(1, min(int(days), MAX_DAYS))
    stamp = int(time.time() if now is None else now)
    totals = {stage: 0 for stage in STAGES}
    rows = []
    for offset in range(window):
        day = day_of(stamp - offset * 86400)
        item = table.get_item(Key={'logId': row_id(flow_code, day)}).get('Item') or {}
        counts = {}
        for stage in STAGES:
            try:
                counts[stage] = int(item.get(f'n_{stage}') or 0)
            except (TypeError, ValueError, ArithmeticError):
                counts[stage] = 0
            totals[stage] += counts[stage]
        rows.append({'day': day, 'counts': counts})
    return {'flowCode': flow_code, 'stages': list(STAGES), 'days': rows, 'totals': totals}
