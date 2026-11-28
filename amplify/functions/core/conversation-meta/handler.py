"""
Conversation Meta Lambda — shared-team-inbox collaboration metadata per conversation.

Stores, per conversation (keyed by contactId), the team-inbox fields that don't belong on
individual messages: status (open/pending/resolved), assignee, labels/tags, and internal
notes (team-only, never sent to the customer).

Endpoints (HTTP API):
  GET    /inbox/meta/{conversationId}        - get meta (status, assignee, tags, notes)
  PUT    /inbox/meta/{conversationId}        - update status / assignee / tags
  POST   /inbox/meta/{conversationId}/note   - append an internal note
  GET    /inbox/meta                         - list all meta (for board/filters)

Reads need Viewer. Writes need Operator, are stamped with the session actor and audit-logged.
"""
import os
import json
import time
import boto3

from lambda_utils.audit import record_audit
from lambda_utils.response import cors_response, options_response, extract_origin
from lambda_utils.logging import get_logger

logger = get_logger(__name__)
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
META_TABLE = os.environ.get('CONVERSATION_META_TABLE', 'stack-wecare-digital-ConversationMetaTable')

VALID_STATUS = ('open', 'pending', 'resolved')


def _table():
    return dynamodb.Table(META_TABLE)


def _get(cid):
    item = _table().get_item(Key={'conversationId': cid}).get('Item')
    return item or {'conversationId': cid, 'status': 'open', 'assignee': '', 'tags': [], 'notes': []}


def _actor(event):
    """Who is acting, from the verified session. Never from the request body."""
    auth = event.get('_auth') or {}
    return str(auth.get('username') or auth.get('email') or 'system')


def handler(event, context):
    origin = extract_origin(event)
    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()
    if method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event, required_role='Viewer' if method == 'GET' else 'Operator')
    if _auth is not None:
        return _auth

    pp = event.get('pathParameters') or {}
    cid = pp.get('conversationId')
    path = event.get('rawPath', event.get('path', ''))
    is_note = path.endswith('/note')

    try:
        if method == 'GET' and not cid:
            resp = _table().scan()
            return cors_response(200, {'meta': resp.get('Items', []), 'count': resp.get('Count', 0)}, origin)

        if method == 'GET' and cid:
            return cors_response(200, {'meta': _get(cid)}, origin)

        if method == 'POST' and cid and is_note:
            body = json.loads(event.get('body', '{}'))
            if not isinstance(body, dict):
                return cors_response(400, {'error': 'JSON object required'}, origin)
            text = str(body.get('text', '')).strip()[:2000]
            if not text:
                return cors_response(400, {'error': 'note text required'}, origin)
            actor = _actor(event)
            item = _get(cid)
            notes = item.get('notes', []) or []
            # The author is the session actor; a `by` field in the body is ignored.
            notes.append({'text': text, 'by': actor[:80], 'at': int(time.time())})
            item['notes'] = notes[-100:]
            item['updatedAt'] = int(time.time())
            item['updatedBy'] = actor
            _table().put_item(Item=item)
            record_audit(action='conversation_meta.note', actor=actor,
                         resource_type='conversation', resource_id=cid,
                         details={'noteLength': len(text)})
            return cors_response(200, {'meta': item}, origin)

        if method == 'PUT' and cid:
            body = json.loads(event.get('body', '{}'))
            if not isinstance(body, dict):
                return cors_response(400, {'error': 'JSON object required'}, origin)
            item = _get(cid)
            before = {f: item.get(f) for f in ('status', 'assignee', 'tags')}
            if 'status' in body and body['status'] in VALID_STATUS:
                item['status'] = body['status']
            if 'assignee' in body:
                item['assignee'] = str(body['assignee'])[:120]
            if 'tags' in body and isinstance(body['tags'], list):
                item['tags'] = [str(t)[:40] for t in body['tags']][:20]
            actor = _actor(event)
            item['updatedAt'] = int(time.time())
            item['updatedBy'] = actor
            _table().put_item(Item=item)
            changes = {f: {'from': before[f], 'to': item.get(f)} for f in before
                       if before[f] != item.get(f)}
            record_audit(action='conversation_meta.update', actor=actor,
                         resource_type='conversation', resource_id=cid,
                         details={'changes': changes})
            return cors_response(200, {'meta': item}, origin)

        return cors_response(405, {'error': 'method not allowed'}, origin)
    except json.JSONDecodeError:
        return cors_response(400, {'error': 'invalid JSON'}, origin)
    except Exception as e:
        logger.error(f'conversation-meta error: {e}')
        return cors_response(500, {'error': 'internal error'}, origin)
