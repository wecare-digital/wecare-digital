"""Server-side Wix client limited to commerce/product and legacy page SEO reads."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from pathlib import Path

import boto3

WIX_API = 'https://www.wixapis.com'
SITE_BASE = 'https://wecare.digital'
SECRET_NAME = os.environ.get('WIX_API_KEY_SECRET', '').strip()
SITE_ID = os.environ.get('WIX_SITE_ID', '').strip()
ACCOUNT_ID = os.environ.get('WIX_ACCOUNT_ID', '').strip()
WIX_CLIENT_ID = os.environ.get(
    'WIX_CLIENT_ID', '42b3cdbf-d90e-4138-a06c-ddda4fb8da01'
).strip()
_api_key = None
_visitor_access_token = None
_visitor_access_token_expires_at = 0.0

# ── Upstream budget and per-sandbox caches ──────────────────────────────────────
#
# THE 30-SECOND WALL, and why a flat per-call timeout could not avoid it.
#
# API Gateway cuts a Lambda integration off at 30s and returns 503 with no body.
# Measured on 2026-09-28: `wecare-seo-tools` peaked at 30,499ms and one access-log line
# reads `30001ms status=503` on a per-slug path. The cause is arithmetic rather than a
# slow network. Every blog call did this:
#
#   _blog_reference_maps()   2+ paginated upstream calls, EVERY request, uncached
#   list_blog_posts()        889 posts at 100 a page = 9 sequential queries
#   each of those            urlopen(timeout=30)
#
# so the worst case was 11 x 30s = 330s against a 30s ceiling. A single stalled page
# spent the entire budget, and the caller saw a 503 that looked like our fault rather
# than a timeout. Wix also returned a genuine 503 twice in 7 days, and with no retry
# that surfaced straight into the build - `generate-sitemap.js` fetches this endpoint at
# build time and refuses to write a sitemap when it comes back empty.
#
# Three changes, and each addresses a different one of those terms:
#
#   1. A per-call timeout well under the ceiling, so no single upstream call can spend
#      the whole budget.
#   2. One retry on the retryable statuses, because a 503 from Wix is usually transient
#      and a build must not fail on it.
#   3. Per-sandbox TTL caches on the two expensive reads, so a warm invocation makes NO
#      upstream call at all. This is the change that actually removes the timeout: the
#      reference maps are category and tag labels that change on a content edit, not per
#      request, and re-fetching them on every single call was pure waste.
#
# Lazy, module-level, and warm-sandbox-scoped, which is the same shape the visitor token
# above already uses. Not a shared cache - a cold sandbox pays full price once, which is
# correct: a cross-invocation store would need a table, and the value here is reference
# data that is cheap to re-derive and harmful to serve indefinitely.
_REQUEST_TIMEOUT = float(os.environ.get('WIX_REQUEST_TIMEOUT_SECONDS', '8'))
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_BLOG_CACHE_TTL = float(os.environ.get('WIX_BLOG_CACHE_TTL_SECONDS', '300'))

# key -> (fetched_at, value). Holds the last GOOD value indefinitely so that
# _cached() can serve it when a refresh fails; TTL controls freshness, not eviction.
_cache: Dict[str, Any] = {}


def _cached(key: str, producer, ttl: float = _BLOG_CACHE_TTL):
    """Memoise `producer` for `ttl` seconds, and serve stale rather than fail.

    STALE BEATS EMPTY HERE, and that is a deliberate asymmetry worth stating. This data
    feeds the public blog index and, at build time, the sitemap. A five-minute-old
    category label is a non-event. An exception - or worse, an empty list - during a
    build makes `next build` emit a site with no blog, and `generate-sitemap.js` exists
    specifically because that once happened from a two-second network blip.
    So a failed refresh with a previous value in hand returns the previous value and logs
    nothing to the caller; a failed refresh with nothing in hand still raises.
    """
    entry = _cache.get(key)
    if entry is not None and (time.time() - entry[0]) < ttl:
        return entry[1]
    try:
        value = producer()
    except Exception:
        if entry is not None:
            return entry[1]
        raise
    _cache[key] = (time.time(), value)
    return value


def clear_blog_cache() -> None:
    """Drop the caches. Called after a write so a mutation is visible immediately.

    Without this, creating or cleaning a post would leave the reader serving the
    pre-edit corpus for up to the TTL, and the Admin who just made the change is
    precisely the person who would report it as a bug.
    """
    _cache.clear()

def public_page_catalog() -> list[dict]:
    """Read the same generated catalogue that the public site and MCP publish."""
    packaged = Path(__file__).resolve().parent / 'public-pages.json'
    repository = Path(__file__).resolve().parents[4] / 'config' / 'public-pages.json'
    catalog = packaged if packaged.is_file() else repository
    return json.loads(catalog.read_text(encoding='utf-8'))['pages']


def _load_api_key() -> str:
    """The authenticated Wix API key, for writes and commerce reads.

    THE KILL SWITCH IS CHECKED FIRST, before any Secrets Manager read. Until 2026-09-29
    this function ignored `WIX_CREDENTIALS_DISABLED` entirely: the switch was honoured in
    `ecommerce/wix-store` and not here, so it disabled the store and left the BLOG paths -
    the ones that publish - running. A switch that covers one of three credential paths is
    the same defect as a switch nothing reads.

    Note what stays unaffected: `_load_visitor_access_token()` below, which serves the
    public blog anonymously with a public client id. See `lambda_utils.wix_guard` for why
    disabling that would make the control unusable during the incident it exists for.
    """
    global _api_key
    from lambda_utils.wix_guard import refuse_if_disabled
    refuse_if_disabled('seo-tools authenticated Wix client')

    if _api_key is not None:
        return _api_key
    if not SECRET_NAME or not SITE_ID:
        raise RuntimeError('Wix Headless credentials are not configured')
    raw = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1')).get_secret_value(
        SecretId=SECRET_NAME
    ).get('SecretString', '')
    try:
        value = json.loads(raw)
        _api_key = str(value.get('api_key') or value.get('apiKey') or value.get('key') or value.get('value') or '')
    except (TypeError, ValueError):
        _api_key = str(raw)
    if not _api_key or not SITE_ID:
        raise RuntimeError('Wix server configuration is incomplete')
    return _api_key


def request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {
        'Authorization': _load_api_key(), 'wix-site-id': SITE_ID,
        'Content-Type': 'application/json', 'Accept': 'application/json',
    }
    if ACCOUNT_ID:
        headers['wix-account-id'] = ACCOUNT_ID
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(WIX_API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        error.read()
        raise RuntimeError(f'Wix API request failed with status {error.code}') from error
    except urllib.error.URLError as error:
        raise RuntimeError('Wix API request failed') from error


def _load_visitor_access_token() -> str:
    global _visitor_access_token, _visitor_access_token_expires_at
    now = time.time()
    if (
        _visitor_access_token
        and now < _visitor_access_token_expires_at - 60
    ):
        return _visitor_access_token
    if not WIX_CLIENT_ID:
        raise RuntimeError('Wix Headless client ID is not configured')
    payload = json.dumps({
        'clientId': WIX_CLIENT_ID,
        'grantType': 'anonymous',
    }).encode('utf-8')
    req = urllib.request.Request(
        WIX_API + '/oauth2/token',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        error.read()
        raise RuntimeError(
            f'Wix visitor token request failed with status {error.code}'
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError('Wix visitor token request failed') from error

    token = str(data.get('access_token') or '').strip()
    if not token:
        raise RuntimeError('Wix visitor token response did not include an access token')
    expires_in = int(data.get('expires_in') or 0)
    _visitor_access_token = token
    _visitor_access_token_expires_at = now + max(expires_in, 300)
    return token


def public_blog_request(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(
        WIX_API + path,
        data=data,
        headers={
            'Authorization': _load_visitor_access_token(),
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method=method,
    )
    # ONE retry, and only for the statuses where retrying can help. A 404 means the slug
    # does not exist and get_blog_post_by_slug reads that string to return None, so
    # retrying it would double the latency of every miss; a 401 means the visitor token
    # is wrong and will be wrong again. 429/5xx is the transient family - Wix returned a
    # real 503 twice in 7 days and with no retry that reached the build.
    #
    # Total worst case is 2 x _REQUEST_TIMEOUT + backoff, which must stay comfortably
    # under the 30s API Gateway ceiling even when a caller makes several of these.
    last: Exception
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as response:
                raw = response.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            error.read()
            last = RuntimeError(
                f'Wix public Blog API request failed with status {error.code}'
            )
            if error.code not in _RETRY_STATUSES:
                raise last from error
        except urllib.error.URLError as error:
            last = RuntimeError('Wix public Blog API request failed')
        except TimeoutError as error:
            last = RuntimeError('Wix public Blog API request timed out')
        if attempt == 0:
            time.sleep(0.4)
    raise last


def public_json(path: str, timeout: int = 8) -> Dict[str, Any]:
    req = urllib.request.Request(SITE_BASE + path, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return {}


def page_seo(path: str) -> Dict[str, Any]:
    value = public_json('/_functions/seohead?path=' + urllib.parse.quote(path, safe=''))
    schemas = value.get('structuredData', []) or []
    return {
        'title': value.get('title', ''), 'metaDescription': value.get('description', ''),
        'keywords': value.get('keywords', []) or [],
        'jsonLdTypes': [schema.get('@type') for schema in schemas if schema.get('@type')],
        'hasJsonLd': bool(schemas), 'canonical': value.get('canonical', ''),
    }


def list_site_pages() -> List[Dict[str, Any]]:
    """Current published pages, without resurrecting a legacy Wix inventory."""
    return [
        {
            'path': page['path'], 'name': page['name'], 'type': page['group'],
            'url': SITE_BASE + page['path'], 'title': page['name'],
            'metaDescription': page['description'], 'keywords': [],
            'jsonLdTypes': [], 'hasJsonLd': False,
            'canonical': SITE_BASE + page['path'],
        }
        for page in public_page_catalog()
    ]


DEFAULT_BLOG_AUTHOR = os.environ.get('WIX_BLOG_AUTHOR_NAME', 'Anew by WECARE.DIGITAL').strip() or 'Anew by WECARE.DIGITAL'


def _seo_values(post: Dict[str, Any]) -> Dict[str, Any]:
    seo = post.get('seoData') or {}
    title = ''
    description = ''
    robots = 'index, follow, max-image-preview:large'
    for tag in seo.get('tags', []) or []:
        tag_type = str(tag.get('type') or '').lower()
        props = tag.get('props') or {}
        if tag_type == 'title':
            title = str(tag.get('children') or '').strip()
        elif tag_type == 'meta':
            name = str(props.get('name') or '').lower()
            if name == 'description':
                description = str(props.get('content') or '').strip()
            elif name == 'robots':
                robots = str(props.get('content') or robots).strip()
    keywords = []
    for keyword in (seo.get('settings') or {}).get('keywords', []) or []:
        term = str(keyword.get('term') or '').strip()
        if term:
            keywords.append(term)
    return {
        'seoTitle': title,
        'metaDescription': description,
        'robots': robots,
        'keywords': keywords,
    }


def _paged_blog_labels(path: str, key: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    offset = 0
    while True:
        data = public_blog_request(
            'POST',
            path,
            {'query': {'paging': {'limit': 100, 'offset': offset}}},
        )
        page = data.get(key, []) or []
        items.extend(page)
        if len(page) < 100:
            break
        offset += len(page)
    return items


def _blog_reference_maps() -> Dict[str, Dict[str, str]]:
    """Category and tag id -> label, cached per sandbox.

    THE SINGLE BIGGEST WASTE IN THIS MODULE before caching. Both `list_blog_posts` and
    `get_blog_post_by_slug` call this first, so every one of the ~185,000 daily requests
    paid for at least two extra paginated upstream queries to resolve labels that change
    when someone edits a category - which is to say, almost never.
    """
    return _cached('blog_refs', _fetch_blog_reference_maps)


def _fetch_blog_reference_maps() -> Dict[str, Dict[str, str]]:
    categories = _paged_blog_labels('/blog/v3/categories/query', 'categories')
    tags = _paged_blog_labels('/v3/tags/query', 'tags')
    return {
        'categories': {
            str(item.get('id') or ''): str(
                item.get('label') or item.get('title') or ''
            ).strip()
            for item in categories if item.get('id')
        },
        'tags': {
            str(item.get('id') or ''): str(item.get('label') or '').strip()
            for item in tags if item.get('id')
        },
    }


def _blog_view(post: Dict[str, Any], refs: Dict[str, Dict[str, str]], include_content: bool) -> Dict[str, Any]:
    slug = str(post.get('slug') or '').strip()
    seo = _seo_values(post)
    category_ids = post.get('categoryIds') or []
    tag_ids = post.get('tagIds') or []
    category = next((refs['categories'].get(str(value), '') for value in category_ids if refs['categories'].get(str(value))), '')
    tags = [refs['tags'][str(value)] for value in tag_ids if refs['tags'].get(str(value))]
    author = DEFAULT_BLOG_AUTHOR
    result = {
        'id': post.get('id', ''),
        'title': post.get('title', ''),
        'slug': slug,
        'excerpt': post.get('excerpt', ''),
        'url': f'{SITE_BASE}/post/{slug}/',
        'seoTitle': seo['seoTitle'],
        'metaDescription': seo['metaDescription'],
        'focusKeyword': seo['keywords'][0] if seo['keywords'] else '',
        'keywords': seo['keywords'],
        'jsonLd': {},
        'publishedDate': post.get('firstPublishedDate', ''),
        'modifiedDate': post.get('lastPublishedDate') or post.get('firstPublishedDate', ''),
        'coverImage': '',
        'category': category,
        'tags': tags,
        'hashtags': post.get('hashtags', []) or [],
        'authorName': author,
        'robots': seo['robots'],
    }
    if include_content:
        result['content'] = post.get('contentText', '') or ''
        result['richContent'] = post.get('richContent') or {}
    return result


def list_blog_posts() -> List[Dict[str, Any]]:
    """The whole published corpus, cached per sandbox.

    889 posts at 100 a page is 9 sequential upstream queries plus the reference maps, and
    this is the single hottest read in the account. Cached, a warm invocation makes zero
    upstream calls; uncached it was the path that reached the 30s ceiling.
    """
    return _cached('blog_list', _fetch_blog_posts)


def _fetch_blog_posts() -> List[Dict[str, Any]]:
    refs = _blog_reference_maps()
    posts: List[Dict[str, Any]] = []
    cursor = ''
    # A DEADLINE ON THE LOOP, because the page count is set by the corpus rather than by
    # us: it was 9 pages at 889 posts and grows with every publish. Without this, a slow
    # upstream is cut off mid-flight by API Gateway at 30s and the caller gets a bodiless
    # 503. Raising instead means _cached() can fall back to the previous good corpus, and
    # a caller with no cache gets an error it can report.
    #
    # It RAISES rather than returning what it has so far. A truncated corpus is the worse
    # outcome by a distance: it looks like success, and `generate-sitemap.js` would write
    # a sitemap that silently drops the missing posts. Its own guard only catches ZERO
    # posts, not 400 of 889.
    deadline = time.monotonic() + float(os.environ.get('WIX_BLOG_LIST_BUDGET_SECONDS', '20'))
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(
                f'Wix blog listing exceeded its time budget after {len(posts)} posts'
            )
        paging = {'limit': 100}
        if cursor:
            paging['cursor'] = cursor
        body = {
            'fieldsets': ['URL', 'SEO'],
            'query': {'cursorPaging': paging},
            'skipCount': True,
        }
        data = public_blog_request('POST', '/v3/posts/query', body)
        posts.extend(data.get('posts', []) or [])
        cursor = str(((data.get('pagingMetadata') or {}).get('cursors') or {}).get('next') or '')
        if not cursor:
            break
    return [_blog_view(post, refs, include_content=False) for post in posts]


def get_blog_post_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """One post with its body, cached per sandbox per slug.

    This is the endpoint the 185,000 daily requests actually hit: 890 distinct paths,
    each slug about 219 times in 24 hours. The frontend memo in src/lib/public-blog.ts
    removes most of that multiplication at source, and this removes the rest - a warm
    sandbox serves a repeat without touching Wix at all.

    A MISS IS NOT CACHED. `None` here means either "no such post" or "the lookup failed",
    and the two must not be conflated: caching a failure would keep a real post missing
    for the whole TTL. Same reasoning as the frontend memo, which deletes its entry on a
    null for exactly this reason.
    """
    wanted = str(slug or '').strip().strip('/')
    if not wanted:
        return None
    post = _cached(f'blog_post:{wanted}', lambda: _fetch_blog_post(wanted))
    if post is None:
        _cache.pop(f'blog_post:{wanted}', None)
    return post


def _fetch_blog_post(wanted: str) -> Optional[Dict[str, Any]]:
    refs = _blog_reference_maps()
    params = urllib.parse.urlencode([
        ('fieldsets', 'URL'),
        ('fieldsets', 'CONTENT_TEXT'),
        ('fieldsets', 'SEO'),
        ('fieldsets', 'RICH_CONTENT'),
    ])
    try:
        data = public_blog_request(
            'GET',
            '/v3/posts/slugs/' + urllib.parse.quote(wanted, safe='') + '?' + params,
        )
    except RuntimeError as error:
        if 'status 404' in str(error):
            return None
        raise
    post = data.get('post')
    if not post:
        return None
    return _blog_view(post, refs, include_content=True)


def list_products() -> List[Dict[str, Any]]:
    data = request('POST', '/stores/v3/products/query', {
        'fields': ['CURRENCY', 'MEDIA_ITEMS_INFO', 'DESCRIPTION'],
        'query': {'cursorPaging': {'limit': 100}},
    })
    products = []
    for product in data.get('products', []):
        price_range = product.get('actualPriceRange', {}) or {}
        minimum = price_range.get('minValue', {}) or {}
        amount = minimum.get('amount', '')
        currency = product.get('currency', 'INR')
        media = product.get('media', {}) or {}
        image = (media.get('main', {}) or {}).get('url', '')
        inventory = product.get('inventory', {}) or {}
        availability = str(inventory.get('availabilityStatus', '')).upper()
        products.append({
            'id': product.get('id', ''), 'name': product.get('name', ''),
            'slug': product.get('slug', ''),
            'url': f"{SITE_BASE}/store/product/{product.get('slug', '')}",
            'description': str(product.get('plainDescription', '') or '')[:200],
            'price': f"{currency} {amount}".strip() if amount else '',
            'priceAmount': amount or 0, 'currency': currency,
            'inStock': availability in ('IN_STOCK', 'PARTIALLY_OUT_OF_STOCK'),
            'image': image,
            'type': str(product.get('productType', '')).lower(),
            'hasJsonLd': False, 'jsonLdType': '',
        })
    return products
