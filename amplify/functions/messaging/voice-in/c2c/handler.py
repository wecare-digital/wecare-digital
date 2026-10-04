"""Legacy click-to-call records and CDR ingestion.

    GET    /voice-in/c2c    list historical C2C call records
    DELETE /voice-in/c2c    delete / clear records (retention)
    POST   /voice-in/c2c    CDR callback ingestion only

Outbound click-to-call INITIATION was removed on 2026-09-19. It dialled a retired
India voice provider's API, which the provider policy prohibits, and PSTN voice is
now Plivo. A POST that is not a recognised CDR callback is answered 410, naming
the replacement, rather than failing obscurely.

What remains is deliberate:

  * historical records in the C2C table, describing calls that really were placed
    and retained as audit evidence;
  * CDR callback ingestion and its notification fan-out, which routes through AWS
    End User Messaging via lambda_utils.comms;
  * recording references already written to S3.

Retired vendor hostnames and credential identifiers are deliberately not repeated
in this file, so the provider-policy scan stays high-precision over runtime code.
See docs/provider-retirement-inventory.md.
"""

import os
import json
import uuid
import time
import logging
import boto3
import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Dict, Any
from decimal import Decimal

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.privacy import mask_contact_id  # contactId is `wa` + the customer's digits
from lambda_utils.middleware import require_auth
from lambda_utils import retired_store
# Imported for its import-time validation side effect, not for a value: the
# only read of META_API_VERSION here went with the deleted wd_menu send.
from lambda_utils.meta_version import META_API_VERSION  # noqa: F401
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# AWS clients
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
s3 = boto3.client('s3', region_name=AWS_REGION)
lambda_client = boto3.client('lambda', region_name=AWS_REGION)

# Environment variables
# The code identifier stops naming a provider; the physical table name is
# unchanged because renaming it would not move any data.
#
# No env fallback is needed for the old variable name: its deployed value is
# identical to this default, so a function whose configuration has not been
# updated resolves to the same table either way. Verified against the live
# configuration - the retired-provider table variable still set on this function
# carries exactly this value. Its name is not written out here because
# scripts/check-provider-policy.sh treats the literal as a runtime reference to a
# prohibited provider, and that bluntness is correct: a prohibition that can be
# talked around with a comment is not a prohibition.
#
# CORRECTION, measured 2026-09-24 - this comment previously read "it holds real
# historical records that must stay readable", which is false. `ListTables` does
# not return this table; it was deleted on 2026-09-20 with the Airtel retirement,
# as operations/system-cleanup already records. Five call sites below name it, and
# this function took 39 invocations in 30 days, so the reads were answering 500.
# They now answer 410 via _legacy_store_gone: the data was deliberately removed,
# which is a different statement from "the platform is broken" and points at a
# different remedy. Restoring it, if that is wanted, is a retention decision for
# the owner and is not something this handler can take.
LEGACY_C2C_TABLE = os.environ.get('LEGACY_C2C_TABLE',
                                  'stack-wecare-digital-AirtelC2CTable')


def _legacy_store_gone(operation: str) -> Dict[str, Any]:
    """410 for a read against the deleted retired-provider call store."""
    logger.info({
        'event': 'retired_store_absent',
        'operation': operation,
        'table': LEGACY_C2C_TABLE,
    })
    return _response(retired_store.ABSENT_HTTP_STATUS, retired_store.absent_payload(
        LEGACY_C2C_TABLE,
        what='Retired-provider click-to-call history',
        retired='Deleted 2026-09-20 with the Airtel retirement.',
    ))
# Read from the environment, and default to the bucket that actually exists.
#
# This was the literal 'app.wecare.digital' until 2026-09-28, which made the
# S3_BUCKET env var on this function inert: the deployed value was repointed
# during the media cutover and the code ignored it. That bucket was then deleted,
# so the literal named nothing and every delete_object below would have raised
# NoSuchBucket. The sibling handler in voice-in/obd already read the env var,
# which is why only this one broke.
S3_BUCKET = os.environ.get('S3_BUCKET', media_paths.BUCKET)
S3_RECORDING_PREFIX = media_paths.public('stack/voice/')
CALL_TTL_SECONDS = 90 * 24 * 60 * 60

# Cached secrets
_secrets_cache = None


# _get_secrets() removed: the retired provider credential is no longer read
# here. The secret still exists in Secrets Manager with no reader and is
# deleted under separate destructive approval.


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Click-to-Call requests."""
    request_id = context.aws_request_id if context else str(uuid.uuid4())
    global origin
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    path = event.get('rawPath', event.get('path', ''))
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'c2c_handler',
        'method': http_method,
        'path': path,
        'requestId': request_id
    }))

    try:
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'}, origin)

        # ── Authenticate API Gateway callers ──
        # These routes were public (AuthorizationType=NONE) with no handler check
        # either, which left DELETE /voice-in/c2c and DELETE /voice-in/c2c/clear-logs
        # able to wipe call history anonymously. The provider webhook this once
        # served is retired; the live callers are dashboard reads and clears, which
        # already send a Cognito bearer token. require_auth skips OPTIONS and
        # internal Lambda invokes, so nothing internal changes.
        auth_failure = require_auth(event)
        if auth_failure is not None:
            return auth_failure

        body = json.loads(event.get('body', '{}')) if event.get('body') else {}

        # GET - List calls
        if http_method == 'GET':
            return _list_calls(query_params, request_id)

        # DELETE - Delete call logs
        if http_method == 'DELETE' or '/delete' in path or '/clear-logs' in path:
            call_ids = body.get('callIds', [])
            call_id = query_params.get('callId')
            hard_delete = query_params.get('hard') == 'true' or body.get('hardDelete', False)
            clear_all = body.get('clearAll', False)

            if clear_all:
                return _clear_logs(request_id)
            elif call_id:
                return _delete_call(call_id, hard_delete, request_id)
            elif call_ids:
                return _delete_calls(call_ids, hard_delete, request_id)
            return _response(400, {'error': 'callId, callIds, or clearAll is required'})


        # POST that is not a CDR callback. Clear-logs-via-POST is still
        # honoured, because the dashboard uses it for retention.
        if body.get('clearAll') or body.get('_action') == 'clear-logs':
            return _clear_logs(request_id)

        # Outbound initiation is gone. Answer explicitly: a caller still
        # posting fromNumber/toNumber expecting a call to be placed must be
        # told the capability moved, not left to infer it from a 400 about
        # missing fields.
        logger.warning(json.dumps({
            'event': 'c2c_initiation_removed',
            'requestId': request_id,
        }))
        return _response(410, {
            'error': 'Click-to-call initiation has been removed.',
            'errorCode': 'ENDPOINT_REMOVED',
            'detail': ('This endpoint dialled a retired India voice provider. '
                       'PSTN voice is now Plivo. Outbound calling is delivered '
                       'by the Plivo browser softphone and is gated behind '
                       'PSTN_BROWSER_ROUTING_ENABLED. This endpoint still '
                       'serves GET for historical records and POST for CDR '
                       'callbacks.'),
        })

    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON'})
    except Exception as e:
        logger.error(f"C2C error: {str(e)}")
        return _response(500, {'error': 'Internal server error'})


# _make_c2c_call() and _generate_hmac_headers() removed 2026-09-19 with the
# initiation endpoint. They built and HMAC-signed requests to a prohibited
# provider; keeping them would leave a working dialler one call site away.


def _list_calls(params: Dict, request_id: str) -> Dict[str, Any]:
    """List C2C calls."""
    try:
        table = dynamodb.Table(LEGACY_C2C_TABLE)
        from boto3.dynamodb.conditions import Attr

        scan_kwargs = {'Limit': int(params.get('limit', 100))}
        filter_expressions = []

        if params.get('contactId'):
            filter_expressions.append(Attr('contactId').eq(params['contactId']))
        if params.get('status'):
            filter_expressions.append(Attr('status').eq(params['status']))
        if params.get('fromNumber'):
            filter_expressions.append(Attr('fromNumber').contains(params['fromNumber']))
        if params.get('toNumber'):
            filter_expressions.append(Attr('toNumber').contains(params['toNumber']))

        if filter_expressions:
            combined = filter_expressions[0]
            for expr in filter_expressions[1:]:
                combined = combined & expr
            scan_kwargs['FilterExpression'] = combined

        result = table.scan(**scan_kwargs)
        calls = result.get('Items', [])
        calls.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)

        return _response(200, {
            'calls': [_normalize_call(c) for c in calls],
            'count': len(calls)
        })
    except Exception as e:
        if retired_store.is_absent(e):
            return _legacy_store_gone('List')
        logger.error(f"List calls error: {str(e)}")
        return _response(500, {'error': str(e)})


# _store_call() removed 2026-09-19. It wrote a row for a call this function had
# just placed, so it existed only for the initiation path and had no callers
# left once that path was removed. Historical rows are read by _list_calls and
# normalised by _normalize_call below.
#
# The original note ended "CDR callbacks write through _handle_cdr_callback".
# That is no longer true: the Airtel CDR write path was removed on 2026-09-25 (see
# below), so nothing writes VoiceCDRTable from this function. It is read-only here.


def _normalize_call(item: Dict) -> Dict:
    """Normalize call record for API response."""
    return {
        'callId': item.get('callId', ''),
        'contactId': item.get('contactId', ''),
        'fromNumber': item.get('fromNumber', ''),
        'toNumber': item.get('toNumber', ''),
        'callerId': item.get('callerId', ''),
        'status': item.get('status', ''),
        'duration': int(float(item.get('duration', 0))),
        'recordingEnabled': item.get('recordingEnabled', True),
        'recordingUrl': item.get('recordingUrl', ''),
        's3RecordingKey': item.get('s3RecordingKey', ''),
        'correlationId': item.get('correlationId', ''),
        'errorDetails': item.get('errorDetails', ''),
        'createdAt': int(float(item.get('createdAt', 0))),
        'updatedAt': int(float(item.get('updatedAt', 0))),
    }


# Airtel CDR-callback surface REMOVED 2026-09-25.
#
# `_is_cdr_callback`, `_handle_cdr_callback` and `_normalize_cdr_payload` accepted
# an Airtel C2C CDR payload POSTed to this endpoint and wrote it into
# VoiceCDRTable. Airtel is a retired provider, so nothing sends them.
#
# Proven before removal, over the full 30-day log retention window: zero
# `c2c_cdr_callback_received` events, against a control pattern (`REPORT`) that
# matched in the same query. The function is live and was invoked 41 times in that
# window, so this removes a branch, not a dead function.
#
# Reading CDR history is NOT affected - VOICE_CDR_TABLE is still read below.
#
# `_safe_int_val` and `_store_recording_to_s3` went with it: both were only ever
# called from `_handle_cdr_callback`, so removing the branch left them unreachable.
def _lookup_contact_id(phone: str) -> str:
    """Look up contactId from ContactsTable by phone number."""
    clean = phone.replace('+', '').replace(' ', '')
    contacts_table = dynamodb.Table('stack-wecare-digital-ContactsTable')
    for variant in [phone, clean, '+' + clean]:
        try:
            resp = contacts_table.query(
                IndexName='phone-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('phone').eq(variant),
                Limit=1
            )
            items = resp.get('Items', [])
            if items:
                return items[0].get('contactId') or items[0].get('id') or clean
        except Exception:
            pass
    return clean


def _store_to_inbox(message_id: str, contact_id: str, contact_phone: str,
                    content: str, channel: str, status: str,
                    message_type: str, phone_number_id: str = '',
                    wamid: str = '', request_id: str = '') -> None:
    """Store a sent notification in WhatsAppOutboundTable for inbox visibility."""
    try:
        now = int(time.time())
        store_id = message_id or f"c2c_{contact_phone}_{now}"
        outbound_table = dynamodb.Table('stack-wecare-digital-WhatsAppOutboundTable')
        item = {
            'id': store_id,
            'messageId': store_id,
            'contactId': contact_id,
            'contactPhone': contact_phone,
            'content': content,
            'channel': channel,
            'direction': 'outbound',
            'status': status,
            'messageType': message_type,
            'timestamp': Decimal(str(now)),
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + 30 * 24 * 60 * 60)),
            'requestId': request_id,
        }
        if wamid:
            item['whatsappMessageId'] = wamid
        else:
            item['whatsappMessageId'] = store_id
        if phone_number_id:
            item['phoneNumberId'] = phone_number_id
            item['awsPhoneNumberId'] = phone_number_id
        outbound_table.put_item(Item=item)
        logger.info(json.dumps({
            'event': 'c2c_notification_stored_in_inbox',
            'id': store_id,
            'channel': channel,
            'contactId': mask_contact_id(contact_id),
            'requestId': request_id,
        }))
    except Exception as e:
        logger.warning(f'Failed to store C2C notification in inbox: {e}')


def _send_c2c_cdr_notifications(cdr_record: Dict, request_id: str) -> None:
    """Send RCS + SMS notifications on C2C CDR events.

    Sends to the CALLER (Party A) after call completes.
    Channel priority: SMS (AWS End User Messaging) → RCS (Sinch rcsmenu template)
    Updates CDR record with trigger metadata for dashboard display.
    """
    try:
        caller = cdr_record.get('callerNumber', '')
        if not caller:
            return

        # Normalize phone: handle "9903300044", "09903300044", "+919903300044", "919903300044"
        clean_caller = caller.replace('+', '').replace(' ', '').replace('-', '')
        if clean_caller.startswith('0') and len(clean_caller) == 11:
            clean_caller = clean_caller[1:]
        if not (clean_caller.startswith('91') and len(clean_caller) == 12):
            if len(clean_caller) >= 10:
                clean_caller = '91' + clean_caller[-10:]

        contact_id = _lookup_contact_id(clean_caller)
        now_ts = int(time.time())
        sms_message_id = ''
        rcs_message_id = ''
        rcs_sent = False

        # ── 0. Send SMS via Airtel IQ (same as WhatsApp calling disconnect) ──
        session_id = cdr_record.get('vmSessionId', '') or cdr_record.get('clientCorrelationId', '')
        ivr_sms_content = (
            "Thanks for contacting WECARE.DIGITAL!\n\n"
            "Submit your request here: https://wecare.digital/submit-request/ "
            "or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\n"
            "We'll review it and follow up if needed."
        )
        try:
            # One call, every country. comms.notify selects the AWS region and
            # applies the TRAI DLT gate; this handler decides neither.
            from lambda_utils.comms.notify import send_notification_sms
            send_notification_sms(
                '+' + clean_caller, ivr_sms_content,
                dlt_template_key='ivr-default',
                campaign='c2c-cdr', request_id=request_id)
            sms_message_id = f"c2c_sms_{session_id}_{now_ts}"
            _store_to_inbox(
                message_id=sms_message_id,
                contact_id=contact_id,
                contact_phone=clean_caller,
                content=ivr_sms_content,
                channel='sms',
                status='sent',
                message_type='cdr_c2c',
                request_id=request_id,
            )
            logger.info(json.dumps({
                'event': 'c2c_cdr_sms_triggered',
                'caller': clean_caller[-4:],
                'provider': 'aws-end-user-messaging',
                'smsId': sms_message_id,
                'requestId': request_id,
            }))
        except Exception as sms_err:
            logger.warning(f'C2C CDR SMS failed (non-blocking): {sms_err}')

        # ── 1. RCS via Sinch (rcsmenu template) ──
        try:
            from lambda_utils.sinch_rcs import is_rcs_enabled, send_rcs_ivr_notification
            if is_rcs_enabled():
                rcs_result = send_rcs_ivr_notification(clean_caller, request_id)
                rcs_sent = rcs_result.get('success', False)
                if rcs_sent:
                    rcs_message_id = rcs_result.get('message_id', '')
                    _store_to_inbox(
                        message_id=rcs_message_id,
                        contact_id=contact_id,
                        contact_phone=clean_caller,
                        content='[RCS notification] WECARE.DIGITAL customerservice',
                        channel='rcs',
                        status='sent',
                        message_type='cdr_c2c',
                        request_id=request_id,
                    )
                else:
                    logger.warning(f"C2C RCS returned success=false: {rcs_result.get('error', 'unknown')}")
        except Exception as rcs_err:
            logger.warning(f'C2C CDR RCS notification failed (non-blocking): {rcs_err}')

        # ── 3. Update CDR record with trigger metadata ──
        cdr_id = cdr_record.get('id', '')
        if cdr_id:
            try:
                table = dynamodb.Table(VOICE_CDR_TABLE)
                update_expr_parts = []
                expr_values = {}

                if sms_message_id:
                    update_expr_parts.append('smsTriggered = :smsT')
                    expr_values[':smsT'] = True
                    update_expr_parts.append('smsMessageId = :smsId')
                    expr_values[':smsId'] = sms_message_id
                    update_expr_parts.append('smsDltTemplateId = :smsDlt')
                    expr_values[':smsDlt'] = '1007277993798259629'
                    update_expr_parts.append('smsContent = :smsCont')
                    expr_values[':smsCont'] = ivr_sms_content[:200]
                    update_expr_parts.append('smsTimestamp = :smsTs')
                    expr_values[':smsTs'] = str(now_ts)

                if rcs_sent and rcs_message_id:
                    update_expr_parts.append('rcsMessageTriggered = :rcsT')
                    expr_values[':rcsT'] = True
                    update_expr_parts.append('rcsMessageId = :rcsId')
                    expr_values[':rcsId'] = rcs_message_id
                    update_expr_parts.append('rcsMessageContent = :rcsCont')
                    expr_values[':rcsCont'] = '[RCS notification] WECARE.DIGITAL customerservice'
                    update_expr_parts.append('rcsMessageTimestamp = :rcsTs')
                    expr_values[':rcsTs'] = str(now_ts)

                if update_expr_parts:
                    table.update_item(
                        Key={'id': cdr_id},
                        UpdateExpression='SET ' + ', '.join(update_expr_parts),
                        ExpressionAttributeValues=expr_values,
                    )
                    logger.info(json.dumps({
                        'event': 'c2c_cdr_trigger_metadata_updated',
                        'cdrId': cdr_id,
                        'sms': bool(sms_message_id),
                        'rcs': rcs_sent,
                        'requestId': request_id,
                    }))
            except Exception as e:
                logger.warning(f'C2C CDR trigger metadata update failed (non-blocking): {e}')

    except Exception as e:
        logger.warning(f'C2C CDR notification error: {e}')


def _clean_phone_number(phone: str) -> str:
    """Clean phone number to 10 digits."""
    if not phone:
        return ''
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    return digits if len(digits) == 10 else ''


def _delete_call(call_id: str, hard_delete: bool, request_id: str) -> Dict[str, Any]:
    """Delete a single C2C call record (soft or hard delete)."""
    try:
        table = dynamodb.Table(LEGACY_C2C_TABLE)

        if hard_delete:
            # Delete S3 recording if exists
            try:
                result = table.get_item(Key={'callId': call_id})
                call = result.get('Item')
                if call and call.get('s3RecordingKey'):
                    s3.delete_object(Bucket=S3_BUCKET, Key=call['s3RecordingKey'])
            except Exception as e:
                logger.warning(f"Failed to delete S3 recording: {str(e)}")

            table.delete_item(Key={'callId': call_id})
            return _response(200, {'success': True, 'deleted': call_id, 'type': 'hard'})
        else:
            now = int(time.time())
            table.update_item(
                Key={'callId': call_id},
                UpdateExpression='SET #status = :status, deletedAt = :deletedAt, updatedAt = :updatedAt',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'DELETED',
                    ':deletedAt': Decimal(str(now)),
                    ':updatedAt': Decimal(str(now))
                }
            )
            return _response(200, {'success': True, 'deleted': call_id, 'type': 'soft'})
    except Exception as e:
        if retired_store.is_absent(e):
            return _legacy_store_gone('Delete')
        logger.error(f"Delete call error: {str(e)}")
        return _response(500, {'error': str(e)})


def _delete_calls(call_ids: list, hard_delete: bool, request_id: str) -> Dict[str, Any]:
    """Delete multiple C2C call records."""
    deleted_count = 0
    for call_id in call_ids:
        try:
            result = _delete_call(call_id, hard_delete, request_id)
            if json.loads(result.get('body', '{}')).get('success'):
                deleted_count += 1
        except Exception as e:
            logger.warning(f'C2C call delete failed for {call_id}: {e}')

    return _response(200, {
        'success': True,
        'deletedCount': deleted_count,
        'type': 'hard' if hard_delete else 'soft'
    })


def _clear_logs(request_id: str) -> Dict[str, Any]:
    """Clear all C2C call logs (handles pagination for large tables)."""
    try:
        table = dynamodb.Table(LEGACY_C2C_TABLE)
        deleted_count = 0

        scan_kwargs = {'ProjectionExpression': 'callId,s3RecordingKey'}
        while True:
            result = table.scan(**scan_kwargs)
            for item in result.get('Items', []):
                if item.get('s3RecordingKey'):
                    try:
                        s3.delete_object(Bucket=S3_BUCKET, Key=item['s3RecordingKey'])
                    except Exception as e:
                        logger.warning(f"S3 recording cleanup failed for {item['s3RecordingKey']}: {e}")
                table.delete_item(Key={'callId': item['callId']})
                deleted_count += 1

            if 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']

        return _response(200, {
            'success': True,
            'deletedCount': deleted_count,
            'message': f'Cleared {deleted_count} C2C call logs'
        })
    except Exception as e:
        if retired_store.is_absent(e):
            # Asked to clear a store that is already gone. The caller's intent is
            # satisfied, but it must not be told it deleted rows it did not.
            return _legacy_store_gone('Clear logs')
        logger.error(f"Clear logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _response(status_code: int, body: Dict, resp_origin: str = '') -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(resp_origin or origin),
        'body': json.dumps(body, default=str)
    }
