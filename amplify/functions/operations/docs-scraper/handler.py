"""
Documentation Scraper — WECARE.DIGITAL

Fetches external documentation (e.g. Meta Business/WhatsApp docs), renders it
with headless Chromium (Playwright), cleans it to Markdown (BeautifulSoup),
detects changes via content hashing, keeps an append-only changelog, and stores
everything in the single media bucket under o/stream/media/docs/.

Runs as a container Lambda (see Dockerfile). Invoked by:
  - EventBridge daily cron        -> {}  or  {"action": "scrape"}   (scrape all sources)
  - Frontend "add source"         -> {"action": "add_source", "name": "...", "rootUrl": "...",
                                       "sidebarSelector": "nav", "contentSelector": "main"}
  - Frontend "upgrade/re-fetch"   -> {"action": "scrape", "source": "meta-business-agent"}
  - Frontend "list sources"       -> {"action": "list_sources"}
  - Frontend "changelog"          -> {"action": "changelog", "limit": 50}

S3 layout (bucket: wecare-digital-get; was app.wecare.digital until 2026-09-28).
The `o/` root below is part of the key, matching PREFIX = media_paths.public(...):
  o/stream/media/docs/_sources.json                 list of sources (frontend-editable)
  o/stream/media/docs/_index.json                   {url: {hash, key, source, lastSeen}}
  o/stream/media/docs/_changelog.jsonl              append-only change log (one JSON per line)
  o/stream/media/docs/<source-slug>/<page-slug>.md  cleaned page content
"""

import os
import re
import json
import hashlib
import datetime
from typing import Any, Dict, List

import boto3

from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_headers, options_response, extract_origin
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

BUCKET = os.environ.get('DOCS_BUCKET', media_paths.BUCKET)
PREFIX = os.environ.get('DOCS_PREFIX', media_paths.PUBLIC_STREAM_MEDIA_DOCS_PREFIX).rstrip('/')
SOURCES_KEY = f'{PREFIX}/_sources.json'
INDEX_KEY = f'{PREFIX}/_index.json'
CHANGELOG_KEY = f'{PREFIX}/_changelog.jsonl'

s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))


# ─── helpers ───────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _slug(text: str) -> str:
    text = re.sub(r'^https?://', '', text or '').strip('/')
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:120] or 'page'


def _s3_get_json(key: str, default):
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return json.loads(obj['Body'].read().decode('utf-8'))
    except s3.exceptions.NoSuchKey:
        return default
    except Exception:
        return default


def _s3_put_json(key: str, data) -> None:
    s3.put_object(Bucket=BUCKET, Key=key,
                  Body=json.dumps(data, indent=2).encode('utf-8'),
                  ContentType='application/json')


def _append_changelog(entries: List[Dict[str, Any]]) -> None:
    if not entries:
        return
    existing = ''
    try:
        existing = s3.get_object(Bucket=BUCKET, Key=CHANGELOG_KEY)['Body'].read().decode('utf-8')
    except Exception:
        existing = ''
    lines = existing + ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in entries)
    s3.put_object(Bucket=BUCKET, Key=CHANGELOG_KEY,
                  Body=lines.encode('utf-8'), ContentType='application/x-ndjson')


# ─── cleaning ──────────────────────────────────────────────────────────────
def _clean_html(html: str, content_selector: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    for tag in soup(['nav', 'header', 'footer', 'script', 'style', 'noscript', 'iframe', 'svg']):
        tag.decompose()
    node = soup.select_one(content_selector) or soup.find('main') or soup.body
    return node.get_text(separator='\n', strip=True) if node else ''


def _default_prefix(root_url: str) -> str:
    """Doc-section prefix: strip the last path segment.
    .../documentation/meta-business-agent/overview -> .../documentation/meta-business-agent/"""
    p = root_url.split('#')[0].split('?')[0].rstrip('/')
    return (p.rsplit('/', 1)[0] + '/') if '/' in p.split('://', 1)[-1] else p + '/'


def _discover_links(html: str, base_url: str, path_prefix: str) -> List[str]:
    """Collect sub-page links belonging to the same doc section (by URL path
    prefix). This is far more robust than a CSS sidebar selector for JS-heavy
    sites like Meta docs that use obfuscated/dynamic class names."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, 'lxml')
    urls = []
    for a in soup.find_all('a', href=True):
        href = a['href'].split('#')[0].split('?')[0]
        if not href or href.startswith(('mailto:', 'javascript:')):
            continue
        full = urljoin(base_url, href)
        if full.startswith('http') and full.startswith(path_prefix) and full not in urls:
            urls.append(full)
    return urls


# ─── scraping ──────────────────────────────────────────────────────────────
def _scrape_source(source: Dict[str, Any], index: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch every page of a source, write changed ones, return changelog entries."""
    from playwright.sync_api import sync_playwright

    name = source['name']
    slug = _slug(name)
    root = source['rootUrl']
    content_selector = source.get('contentSelector', 'main')
    path_prefix = source.get('pathPrefix') or _default_prefix(root)
    changes: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page()

        page.goto(root, wait_until='networkidle', timeout=45000)
        root_html = page.content()
        urls = [root] + [u for u in _discover_links(root_html, root, path_prefix) if u != root]
        # Limit breadth per run to stay within Lambda timeout; cron catches the rest next day.
        urls = urls[: int(os.environ.get('MAX_PAGES_PER_RUN', '40'))]

        for url in urls:
            try:
                if url == root:
                    html = root_html
                else:
                    page.goto(url, wait_until='networkidle', timeout=45000)
                    html = page.content()
                text = _clean_html(html, content_selector)
                if not text:
                    continue
                new_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
                prev = index.get(url)
                if prev and prev.get('hash') == new_hash:
                    prev['lastSeen'] = _now()
                    continue  # unchanged
                key = f'{PREFIX}/{slug}/{_slug(url)}.md'
                body = f'# Source: {url}\n# Fetched: {_now()}\n\n{text}\n'
                s3.put_object(Bucket=BUCKET, Key=key,
                              Body=body.encode('utf-8'), ContentType='text/markdown')
                changes.append({
                    'ts': _now(), 'source': name, 'url': url,
                    'type': 'updated' if prev else 'new',
                    'oldHash': (prev or {}).get('hash'), 'newHash': new_hash, 'key': key,
                })
                index[url] = {'hash': new_hash, 'key': key, 'source': name, 'lastSeen': _now()}
            except Exception as e:
                changes.append({'ts': _now(), 'source': name, 'url': url, 'type': 'error', 'error': str(e)})

        browser.close()
    return changes


# ─── actions ────────────────────────────────────────────────────────────────
def _scrape(event) -> Dict[str, Any]:
    sources = _s3_get_json(SOURCES_KEY, [])
    only = event.get('source')
    if only:
        sources = [s for s in sources if s.get('name') == only]
    if not sources:
        return {'statusCode': 404, 'body': json.dumps({'error': 'no matching sources'})}
    index = _s3_get_json(INDEX_KEY, {})
    all_changes: List[Dict[str, Any]] = []
    for src in sources:
        all_changes.extend(_scrape_source(src, index))
    _s3_put_json(INDEX_KEY, index)
    _append_changelog(all_changes)
    summary = {
        'scraped': [s['name'] for s in sources],
        'changed': [c for c in all_changes if c['type'] in ('new', 'updated')],
        'errors': [c for c in all_changes if c['type'] == 'error'],
        'changedCount': sum(1 for c in all_changes if c['type'] in ('new', 'updated')),
    }
    return {'statusCode': 200, 'body': json.dumps(summary)}


def _add_source(event) -> Dict[str, Any]:
    if not event.get('rootUrl') or not event.get('name'):
        return {'statusCode': 400, 'body': json.dumps({'error': 'name and rootUrl required'})}
    sources = _s3_get_json(SOURCES_KEY, [])
    if any(s.get('name') == event['name'] for s in sources):
        return {'statusCode': 409, 'body': json.dumps({'error': 'source already exists'})}
    sources.append({
        'name': event['name'],
        'rootUrl': event['rootUrl'],
        # Optional overrides; pathPrefix defaults to the doc-section of rootUrl.
        'pathPrefix': event.get('pathPrefix') or _default_prefix(event['rootUrl']),
        'contentSelector': event.get('contentSelector', 'main'),
        'addedAt': _now(),
    })
    _s3_put_json(SOURCES_KEY, sources)
    return {'statusCode': 200, 'body': json.dumps({'ok': True, 'sources': [s['name'] for s in sources]})}


def _list_sources(_event) -> Dict[str, Any]:
    return {'statusCode': 200, 'body': json.dumps(_s3_get_json(SOURCES_KEY, []))}


def _changelog(event) -> Dict[str, Any]:
    limit = int(event.get('limit', 50))
    try:
        raw = s3.get_object(Bucket=BUCKET, Key=CHANGELOG_KEY)['Body'].read().decode('utf-8')
        rows = [json.loads(l) for l in raw.strip().splitlines() if l.strip()]
    except Exception:
        rows = []
    return {'statusCode': 200, 'body': json.dumps(rows[-limit:][::-1])}


def lambda_handler(event, context):
    event = event or {}
    origin = extract_origin(event) if isinstance(event, dict) else ''
    method = (event.get('requestContext', {}).get('http', {}).get('method', '')
              if isinstance(event, dict) else '')
    if method == 'OPTIONS':
        return options_response(origin)
    # Support both direct invoke and API Gateway proxy (body may be a JSON string).
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:
            event = {}
    auth_result = require_auth(event, required_role='Admin')
    if auth_result is not None:
        return auth_result

    route = (event or {}).get('routeKey', '')  # API GW v2, e.g. "GET /docs/sources"
    qs = (event or {}).get('queryStringParameters') or {}
    if isinstance(event.get('body'), str):
        try:
            event = {**event, **json.loads(event['body'])}
        except Exception:
            pass

    # Resolve action from REST route first, then body/query, default to scrape.
    ROUTE_ACTIONS = {
        'GET /docs/sources': 'list_sources',
        'POST /docs/sources': 'add_source',
        'POST /docs/scrape': 'scrape',
        'GET /docs/changelog': 'changelog',
    }
    action = ROUTE_ACTIONS.get(route) or (event or {}).get('action') or qs.get('action') or 'scrape'
    if qs.get('limit') and 'limit' not in event:
        event['limit'] = qs['limit']
    if qs.get('source') and 'source' not in event:
        event['source'] = qs['source']
    if action == 'add_source':
        result = _add_source(event)
    elif action == 'list_sources':
        result = _list_sources(event)
    elif action == 'changelog':
        result = _changelog(event)
    else:
        result = _scrape(event or {})
    result['headers'] = cors_headers(origin)
    return result
