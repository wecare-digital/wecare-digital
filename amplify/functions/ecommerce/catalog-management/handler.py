"""
WhatsApp Commerce Catalog Management Lambda

Purpose: Manage WhatsApp Business catalogs via Meta Graph API
- GET  /catalog          → List catalogs for a WABA
- GET  /catalog/products → List products in a catalog
- POST /catalog/products → Add product to catalog
- PUT  /catalog/products → Update product
- DELETE /catalog/products → Delete product
- POST /catalog/sync     → Sync catalog to DynamoDB CatalogCache table

Uses Meta Graph API: /{catalog_id}/products, /{waba_id}/product_catalogs
"""

import os
import json
import time
import uuid
import hmac
import hashlib
import boto3
import urllib.request
import urllib.parse
from decimal import Decimal
from typing import Dict, Any, Optional

from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, extract_origin
from lambda_utils.privacy import mask_phone

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=REGION)
secrets_client = boto3.client('secretsmanager', region_name=REGION)

from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
META_TOKEN_SECRET = os.environ.get('META_TOKEN_SECRET', 'wecare/meta-system-user-token')
CATALOG_CACHE_TABLE = os.environ.get('CATALOG_CACHE_TABLE', 'stack-wecare-digital-CatalogCacheTable')
GRAPH_BASE = f'https://graph.facebook.com/{META_API_VERSION}'

WABA1_ID = os.environ.get('WABA1_ID', '2094615664435155')
WABA2_ID = os.environ.get('WABA2_ID', '2513394156072604')
WABA2_IDS = {WABA2_ID}

_token_cache = {}
origin = ''


def _load_secrets():
    if 'loaded' in _token_cache:
        return
    resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
    data = json.loads(resp['SecretString'])
    _token_cache['token1'] = (data.get('access_token') or '').strip()
    _token_cache['token2'] = (data.get('access_token_waba2') or data.get('access_token') or '').strip()
    _token_cache['app_secret'] = (data.get('app_secret') or '').strip()
    _token_cache['loaded'] = True


def _get_token(waba_id: str = None) -> str:
    _load_secrets()
    key = 'token2' if waba_id in WABA2_IDS else 'token1'
    return _token_cache.get(key, _token_cache.get('token1', ''))


def _graph_api(endpoint: str, method: str = 'GET', payload: Dict = None,
               params: Dict = None, waba_id: str = None) -> Dict:
    _load_secrets()
    token = _get_token(waba_id)
    app_secret = _token_cache.get('app_secret', '')
    url = f'{GRAPH_BASE}/{endpoint}'
    proof_params = {}
    if app_secret:
        proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        proof_params['appsecret_proof'] = proof
    all_params = {**(params or {}), **proof_params}
    if all_params:
        url += '?' + urllib.parse.urlencode(all_params)
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.error(f'Graph API error {e.code}: {error_body}')
        try:
            return {'error': json.loads(error_body)}
        except (json.JSONDecodeError, TypeError):
            return {'error': {'message': error_body, 'code': e.code}}


def _resp(code: int, body: Dict) -> Dict:
    return {'statusCode': code, 'headers': cors_headers(origin), 'body': json.dumps(body, default=str)}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    rc = event.get('requestContext', {})
    method = rc.get('http', {}).get('method', event.get('httpMethod', 'GET'))
    path = rc.get('http', {}).get('path', '') or event.get('rawPath', '') or event.get('path', '')
    params = event.get('queryStringParameters') or {}

    if method == 'OPTIONS':
        return _resp(200, {'ok': True})

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth

    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
    except (json.JSONDecodeError, TypeError):
        body = {}

    waba_id = params.get('wabaId') or body.get('wabaId') or WABA1_ID
    catalog_id = params.get('catalogId') or body.get('catalogId', '')

    try:
        if '/sync' in path:
            return _sync_catalog(catalog_id, waba_id, request_id)
        elif '/products' in path:
            product_id = params.get('productId') or body.get('productId', '')
            if method == 'GET':
                return _list_products(catalog_id, params)
            elif method == 'POST':
                return _add_product(catalog_id, body, waba_id)
            elif method == 'PUT':
                return _update_product(product_id, body)
            elif method == 'DELETE':
                return _delete_product(product_id)
        else:
            if method == 'GET':
                return _list_catalogs(waba_id)
        return _resp(404, {'error': f'Unknown path: {path}'})
    except Exception as e:
        logger.exception(f'[{request_id}] Error')
        return _resp(500, {'error': str(e)})


def _list_catalogs(waba_id: str) -> Dict:
    result = _graph_api(f'{waba_id}/product_catalogs',
                        params={'fields': 'id,name,product_count'}, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'catalogs': result.get('data', [])})


def _list_products(catalog_id: str, params: Dict) -> Dict:
    if not catalog_id:
        return _resp(400, {'error': 'catalogId required'})
    limit = params.get('limit', '50')
    result = _graph_api(f'{catalog_id}/products',
                        params={'fields': 'id,name,retailer_id,price,currency,availability,image_url,url', 'limit': limit})
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'products': result.get('data', []), 'paging': result.get('paging', {})})


def _add_product(catalog_id: str, body: Dict, waba_id: str) -> Dict:
    if not catalog_id:
        return _resp(400, {'error': 'catalogId required'})
    payload = {k: v for k, v in body.items() if k in (
        'name', 'retailer_id', 'price', 'currency', 'availability',
        'description', 'image_url', 'url', 'category'
    )}
    if not payload.get('name'):
        return _resp(400, {'error': 'name required'})
    result = _graph_api(f'{catalog_id}/products', method='POST', payload=payload, waba_id=waba_id)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True, 'product': result})


def _update_product(product_id: str, body: Dict) -> Dict:
    if not product_id:
        return _resp(400, {'error': 'productId required'})
    payload = {k: v for k, v in body.items() if k in (
        'name', 'price', 'currency', 'availability', 'description', 'image_url', 'url'
    )}
    result = _graph_api(product_id, method='POST', payload=payload)
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})


def _delete_product(product_id: str) -> Dict:
    if not product_id:
        return _resp(400, {'error': 'productId required'})
    result = _graph_api(product_id, method='DELETE')
    if 'error' in result:
        return _resp(400, result)
    return _resp(200, {'success': True})


def _sync_catalog(catalog_id: str, waba_id: str, request_id: str) -> Dict:
    """Sync catalog products from Meta to DynamoDB CatalogCache table."""
    if not catalog_id:
        return _resp(400, {'error': 'catalogId required'})

    table = dynamodb.Table(CATALOG_CACHE_TABLE)
    now = int(time.time())
    synced = 0
    after = ''

    while True:
        params = {'fields': 'id,name,retailer_id,price,currency,availability,image_url,url,description', 'limit': '100'}
        if after:
            params['after'] = after
        result = _graph_api(f'{catalog_id}/products', params=params, waba_id=waba_id)
        if 'error' in result:
            return _resp(400, {'error': 'Failed to fetch products', 'detail': result})

        products = result.get('data', [])
        for p in products:
            table.put_item(Item={
                'id': p.get('id', str(uuid.uuid4())),
                'catalogId': catalog_id,
                'wabaId': waba_id,
                'name': p.get('name', ''),
                'retailerId': p.get('retailer_id', ''),
                'price': p.get('price', ''),
                'currency': p.get('currency', 'INR'),
                'availability': p.get('availability', ''),
                'imageUrl': p.get('image_url', ''),
                'url': p.get('url', ''),
                'description': p.get('description', ''),
                'syncedAt': Decimal(str(now)),
                'ttl': Decimal(str(now + 7 * 86400)),  # 7 day cache
            })
            synced += 1

        paging = result.get('paging', {})
        after = paging.get('cursors', {}).get('after', '')
        if not after or not paging.get('next'):
            break

    logger.info(json.dumps({'event': 'catalog_synced', 'catalogId': catalog_id, 'synced': synced, 'requestId': request_id}))
    return _resp(200, {'success': True, 'synced': synced, 'catalogId': catalog_id})
