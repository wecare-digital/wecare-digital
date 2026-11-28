"""
Automation Rules Lambda — CRUD for cross-channel automation rules.

A rule: when an inbound message matches a trigger (keyword/any) on a channel, run an
action (auto-reply text / AI). Rules live in AutomationRulesTable; the shared
lambda_utils/automation.py evaluator (called by inbound handlers) reads them.

Endpoints (HTTP API):
  GET    /automation/rules          - list rules
  POST   /automation/rules          - create rule
  PUT    /automation/rules/{id}     - update rule
  DELETE /automation/rules/{id}     - delete rule

Reads need Viewer. Writes need Operator, are stamped with the session actor and audit-logged.
"""
import os
import json
import time
import uuid
import boto3

from lambda_utils.audit import record_audit
from lambda_utils.response import cors_response, options_response, extract_origin
from lambda_utils.logging import get_logger

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
RULES_TABLE = os.environ.get('AUTOMATION_RULES_TABLE', 'stack-wecare-digital-AutomationRulesTable')

VALID_CHANNELS = ('any', 'whatsapp', 'sms', 'rcs', 'email')
VALID_TRIGGERS = ('keyword', 'any')
VALID_ACTIONS = ('reply', 'ai')
#: The editable rule fields and their values on a new rule.
RULE_DEFAULTS = {
    'name': 'Untitled rule', 'enabled': True, 'channel': 'any', 'triggerType': 'keyword',
    'triggerValue': '', 'actionType': 'reply', 'actionValue': '', 'priority': 100,
}


def _table():
    return dynamodb.Table(RULES_TABLE)


def _actor(event):
    """Who is acting, from the verified session. Never from the request body."""
    auth = event.get('_auth') or {}
    return str(auth.get('username') or auth.get('email') or 'system')


def _rule_fields(body, base):
    """`base` with the rule fields present in `body` applied through the validators.

    POST passes RULE_DEFAULTS and PUT the stored rule, so both run the same checks. An
    unknown channel, trigger or action keeps the base value. A priority that is not an
    integer raises ValueError.
    """
    out = {field: base.get(field, default) for field, default in RULE_DEFAULTS.items()}
    if 'name' in body:
        out['name'] = str(body['name'])[:120]
    if 'enabled' in body:
        out['enabled'] = bool(body['enabled'])
    for field, valid in (('channel', VALID_CHANNELS), ('triggerType', VALID_TRIGGERS),
                         ('actionType', VALID_ACTIONS)):
        if body.get(field) in valid:
            out[field] = body[field]
    if 'triggerValue' in body:
        out['triggerValue'] = str(body['triggerValue'])[:200]
    if 'actionValue' in body:
        out['actionValue'] = str(body['actionValue'])[:2000]
    if 'priority' in body:
        try:
            out['priority'] = int(body['priority'])
        except (TypeError, ValueError, OverflowError):
            raise ValueError('priority must be an integer') from None
    return out


def _priority_key(rule):
    """List order. A stored priority that is not a number sorts last instead of failing."""
    try:
        return (0, int(rule.get('priority', 100)))
    except (TypeError, ValueError, OverflowError):
        return (1, 0)


def handler(event, context):
    origin = extract_origin(event)
    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()
    if method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    # A rule auto-replies to customers, so every change needs Operator.
    _auth = require_auth(event, required_role='Viewer' if method == 'GET' else 'Operator')
    if _auth is not None:
        return _auth

    path_params = event.get('pathParameters') or {}
    rule_id = path_params.get('id') or path_params.get('ruleId')

    try:
        if method == 'GET':
            resp = _table().scan()
            items = sorted(resp.get('Items', []), key=_priority_key)
            return cors_response(200, {'rules': items, 'count': len(items)}, origin)

        if method == 'POST':
            body = json.loads(event.get('body', '{}'))
            if not isinstance(body, dict):
                return cors_response(400, {'error': 'JSON object required'}, origin)
            try:
                fields = _rule_fields(body, RULE_DEFAULTS)
            except ValueError as exc:
                return cors_response(400, {'error': str(exc)}, origin)
            now = int(time.time())
            rid = str(uuid.uuid4())
            actor = _actor(event)
            item = {'id': rid, **fields, 'createdAt': now, 'updatedAt': now,
                    'createdBy': actor, 'updatedBy': actor}
            _table().put_item(Item=item)
            record_audit(action='automation_rule.create', actor=actor,
                         resource_type='automation_rule', resource_id=rid, details={'rule': fields})
            return cors_response(200, {'rule': item}, origin)

        if method == 'PUT':
            if not rule_id:
                return cors_response(400, {'error': 'rule id required'}, origin)
            body = json.loads(event.get('body', '{}'))
            if not isinstance(body, dict):
                return cors_response(400, {'error': 'JSON object required'}, origin)
            existing = _table().get_item(Key={'id': rule_id}).get('Item')
            if not existing:
                return cors_response(404, {'error': 'rule not found'}, origin)
            try:
                fields = _rule_fields(body, existing)
            except ValueError as exc:
                return cors_response(400, {'error': str(exc)}, origin)
            changes = {f: {'from': existing.get(f), 'to': v} for f, v in fields.items()
                       if existing.get(f) != v}
            actor = _actor(event)
            existing.update(fields)
            existing['updatedAt'] = int(time.time())
            existing['updatedBy'] = actor
            _table().put_item(Item=existing)
            record_audit(action='automation_rule.update', actor=actor,
                         resource_type='automation_rule', resource_id=rule_id,
                         details={'changes': changes})
            return cors_response(200, {'rule': existing}, origin)

        if method == 'DELETE':
            if not rule_id:
                return cors_response(400, {'error': 'rule id required'}, origin)
            deleted = _table().delete_item(Key={'id': rule_id}, ReturnValues='ALL_OLD').get('Attributes')
            record_audit(action='automation_rule.delete', actor=_actor(event),
                         resource_type='automation_rule', resource_id=rule_id,
                         details={'rule': deleted or None})
            return cors_response(200, {'success': True, 'deleted': rule_id}, origin)

        return cors_response(405, {'error': 'method not allowed'}, origin)
    except json.JSONDecodeError:
        return cors_response(400, {'error': 'invalid JSON'}, origin)
    except Exception as e:
        logger.error(f'automation-rules error: {e}')
        return cors_response(500, {'error': 'internal error'}, origin)
