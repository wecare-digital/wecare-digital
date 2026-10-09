"""IAM-only preparation of seven named, unpublished design previews.

The Orders draft may reuse the verified published service endpoint. No publication,
customer routing, sends, payments, registry writes or deletion operations.
Assets are fixed files in the deployment package, not caller-provided code/data.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

WABA = '2094615664435155'
NAMES = {
    'submit-request': 'WD_Submit_Request_Design_v1',
    'request-amendment': 'WD_Request_Amendment_Design_v1',
    'drop-docs': 'WD_Drop_Docs_Design_v1',
    'vault': 'WD_Vault_Design_v1',
    'shipments': 'WD_Shipments_Design_v1',
    'leave-review': 'WD_Leave_Review_Design_v1',
    'orders': 'WD_Orders_Design_v1',
}

def unwrap(response):
    if 'body' in response:
        return json.loads(response['body'])
    return response

def inventory(graph):
    rows, after, seen = [], None, set()
    while True:
        params = {'fields': 'id,name,status,validation_errors', 'limit': 100}
        if after:
            params['after'] = after
        response = graph(WABA + '/flows', params=params, waba_id=WABA)
        if response.get('error'):
            return response
        rows.extend(response.get('data') or [])
        paging = response.get('paging') or {}
        if not paging.get('next'):
            return {'flows': rows}
        after = (paging.get('cursors') or {}).get('after')
        if not after or after in seen or len(rows) >= 1000:
            return {'error': 'Incomplete Flow inventory; no draft mutation attempted'}
        seen.add(after)

def handle(event, graph, create, upload, get_flow, update_flow=None):
    if any(k in event for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    action = event.get('action', 'inspect')
    if action not in ('inspect', 'prepare', 'connect_orders_endpoint'):
        return {'error': 'Unsupported draft action'}
    service = event.get('service')
    if action != 'inspect' and service not in NAMES:
        return {'error': 'Unknown service'}
    if action == 'connect_orders_endpoint' and (service != 'orders' or update_flow is None):
        return {'error': 'Only the Orders draft endpoint may be connected'}
    response = inventory(graph)
    if response.get('error') or action == 'inspect':
        return response
    name = NAMES[service]
    matches = [row for row in response['flows'] if row.get('name') == name]
    if len(matches) > 1:
        return {'error': 'Ambiguous design draft name'}
    if matches and matches[0].get('status') != 'DRAFT':
        return {'error': 'Existing design Flow is immutable; no change attempted'}
    if action == 'connect_orders_endpoint':
        if not matches:
            return {'error': 'Prepare the Orders draft first'}
        source = unwrap(get_flow('1107164111921876')).get('flow') or {}
        endpoint = source.get('endpoint_uri', '')
        parsed = urlsplit(endpoint)
        if (source.get('id') != '1107164111921876' or source.get('status') != 'PUBLISHED'
                or source.get('validation_errors') or parsed.scheme != 'https' or not parsed.netloc
                or parsed.username or parsed.password or parsed.fragment):
            return {'error': 'Published service endpoint not verified; no change attempted'}
        result = unwrap(update_flow(matches[0]['id'], {'endpoint_uri': endpoint}))
        if result.get('error'):
            return result
        meta = unwrap(get_flow(matches[0]['id'])).get('flow') or {}
        return {'id': matches[0]['id'], 'status': meta.get('status'),
                'endpoint_connected': meta.get('endpoint_uri') == endpoint, 'validation_errors': meta.get('validation_errors')}
    # Read before creation so missing assets cannot create empty draft records.
    content = json.loads((Path(__file__).parent / 'design-drafts' / (service + '.json')).read_text())
    created = not matches
    if matches:
        flow_id = matches[0]['id']
    else:
        result = unwrap(create(WABA, {'name': name, 'categories': ['OTHER']}))
        if result.get('error'):
            return result
        flow_id = (result.get('flow') or {}).get('id')
        if not flow_id:
            return {'error': 'Draft creation outcome unknown; inspect before retry'}
    result = unwrap(upload(flow_id, {'wabaId': WABA, 'flowJson': content}))
    if result.get('error') or result.get('hasErrors'):
        return {'id': flow_id, 'name': name, 'created': created, 'upload': result}
    meta = unwrap(get_flow(flow_id))
    return {'id': flow_id, 'name': name, 'created': created, 'upload': result,
            'flow': meta.get('flow') or {}, 'error': meta.get('error')}
