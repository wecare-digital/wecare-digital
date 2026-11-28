"""
Settings API Lambda Function (wecare-ai-config-management)

The generic SystemConfig settings reader/writer behind GET/PUT /ai/config?key=. The name and
route are kept so the deployed Lambda and API route do not change. There is no AI behaviour:
no model calls, prompts, fallbacks, interaction logs or auto-reply configuration.

Table: SystemConfigTable
Keys: the Workspace settings rows in SETTINGS_CONFIG_KEYS through ?key= / body.key; no other row

Authority: a staff token (Viewer or above) for reads. Every write needs Operator.
Writes are audit-logged.
"""

import hashlib
import os
import json
import boto3
from typing import Dict, Any
from decimal import Decimal
import time

from lambda_utils.response import cors_headers, options_response, extract_origin
from lambda_utils.ecommerce import item_processes

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')

#: The SystemConfig rows the Workspace settings pages read and write through
#: `GET /ai/config?key=` and `PUT /ai/config {key}`: menus, keyword-to-Flow triggers
#: (including the F001 Subscribe switch), the F001 Subscribe copy, item payment processes and
#: Vault delivery timing. Every other row in the table (dedup markers, cleanup confirmations,
#: captured webhook events, account wiring) is not a setting, and this route refuses to read
#: or rewrite it.
SETTINGS_CONFIG_KEYS = item_processes.CONFIG_KEYS | frozenset({
    'customerservice_menu_config',
    'flow_triggers_config', 'subscribe_messages_config',
    'vault_delivery_timing_v1',
})

# Vault journey rows document existing approved send metadata. Workspace may
# preview them but must never modify them through the generic settings editor.
READONLY_REFERENCE_CONFIG_KEYS = frozenset({
    'vault_whatsapp_template_journey_v1',
})


def _required_write_role(method: str, path: str) -> str:
    """'' for a read; otherwise the least staff role that may make this change."""
    if method in ('GET', 'HEAD'):
        return ''
    return 'Operator'


def _audit_config_write(event: Dict[str, Any], method: str, path: str, config_key: str,
                        request_id: str) -> None:
    """One structured line per settings write: who (pseudonymous), what, which key."""
    auth = event.get('_auth') or {}
    actor = str(auth.get('username') or '')
    logger.info(json.dumps({
        'event': 'settings_write_audit',
        'method': method,
        'path': path,
        'configKey': config_key,
        # A short hash, not the username: correlatable with the staff pool, not PII in logs.
        'actor': hashlib.sha256(actor.encode('utf-8')).hexdigest()[:12] if actor else 'internal',
        'groups': list(auth.get('groups') or []),
        'requestId': request_id,
    }))


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Settings API Handler

    Routes:
    - GET /ai/config?key=<settings key> - Read a settings row
    - PUT /ai/config {key, config} - Write a settings row
    """
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    # Handle both API Gateway v1 (REST) and v2 (HTTP) event formats
    request_context = event.get('requestContext', {})
    if 'http' in request_context:
        http_method = request_context.get('http', {}).get('method', 'GET')
        path = request_context.get('http', {}).get('path', '')
    else:
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '')

    if not path:
        path = event.get('rawPath', '')

    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'settings_request',
        'method': http_method,
        'path': path,
        'rawPath': event.get('rawPath', ''),
        'requestId': request_id
    }))

    if http_method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    write_role = _required_write_role(http_method, path)
    _auth = require_auth(event, required_role=write_role or None)
    if _auth is not None:
        return _auth

    try:
        body = {}
        if event.get('body'):
            body = json.loads(event.get('body', '{}'))
        if write_role:
            _audit_config_write(event, http_method, path,
                                str(body.get('key') or '') if isinstance(body, dict) else '',
                                request_id)

        if '/ai/config' in path:
            if http_method == 'GET':
                cfg_key = query_params.get('key', '')
                if cfg_key not in SETTINGS_CONFIG_KEYS | READONLY_REFERENCE_CONFIG_KEYS:
                    return _error_response(400, 'Unknown settings key')
                return _get_config(request_id, config_key=cfg_key)
            if http_method == 'PUT':
                cfg_key = body.pop('key', '') if isinstance(body, dict) else ''
                if cfg_key not in SETTINGS_CONFIG_KEYS:
                    return _error_response(400, 'Unknown settings key')
                return _update_config(body, request_id, config_key=cfg_key)

        return _error_response(400, 'Invalid request')

    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'settings_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _error_response(500, str(e))


def _get_config(request_id: str, config_key: str) -> Dict[str, Any]:
    """Get a SystemConfig settings entry by key."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        response = config_table.get_item(Key={'id': config_key})

        if 'Item' not in response:
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({'config': None, 'configKey': config_key})
            }
        config_value = response['Item'].get('configValue', '{}')
        try:
            config = json.loads(config_value) if isinstance(config_value, str) else config_value
        except (json.JSONDecodeError, TypeError):
            config = config_value

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'config': config, 'configKey': config_key})
        }
    except Exception as e:
        logger.error(f'Failed to get config [{config_key}]: {str(e)}')
        return _error_response(500, f'Failed to get config: {str(e)}')


def _update_config(body: Dict, request_id: str, config_key: str) -> Dict[str, Any]:
    """Update a SystemConfig settings entry by key."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        # This is the ONLY operator-editable Vault timer. Never accept a field
        # that could re-introduce status, native-pay or paid-invoice sleep.
        # Legacy records with orderStatusGapSeconds remain readable while new
        # writes replace them with this single bounded access-only field.
        if config_key == 'vault_delivery_timing_v1':
            proposed = body.get('config')
            required = {'postReceiptAccessGapSeconds'}
            if (not isinstance(proposed, dict) or set(proposed) != required
                    or type(proposed['postReceiptAccessGapSeconds']) is not int
                    or not 0 <= proposed['postReceiptAccessGapSeconds'] <= 5):
                return _error_response(400, 'Access Vault delay must be a whole number of seconds (0-5)')

        if config_key in item_processes.CONFIG_KEYS:
            error = item_processes.validate_draft(config_key, body.get('config'))
            if error:
                return _error_response(400, error)

        config_value = body.get('config', body.get('configValue', body))
        store_val = json.dumps(config_value) if not isinstance(config_value, str) else config_value
        config_table.put_item(Item={
            'id': config_key,
            'configValue': store_val,
            'updatedAt': Decimal(str(int(time.time())))
        })
        logger.info(json.dumps({
            'event': 'system_config_updated',
            'configKey': config_key,
            'requestId': request_id
        }))
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'configKey': config_key})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update config: {str(e)}')


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }
