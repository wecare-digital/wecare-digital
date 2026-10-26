"""
Voice CDR Read Lambda Function

    GET    /voice-cdr-read   call detail records, newest first, with stats
    DELETE /voice-cdr-read   clear every record (body {"clearAll": true})

Reads VoiceCDRTable and nothing else. That table has one writer,
messaging/plivo-answer (`_persist_cdr`), which keeps one row per PSTN call under
id `plivo#{CallUUID}` with `source='plivo'`. Each record in the response carries
exactly the attributes that writer stores (`CDR_FIELDS`), type-normalised for
JSON. An attribute outside that set is not returned, and no field is renamed.

Two read-side rules a caller can rely on:
  * `hangupCause` is the provider's hangup cause (e.g. NORMAL_CLEARING) and
    `hangupStatus` is the party that hung up (Plivo's HangupSource). Each is read
    from the attribute of the same name.
  * `direction` is the normalised INBOUND / OUTBOUND, the same vocabulary as
    `callType`. That is what the Call History direction filter compares against;
    the provider's own spelling (inbound, outbound-api) is not passed through.

`timestamp` is written in UTC as '%Y-%m-%d %H:%M:%S'; `createdAt` is epoch
seconds, set once per call, and is the sort key.

Query parameters (all optional):
- callType: INBOUND or OUTBOUND
- status: overallCallStatus as plivo-answer maps it (Answered, Missed, Busy,
  Ringing, In Progress)
- limit: number of records (default 100, max 500)
- startDate / endDate: createdAt bounds, epoch seconds
- callerNumber / destinationNumber: substring match
- hangupStatus: the party that hung up
- search: substring of the provider call id (callUuid)
- dashboard=true: adds the daily call trend and per-CLI volume

Stats (over the returned page): total, inbound, outbound, answered, missed, busy,
average conversation duration, total billable seconds, and breakdowns byCallType,
byStatus, byHangupCause and byHangupStatus.

Auth: `require_auth` on anything that arrives through API Gateway. Internal
Lambda invokes (the AI assistant's `get_voice_cdr` tool) carry no gateway
context and are admitted by the middleware.
"""

import os
import json
import boto3
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List

from lambda_utils.response import cors_headers, extract_origin
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
VOICE_CDR_TABLE = os.environ.get('VOICE_CDR_TABLE', 'stack-wecare-digital-VoiceCDRTable')

#: The attributes plivo-answer._persist_cdr writes, grouped by the JSON type they are
#: returned as. Together they are the whole response record: 31 attributes, which is
#: also every attribute present on the live table.
CDR_STRING_FIELDS = (
    'id', 'source', 'route', 'callUuid',
    'callerNumber', 'destinationNumber', 'callerId', 'callType', 'direction',
    'overallCallStatus', 'hangupCause', 'hangupStatus', 'timestamp',
    # snake_case copies plivo-answer still writes beside the camelCase fields
    'call_uuid', 'from_number', 'to_number', 'call_status', 'hangup_cause',
    'hangup_source', 'duration_seconds', 'end_time',
)
CDR_INT_FIELDS = (
    'createdAt', 'received_at', 'expiresAt', 'cdrRank',
    'durationMs', 'conversationDurationMs', 'billableDurationMs',
)
CDR_FLOAT_FIELDS = (
    'durationSec', 'conversationDurationSec', 'billableDurationSec',
)
CDR_FIELDS = CDR_STRING_FIELDS + CDR_INT_FIELDS + CDR_FLOAT_FIELDS


class DecimalEncoder(json.JSONEncoder):
    """Handle Decimal types from DynamoDB."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj) if obj % 1 else int(obj)
        return super().default(obj)


def _seconds_to_mmss(seconds) -> str:
    """Seconds as mm:ss for display."""
    try:
        total_sec = int(float(seconds or 0))
    except (ValueError, TypeError, OverflowError):
        return "00:00"
    return f"{total_sec // 60:02d}:{total_sec % 60:02d}"


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Read CDR records with filtering and statistics.

    Returns:
    - records: CDR records, each carrying exactly `CDR_FIELDS`
    - count: number of records returned
    - stats: aggregates over the returned records
    - dashboard: trend and per-CLI volume, only when `dashboard=true`
    """
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    logger.info(json.dumps({
        'event': 'voice_cdr_read_request',
        'requestId': request_id
    }))

    try:
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', ''))
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'}, origin)

        from lambda_utils.middleware import require_auth
        required_role = 'Admin' if http_method in ('DELETE', 'POST') else None
        _auth = require_auth(event, required_role=required_role)
        if _auth is not None:
            return _auth

        path = event.get('path', event.get('rawPath', ''))

        # DELETE /voice-cdr-read with {"clearAll": true} (the Call History and System
        # Cleanup "Clear" actions), or a clear path / `_action: clear-logs` body.
        if http_method == 'DELETE' or (http_method == 'POST' and 'clear' in str(event.get('body', ''))):
            body = {}
            try:
                body = json.loads(event.get('body', '{}') or '{}')
            except Exception as e:
                logger.debug(f'Body parse failed in CDR read: {e}')
            if 'clear' in path or body.get('clearAll') or body.get('_action') == 'clear-logs':
                return _clear_cdr_logs(request_id)

        params = event.get('queryStringParameters') or {}
        call_type = params.get('callType', '')
        status = params.get('status', '')
        limit = min(int(params.get('limit', 100)), 500)
        start_date = params.get('startDate', '')
        end_date = params.get('endDate', '')
        caller_number = params.get('callerNumber', '')
        destination_number = params.get('destinationNumber', '')
        hangup_status = params.get('hangupStatus', '')
        search = params.get('search', '')
        include_dashboard = params.get('dashboard', '') == 'true'

        logger.info(json.dumps({
            'event': 'cdr_query_params',
            'callType': call_type,
            'status': status,
            'limit': limit,
            'dashboard': include_dashboard,
            'requestId': request_id
        }))

        table = dynamodb.Table(VOICE_CDR_TABLE)

        # Build scan with filters
        scan_kwargs = {}
        filter_expressions = []
        expression_values = {}

        if call_type:
            filter_expressions.append('callType = :callType')
            expression_values[':callType'] = call_type

        if status:
            filter_expressions.append('overallCallStatus = :status')
            expression_values[':status'] = status

        if start_date:
            filter_expressions.append('createdAt >= :startDate')
            expression_values[':startDate'] = int(start_date)

        if end_date:
            filter_expressions.append('createdAt <= :endDate')
            expression_values[':endDate'] = int(end_date)

        if caller_number:
            filter_expressions.append('contains(callerNumber, :callerNumber)')
            expression_values[':callerNumber'] = caller_number

        if destination_number:
            filter_expressions.append('contains(destinationNumber, :destNumber)')
            expression_values[':destNumber'] = destination_number

        if hangup_status:
            filter_expressions.append('hangupStatus = :hangupStatus')
            expression_values[':hangupStatus'] = hangup_status

        if search:
            filter_expressions.append('contains(callUuid, :search)')
            expression_values[':search'] = search

        if filter_expressions:
            scan_kwargs['FilterExpression'] = ' AND '.join(filter_expressions)
            scan_kwargs['ExpressionAttributeValues'] = expression_values

        all_records = []
        response = table.scan(**scan_kwargs)
        all_records.extend(response.get('Items', []))

        while 'LastEvaluatedKey' in response:
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = table.scan(**scan_kwargs)
            all_records.extend(response.get('Items', []))

        all_records.sort(key=lambda x: _number(x.get('createdAt'), float), reverse=True)
        records = [_format_record(r) for r in all_records[:limit]]

        result = {
            'records': records,
            'count': len(records),
            'stats': _calculate_stats(records),
        }

        if include_dashboard:
            result['dashboard'] = _calculate_dashboard(records)

        return _response(200, result)

    except Exception as e:
        logger.error(json.dumps({
            'event': 'voice_cdr_read_error',
            'error': str(e),
            'errorType': type(e).__name__,
            'requestId': request_id
        }))
        return _response(500, {'error': str(e)})


def _number(value, kind):
    """`value` as `kind` (int or float); 0 for an absent or non-numeric value."""
    if value in (None, ''):
        return kind(0)
    try:
        return kind(float(value))
    except (ValueError, TypeError, OverflowError):
        return kind(0)


def _direction(item: Dict) -> str:
    """INBOUND / OUTBOUND, from callType, else from the provider's direction.

    The fallback uses the same rule as plivo-answer, which writes callType from that
    direction: 'inbound' -> INBOUND, 'outbound' / 'outbound-api' -> OUTBOUND.
    """
    call_type = str(item.get('callType') or '').strip().upper()
    if call_type in ('INBOUND', 'OUTBOUND'):
        return call_type
    raw = str(item.get('direction') or '').strip().lower()
    if raw.startswith('in'):
        return 'INBOUND'
    if raw.startswith('out'):
        return 'OUTBOUND'
    return ''


def _format_record(item: Dict) -> Dict:
    """One VoiceCDRTable item as the API returns it: exactly `CDR_FIELDS`.

    Strings default to '' and numbers to 0, so every record has the same keys
    whichever callbacks reached the row.
    """
    record: Dict[str, Any] = {}
    for name in CDR_STRING_FIELDS:
        value = item.get(name)
        record[name] = '' if value is None else str(value)
    for name in CDR_INT_FIELDS:
        record[name] = _number(item.get(name), int)
    for name in CDR_FLOAT_FIELDS:
        record[name] = _number(item.get(name), float)
    record['direction'] = _direction(item)
    return record


def _count_by(records: List[Dict], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for r in records:
        counts[r.get(field) or 'Unknown'] += 1
    return dict(counts)


def _calculate_stats(records: List[Dict]) -> Dict:
    """Aggregates over formatted records (the page the caller receives)."""
    by_call_type = _count_by(records, 'callType')
    by_status = _count_by(records, 'overallCallStatus')

    conv_durations = [r['conversationDurationSec'] for r in records if r['conversationDurationSec']]
    avg_conversation = round(sum(conv_durations) / len(conv_durations), 2) if conv_durations else 0
    billable = round(sum(r['billableDurationSec'] for r in records), 2)

    return {
        'total': len(records),
        'inbound': by_call_type.get('INBOUND', 0),
        'outbound': by_call_type.get('OUTBOUND', 0),
        'answered': by_status.get('Answered', 0),
        'missed': by_status.get('Missed', 0),
        'busy': by_status.get('Busy', 0),
        'avgConversationDuration': avg_conversation,
        'avgConversationDurationDisplay': _seconds_to_mmss(avg_conversation),
        'totalBillable': billable,
        'totalBillableDisplay': _seconds_to_mmss(billable),
        'byCallType': by_call_type,
        'byStatus': by_status,
        'byHangupCause': _count_by(records, 'hangupCause'),
        'byHangupStatus': _count_by(records, 'hangupStatus'),
    }


def _calculate_dashboard(records: List[Dict]) -> Dict:
    """
    Dashboard aggregations over formatted records.

    Returns:
    - callTrend: answered vs not answered, per UTC date of `timestamp`
    - avgConversationDuration: mm:ss, and avgConversationDurationSec
    - callVolumeByCli: call count per callerId with status and direction breakdown
    """
    trend_data = defaultdict(lambda: {'answered': 0, 'missed': 0, 'total': 0})
    cli_data = defaultdict(lambda: {'total': 0, 'answered': 0, 'missed': 0, 'inbound': 0, 'outbound': 0})
    for r in records:
        answered = r['overallCallStatus'] == 'Answered'

        ts = r['timestamp']
        date_key = ts.split(' ')[0] if ' ' in ts else 'unknown'
        trend_data[date_key]['total'] += 1
        trend_data[date_key]['answered' if answered else 'missed'] += 1

        cli = r['callerId'] or 'Unknown'
        cli_data[cli]['total'] += 1
        cli_data[cli]['answered' if answered else 'missed'] += 1
        cli_data[cli]['inbound' if r['callType'] == 'INBOUND' else 'outbound'] += 1

    conv = [r['conversationDurationSec'] for r in records if r['conversationDurationSec']]
    avg_conv = sum(conv) / len(conv) if conv else 0

    return {
        'callTrend': [{'date': k, **v} for k, v in sorted(trend_data.items())],
        'avgConversationDuration': _seconds_to_mmss(avg_conv),
        'avgConversationDurationSec': round(avg_conv, 2),
        'callVolumeByCli': [
            {'callerId': k, **v}
            for k, v in sorted(cli_data.items(), key=lambda x: x[1]['total'], reverse=True)
        ],
    }


def _clear_cdr_logs(request_id: str) -> Dict[str, Any]:
    """Clear all CDR records from VoiceCDRTable."""
    ddb_client = boto3.client('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    try:
        desc = ddb_client.describe_table(TableName=VOICE_CDR_TABLE)
        key_names = [k['AttributeName'] for k in desc['Table']['KeySchema']]
    except Exception:
        key_names = ['id']

    table = dynamodb.Table(VOICE_CDR_TABLE)
    deleted = 0
    proj_aliases = {f'#k{i}': name for i, name in enumerate(key_names)}
    scan_kwargs = {
        'ProjectionExpression': ', '.join(proj_aliases.keys()),
        'ExpressionAttributeNames': proj_aliases,
    }
    while True:
        resp = table.scan(**scan_kwargs)
        items = resp.get('Items', [])
        if not items:
            break
        with table.batch_writer() as batch:
            for item in items:
                key = {k: item[k] for k in key_names if k in item}
                if key:
                    batch.delete_item(Key=key)
                    deleted += 1
        if 'LastEvaluatedKey' not in resp:
            break
        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']

    logger.info(json.dumps({'event': 'cdr_logs_cleared', 'deleted': deleted, 'requestId': request_id}))
    return _response(200, {'success': True, 'totalDeleted': deleted})


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, cls=DecimalEncoder)
    }
