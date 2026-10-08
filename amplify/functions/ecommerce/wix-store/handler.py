"""
Wix Store Integration Lambda Function

Purpose: API-only bridge between WECARE.DIGITAL and a Wix Headless commerce backend.

Catalog reads and product management use Wix Stores Catalog V3.
Inventory uses Inventory Items V3.
Orders use the Wix eCommerce Orders APIs.
No Wix Editor or Velo runtime is required.

Wix Catalog V3 docs: https://dev.wix.com/docs/api-reference/business-solutions/stores/catalog-v3/introduction
"""

import os
import json
import logging
import uuid
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
# Pure Wix transforms, lifted out in 7.2. This module imports no AWS SDK and reads no
# credential, so these 13 functions are unit-testable without standing up the
# integration - which is what made ~270 lines of shape-mapping untestable before.
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.ecommerce import order_keys  # ORDERNO#/REFERENCE# reservations, fail-closed
from lambda_utils.ecommerce.wix_domain import (  # noqa: F401
    _base36,
    _extract_id,
    _fields_suffix,
    _first_variant,
    _generate_sku,
    _generate_wd_order_number,
    _get_main_media,
    _money_amount,
    _normalize_category,
    _normalize_v3_product,
    _parse_body,
    _read_only_variant_to_product_variant,
    _simple_product_to_v3,
)

logger = get_logger(__name__)

# REST API config. No legacy secret/site defaults are allowed: the fresh
# Headless project must be configured explicitly before Wix calls can run.
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
WIX_API_KEY_SECRET = os.environ.get('WIX_API_KEY_SECRET', '').strip()
# S3_BUCKET and CDN_DOMAIN were NEVER DEFINED in this module.
#
# `_s3_public_url` referenced S3_BUCKET and the product-image upload passed it to
# put_object, but nothing ever assigned it and it is not in the wix_domain import
# list above - so both paths raised NameError on every call. That predates the
# 2026-09-28 bucket migration; those two code paths have never worked.
#
# Defined here as the same env-with-live-default pair used elsewhere, and kept
# separate on purpose: the bucket name is for S3 API calls, the domain is for URLs a
# caller will fetch. Interpolating the bucket name into a URL only ever worked while
# the bucket happened to be named app.wecare.digital.
S3_BUCKET = os.environ.get('S3_BUCKET', media_paths.BUCKET)
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)
# Referenced by _upload_product_image but never defined until 2026-09-28, so that
# path raised NameError rather than uploading. Same folder product-image-gen uses.
S3_PRODUCT_PREFIX = os.environ.get('S3_PRODUCT_PREFIX',
                                   media_paths.public('stack/store/products'))


_wix_api_key_cache = ''


def _credentials_disabled() -> bool:
    """Whether the operator has switched Wix credentials off.

    Read on every call rather than captured at import: this is an incident control, and
    a value that only takes effect once every warm sandbox recycles is not one.

    This switch did NOTHING until 2026-09-23. `WIX_CREDENTIALS_DISABLED=true` and
    `CREDENTIAL_PURGE_EPOCH` were both set on the live function and neither name
    appeared anywhere in the repository — so somebody disabled Wix with a variable the
    code never read. What actually stopped Wix was the absence of `WIX_API_KEY_SECRET`,
    which makes the loader below raise: off by accident rather than by the switch.

    A kill switch nobody can trust is worse than no kill switch, because the next
    person flips it and believes they are safe. Same shape as the dashboard's tool
    checkboxes, which were toggled, rendered, and never sent to the backend.
    """
    return str(os.environ.get('WIX_CREDENTIALS_DISABLED', '')).strip().lower() in (
        '1', 'true', 'yes', 'on')


def _load_wix_api_key() -> str:
    """Resolve the Wix API key from Secrets Manager. No env fallback.

    Called on first use and cached for the life of the execution environment —
    deliberately NOT at import time, so replacing the value in Secrets Manager takes
    effect when a sandbox recycles instead of being frozen in at module init.

    An earlier version of this docstring claimed the function "runs with SnapStart
    (SnapStart.ApplyOn=PublishedVersions)". It does not: measured across all 62
    functions, SnapStart is `None` everywhere. Lazy loading is still correct, for the
    plainer reason above, but the SnapStart justification was false — and a comment
    that states a false fact about the runtime is how the wrong mitigation gets
    applied. See .kiro/steering/lambda-snapstart-deploy.md.

    It also claimed "env as migration fallback". There is no env fallback: the function
    raises when the secret is absent. The claim invited someone to set a plaintext
    credential in an environment variable and expect it to work.
    """
    global _wix_api_key_cache

    # Checked FIRST, so a disabled integration performs no credential read at all.
    if _credentials_disabled():
        raise RuntimeError(
            'Wix credentials are disabled by WIX_CREDENTIALS_DISABLED. This is '
            'deliberate; clear that variable to re-enable rather than working around '
            'it.')

    if _wix_api_key_cache:
        return _wix_api_key_cache
    if WIX_API_KEY_SECRET:
        try:
            raw = secrets_client.get_secret_value(SecretId=WIX_API_KEY_SECRET).get('SecretString', '') or ''
            try:
                data = json.loads(raw)
                _wix_api_key_cache = (data.get('api_key') or data.get('apiKey') or data.get('WIX_API_KEY')
                                      or data.get('key') or data.get('value') or '').strip()
            except (ValueError, TypeError):
                _wix_api_key_cache = raw.strip()
        except Exception as e:
            logger.warning(f'Wix API key: explicit Secrets Manager load failed: {e}')
    if not _wix_api_key_cache:
        raise RuntimeError('Wix Headless API credentials are not configured')
    return _wix_api_key_cache


WIX_SITE_ID = os.environ.get('WIX_SITE_ID', '')
WIX_ACCOUNT_ID = os.environ.get('WIX_ACCOUNT_ID', '')
WIX_API_BASE = os.environ.get('WIX_API_BASE_URL', 'https://www.wixapis.com')

dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
PRODUCTS_CACHE_TABLE = os.environ.get('WIX_PRODUCTS_CACHE_TABLE', 'stack-wecare-digital-WixProductsCache')
ORDERS_CACHE_TABLE = os.environ.get('WIX_ORDERS_CACHE_TABLE', 'stack-wecare-digital-WixOrdersCache')
ORDER_IDS_TABLE = os.environ.get('WIX_ORDER_IDS_TABLE', 'stack-wecare-digital-WixOrderIds')

# Module-level origin for CORS (set per-invocation in handler)
origin = ''

CATALOG_PRODUCT_FIELDS = [
    'URL',
    'CURRENCY',
    'MEDIA_ITEMS_INFO',
    'DESCRIPTION',
    'PLAIN_DESCRIPTION',
    'DIRECT_CATEGORIES_INFO',
    'ALL_CATEGORIES_INFO',
    'VARIANT_OPTION_CHOICE_NAMES',
    'WEIGHT_MEASUREMENT_UNIT_INFO',
]

CATEGORY_TREE_REFERENCE = {'appNamespace': '@wix/stores'}










def _hydrate_product_variants(products: list) -> list:
    """Attach variants to Query/Search Products V3 results in one batched read.

    Query Products and Search Products intentionally omit variant data. The
    Read-Only Variants V3 API is designed for this use case and supports
    filtering by up to a page of product IDs plus cursor paging up to 1,000
    variants per call.
    """
    rows = [dict(product or {}) for product in (products or [])]
    product_ids = [row.get('id') for row in rows if row.get('id')]
    if not product_ids:
        return rows

    variants_by_product = {product_id: [] for product_id in product_ids}
    cursor = ''

    while True:
        if cursor:
            query = {'cursorPaging': {'limit': 1000, 'cursor': cursor}}
        else:
            query = {
                'filter': {'productData.productId': {'$in': product_ids}},
                'cursorPaging': {'limit': 1000},
            }

        result = _wix_request(
            '/stores/v3/products/query-variants',
            method='POST',
            body={'fields': ['CURRENCY'], 'query': query},
        )

        for variant in result.get('variants', []):
            product_id = (variant.get('productData') or {}).get('productId')
            if product_id in variants_by_product:
                variants_by_product[product_id].append(
                    _read_only_variant_to_product_variant(variant)
                )

        metadata = result.get('pagingMetadata') or {}
        cursor = (metadata.get('cursors') or {}).get('next', '')
        if not cursor:
            break

    for row in rows:
        product_id = row.get('id')
        if product_id in variants_by_product:
            row['variantsInfo'] = {'variants': variants_by_product[product_id]}

    return rows









# ===================================================================
# HANDLER
# ===================================================================


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route authenticated admin/store requests to the Wix REST APIs."""
    request_id = context.aws_request_id if context else 'local'
    # `origin` is a module-level global that `_response` reads, and a Lambda execution
    # environment is REUSED across invocations - so without the reset in the `finally`
    # below, the value set here survives into the next request that does not set it.
    #
    # Two paths do not set it. `_sync_products` and `_sync_orders` run on a schedule with
    # no HTTP event, and both return through `_response`: on a warm sandbox they would
    # emit the last HTTP caller's Origin in a CORS header on a cron response. The reset
    # makes that a blank origin instead of somebody else's.
    #
    # Threading `origin` through every signature would be the cleaner boundary, and it is
    # deliberately NOT done here: 36 call sites across 22 functions, only 2 of which have
    # an origin to pass, in a 1,743-line handler whose integration is entirely switched
    # off and therefore cannot be live-verified. A reset is small, provable, and fixes the
    # leak; the signature change is recorded as the remaining half of 7.2.
    global origin
    origin = extract_origin(event)

    try:
        http_method = event.get(
            'httpMethod',
            event.get('requestContext', {}).get('http', {}).get('method', 'GET'),
        )
        path = event.get('path', event.get('rawPath', '/'))
        params = event.get('queryStringParameters', {}) or {}

        if path.rstrip('/') == '/wix-store/cart':
            return _customer_cart(event, http_method)

        from lambda_utils.middleware import require_auth
        required_role = 'Admin' if http_method != 'GET' else None
        auth_result = require_auth(event, required_role=required_role)
        if auth_result is not None:
            return auth_result

        logger.info(json.dumps({
            'action': 'wix_store_request',
            'method': http_method,
            'path': path,
            'catalogVersion': 'v3',
            'requestId': request_id,
        }))

        if http_method == 'POST':
            if '/create-product' in path:
                return _create_product_rest(_parse_body(event), request_id)
            if '/bulk-create-products' in path:
                return _bulk_create_products_rest(_parse_body(event), request_id)
            if '/update-product' in path:
                return _update_product_rest(_parse_body(event), request_id)
            if '/delete-product' in path:
                body = _parse_body(event)
                pid = str(body.get('productId', '')).strip()
                if not pid:
                    return _response(400, {'error': 'Missing productId', 'requestId': request_id})
                _wix_request(f'/stores/v3/products/{pid}', method='DELETE')
                return _response(200, {'deleted': True, 'requestId': request_id})
            if '/add-product-image' in path:
                return _add_product_image(_parse_body(event), request_id)
            if '/upload-product-image' in path:
                return _upload_product_image(event, _parse_body(event), request_id)
            if '/backfill-order-ids' in path:
                return _backfill_order_ids(request_id)
            if '/sync' in path:
                if 'products' in path:
                    return _sync_products(request_id)
                if 'orders' in path:
                    return _sync_orders(request_id)

        if '/sites' in path:
            return _list_sites(params, request_id)

        if '/collections' in path:
            category_id = _extract_id(path, 'collections')
            if category_id and '/products' in path.split('collections/' + category_id)[-1]:
                return _collection_products(category_id, params, request_id)
            if category_id:
                return _get_collection(category_id, request_id)
            return _list_collections(params, request_id)

        if '/products' in path:
            product_id = _extract_id(path, 'products')
            return _get_product(product_id, request_id) if product_id else _list_products(params, request_id)

        if '/inventory' in path:
            product_id = _extract_id(path, 'inventory')
            return _get_inventory(product_id, request_id) if product_id else _query_inventory(params, request_id)

        if '/orders' in path:
            order_id = _extract_id(path, 'orders')
            if order_id:
                if '/fulfillments' in path:
                    return _order_fulfillments(order_id, request_id)
                if '/transactions' in path:
                    return _order_transactions(order_id, request_id)
                return _get_order(order_id, request_id)
            return _search_orders(params, request_id)

        if '/sample-products' in path:
            return _get_sample_products(request_id)

        return _response(404, {'error': 'Not found', 'path': path})

    except Exception as e:
        logger.error(json.dumps({
            'action': 'wix_store_error',
            'error': str(e),
            'requestId': request_id,
        }))
        return _response(500, {'error': 'Internal server error', 'message': str(e)})
    finally:
        # Clear the request-scoped global so it cannot outlive this invocation. See the
        # note at the top of this function: the execution environment is reused, and the
        # two scheduled sync paths return through `_response` without ever setting it.
        origin = ''

def _customer_cart(event, method):
    from lambda_utils import customer_auth
    from lambda_utils.ecommerce.cart_v2 import CartV2, is_enabled as cart_v2_enabled
    from lambda_utils.ecommerce.customer_cart import CustomerCart, CartBusy, CartMissing

    if method == 'OPTIONS':
        return _response(200, {})
    identity, denied = customer_auth.require_customer(event)
    if denied:
        return denied
    # Cart V2 is opt-in: `WIX_CART_V2_ENABLED` must be truthy, and absence means off. The
    # decision lives in `cart_v2.is_enabled` so this route and `ecommerce/checkout` cannot
    # disagree about whether V2 serves. Off, this route creates no cart at all, which matters
    # because serving it performs real Create Cart and Add Line Items writes against the live
    # site for any authenticated customer.
    if not cart_v2_enabled():
        return _response(503, {'error': 'CART_UNAVAILABLE'})
    if method not in ('GET', 'POST'):
        return _response(405, {'error': 'METHOD_NOT_ALLOWED'})
    try:
        command = {'action': 'get'} if method == 'GET' else _parse_body(event)
        table = boto3.resource('dynamodb').Table(order_keys.commerce_keys_table_name())
        result = CustomerCart(table, CartV2(_wix_request)).execute(identity, command)
        return _response(200, result)
    except customer_auth.CustomerNotAuthorized:
        return customer_auth.denied_response(event)
    except CartMissing:
        return _response(404, {'error': 'CART_NOT_FOUND'})
    except CartBusy:
        return _response(409, {'error': 'CART_RECONCILIATION_REQUIRED'})
    except ValueError:
        return _response(422, {'error': 'CART_VALIDATION_FAILED'})
    except Exception:
        # Provider errors may contain customer information or internal identifiers.
        logger.error('{"event":"customer_cart_unavailable"}')
        return _response(503, {'error': 'CART_UNAVAILABLE'})


def _wix_request(endpoint: str, method: str = 'GET', body: dict = None,
                 level: str = 'site') -> Dict[str, Any]:
    """
    Authenticated request to Wix REST API.

    level='site'    → sends wix-site-id header (products, orders, inventory, etc.)
    level='account' → sends wix-account-id header (sites API)
    These headers are mutually exclusive per Wix docs.
    """
    url = f"{WIX_API_BASE}{endpoint}"
    headers = {
        'Authorization': _load_wix_api_key(),
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if level == 'account':
        headers['wix-account-id'] = WIX_ACCOUNT_ID
    else:
        headers['wix-site-id'] = WIX_SITE_ID

    data = json.dumps(body).encode('utf-8') if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        logger.error(json.dumps({
            'action': 'wix_api_error',
            'status': e.code,
            'url': url,
            'response': error_body[:500],
        }))
        raise RuntimeError(f"Wix API error {e.code}: {error_body[:200]}")


# ===================================================================
# SITES (account-level)
# ===================================================================

def _list_sites(params: dict, request_id: str) -> Dict[str, Any]:
    """Query sites from Wix account. Use to discover WIX_SITE_ID."""
    limit = int(params.get('limit', 50))
    offset = int(params.get('offset', 0))

    result = _wix_request(
        '/site-management/v1/sites/query',
        method='POST',
        body={'query': {
            'paging': {'limit': limit, 'offset': offset},
            'sort': [{'fieldName': 'dateUpdated', 'order': 'DESC'}],
        }},
        level='account',
    )

    sites = []
    for s in result.get('sites', []):
        sites.append({
            'id': s.get('id'),
            'displayName': s.get('displayName', ''),
            'viewUrl': s.get('viewUrl', ''),
            'editUrl': s.get('editUrl', ''),
            'published': s.get('published', False),
            'premium': s.get('premium', False),
            'thumbnail': s.get('thumbnail', {}).get('url', ''),
            'dashboardUrl': f"https://manage.wix.com/dashboard/{s.get('id', '')}",
            'createdDate': s.get('dateCreated', ''),
            'updatedDate': s.get('dateUpdated', ''),
        })

    return _response(200, {
        'sites': sites,
        'totalResults': result.get('totalResults', len(sites)),
        'requestId': request_id,
    })


# ===================================================================
# PRODUCTS
# ===================================================================


def _list_products(params: dict, request_id: str) -> Dict[str, Any]:
    """List/search Catalog V3 products while preserving the admin UI contract."""
    limit = max(1, min(int(params.get('limit', 100)), 100))
    cursor = params.get('cursor', '')
    search_text = str(params.get('search', '') or '').strip()
    category_id = str(params.get('collectionId', '') or '').strip()

    if search_text or category_id:
        search = {'cursorPaging': {'limit': limit}}
        if cursor:
            search['cursorPaging']['cursor'] = cursor
        if search_text:
            search['search'] = {
                'expression': search_text,
                'fields': ['name'],
                'fuzzy': False,
            }
        if category_id:
            search['filter'] = {
                'directCategoriesInfo.categories': {
                    '$matchItems': [{'id': {'$eq': category_id}}]
                }
            }
        result = _wix_request('/stores/v3/products/search', method='POST', body={
            'fields': CATALOG_PRODUCT_FIELDS,
            'search': search,
        })
    else:
        paging = {'limit': limit}
        if cursor:
            paging['cursor'] = cursor
        result = _wix_request('/stores/v3/products/query', method='POST', body={
            'fields': CATALOG_PRODUCT_FIELDS,
            'query': {'cursorPaging': paging},
        })

    raw_products = _hydrate_product_variants(result.get('products', []))
    products = [_normalize_v3_product(p) for p in raw_products]
    paging = result.get('pagingMetadata') or {}
    return _response(200, {
        'products': products,
        'totalResults': paging.get('count', len(products)),
        'nextCursor': (paging.get('cursors') or {}).get('next', ''),
        'siteUrl': 'https://wecare.digital',
        'dashboardUrl': f'https://manage.wix.com/dashboard/{WIX_SITE_ID}/store/products',
        'requestId': request_id,
    })


def _get_product(product_id: str, request_id: str) -> Dict[str, Any]:
    endpoint = f'/stores/v3/products/{product_id}{_fields_suffix(CATALOG_PRODUCT_FIELDS)}'
    product = _wix_request(endpoint).get('product', {})
    normalized = _normalize_v3_product(product)

    try:
        inventory = _wix_request('/stores/v3/inventory-items/query', method='POST', body={
            'query': {
                'filter': {'productId': {'$eq': product_id}},
                'cursorPaging': {'limit': 1000},
            }
        }).get('inventoryItems', [])
        normalized['_inventoryItems'] = inventory
        normalized['quantityInStock'] = sum(
            float(item.get('quantity') or 0) for item in inventory
            if item.get('quantity') is not None
        ) if inventory else normalized.get('quantityInStock')
        if inventory:
            normalized['inStock'] = any(
                item.get('inStock') is True
                or str(item.get('availabilityStatus') or '').upper() == 'IN_STOCK'
                for item in inventory
            )
    except Exception as error:
        normalized['_inventoryError'] = str(error)

    normalized['_dashboardUrl'] = f'https://manage.wix.com/dashboard/{WIX_SITE_ID}/store/products'
    return _response(200, {'product': normalized, 'requestId': request_id})


def _list_collections(params: dict, request_id: str) -> Dict[str, Any]:
    """Compatibility route: V3 categories replace legacy Stores collections."""
    limit = max(1, min(int(params.get('limit', 100)), 1000))
    cursor = params.get('cursor', '')
    paging = {'limit': limit}
    if cursor:
        paging['cursor'] = cursor
    result = _wix_request('/categories/v1/categories/query', method='POST', body={
        'query': {'cursorPaging': paging},
        'treeReference': CATEGORY_TREE_REFERENCE,
        'returnNonVisibleCategories': True,
    })
    categories = [_normalize_category(x) for x in result.get('categories', [])]
    metadata = result.get('pagingMetadata') or {}
    return _response(200, {
        'collections': categories,
        'categories': categories,
        'totalResults': metadata.get('count', len(categories)),
        'nextCursor': (metadata.get('cursors') or {}).get('next', ''),
        'requestId': request_id,
    })


def _get_collection(collection_id: str, request_id: str) -> Dict[str, Any]:
    endpoint = (
        f'/categories/v1/categories/{collection_id}'
        '?treeReference.appNamespace=%40wix%2Fstores'
    )
    category = _normalize_category(_wix_request(endpoint).get('category', {}))
    return _response(200, {
        'collection': category,
        'category': category,
        'requestId': request_id,
    })


def _collection_products(collection_id: str, params: dict, request_id: str) -> Dict[str, Any]:
    limit = max(1, min(int(params.get('limit', 100)), 100))
    cursor = params.get('cursor', '')
    paging = {'limit': limit}
    if cursor:
        paging['cursor'] = cursor
    result = _wix_request('/stores/v3/products/search', method='POST', body={
        'fields': CATALOG_PRODUCT_FIELDS,
        'search': {
            'filter': {
                'directCategoriesInfo.categories': {
                    '$matchItems': [{'id': {'$eq': collection_id}}]
                }
            },
            'cursorPaging': paging,
        },
    })
    raw_products = _hydrate_product_variants(result.get('products', []))
    products = [_normalize_v3_product(p) for p in raw_products]
    metadata = result.get('pagingMetadata') or {}
    return _response(200, {
        'products': products,
        'collectionId': collection_id,
        'totalResults': metadata.get('count', len(products)),
        'nextCursor': (metadata.get('cursors') or {}).get('next', ''),
        'requestId': request_id,
    })


def _query_inventory(params: dict, request_id: str) -> Dict[str, Any]:
    limit = max(1, min(int(params.get('limit', 100)), 1000))
    cursor = params.get('cursor', '')
    paging = {'limit': limit}
    if cursor:
        paging['cursor'] = cursor
    result = _wix_request('/stores/v3/inventory-items/query', method='POST', body={
        'query': {'cursorPaging': paging}
    })
    items = result.get('inventoryItems', [])
    metadata = result.get('pagingMetadata') or {}
    return _response(200, {
        'inventoryItems': items,
        'totalResults': metadata.get('count', len(items)),
        'nextCursor': (metadata.get('cursors') or {}).get('next', ''),
        'requestId': request_id,
    })


def _get_inventory(product_id: str, request_id: str) -> Dict[str, Any]:
    result = _wix_request('/stores/v3/inventory-items/query', method='POST', body={
        'query': {
            'filter': {'productId': {'$eq': product_id}},
            'cursorPaging': {'limit': 1000},
        }
    })
    items = result.get('inventoryItems', [])
    return _response(200, {
        'productId': product_id,
        'inventoryItems': items,
        'inventoryItem': items[0] if items else {},
        'requestId': request_id,
    })

def _search_orders(params: dict, request_id: str) -> Dict[str, Any]:
    """
    Search orders via eCommerce Orders API.
    Returns full order objects including:
      - number (custom/sequential order number)
      - buyerInfo (email, contactId, memberId)
      - lineItems with product details
      - priceSummary, shippingInfo, billingInfo
      - paymentStatus, fulfillmentStatus
      - channelInfo (including externalOrderId for custom order numbers)
      - customFields

    Query params:
      - status: APPROVED, CANCELED, etc.
      - paymentStatus: PAID, NOT_PAID, PARTIALLY_PAID, PARTIALLY_REFUNDED, FULLY_REFUNDED
      - fulfillmentStatus: NOT_FULFILLED, PARTIALLY_FULFILLED, FULFILLED
      - email: filter by buyer email
      - memberId: filter by Wix member ID (logged-in user)
      - customOrderNumber: filter by WD custom order number
      - dateFrom / dateTo: ISO date range on createdDate
      - limit / cursor: pagination
    """
    limit = int(params.get('limit', 50))

    search_body: Dict[str, Any] = {
        'search': {
            'cursorPaging': {'limit': limit},
            'sort': [{'fieldName': 'createdDate', 'order': 'DESC'}],
        }
    }

    # Build filter
    filt: Dict[str, Any] = {}

    if params.get('status'):
        filt['status'] = {'$eq': params['status'].upper()}
    if params.get('paymentStatus'):
        filt['paymentStatus'] = {'$eq': params['paymentStatus'].upper()}
    if params.get('fulfillmentStatus'):
        filt['fulfillmentStatus'] = {'$eq': params['fulfillmentStatus'].upper()}
    if params.get('email'):
        filt['buyerInfo.email'] = {'$eq': params['email']}
    if params.get('memberId'):
        filt['buyerInfo.memberId'] = {'$eq': params['memberId']}
    if params.get('orderNumber'):
        filt['number'] = {'$eq': int(params['orderNumber'])}

    # Date range
    date_filter = {}
    if params.get('dateFrom'):
        date_filter['$gte'] = params['dateFrom']
    if params.get('dateTo'):
        date_filter['$lte'] = params['dateTo']
    if date_filter:
        filt['createdDate'] = date_filter

    if filt:
        search_body['search']['filter'] = filt

    # Cursor-based pagination
    cursor = params.get('cursor')
    if cursor:
        search_body['search']['cursorPaging']['cursor'] = cursor

    result = _wix_request('/ecom/v1/orders/search', method='POST', body=search_body)
    orders = result.get('orders', [])

    # Enrich each order with a clean summary
    enriched = []
    for order in orders:
        enriched.append(_enrich_order(order))

    paging = result.get('pagingMetadata', {})

    return _response(200, {
        'orders': enriched,
        'totalResults': paging.get('count', len(enriched)),
        'cursors': paging.get('cursors', {}),
        'hasNext': paging.get('hasNext', False),
        'requestId': request_id,
    })


def _get_order(order_id: str, request_id: str) -> Dict[str, Any]:
    """Get full order detail by ID, including transactions and fulfillments."""
    result = _wix_request(f'/ecom/v1/orders/{order_id}')
    order = result.get('order', {})

    # Fetch transactions
    try:
        txn = _wix_request(f'/ecom/v1/transactions/orders/{order_id}')
        order['_transactions'] = txn.get('orderTransactions', {})
    except Exception as e:
        logger.warning(f'Transactions fetch failed for order {order_id}: {e}')
        order['_transactions'] = []

    # Fetch fulfillments
    try:
        ful = _wix_request(f'/ecom/v1/fulfillments/orders/{order_id}')
        order['_fulfillments'] = ful.get('orderFulfillments', {})
    except Exception as e:
        logger.warning(f'Fulfillments fetch failed for order {order_id}: {e}')
        order['_fulfillments'] = []

    return _response(200, {'order': _enrich_order(order), 'requestId': request_id})


def _order_fulfillments(order_id: str, request_id: str) -> Dict[str, Any]:
    """List fulfillments for a specific order."""
    result = _wix_request(f'/ecom/v1/fulfillments/orders/{order_id}')
    return _response(200, {
        'orderId': order_id,
        'fulfillments': result.get('orderFulfillments', {}),
        'requestId': request_id,
    })


def _order_transactions(order_id: str, request_id: str) -> Dict[str, Any]:
    """List transactions for a specific order."""
    result = _wix_request(f'/ecom/v1/transactions/orders/{order_id}')
    return _response(200, {
        'orderId': order_id,
        'transactions': result.get('orderTransactions', {}),
        'requestId': request_id,
    })


# ===================================================================
# WD ORDER NUMBER GENERATION + DYNAMO MAPPING
# ===================================================================



def _get_or_create_wd_order_number(order_id: str, order_date: str = '',
                                    native_number: str = '') -> str:
    """
    Look up or create a WD-ORD number for a Wix order.
    Stores the mapping in DynamoDB (WixOrderIds table).
    Returns the WD-ORD number.

    Two defects fixed here, both of which made this function's name a lie.

    It was NOT idempotent. The reuse check was `startswith('WD-ORD-')`, but
    `_generate_wd_order_number` emits 'WD-ORD - A1B2C3D4 - ...' with a SPACE at index 6.
    So the check was false for every number this function had ever written, and each call
    regenerated and overwrote the mapping. `_enrich_order` calls this per order per listing,
    so every refresh of the orders view reissued every order number - and
    `_backfill_order_ids` then pushed the new value onto the Wix order. Matching is now
    `order_keys.is_wd_order_number`, which accepts both live formats.

    It also FAILED OPEN. The old `except` returned `_generate_wd_order_number(...)` without
    storing it, so the one situation where a duplicate is most likely - DynamoDB unavailable -
    was the situation that skipped the uniqueness record. A number that exists only in a
    response is a duplicate waiting to be issued, so the number is now reserved with a
    conditional write before it is returned, and a storage failure raises.
    """
    table = dynamodb.Table(ORDER_IDS_TABLE)

    # Existing mapping wins, always. This is the idempotent path and it must come first.
    try:
        item = table.get_item(Key={'orderId': order_id}).get('Item')
    except Exception as e:
        logger.error(json.dumps({
            'action': 'wd_order_number_lookup_failed',
            'orderId': order_id,
            'error': type(e).__name__,
        }))
        raise order_keys.OrderIdentityUnavailable(
            f'could not read the order-number mapping for {order_id}'
        ) from e

    if item and order_keys.is_wd_order_number(item.get('wdOrderNumber', '')):
        return item['wdOrderNumber']

    # No mapping yet. Reserve a number under ORDERNO#<number> BEFORE returning it, so a
    # collision is refused by DynamoDB rather than discovered by a customer.
    wd_num = order_keys.reserve_order_number(
        table, order_date,
        generate=_generate_wd_order_number,
        extra={'wixOrderId': order_id},
    )

    try:
        table.put_item(Item={
            'orderId': order_id,
            'wdOrderNumber': wd_num,
            'nativeNumber': str(native_number),
            'orderDate': order_date,
            'createdAt': datetime.now(timezone.utc).isoformat(),
        }, ConditionExpression='attribute_not_exists(orderId)')
    except Exception as e:
        # A concurrent caller mapped this Wix order first. Its number is authoritative;
        # ours stays reserved and unused, which is the safe direction to lose in.
        if getattr(e, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            winner = table.get_item(Key={'orderId': order_id}).get('Item') or {}
            if order_keys.is_wd_order_number(winner.get('wdOrderNumber', '')):
                logger.info(json.dumps({
                    'action': 'wd_order_number_race_lost',
                    'orderId': order_id,
                    'kept': winner['wdOrderNumber'],
                }))
                return winner['wdOrderNumber']
        logger.error(json.dumps({
            'action': 'wd_order_number_store_failed',
            'orderId': order_id,
            'error': type(e).__name__,
        }))
        raise order_keys.OrderIdentityUnavailable(
            f'reserved a number for {order_id} but could not store the mapping'
        ) from e

    logger.info(json.dumps({
        'action': 'wd_order_number_created',
        'orderId': order_id,
        'wdOrderNumber': wd_num,
        'nativeNumber': native_number,
    }))
    return wd_num


def _backfill_order_ids(request_id: str) -> Dict[str, Any]:
    """
    Backfill WD-ORD numbers for ALL existing Wix orders.
    1. Fetches all orders from Wix
    2. Generates WD numbers, stores in DynamoDB
    3. Pushes WD number to Wix order via PATCH (extendedFields)
    POST /backfill-order-ids
    """
    backfilled = 0
    wix_updated = 0
    skipped = 0
    errors = []
    cursor = None

    while True:
        body: Dict[str, Any] = {
            'search': {
                'cursorPaging': {'limit': 100},
                'sort': [{'fieldName': 'createdDate', 'order': 'ASC'}],
            }
        }
        if cursor:
            body['search']['cursorPaging']['cursor'] = cursor

        result = _wix_request('/ecom/v1/orders/search', method='POST', body=body)
        orders = result.get('orders', [])
        if not orders:
            break

        for o in orders:
            oid = o.get('id', '')
            if not oid:
                continue
            order_date = o.get('createdDate', '')
            native_num = str(o.get('number', ''))
            try:
                wd_num = _get_or_create_wd_order_number(oid, order_date, native_num)
                backfilled += 1

                # Push WD number to Wix order via PATCH extendedFields
                try:
                    _wix_request(f'/ecom/v1/orders/{oid}', method='PATCH', body={
                        'order': {
                            'extendedFields': {
                                'namespaces': {
                                    '_user_fields': {
                                        'customOrderNumber': wd_num,
                                    }
                                }
                            }
                        }
                    })
                    wix_updated += 1
                except Exception as we:
                    logger.warning(json.dumps({
                        'action': 'backfill_wix_update_failed',
                        'orderId': oid,
                        'error': str(we),
                    }))

                logger.info(json.dumps({
                    'action': 'backfill_order',
                    'orderId': oid,
                    'native': native_num,
                    'wd': wd_num,
                }))
            except Exception as e:
                skipped += 1
                errors.append({'orderId': oid, 'error': str(e)})

        paging = result.get('pagingMetadata', {})
        if paging.get('hasNext') and paging.get('cursors', {}).get('next'):
            cursor = paging['cursors']['next']
        else:
            break

    return _response(200, {
        'backfilled': backfilled,
        'wixUpdated': wix_updated,
        'skipped': skipped,
        'errors': errors[:10],
        'requestId': request_id,
    })


def _enrich_order(order: dict) -> dict:
    """
    Add a clean _summary to the raw order for easy consumption.
    Includes custom order number, buyer details, line items summary, totals.
    Auto-generates WD-ORD number if one doesn't exist.
    """
    buyer = order.get('buyerInfo', {})
    price = order.get('priceSummary', {})
    channel = order.get('channelInfo', {})
    billing = order.get('billingInfo', {}).get('contactDetails', {})
    shipping_info = order.get('shippingInfo', {})

    # Auto-generate WD order number if not already set
    order_id = order.get('id', '')
    order_date = order.get('createdDate', '')
    native_number = str(order.get('number', ''))
    existing_external = channel.get('externalOrderId', '')
    existing_custom_fields = order.get('customFields', [])

    # Check if a WD number already exists in customFields or externalOrderId
    wd_order_number = ''
    if existing_external and existing_external.startswith('WD-ORD-'):
        wd_order_number = existing_external
    else:
        for cf in existing_custom_fields:
            val = cf.get('value', '')
            if val.startswith('WD-ORD-'):
                wd_order_number = val
                break

    # If no WD number found, generate one via DynamoDB mapping
    if not wd_order_number and order_id:
        wd_order_number = _get_or_create_wd_order_number(order_id, order_date, native_number)

    # Inject into order for frontend consumption
    order['customOrderNumber'] = wd_order_number

    line_items_summary = []
    for item in order.get('lineItems', []):
        line_items_summary.append({
            'name': item.get('productName', {}).get('original', ''),
            'quantity': item.get('quantity', 0),
            'price': item.get('price', {}).get('amount', '0'),
            'sku': item.get('physicalProperties', {}).get('sku', ''),
            'image': item.get('image', {}).get('url', ''),
            'catalogItemId': item.get('catalogReference', {}).get('catalogItemId', ''),
        })

    order['_summary'] = {
        'orderNumber': order.get('number'),
        'customOrderNumber': wd_order_number,
        'externalOrderId': channel.get('externalOrderId', ''),
        'status': order.get('status', ''),
        'paymentStatus': order.get('paymentStatus', ''),
        'fulfillmentStatus': order.get('fulfillmentStatus', ''),
        'buyerEmail': buyer.get('email', ''),
        'buyerContactId': buyer.get('contactId', ''),
        'buyerMemberId': buyer.get('memberId', ''),
        'billingName': f"{billing.get('firstName', '')} {billing.get('lastName', '')}".strip(),
        'billingPhone': billing.get('phone', ''),
        'totalAmount': price.get('total', {}).get('amount', '0'),
        'subtotal': price.get('subtotal', {}).get('amount', '0'),
        'shipping': price.get('shipping', {}).get('amount', '0'),
        'tax': price.get('tax', {}).get('amount', '0'),
        'discount': price.get('discount', {}).get('amount', '0'),
        'currency': order.get('currency', ''),
        'lineItemCount': len(order.get('lineItems', [])),
        'lineItems': line_items_summary,
        'createdDate': order.get('createdDate', ''),
        'updatedDate': order.get('updatedDate', ''),
        'purchasedDate': order.get('purchasedDate', ''),
        'archived': order.get('archived', False),
        'customFields': order.get('customFields', []),
        'buyerNote': order.get('buyerNote', ''),
    }
    return order


# ===================================================================
# PRODUCT CREATION (REST API MODE)
# ===================================================================

SKU_PREFIX = 'WD'







def _create_product_rest(body: dict, request_id: str) -> Dict[str, Any]:
    source = dict(body.get('product') or {})
    if not source.get('name'):
        return _response(400, {'error': 'Missing product.name', 'requestId': request_id})

    image_urls = source.pop('imageUrls', [])
    s3_keys = source.pop('s3Keys', [])
    media_folder = source.pop('folder', 'products')
    product_data = _simple_product_to_v3(source)

    try:
        result = _wix_request('/stores/v3/products', method='POST', body={
            'fields': CATALOG_PRODUCT_FIELDS,
            'product': product_data,
        })
        created = result.get('product', {})
        pid = created.get('id', '')
        if pid and (image_urls or s3_keys):
            image_result = _add_product_image({
                'productId': pid,
                'imageUrls': image_urls,
                's3Keys': s3_keys,
                'folder': media_folder,
            }, request_id)
            if image_result.get('statusCode') >= 400:
                created['_imageAttachError'] = json.loads(image_result.get('body', '{}')).get('error', '')
            else:
                created = _wix_request(
                    f'/stores/v3/products/{pid}{_fields_suffix(CATALOG_PRODUCT_FIELDS)}'
                ).get('product', created)
        return _response(200, {
            'product': _normalize_v3_product(created),
            'created': True,
            'requestId': request_id,
        })
    except Exception as error:
        return _response(500, {'error': str(error), 'requestId': request_id})



def _update_product_rest(body: dict, request_id: str) -> Dict[str, Any]:
    source = body.get('updates') or body.get('product') or {}
    product_id = str(body.get('productId') or source.get('id') or '').strip()
    if not product_id:
        return _response(400, {'error': 'Missing productId', 'requestId': request_id})

    current = _wix_request(
        f'/stores/v3/products/{product_id}{_fields_suffix(CATALOG_PRODUCT_FIELDS)}'
    ).get('product', {})
    revision = current.get('revision')
    if revision is None:
        return _response(409, {'error': 'Product revision unavailable', 'requestId': request_id})

    patch_product = {'id': product_id, 'revision': revision}
    for key in ('name', 'visible', 'visibleInPos', 'seoData', 'media', 'ribbon'):
        if key in source:
            patch_product[key] = source[key]

    if 'plainDescription' in source:
        patch_product['plainDescription'] = source['plainDescription']
    elif isinstance(source.get('description'), str):
        patch_product['plainDescription'] = source['description']

    if isinstance(source.get('brand'), dict) and source['brand'].get('id'):
        patch_product['brand'] = {'id': source['brand']['id']}

    variant_change = any(key in source for key in ('price', 'priceData', 'sku', 'variantsInfo'))
    if variant_change:
        variants = json.loads(json.dumps(
            (source.get('variantsInfo') or current.get('variantsInfo') or {}).get('variants') or []
        ))
        if not variants:
            variants = [{'price': {'actualPrice': {'amount': '0'}}}]
        first = variants[0]
        if 'sku' in source:
            first['sku'] = source.get('sku') or ''
        if 'priceData' in source or 'price' in source:
            amount = (source.get('priceData') or {}).get('price', source.get('price', 0))
            first.setdefault('price', {})['actualPrice'] = {'amount': str(amount)}
        patch_product['variantsInfo'] = {'variants': variants}
        patch_product['options'] = source.get('options', current.get('options', []))

    if 'options' in source and 'variantsInfo' not in patch_product:
        patch_product['options'] = source['options']
        patch_product['variantsInfo'] = current.get('variantsInfo', {'variants': []})

    result = _wix_request(
        f'/stores/v3/products/{product_id}',
        method='PATCH',
        body={'fields': CATALOG_PRODUCT_FIELDS, 'product': patch_product},
    )
    return _response(200, {
        'product': _normalize_v3_product(result.get('product', {})),
        'updated': True,
        'requestId': request_id,
    })

def _bulk_create_products_rest(body: dict, request_id: str) -> Dict[str, Any]:
    products_array = body.get('products', [])
    if not products_array:
        return _response(400, {'error': 'Missing or empty products array', 'requestId': request_id})

    results = []
    for source in products_array:
        product_data = _simple_product_to_v3(source)
        try:
            created = _wix_request('/stores/v3/products', method='POST', body={
                'product': product_data
            }).get('product', {})
            results.append({
                'success': True,
                'name': source.get('name', ''),
                'productId': created.get('id', ''),
            })
        except Exception as error:
            results.append({
                'success': False,
                'name': source.get('name', ''),
                'error': str(error),
            })

    return _response(200, {
        'total': len(products_array),
        'succeeded': sum(1 for row in results if row['success']),
        'failed': sum(1 for row in results if not row['success']),
        'results': results,
        'requestId': request_id,
    })

def _s3_public_url(key: str) -> str:
    """Convert an S3 key to a public HTTPS URL."""
    return f'https://{CDN_DOMAIN}/{key}'


def _import_to_wix_media(url: str, display_name: str, folder: str = 'products') -> Dict[str, Any]:
    """
    Import an external image URL into Wix Media Manager.
    Returns the Wix-hosted media file descriptor.

    Uses POST https://www.wixapis.com/site-media/v1/files/import

    Args:
        url: Public URL of the image to import
        display_name: File name in Wix Media Manager (include extension)
        folder: Optional logical label retained for caller compatibility
    """

    # Detect mime type from extension
    ext = display_name.rsplit('.', 1)[-1].lower() if '.' in display_name else 'png'
    mime_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}
    mime_type = mime_map.get(ext, 'image/png')

    import_body = {
        'url': url,
        'displayName': display_name,
        'mediaType': 'IMAGE',
        'mimeType': mime_type,
    }

    # Use site-media API (different from stores API)
    api_url = f'{WIX_API_BASE}/site-media/v1/files/import'
    headers = {
        'Authorization': _load_wix_api_key(),
        'Content-Type': 'application/json',
        'wix-site-id': WIX_SITE_ID,
    }
    data = json.dumps(import_body).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, headers=headers, method='POST')

    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode('utf-8'))

    return result.get('file', {})



def _add_product_media_api(product_id: str, wix_media_urls: list) -> Dict[str, Any]:
    current = _wix_request(
        f'/stores/v3/products/{product_id}?fields=MEDIA_ITEMS_INFO'
    ).get('product', {})
    revision = current.get('revision')
    if revision is None:
        raise RuntimeError('Catalog V3 product revision unavailable')

    media = current.get('media') or {}
    existing = list(((media.get('itemsInfo') or {}).get('items') or []))
    known_urls = {item.get('url') for item in existing if isinstance(item, dict)}
    for url in wix_media_urls:
        if url and url not in known_urls:
            existing.append({'url': url})
            known_urls.add(url)

    main = media.get('main') or ({'url': wix_media_urls[0]} if wix_media_urls else {})
    return _wix_request(
        f'/stores/v3/products/{product_id}',
        method='PATCH',
        body={
            'fields': ['MEDIA_ITEMS_INFO', 'CURRENCY'],
            'product': {
                'id': product_id,
                'revision': revision,
                'media': {
                    'main': main,
                    'itemsInfo': {'items': existing},
                },
            },
        },
    )


def _add_product_image(body: dict, request_id: str) -> Dict[str, Any]:
    pid = body.get('productId', '')
    if not pid:
        return _response(400, {'error': 'Missing productId', 'requestId': request_id})

    folder = body.get('folder', 'products')
    urls_to_import = list(body.get('imageUrls', []))
    urls_to_import.extend(_s3_public_url(key) for key in body.get('s3Keys', []))
    if not urls_to_import:
        return _response(400, {'error': 'No imageUrls or s3Keys provided', 'requestId': request_id})

    try:
        wix_media_urls = []
        imported_files = []
        for url in urls_to_import:
            file_name = url.rstrip('/').split('/')[-1].split('?')[0] or 'image.png'
            wix_file = _import_to_wix_media(url, file_name, folder)
            wix_url = wix_file.get('url', '')
            if wix_url:
                wix_media_urls.append(wix_url)
                imported_files.append({
                    'wixId': wix_file.get('id', ''),
                    'wixUrl': wix_url,
                    'sourceUrl': url,
                    'displayName': wix_file.get('displayName', ''),
                })

        if not wix_media_urls:
            return _response(500, {'error': 'Failed to import images to Wix Media Manager', 'requestId': request_id})

        updated = _add_product_media_api(pid, wix_media_urls).get('product', {})
        normalized = _normalize_v3_product(updated)
        return _response(200, {
            'productId': pid,
            'mediaCount': normalized.get('_mediaCount', 0),
            'mainImage': normalized.get('_mainImage', ''),
            'importedFiles': imported_files,
            'updated': True,
            'requestId': request_id,
        })
    except Exception as error:
        return _response(500, {'error': str(error), 'requestId': request_id})

def _upload_product_image(event: dict, body: dict, request_id: str) -> Dict[str, Any]:
    """
    Upload a base64-encoded image to S3 and optionally attach it to a product.

    Body:
      imageBase64: required — base64-encoded image data
      fileName: required — e.g. 'visa-tourist.jpg'
      contentType: optional — e.g. 'image/jpeg' (default: auto-detect from extension)
      productId: optional — if provided, also attaches the image to this product
    """
    import base64

    image_b64 = body.get('imageBase64', '')
    file_name = body.get('fileName', '')
    if not image_b64 or not file_name:
        return _response(400, {'error': 'Missing imageBase64 or fileName', 'requestId': request_id})

    # Flat storage with wecare-digital prefix — no nesting
    short_id = uuid.uuid4().hex[:8]
    ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else 'jpg'
    s3_key = f'{S3_PRODUCT_PREFIX}/wecare-digital-{short_id}.{ext}'

    # Auto-detect content type
    ext = file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else 'jpg'
    content_type = body.get('contentType', {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'png': 'image/png', 'webp': 'image/webp',
        'gif': 'image/gif', 'svg': 'image/svg+xml',
    }.get(ext, 'image/jpeg'))

    try:
        s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=base64.b64decode(image_b64),
            ContentType=content_type,
            CacheControl='public, max-age=31536000',
        )
        public_url = _s3_public_url(s3_key)

        result = {
            's3Key': s3_key,
            'publicUrl': public_url,
            'uploaded': True,
            'requestId': request_id,
        }

        # Optionally attach to product via Wix Media Manager import flow
        pid = body.get('productId', '')
        if pid:
            folder = body.get('folder', 'products')
            attach_result = _add_product_image({
                'productId': pid,
                'imageUrls': [public_url],
                'folder': folder,
            }, request_id)
            result['productAttached'] = True
            result['productId'] = pid

        return _response(200, result)
    except Exception as e:
        return _response(500, {'error': str(e), 'requestId': request_id})


def _get_sample_products(request_id: str) -> Dict[str, Any]:
    """Return BNB CLUB sample product templates."""
    samples = {
        'category': 'BNB CLUB',
        'products': [
            {
                'name': 'Visa Assistance — Tourist Visa (Single Country)',
                'productType': 'digital',
                'priceData': {'currency': 'INR', 'price': 2999},
                'sku': 'BNB-VISA-SINGLE-001',
                'ribbon': 'BNB CLUB',
                'brand': 'WECARE.DIGITAL',
            },
            {
                'name': 'Visa Assistance — Schengen Multi-Country',
                'productType': 'digital',
                'priceData': {'currency': 'INR', 'price': 4999},
                'sku': 'BNB-VISA-SCHENGEN-001',
                'ribbon': 'BNB CLUB',
                'brand': 'WECARE.DIGITAL',
            },
            {
                'name': 'Visa Assistance — Business / Conference Visa',
                'productType': 'digital',
                'priceData': {'currency': 'INR', 'price': 3999},
                'sku': 'BNB-VISA-BUSINESS-001',
                'ribbon': 'BNB CLUB',
                'brand': 'WECARE.DIGITAL',
            },
        ],
    }
    return _response(200, {**samples, 'requestId': request_id})


# ===================================================================
# SYNC TO DYNAMODB CACHE
# ===================================================================


def _sync_products(request_id: str) -> Dict[str, Any]:
    """Sync Catalog V3 product summaries to the existing DynamoDB cache."""
    table = dynamodb.Table(PRODUCTS_CACHE_TABLE)
    synced = 0
    cursor = ''

    while True:
        paging = {'limit': 100}
        if cursor:
            paging['cursor'] = cursor
        result = _wix_request('/stores/v3/products/query', method='POST', body={
            'fields': CATALOG_PRODUCT_FIELDS,
            'query': {'cursorPaging': paging},
        })
        products = _hydrate_product_variants(result.get('products', []))
        if not products:
            break

        with table.batch_writer() as batch:
            for raw in products:
                p = _normalize_v3_product(raw)
                batch.put_item(Item={
                    'productId': p.get('id'),
                    'name': p.get('name', ''),
                    'slug': p.get('slug', ''),
                    'price': str(p.get('formattedPrice', '')),
                    'currency': p.get('currency', 'INR'),
                    'inStock': bool(p.get('inStock')),
                    'productType': p.get('productType', ''),
                    'mediaUrl': p.get('_mainImage', ''),
                    'rawData': json.dumps(raw, default=str),
                    'syncedAt': datetime.now(timezone.utc).isoformat(),
                })
                synced += 1

        metadata = result.get('pagingMetadata') or {}
        cursor = (metadata.get('cursors') or {}).get('next', '')
        if not cursor:
            break

    logger.info(json.dumps({
        'action': 'sync_products_complete',
        'count': synced,
        'catalogVersion': 'v3',
        'requestId': request_id,
    }))
    return _response(200, {
        'message': f'Synced {synced} products',
        'count': synced,
        'requestId': request_id,
    })

def _sync_orders(request_id: str) -> Dict[str, Any]:
    """Sync Wix orders to DynamoDB — both WixOrdersCache AND central OrdersTable."""
    cache_table = dynamodb.Table(ORDERS_CACHE_TABLE)
    orders_table = dynamodb.Table(ORDER_IDS_TABLE.replace('WixOrderIds', 'OrderTable') if 'WixOrderIds' in ORDER_IDS_TABLE else os.environ.get('ORDERS_TABLE', 'stack-wecare-digital-OrderTable'))
    synced = 0
    orders_synced = 0
    cursor = None

    while True:
        body: Dict[str, Any] = {
            'search': {
                'cursorPaging': {'limit': 100},
                'sort': [{'fieldName': 'createdDate', 'order': 'DESC'}],
            }
        }
        if cursor:
            body['search']['cursorPaging']['cursor'] = cursor

        result = _wix_request('/ecom/v1/orders/search', method='POST', body=body)
        orders = result.get('orders', [])
        if not orders:
            break

        # 1) Write to WixOrdersCache (raw mirror)
        with cache_table.batch_writer() as batch:
            for o in orders:
                buyer = o.get('buyerInfo', {})
                price = o.get('priceSummary', {})
                channel = o.get('channelInfo', {})
                batch.put_item(Item={
                    'orderId': o.get('id'),
                    'orderNumber': str(o.get('number', '')),
                    'externalOrderId': channel.get('externalOrderId', ''),
                    'buyerEmail': buyer.get('email', ''),
                    'buyerPhone': o.get('billingInfo', {}).get('contactDetails', {}).get('phone', ''),
                    'totalPrice': str(price.get('total', {}).get('amount', '0')),
                    'currency': o.get('currency', 'USD'),
                    'paymentStatus': o.get('paymentStatus', ''),
                    'fulfillmentStatus': o.get('fulfillmentStatus', ''),
                    'status': o.get('status', ''),
                    'lineItemCount': len(o.get('lineItems', [])),
                    'createdDate': o.get('createdDate', ''),
                    'rawData': json.dumps(o, default=str),
                    'syncedAt': datetime.now(timezone.utc).isoformat(),
                })
                synced += 1

        # 2) Write to central OrdersTable (normalized, order-centric)
        for o in orders:
            try:
                from lambda_utils.ecommerce.order_links import canonical_order_for_wix
                canonical = canonical_order_for_wix(orders_table, dynamodb.Table(ORDER_IDS_TABLE), o.get('id', ''))
                if canonical:
                    # This Wix order was created by our paid checkout. Keep its one UUID/public
                    # number rather than minting a second legacy WD-ORD row on a sync replay.
                    orders_table.update_item(
                        Key={'orderId': canonical['orderId']},
                        UpdateExpression='SET fulfillmentStatus=:status, syncedAt=:now',
                        ConditionExpression='wixOrderId=:wix',
                        ExpressionAttributeValues={':status': o.get('fulfillmentStatus', ''),
                            ':now': int(datetime.now(timezone.utc).timestamp()), ':wix': o.get('id', '')})
                    orders_synced += 1
                    continue
                enriched = _enrich_order(o)
                summary = enriched.get('_summary', {})
                wd_num = summary.get('customOrderNumber', '')
                if not wd_num or not wd_num.startswith('WD-ORD'):
                    # Generate WD number if missing
                    wd_num = _get_or_create_wd_order_number(
                        o.get('id', ''),
                        o.get('createdDate', ''),
                        str(o.get('number', '')),
                    )
                if not wd_num:
                    continue

                short = wd_num.split(' - ')[1] if len(wd_num.split(' - ')) >= 2 else wd_num[:8]
                buyer = o.get('buyerInfo', {})
                billing = o.get('billingInfo', {}).get('contactDetails', {})
                price = o.get('priceSummary', {})
                items = o.get('lineItems', [])
                items_summary = ', '.join(
                    f"{i.get('productName', {}).get('translated', '') or i.get('name', '')} × {i.get('quantity', 1)}"
                    for i in items[:5]
                )
                total_amount = float(price.get('total', {}).get('amount', 0) or 0)
                phone = billing.get('phone', '') or buyer.get('phone', '')

                # IST date formatting
                order_date_ist = ''
                order_date = ''
                order_time = ''
                created = o.get('createdDate', '')
                if created:
                    try:
                        dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
                        order_date_ist = ist.strftime('%-d %b %Y, %-I:%M %p')
                        order_date = ist.strftime('%Y-%m-%d')
                        order_time = ist.strftime('%H:%M:%S')
                    except Exception:
                        pass

                now = int(datetime.now(timezone.utc).timestamp())
                item = {
                    'orderId': wd_num,
                    'shortId': short,
                    'source': 'wix',
                    'sourceOrderId': o.get('id', ''),
                    'sourceOrderNumber': str(o.get('number', '')),
                    'customerPhone': phone,
                    'customerName': billing.get('firstName', '') + ' ' + billing.get('lastName', ''),
                    'customerEmail': buyer.get('email', ''),
                    'orderDate': order_date,
                    'orderTime': order_time,
                    'orderDateIST': order_date_ist,
                    'itemsSummary': items_summary,
                    'itemsJson': json.dumps(items, default=str),
                    'itemCount': len(items),
                    'totalAmount': Decimal(str(total_amount)) if total_amount else Decimal('0'),
                    'currency': o.get('currency', 'INR'),
                    'orderStatus': (o.get('status', 'active') or 'active').lower(),
                    'paymentStatus': (o.get('paymentStatus', 'pending') or 'pending').lower(),
                    'fulfillmentStatus': o.get('fulfillmentStatus', ''),
                    'createdAt': now,
                    'updatedAt': now,
                    'syncedAt': now,
                }
                orders_table.put_item(Item={k: v for k, v in item.items() if v is not None and v != ''})
                orders_synced += 1
            except Exception as e:
                logger.warning(f'OrdersTable sync failed for order {o.get("id", "")}: {e}')

        paging = result.get('pagingMetadata', {})
        if paging.get('hasNext') and paging.get('cursors', {}).get('next'):
            cursor = paging['cursors']['next']
        else:
            break

    logger.info(json.dumps({
        'action': 'sync_orders_complete',
        'cache_synced': synced,
        'orders_table_synced': orders_synced,
        'requestId': request_id,
    }))
    return _response(200, {
        'message': f'Synced {synced} to cache, {orders_synced} to OrdersTable',
        'cacheSynced': synced,
        'ordersTableSynced': orders_synced,
        'requestId': request_id,
    })


# ===================================================================
# HELPERS
# ===================================================================







def _response(status_code: int, body: dict) -> Dict[str, Any]:
    """Build API Gateway response."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str),
    }
