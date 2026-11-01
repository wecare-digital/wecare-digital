"""Periodic, read-only Meta inspection and atomic template-to-Flow mapping reconciliation.

No customer messages, Meta mutations, template sends, or Flow launch policy changes.
Only the dedicated TemplateFlowMapping DynamoDB table is written. Aborts without
writes on partial Meta listings, unknown Flows, duplicate IDs and invalid health.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Callable

from boto3.dynamodb.types import TypeSerializer

logger = logging.getLogger(__name__)
META_TEMPLATE_FIELDS = 'id,name,status,category,language,components'
META_FLOW_FIELDS = 'id,name,status,validation_errors,health_status'
MAX_META_PAGES = 10
MAX_WRITES = 100


def _numeric_id(value):
    text = str(value or '').strip()
    if not text.isascii() or not text.isdigit() or not text:
        raise ValueError('Meta returned a nonnumeric object ID')
    return text


def _meta_pages(graph_get: Callable, edge: str, fields: str) -> list[dict]:
    """Return every provider page, or refuse to use any of the result."""
    rows = []
    after = ''
    seen = set()
    for _ in range(MAX_META_PAGES):
        params = {'fields': fields, 'limit': '100'}
        if after:
            params['after'] = after
        result = graph_get(edge, params=params)
        if not isinstance(result, dict) or result.get('error'):
            raise ValueError('Meta inventory request failed; registry not modified')
        batch = result.get('data')
        if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
            raise ValueError('Meta inventory returned an invalid page')
        rows.extend(batch)
        paging = result.get('paging') or {}
        if not isinstance(paging, dict):
            raise ValueError('Meta paging was invalid')
        if not paging.get('next'):
            return rows
        after = str((paging.get('cursors') or {}).get('after') or '')
        if not after or after in seen:
            raise ValueError('Meta inventory pagination was incomplete')
        seen.add(after)
    raise ValueError('Meta inventory page cap exceeded; no registry writes')


def _flow_button(template: dict):
    matches = []
    for component in template.get('components') or []:
        if not isinstance(component, dict):
            raise ValueError('Unexpected template component')
        if component.get('type') != 'BUTTONS':
            continue
        for button in component.get('buttons') or []:
            if not isinstance(button, dict):
                raise ValueError('Unexpected template button')
            if button.get('type') == 'FLOW':
                matches.append(button)
    if len(matches) > 1:
        raise ValueError('A template has multiple Flow buttons; manual review required')
    return matches[0] if matches else None


def snapshot(graph_get: Callable, waba_id: str, retained_flow: Callable[[str], bool]):
    """Build authoritative mapping from COMPLETE live Meta pages, without writes."""
    templates = _meta_pages(graph_get, f'{waba_id}/message_templates', META_TEMPLATE_FIELDS)
    flows = _meta_pages(graph_get, f'{waba_id}/flows', META_FLOW_FIELDS)
    if not templates or not flows:
        raise ValueError('Meta inventory unexpectedly empty')
    known_flows = {}
    for flow in flows:
        fid = _numeric_id(flow.get('id'))
        if not retained_flow(fid):
            continue
        if fid in known_flows:
            raise ValueError('Duplicate Meta Flow ID')
        known_flows[fid] = flow
    if len(known_flows) != 8:
        raise ValueError('Retained Meta Flow inventory changed; review before syncing')
    links = {}
    seen_templates = set()
    for template in templates:
        tid = _numeric_id(template.get('id'))
        if tid in seen_templates:
            raise ValueError('Duplicate Meta Template ID')
        seen_templates.add(tid)
        button = _flow_button(template)
        if not button or str(template.get('status') or '').upper() != 'APPROVED':
            continue
        fid = _numeric_id(button.get('flow_id'))
        if not retained_flow(fid) or fid not in known_flows:
            raise ValueError('Approved template points to an unregistered Meta Flow')
        if str(button.get('flow_action') or '').upper() != 'DATA_EXCHANGE':
            raise ValueError('Unexpected Flow button action in Meta')
        flow = known_flows[fid]
        # Health is a prerequisite for a verified usable mapping, not authorization to send.
        if (str(flow.get('status') or '').upper() != 'PUBLISHED'
                or (flow.get('validation_errors') or [])
                or (flow.get('health_status') or {}).get('can_send_message') != 'AVAILABLE'):
            raise ValueError('Meta Flow health/status is not AVAILABLE')
        name = template.get('name')
        if not isinstance(name, str) or not name:
            raise ValueError('Approved Meta template has no name')
        links[(fid, tid)] = {
            'flowId': fid,
            'templateId': tid,
            'templateName': name,
            'flowName': str(flow.get('name') or ''),
            'metaTemplateStatus': 'APPROVED',
            'metaFlowStatus': 'PUBLISHED',
            'flowButtonAction': 'DATA_EXCHANGE',
            'buttonLabel': str(button.get('text') or ''),
            'templateCategory': str(template.get('category') or ''),
            'wabaId': waba_id,
        }
    if not links:
        raise ValueError('No approved Meta Flow buttons; refusing destructive sync')
    return links, {'templateCount': len(templates), 'retainedFlowCount': len(known_flows)}


def reconcile(graph_get: Callable, dynamodb_resource, dynamodb_client,
              waba_id: str, table_name: str, retained_flow: Callable[[str], bool],
              business_id: str, now: int | None = None) -> dict:
    """Atomically replace the mapping snapshot. Does NOT touch other registries.

    Fail closed on partial scans, large unexpected removal, or changes to the
    canonical Flow set. Safe to retry; the complete mapping snapshot is updated as one transaction.
    """
    links, meta = snapshot(graph_get, waba_id, retained_flow)
    table = dynamodb_resource.Table(table_name)
    old = []
    cursor = None
    for _ in range(50):
        params = {'ConsistentRead': True}
        if cursor:
            params['ExclusiveStartKey'] = cursor
        resp = table.scan(**params)
        old.extend(resp.get('Items') or [])
        cursor = resp.get('LastEvaluatedKey')
        if not cursor:
            break
    if cursor:
        raise ValueError('Mapping DynamoDB scan incomplete')
    previous = {}
    for row in old:
        key = (_numeric_id(row.get('flowId')), _numeric_id(row.get('templateId')))
        if key in previous:
            raise ValueError('Duplicate mapping rows in DynamoDB')
        if not retained_flow(key[0]):
            raise ValueError('Unexpected noncanonical mapping found in DynamoDB')
        previous[key] = row
    if previous and len(links) < max(1, len(previous) // 2):
        raise ValueError('More than half of mappings disappeared; refusing destructive sync')
    if len(links) + len(set(previous) - set(links)) > MAX_WRITES:
        raise ValueError('Mapping transaction exceeds safe write cap')
    timestamp = int(now if now is not None else time.time())
    serializer = TypeSerializer()
    pack = lambda v: serializer.serialize(v)
    writes = []
    for key, fields in sorted(links.items()):
        before = previous.get(key) or {}
        item = dict(before)
        item.update(fields)
        item.update({
            'businessId': business_id,
            'source': 'Meta-live-scheduled-reconciler',
            'lastVerifiedAt': Decimal(timestamp),
            'createdAt': before.get('createdAt', Decimal(timestamp)),
            'updatedAt': Decimal(timestamp),
        })
        writes.append({'Put': {
            'TableName': table_name,
            'Item': {field: pack(value) for field, value in item.items()},
        }})
    removed = sorted(set(previous) - set(links))
    for flow_id, template_id in removed:
        before = previous[(flow_id, template_id)]
        writes.append({'Delete': {
            'TableName': table_name,
            'Key': {'flowId': pack(flow_id), 'templateId': pack(template_id)},
            'ConditionExpression': '#last = :previous',
            'ExpressionAttributeNames': {'#last': 'lastVerifiedAt'},
            'ExpressionAttributeValues': {':previous': pack(before.get('lastVerifiedAt'))},
        }})
    # DynamoDB transactions reject duplicate keys and commit all or none.
    dynamodb_client.transact_write_items(
        TransactItems=writes,
        ClientRequestToken=f'tpl-flow-sync-{timestamp}-{len(links)}',
    )
    return {
        'success': True,
        'mappedTemplates': len(links),
        'mappedFlows': len({key[0] for key in links}),
        'removedStaleLinks': len(removed),
        'verifiedAt': timestamp,
        **meta,
    }
