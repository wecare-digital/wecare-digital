"""Bounded IAM-only inventory and fresh catalog preparation. No deletion path."""
BUSINESS_ID = '382642103987922'
FRESH_NAME = 'WECARE.DIGITAL Catalog'
FIELDS = 'id,name,product_count,business,vertical'


def collection(graph, endpoint, fields):
    rows, after = [], None
    seen = set()
    while True:
        params = {'fields': fields, 'limit': 100}
        if after:
            params['after'] = after
        result = graph(endpoint, params=params)
        if 'error' in result:
            return {'error': result['error']}
        rows.extend(result.get('data') or [])
        paging = result.get('paging') or {}
        next_cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('next'):
            return {'data': rows}
        if not next_cursor or next_cursor in seen:
            return {'error': {'message': 'Incomplete catalog pagination'}}
        seen.add(next_cursor)
        after = next_cursor


def handle(event, graph):
    if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    owned = collection(graph, BUSINESS_ID + '/owned_product_catalogs', FIELDS)
    if 'error' in owned:
        return owned
    if event.get('action', 'inspect') == 'inspect':
        shared = collection(graph, BUSINESS_ID + '/client_product_catalogs', FIELDS)
        return {'owned': owned, 'shared': shared, 'readOnly': True}
    if event.get('action') == 'prepare':
        matches = [x for x in owned['data'] if x.get('name') == FRESH_NAME]
        if len(matches) > 1:
            return {'error': {'message': 'Ambiguous fresh catalog identity'}}
        if matches:
            return {'catalog': matches[0], 'created': False}
        result = graph(BUSINESS_ID + '/owned_product_catalogs', method='POST',
                       payload={'name': FRESH_NAME, 'vertical': 'commerce'})
        if 'error' in result:
            return result
        if not result.get('id'):
            return {'error': {'message': 'Catalog creation not confirmed'}}
        return {'catalog': {'id': result['id'], 'name': FRESH_NAME}, 'created': True}
    return {'error': {'message': 'Unsupported catalog lifecycle action'}}
