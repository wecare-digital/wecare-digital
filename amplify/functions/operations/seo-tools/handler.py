"""SEO API for AWS-native blog content plus authenticated Admin SEO tools."""
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from lambda_utils.idempotency import (
    body_hash, claim_admin_action, make_admin_idempotency_key, release_admin_audit,
)
from lambda_utils.middleware import require_auth
from lambda_utils.response import (
    cors_headers, cors_response, extract_origin, options_response,
)

import ai
import blog_source
import faq
import seo_freshness
import seo_refresh
import storage
import page_catalog

logger = logging.getLogger(__name__)
INPUT_COST_PER_M = 3.0
OUTPUT_COST_PER_M = 15.0


def _method_path(event: Dict[str, Any]) -> Tuple[str, str]:
    context = event.get('requestContext', {})
    method = context.get('http', {}).get('method', event.get('httpMethod', 'GET')).upper()
    path = context.get('http', {}).get('path') or event.get('rawPath') or event.get('path', '/')
    return method, path.rstrip('/') or '/'


def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        value = json.loads(event.get('body', '{}') or '{}')
        if not isinstance(value, dict):
            raise ValueError('Request body must be a JSON object')
        return value
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid JSON request body') from error


def _actor(event: Dict[str, Any]) -> str:
    return str(event.get('_auth', {}).get('username', '')).strip()


def _response(status: int, body: Dict[str, Any], origin: str):
    return cors_response(status, body, origin)


# ── Public blog read surface: projection, validators, caching ───────────────────

# The fields a caller may ask for. An allowlist rather than "any key present on the
# record", so `?fields=` cannot be used to probe for internal fields that a future
# version of the native post view (`storage.get_blog_post`) might add.
_PUBLIC_POST_FIELDS = frozenset({
    'slug', 'title', 'excerpt', 'category', 'publishedDate', 'modifiedDate',
    'authorName', 'coverImage', 'url', 'tags', 'seoTitle', 'metaDescription',
    'focusKeyword', 'keywords', 'hashtags', 'robots', 'jsonLd', 'id',
})

# Five minutes at the edge and one in the browser; the native read itself is uncached
# (DynamoDB on every request). stale-while-revalidate lets a CDN serve the old copy
# while it refreshes, which is the correct trade for a blog index.
_BLOG_CACHE_CONTROL = 'public, max-age=60, s-maxage=300, stale-while-revalidate=600'


def _projection(event: Dict[str, Any]) -> Optional[set]:
    """Parse `?fields=a,b,c` into a validated set, or None for "everything".

    WHY THIS EXISTS. The list response is 924 kB for 889 posts, and roughly half of that
    is `jsonLd`, `keywords`, `hashtags`, `robots`, `focusKeyword` and `metaDescription` -
    fields no caller of the public surface renders. `generate-blog-search-index.js`
    documents that it wants exactly four of them and then throws the rest away after
    transferring it.

    Unknown names are IGNORED rather than rejected. A caller asking for a field that was
    removed should get the fields that still exist, not a 400 that breaks a build over a
    rename. `slug` is always included because every consumer keys on it.
    """
    raw = _query(event, 'fields').strip()
    if not raw:
        return None
    wanted = {part.strip() for part in raw.split(',') if part.strip()}
    # THE FALLBACK TESTS THE REQUEST, NOT THE RESULT, and the difference is a real bug
    # that `test_the_etag_tracks_the_projection` caught. Deciding on
    # `keep - {'slug'}` being empty meant `?fields=slug` - a perfectly reasonable request,
    # and exactly what getStaticPaths needs - was indistinguishable from `?fields=nonsense`
    # and returned the entire 924 kB corpus. Fall back only when NOTHING the caller asked
    # for is recognised, which is the case the fallback was actually for: a field rename
    # should not break a build.
    recognised = wanted & _PUBLIC_POST_FIELDS
    if not recognised:
        return None
    return recognised | {'slug'}


def _project(posts, fields: Optional[set]):
    if not fields:
        return posts
    return [{k: v for k, v in post.items() if k in fields} for post in posts]


def _cacheable(status: int, body: Dict[str, Any], origin: str, event: Dict[str, Any]):
    """A public read response carrying an ETag and Cache-Control, honouring If-None-Match.

    WHAT THIS DOES AND DOES NOT BUY, stated plainly so nobody over-credits it.

    The ETag is a sha256 over the serialised body, so an unchanged corpus yields an
    unchanged tag and a conditional request costs 0 bytes of payload instead of 924 kB.
    That only helps a client that actually sends If-None-Match - and Node's global fetch,
    which is what the build uses, does NOT by default. So this is groundwork plus a real
    win for the CDN and for any caller that opts in, NOT the fix for the traffic volume.
    The fix for the volume is the memo in src/lib/public-blog.ts; this is the second
    layer, not the first.

    Deliberately NOT using cors_response for the 304: a 304 MUST NOT carry a body, and
    cors_response always json.dumps one and sets Content-Type.
    """
    payload = json.dumps(body, default=str)
    etag = '"' + hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32] + '"'
    headers = event.get('headers') or {}
    inm = ''
    for key, value in headers.items():
        if str(key).lower() == 'if-none-match':
            inm = str(value or '')
            break
    if status == 200 and inm and etag in inm:
        return {
            'statusCode': 304,
            'headers': {
                **cors_headers(origin),
                'ETag': etag,
                'Cache-Control': _BLOG_CACHE_CONTROL,
                # A 304 must not declare a body type it is not sending.
                'Content-Type': '',
            },
            'body': '',
        }
    response = cors_response(status, body, origin)
    response['headers'] = {
        **response['headers'],
        'ETag': etag,
        'Cache-Control': _BLOG_CACHE_CONTROL,
        'Vary': 'Origin, Accept-Encoding',
    }
    return response


def _query(event: Dict[str, Any], name: str, default: str = '') -> str:
    params = event.get('queryStringParameters') or {}
    return str(params.get(name, default) or default)


def _claim(body: Dict[str, Any], actor: str, action: str, origin: str):
    key = make_admin_idempotency_key(actor, action, body_hash(body))
    try:
        claimed = claim_admin_action(key, actor, action)
    except Exception:
        logger.exception('SEO Admin action claim failed')
        return _response(503, {
            'ok': False,
            'error': 'Mutation guard unavailable; no action was performed',
        }, origin)
    if not claimed:
        return _response(409, {
            'ok': False,
            'error': 'This Admin action was already submitted',
        }, origin)
    return None


def _slug(value: Any) -> str:
    slug = str(value or '').strip()
    if not slug:
        raise ValueError('path is required')
    return slug if slug.startswith('/') else '/' + slug


def _cost(input_tokens: int, output_tokens: int) -> float:
    value = (input_tokens / 1_000_000) * INPUT_COST_PER_M
    value += (output_tokens / 1_000_000) * OUTPUT_COST_PER_M
    return round(value, 4)


def _put_error_log(slug: str, page_type: str, started: float) -> None:
    storage.put_record({
        'id': f'log_{uuid.uuid4().hex}',
        'recordType': 'log',
        'createdAt': storage.now_iso(),
        'slug': slug,
        'blogSlug': slug,
        'pageType': page_type,
        'provider': 'aws-bedrock',
        'model': ai.PRIMARY_MODEL,
        'status': 'error',
        'errorMessage': 'SEO generation failed',
        'inputTokens': 0,
        'outputTokens': 0,
        'costEstimate': 0,
        'durationMs': int((time.monotonic() - started) * 1000),
    })


def _run_audit(
    page: Dict[str, Any], page_type: str, force: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Generate an SEO audit, or return the stored one when the content has not changed.

    THE HASH GATE IS THE COST CONTROL. This used to call ai.invoke_seo unconditionally, so
    auditing a post twice with nothing changed paid Bedrock twice for the same answer. The
    repository already hashes content for this purpose in blog_pipeline, blog_gate and
    blog_sources; the SEO audit path was the one place that did not.

    Placed HERE rather than in the two callers because _blog_audit and _page_audit both funnel
    through this function - one gate covers both, and a third caller added later inherits it.

    `force` re-runs deliberately, because the hash covers the CONTENT and not the prompt: when
    ai.py's system prompt or model chain changes, identical content should be re-auditable
    without editing the post, which is the source mutation this architecture forbids.

    NOTHING ABOUT SOURCE CONTENT IS WRITTEN. The hash is computed from the source and stored on
    the derived audit record. No updatedAt is touched: a freshness check that stamped what it
    checked would corrupt sitemap lastmod and make every check look like an edit.
    """
    started = time.monotonic()
    slug = str(page['slug'])
    try:
        # A failure to read history must not block an audit - it degrades to "run it", which is
        # the previous behaviour, rather than to an error.
        try:
            history = storage.list_slug_records(slug)
        except Exception:  # noqa: BLE001
            logger.exception('audit history read failed for %s; auditing without the hash gate', slug)
            history = []
        content_hash, reusable = seo_freshness.decide(page, page_type, history, force)
        if reusable:
            logger.info(json.dumps({
                'event': 'seo_audit_skipped', 'slug': slug, 'pageType': page_type,
                'auditId': reusable.get('id'), 'reason': 'unchanged_source_hash',
            }))
            return reusable, seo_freshness.skip_log(reusable, page_type)
        generated = ai.invoke_seo(page, page_type)
        result = generated['result']
        created_at = storage.now_iso()
        duration_ms = int((time.monotonic() - started) * 1000)
        input_tokens = int(generated.get('inputTokens', 0))
        output_tokens = int(generated.get('outputTokens', 0))
        estimate = _cost(input_tokens, output_tokens)
        log = {
            'id': f'log_{uuid.uuid4().hex}',
            'recordType': 'log',
            'createdAt': created_at,
            'slug': slug,
            'blogSlug': slug,
            'pageType': page_type,
            'provider': 'aws-bedrock',
            'model': generated.get('model', ai.PRIMARY_MODEL),
            'status': 'success',
            'inputTokens': input_tokens,
            'outputTokens': output_tokens,
            'costEstimate': estimate,
            'durationMs': duration_ms,
        }
        audit = {
            'id': f'audit_{uuid.uuid4().hex}',
            'recordType': 'audit',
            'createdAt': created_at,
            'updatedAt': created_at,
            'slug': slug,
            'blogSlug': slug,
            'blogPostId': page.get('id', ''),
            'blogTitle': page.get('title') or page.get('name') or slug,
            'pageType': page_type,
            'currentSeoTitle': page.get('seoTitle') or page.get('currentSeoTitle') or page.get('title', ''),
            'suggestedSeoTitle': result.get('seoTitle', ''),
            'currentMetaDescription': page.get('metaDescription', ''),
            'suggestedMetaDescription': result.get('metaDescription', ''),
            'focusKeyword': result.get('focusKeyword', ''),
            'secondaryKeywords': result.get('secondaryKeywords', []),
            'suggestedTags': result.get('categoryTags', []),
            'suggestedJsonLd': result.get('jsonLd', {}),
            'internalLinkSuggestions': result.get('internalLinks', []),
            'imageAltSuggestions': result.get('imageAltText', []),
            'seoScoreBefore': result.get('seoScoreBefore', 0),
            'seoScoreAfter': result.get('seoScoreAfter', 0),
            'scoreBreakdown': result.get('scoreBreakdown', {}),
            'warnings': result.get('warnings', []),
            'fullAiResponse': result,
            'aiProvider': 'aws-bedrock',
            'aiModel': generated.get('model', ai.PRIMARY_MODEL),
            'status': 'pending_review',
            # The gate above reads this back. An audit without it is always re-run, which is the
            # correct behaviour for records written before the gate existed.
            'sourceHash': content_hash,
        }
        storage.put_record(log)
        storage.put_record(audit)
        return audit, {
            'inputTokens': input_tokens,
            'outputTokens': output_tokens,
            'costEstimate': estimate,
            'durationMs': duration_ms,
            'model': log['model'],
        }
    except Exception:
        logger.exception('SEO generation failed')
        try:
            _put_error_log(slug, page_type, started)
        except Exception:
            logger.exception('SEO error log persistence failed')
        raise


def _blog_audit(body: Dict[str, Any], actor: str, origin: str):
    slug = str(body.get('slug', '')).strip()
    if not slug:
        raise ValueError('slug is required')
    post = storage.get_blog_post(slug)
    if not post:
        raise LookupError('Blog post not found')
    return _guarded_audit(post, 'blog', body, actor, origin)


def _guarded_audit(page, page_type, body, actor, origin):
    # Audits write derived results, not source/payment state. A fenced lease prevents
    # concurrent model calls without treating a failed audit as a completed mutation.
    action = f'seo.{page_type}.audit.lease'
    key = make_admin_idempotency_key(actor, action, body_hash({
        'path': page.get('slug'), 'sourceHash': seo_freshness.source_hash(page, page_type),
    }))
    token = uuid.uuid4().hex
    try:
        claimed = claim_admin_action(key, actor, action, ttl_seconds=1800, claim_token=token)
    except Exception:
        return _response(503, {'ok': False, 'error': 'Audit guard unavailable'}, origin)
    if not claimed:
        return _response(409, {'ok': False, 'error': 'This audit is already running'}, origin)
    try:
        audit, log = _run_audit(page, page_type, force=bool(body.get('force')))
        return _response(200, {'ok': True, 'audit': audit, 'log': log}, origin)
    finally:
        try:
            release_admin_audit(key, token)
        except Exception:
            logger.exception('Audit lease release failed; lease expiry permits retry')


def _page_audit(body: Dict[str, Any], actor: str, origin: str):
    slug = _slug(body.get('path'))
    page_type = str(body.get('pageType') or 'page').strip().lower()
    stored_type = page_type if page_type in {'product', 'system'} else 'page'
    current = page_catalog.page_seo(slug)
    page = {
        **body,
        **current,
        'slug': slug,
        'name': str(body.get('name') or slug.lstrip('/').replace('-', ' ')),
        'title': current.get('title') or body.get('name') or slug,
        'url': page_catalog.SITE_BASE + slug,
        'currentSeoTitle': current.get('title', ''),
    }
    return _guarded_audit(page, stored_type, body, actor, origin)


def _page_clean(body: Dict[str, Any], actor: str, origin: str):
    slug = _slug(body.get('path'))
    duplicate = _claim({**body, 'path': slug}, actor, 'seo.page.clean', origin)
    if duplicate:
        return duplicate
    removed = storage.delete_slug_audits(slug)
    current = page_catalog.page_seo(slug)
    message = (
        f'Removed {removed} previous audit(s) for {slug}. Page is now clean for fresh audit.'
        if removed else f'No previous audits found for {slug}. Page is already clean.'
    )
    return _response(200, {
        'ok': True,
        'slug': slug,
        'name': body.get('name') or slug,
        'pageType': body.get('pageType') or 'site',
        'cleaned': {'auditsRemoved': removed, 'message': message},
        'currentSeo': current,
    }, origin)


def _review(body: Dict[str, Any], actor: str, origin: str):
    audit_id = str(body.get('auditId', '')).strip()
    action = str(body.get('action', '')).strip().lower()
    if not audit_id or action not in {'approve', 'reject', 'apply'}:
        raise ValueError('auditId and action (approve, reject, or apply) required')
    audit = storage.get_audit(audit_id)
    if not audit:
        raise LookupError('Audit not found')
    if action in {'approve', 'reject'}:
        target = 'approved' if action == 'approve' else 'rejected'
        updated = storage.transition_audit(
            audit_id, ['pending_review'], target, actor,
        )
        if not updated:
            return _response(409, {'ok': False, 'error': 'Audit state changed; refresh and retry'}, origin)
        return _response(200, {'ok': True, 'audit': updated}, origin)
    if audit.get('pageType') != 'blog':
        return _response(501, {
            'ok': False,
            'error': 'Applying SEO is currently supported for blog posts only',
        }, origin)
    if audit.get('status') != 'approved':
        return _response(409, {'ok': False, 'error': 'Audit must be approved before apply'}, origin)
    duplicate = _claim({'auditId': audit_id}, actor, 'seo.blog.apply', origin)
    if duplicate:
        return duplicate
    applying = storage.transition_audit(audit_id, ['approved'], 'applying', actor)
    if not applying:
        return _response(409, {'ok': False, 'error': 'Audit state changed; refresh and retry'}, origin)
    try:
        storage.apply_blog_audit(applying, actor)
    except Exception:
        logger.exception('AWS blog SEO apply failed')
        try:
            restored = storage.transition_audit(
                audit_id, ['applying'], 'approved', actor,
                {'applicationError': 'Blog SEO apply failed'},
            )
        except Exception:
            logger.exception('Failed to restore SEO audit after blog apply failure')
            restored = None
        if not restored:
            logger.error('SEO audit state is unconfirmed after blog apply failure')
            return _response(502, {
                'ok': False,
                'error': 'Blog SEO apply failed; audit state could not be confirmed. Refresh before retrying',
                'stateUnconfirmed': True,
            }, origin)
        return _response(502, {'ok': False, 'error': 'Blog SEO apply failed; audit remains approved'}, origin)
    applied_at = storage.now_iso()
    updated = storage.transition_audit(
        audit_id, ['applying'], 'applied', actor,
        {'appliedAt': applied_at, 'applicationError': ''},
    )
    if not updated:
        return _response(500, {
            'ok': False,
            'error': 'SEO was applied but final audit status persistence failed',
            'applied': True,
        }, origin)
    return _response(200, {'ok': True, 'audit': updated, 'applied': True}, origin)


def _route_get(path: str, event: Dict[str, Any], origin: str):
    if path.endswith('/blog-posts'):
        posts = storage.list_blog_posts()
        return _response(200, {'ok': True, 'posts': posts, 'total': len(posts)}, origin)
    if path.endswith('/blog-create'):
        return _response(200, {'ok': True, **storage.blog_form_options()}, origin)
    if path.endswith('/seo-logs'):
        record_type = 'log' if _query(event, 'type', 'audits') == 'logs' else 'audit'
        scope = _query(event, 'scope')
        records = storage.list_records(record_type, scope)
        key = 'logs' if record_type == 'log' else 'audits'
        return _response(200, {'ok': True, key: records}, origin)
    if path.endswith('/site-pages'):
        pages = page_catalog.list_site_pages()
        return _response(200, {'ok': True, 'pages': pages, 'total': len(pages)}, origin)
    if path.endswith('/product-pages'):
        products = page_catalog.list_products()
        return _response(200, {'ok': True, 'products': products, 'total': len(products)}, origin)
    return _response(404, {'ok': False, 'error': 'SEO route not found'}, origin)


def _route_post(path: str, body: Dict[str, Any], actor: str, origin: str):
    if path.endswith('/blog-update'):
        slug = str(body.get('slug') or '').strip()
        if not slug:
            raise ValueError('slug required')
        post = body.get('post') if isinstance(body.get('post'), dict) else body
        expected_post_id = str(body.get('expectedPostId') or body.get('postId') or '').strip()
        duplicate = _claim(
            {'slug': slug, 'expectedPostId': expected_post_id, 'post': post},
            actor, 'seo.blog.update', origin)
        if duplicate:
            return duplicate
        return _response(200, {
            'ok': True,
            **storage.update_blog_post(
                slug, post, actor, expected_post_id=expected_post_id),
        }, origin)

    if path.endswith('/blog-create'):
        duplicate = _claim(body, actor, 'seo.blog.create', origin)
        if duplicate:
            return duplicate
        return _response(200, {'ok': True, **storage.create_blog_post(body, actor)}, origin)
    if path.endswith('/seo-clean'):
        slug = str(body.get('slug', '')).strip()
        if not slug:
            raise ValueError('slug required')
        duplicate = _claim({'slug': slug}, actor, 'seo.blog.clean', origin)
        if duplicate:
            return duplicate
        return _response(200, {'ok': True, **storage.clean_blog_post(slug, actor)}, origin)
    if path.endswith('/ai-seo-audit'):
        return _blog_audit(body, actor, origin)
    if path.endswith('/page-audit'):
        return _page_audit(body, actor, origin)
    if path.endswith('/page-clean'):
        return _page_clean(body, actor, origin)
    if path.endswith('/seo-approve'):
        return _review(body, actor, origin)
    if path.endswith('/cache-purge'):
        logger.info(json.dumps({'event': 'seo_native_cache_purge_noop', 'actor': actor}))
        return _response(200, {
            'ok': True,
            'purged': False,
            'note': 'Native blog reads have no provider cache to purge.',
        }, origin)
    return _response(404, {'ok': False, 'error': 'SEO route not found'}, origin)
def handler(event: Dict[str, Any], context: Optional[Any]):
    # ── The scheduled derived-SEO freshness check ────────────────────────────────
    #
    # Checked among the non-HTTP branches for the same reason the blog worker is: it arrives
    # from an EventBridge Scheduler target via InvocationType='Event' and carries no
    # requestContext. NOT AN UNAUTHENTICATED HOLE - an API Gateway request delivers its payload
    # as a JSON string under `body`, never as a top-level `seoFreshness` key, and the guard also
    # requires the requestContext to be absent, so the only way in is lambda:InvokeFunction,
    # which is IAM-gated. The refresh is read-only against source content and writes only
    # derived recordType='seo' records.
    if seo_refresh.is_freshness_event(event):
        try:
            return seo_refresh.run(event)
        except Exception:
            logger.exception('seo refresh sweep failed')
            # Returned, not raised: an async invoke that raises is retried by Lambda, and a
            # deterministic failure (e.g. upstream down) would just retry into the same wall.
            # The next scheduled run picks it up.
            return {'event': 'seo_freshness_run', 'error': 'sweep failed', 'refreshed': 0}

    origin = extract_origin(event)
    method, path = _method_path(event)
    if method == 'OPTIONS':
        return options_response(origin)

    # Public read surface for the headless site. The AWS blog store is authoritative;
    # drafts, audits, logs and Admin mutation routes remain protected.
    if method == 'GET' and (path.endswith('/blog-public') or '/blog-public/' in path):
        # A failed native read is surfaced rather than publishing an incomplete static build.
        try:
            if '/blog-public/' in path:
                slug = path.split('/blog-public/', 1)[1].strip('/')
                # AWS is the sole source of truth; see blog_source.py.
                post = blog_source.get_blog_post_by_slug(slug)
                if not post:
                    return _response(404, {'ok': False, 'error': 'Blog post not found'}, origin)
                # APPROVED FAQ IS ATTACHED HERE, and only on the single-post route.
                #
                # This is the seam between the CMS and the published page: the static export
                # builds by fetching this endpoint per post, and src/pages/post/[slug].tsx
                # already renders post.jsonLd.faqSchema. So the frontend needs no change - the
                # approved FAQ lives in an audit record, and this is where it joins the post.
                #
                # NOT ON THE LIST ROUTE. faqSchema is read by the post page alone; the index
                # renders cards from seven fields and never touches it. Enriching the list would
                # add a DynamoDB query per post to a response that already carries 1279 of them,
                # for output nothing consumes.
                #
                # THE QUERY IS GUARDED SEPARATELY from faq.attach's own guard. attach() cannot
                # raise, but list_slug_records talks to DynamoDB and can - and a post must still
                # be served when the SEO table is unreachable. An absent FAQ is invisible; a 503
                # on a published article is not.
                try:
                    post = faq.attach(post, storage.list_slug_records(slug))
                except Exception:  # noqa: BLE001
                    logger.exception('faq lookup failed for slug %s', slug)
                return _cacheable(200, {'ok': True, 'post': post}, origin, event)
            posts = blog_source.list_blog_posts()
            fields = _projection(event)
            return _cacheable(200, {
                'ok': True,
                'posts': _project(posts, fields),
                'total': len(posts),
            }, origin, event)
        except RuntimeError:
            logger.exception('public blog read failed')
            return _response(503, {
                'ok': False,
                'error': 'The blog index is temporarily unavailable',
            }, origin)

    auth_result = require_auth(event, required_role='Admin')
    if auth_result is not None:
        return auth_result
    actor = _actor(event)
    if not actor:
        return _response(403, {'ok': False, 'error': 'Admin identity required'}, origin)
    try:
        if method == 'GET':
            return _route_get(path, event, origin)
        if method == 'POST':
            return _route_post(path, _body(event), actor, origin)
        return _response(405, {'ok': False, 'error': 'Method not allowed'}, origin)
    except ValueError as error:
        return _response(400, {'ok': False, 'error': str(error)}, origin)
    except LookupError as error:
        return _response(404, {'ok': False, 'error': str(error)}, origin)
    except PermissionError as error:
        # A disabled cost flag. 409 rather than 403: the caller is authorised, the
        # capability is switched off, and a 403 would send an Admin looking at their own
        # permissions instead of at the flag.
        return _response(409, {'ok': False, 'error': str(error)}, origin)
    except Exception:
        logger.exception('SEO tools request failed')
        return _response(500, {'ok': False, 'error': 'SEO operation failed'}, origin)
