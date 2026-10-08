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
import blog_analysis
import blog_batches
import blog_draft
import blog_gate
import blog_publish
import blog_qa
import blog_queue
import blog_repetition
import blog_sources
import blog_templates
import blog_verify
import faq
import seo_freshness
import seo_refresh
import storage
import wix

#: The two categories the live site actually has. Imported from the quality gate so the
#: Lambda, the CLI and the admin page cannot disagree about what is acceptable -
#: `src/test/BlogStudioContract.test.ts` asserts the page agrees with the same list.
try:  # pragma: no cover - exercised implicitly by every blog-source route
    import blog_quality_v2 as _quality
    BLOG_CATEGORIES = _quality.CATEGORIES
except ImportError:  # pragma: no cover - a package built without the gate
    _quality = None
    BLOG_CATEGORIES = ('Conversations', 'Gastronomy')

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
# _blog_view might add.
_PUBLIC_POST_FIELDS = frozenset({
    'slug', 'title', 'excerpt', 'category', 'publishedDate', 'modifiedDate',
    'authorName', 'coverImage', 'url', 'tags', 'seoTitle', 'metaDescription',
    'focusKeyword', 'keywords', 'hashtags', 'robots', 'jsonLd', 'id',
})

# Five minutes at the edge, matching the Lambda-side TTL in wix.py so the two layers
# cannot disagree about how stale the corpus may be. stale-while-revalidate lets a CDN
# serve the old copy while it refreshes, which is the correct trade for a blog index.
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
    The fix for the volume is the memo in src/lib/public-blog.ts and the per-sandbox
    caches in wix.py; this is the third layer, not the first.

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
    current = wix.page_seo(slug)
    page = {
        **body,
        **current,
        'slug': slug,
        'name': str(body.get('name') or slug.lstrip('/').replace('-', ' ')),
        'title': current.get('title') or body.get('name') or slug,
        'url': wix.SITE_BASE + slug,
        'currentSeoTitle': current.get('title', ''),
    }
    return _guarded_audit(page, stored_type, body, actor, origin)


def _page_clean(body: Dict[str, Any], actor: str, origin: str):
    slug = _slug(body.get('path'))
    duplicate = _claim({**body, 'path': slug}, actor, 'seo.page.clean', origin)
    if duplicate:
        return duplicate
    removed = storage.delete_slug_audits(slug)
    current = wix.page_seo(slug)
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


def _wix_writes_disabled() -> bool:
    """Read through `wix_guard` rather than the env var directly.

    There must be ONE definition of "are Wix credentials switched off" - the defect that module
    exists to close was a flag read in some places and not others, which produced a switch that
    disabled the store and left blog publishing running.
    """
    try:
        from lambda_utils.wix_guard import credentials_disabled
        return credentials_disabled()
    except ImportError:  # pragma: no cover - wix_guard ships in every package
        return False


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
    if '/blog-batches/' in path:
        # One batch with its rollup and its sources. `?limit=` bounds the source list for a
        # UI page; absent, it returns all of them, which is the point of the batch index.
        batch_id = path.split('/blog-batches/', 1)[1].strip('/')
        limit = int(_query(event, 'limit', '0') or 0)
        return _response(200, {
            'ok': True, 'batch': blog_batches.detail(batch_id, source_limit=limit),
        }, origin)
    if path.endswith('/blog-batches'):
        # `?rollup=none` skips the per-batch source count, which is a real cost switch: each
        # rollup pages that batch's sources, so 50 batches with rollups is 50 index queries.
        with_rollup = _query(event, 'rollup', 'full') != 'none'
        batches = blog_batches.list_batches(with_rollup=with_rollup)
        return _response(200, {
            'ok': True, 'batches': batches, 'total': len(batches),
            'categories': list(BLOG_CATEGORIES),
            'articleClasses': list(_quality.ARTICLE_CLASSES) if _quality else [],
            'batchStatuses': list(blog_batches.BATCH_STATUSES),
        }, origin)
    if '/blog-verify/' in path:
        return _response(200, {
            'ok': True,
            'run': blog_verify.detail(path.split('/blog-verify/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-verify'):
        source_ref = _query(event, 'sourceId')
        batch_ref = _query(event, 'batchId')
        payload: Dict[str, Any] = {
            'ok': True,
            # The assertion list, so the UI renders the thirteen by name rather than hard-coding
            # a list that can fall out of step with the ones that actually run.
            'assertions': [{'assertion': name, 'description': description}
                           for name, description in blog_verify.ASSERTIONS],
        }
        if source_ref:
            payload['runs'] = [blog_verify.view(row)
                               for row in blog_verify.history(source_ref)]
            try:
                payload['expected'] = blog_verify.expectation(source_ref)
            except LookupError:
                # The RUNS outlive the source. A verification record is the evidence that an
                # article was checked, so a deleted source must not take the history with it -
                # answering 404 for the whole payload would do exactly that.
                payload['expected'] = {}
                payload['expectationNote'] = 'the source record no longer exists'
        if batch_ref:
            payload['batchState'] = blog_verify.batch_verify_state(batch_ref)
            # Published and unchecked: live articles nobody has looked at.
            payload['pending'] = blog_verify.pending_verification(batch_ref)
        return _response(200, payload, origin)
    if '/blog-publish/' in path:
        return _response(200, {
            'ok': True,
            'job': blog_publish.detail(path.split('/blog-publish/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-publish'):
        # `?batchId=` answers the release page's real question: which sources could be released
        # right now, AND why each of the others cannot. Filtering to the eligible rows leaves an
        # operator with no idea why the other forty are missing.
        batch_ref = _query(event, 'batchId')
        payload: Dict[str, Any] = {
            'ok': True,
            'jobStatuses': list(blog_publish.JOB_STATUSES),
            'queue': blog_publish.queue(status=_query(event, 'status'),
                                        limit=int(_query(event, 'limit', '0') or 0)),
            # Whether a publish would be refused before it is attempted. An operator looking at
            # a queue needs to know the writes are switched off without pressing anything.
            'wixWritesDisabled': _wix_writes_disabled(),
        }
        if batch_ref:
            payload['batchState'] = blog_publish.batch_publish_state(batch_ref)
            payload['candidates'] = blog_publish.releasable_in_batch(batch_ref)
        return _response(200, payload, origin)
    if '/blog-repetition/' in path:
        return _response(200, {
            'ok': True,
            'run': blog_repetition.detail(path.split('/blog-repetition/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-repetition'):
        batch_ref = _query(event, 'batchId')
        if not batch_ref:
            raise ValueError('batchId is required; repetition is a property of a collection')
        return _response(200, {
            'ok': True,
            'state': blog_repetition.batch_state(batch_ref),
            'runs': [blog_repetition.view(row)
                     for row in blog_repetition.history(batch_ref)],
            'thresholds': {
                'pairBody': blog_repetition.PAIR_BODY,
                'pairBodyNearDuplicate': blog_repetition.PAIR_BODY_NEAR_DUPLICATE,
                'shapeNoticeable': blog_repetition.SHAPE_NOTICEABLE,
                'shapeDominant': blog_repetition.SHAPE_DOMINANT,
                'minCollection': blog_repetition.MIN_COLLECTION,
            },
        }, origin)
    if '/blog-qa/' in path:
        # One run with its full report, proxied from S3 for the same reason the analysis
        # evidence is: the prefix is public and nothing should hand out a URL to it.
        return _response(200, {
            'ok': True,
            'run': blog_qa.run_detail(path.split('/blog-qa/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-qa'):
        source_ref = _query(event, 'sourceId')
        batch_ref = _query(event, 'batchId')
        payload: Dict[str, Any] = {'ok': True, 'humanGates': list(blog_qa.human_gates()),
                                   'gateAnswers': list(blog_qa.GATE_ANSWERS)}
        if source_ref:
            payload['state'] = blog_qa.source_state(source_ref)
            payload['runs'] = [blog_qa.run_view(row)
                               for row in blog_qa.run_history(source_ref)]
            payload['signoffs'] = [blog_qa.signoff_view(row)
                                   for row in blog_qa.signoff_history(source_ref)]
        if batch_ref:
            payload['batchState'] = blog_qa.batch_qa_state(batch_ref)
        if not source_ref and not batch_ref:
            # The corpus coverage on its own, which is the one thing worth reading without
            # naming an article: a QA run is only worth what this reports.
            payload['corpus'] = blog_gate.corpus_state()
        return _response(200, payload, origin)
    if '/blog-templates/' in path:
        # `?history=1` returns every version of the family, which is the audit trail an
        # article's recorded `templateVersion` points into.
        reference = path.split('/blog-templates/', 1)[1].strip('/')
        if _query(event, 'history'):
            versions = blog_templates.history(reference)
            return _response(200, {
                'ok': True,
                'templateId': blog_templates.family_id(reference),
                'versions': [blog_templates.view(row) for row in versions],
            }, origin)
        template = blog_templates.get(reference) or blog_templates.resolve(reference)
        if not template:
            return _response(404, {'ok': False, 'error': 'Unknown template'}, origin)
        return _response(200, {
            'ok': True, 'template': blog_templates.view(template),
            # Whether this exact version may still be edited in place, and by implication
            # whether an edit will fork it. Derived from published articles, not a flag.
            'locked': blog_templates.locked(template['templateId'],
                                            int(template['version'])),
        }, origin)
    if path.endswith('/blog-templates'):
        templates = blog_templates.list_templates(
            include_deprecated=bool(_query(event, 'deprecated')))
        return _response(200, {
            'ok': True, 'templates': templates, 'total': len(templates),
            'anyCategory': blog_templates.ANY_CATEGORY,
            'categories': list(BLOG_CATEGORIES),
        }, origin)
    if '/blog-analysis/' in path:
        # One analysis with its evidence. The evidence is PROXIED through this authenticated
        # route rather than linked: the prefix is on the public root, so returning a URL would
        # hand out the file to anyone it was forwarded to.
        return _response(200, {
            'ok': True,
            'analysis': blog_analysis.detail(path.split('/blog-analysis/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-analysis'):
        # `?sourceId=` gives one source's version history; `?batchId=` gives how much of a
        # wave has actually been read. Neither is derived from a counter.
        source_ref = _query(event, 'sourceId')
        batch_ref = _query(event, 'batchId')
        payload: Dict[str, Any] = {'ok': True}
        if source_ref:
            payload['history'] = [blog_analysis.view(row)
                                  for row in blog_analysis.history(source_ref)]
        if batch_ref:
            payload['reviewState'] = blog_analysis.batch_review_state(batch_ref)
            payload['pendingAnalysis'] = blog_analysis.pending_analysis(batch_ref)
        if not source_ref and not batch_ref:
            raise ValueError('sourceId or batchId is required')
        return _response(200, payload, origin)
    if '/blog-sources/' in path:
        # One source with its extract and draft. Split out from the list route because the
        # extract is hundreds of kB and returning it for 200 sources would make the list
        # response megabytes.
        return _response(200, {
            'ok': True,
            'source': blog_sources.source_detail(path.split('/blog-sources/', 1)[1].strip('/')),
        }, origin)
    if path.endswith('/blog-sources'):
        # `?batchId=` scopes the listing through the batch index rather than reading every
        # source in the system, which is what makes a thousand-source batch viewable.
        return _response(200, {
            'ok': True,
            'categories': list(BLOG_CATEGORIES),
            'articleClasses': list(_quality.ARTICLE_CLASSES) if _quality else [],
            'humanGates': list(_quality.HUMAN_GATES) if _quality else [],
            'aiDraftEnabled': blog_draft.enabled(),
            'maxSourceBytes': blog_sources.MAX_SOURCE_BYTES,
            # Queue and DLQ depth beside the source list, because "nothing is progressing" and
            # "three documents are dead-lettered" look identical from the statuses alone.
            'queue': blog_queue.depth(),
            **blog_sources.status_report(
                limit=int(_query(event, 'limit', '0') or 0),
                batch_id=_query(event, 'batchId')),
        }, origin)
    if path.endswith('/site-pages'):
        pages = wix.list_site_pages()
        return _response(200, {'ok': True, 'pages': pages, 'total': len(pages)}, origin)
    if path.endswith('/product-pages'):
        products = wix.list_products()
        return _response(200, {'ok': True, 'products': products, 'total': len(products)}, origin)
    return _response(404, {'ok': False, 'error': 'SEO route not found'}, origin)


def _route_post(path: str, body: Dict[str, Any], actor: str, origin: str):
    # ── Blog source intake ──────────────────────────────────────────────────────
    #
    # All four of these sit inside _route_post, which runs AFTER the require_auth call in
    # `handler`. That placement is load-bearing for the route-auth gate: the API already
    # carries `ANY /seo-tools/{proxy+}`, so these add no new API Gateway route key and
    # `audit_route_auth.py` continues to classify the whole surface as
    # handler-authenticated on the strength of that one require_auth.
    if path.endswith('/blog-batches/close'):
        batch_id = str(body.get('batchId') or '').strip()
        if not batch_id:
            raise ValueError('batchId is required')
        return _response(200, {'ok': True, **blog_batches.close(batch_id, actor)}, origin)
    if path.endswith('/blog-batches'):
        # Claimed: a double-submitted form would otherwise create two batches with the same
        # name and split one wave's sources across both.
        duplicate = _claim(body, actor, 'seo.blogbatch.create', origin)
        if duplicate:
            return duplicate
        return _response(200, {'ok': True, **blog_batches.create(
            body, actor, tuple(BLOG_CATEGORIES),
            tuple(_quality.ARTICLE_CLASSES) if _quality else ('ARCHIVE_DERIVED',),
        )}, origin)

    if path.endswith('/blog-verify'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        # Read-only, and NOT idempotency-claimed: re-verifying is exactly what an operator does
        # after fixing something, and each run is its own record of a moment.
        return _response(200, {'ok': True, **blog_verify.run(source_id, actor)}, origin)

    if path.endswith('/blog-publish/release'):
        # Records a decision. Performs NO Wix write - publishing is a separate call, because
        # section 38 requires that processing completion never automatically mean publishing.
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        # NOT idempotency-claimed, because `release` is idempotent in the way that matters: a
        # second release resolves to the job that already exists. A 409 would leave the operator
        # unsure whether the first one landed, which is worse on exactly this route.
        return _response(200, {'ok': True, **blog_publish.release(source_id, actor)}, origin)
    if path.endswith('/blog-publish/withdraw'):
        job_id = str(body.get('jobId') or '').strip()
        if not job_id:
            raise ValueError('jobId is required')
        return _response(200, {'ok': True, **blog_publish.unrelease(
            job_id, str(body.get('reason') or ''), actor)}, origin)
    if path.endswith('/blog-publish'):
        job_id = str(body.get('jobId') or '').strip()
        if not job_id:
            raise ValueError('jobId is required')
        # DELIBERATELY NOT IDEMPOTENCY-CLAIMED, and this is the one route where that looks
        # wrong. It is the only Wix mutation in the system, so a claim is the obvious reflex.
        #
        # It was there, and the first live run caught it doing harm. The claim keys on the
        # request body, and the body is just `{jobId}` - so the FIRST attempt records the claim
        # whatever its outcome, and a later legitimate retry of the same job answers 409. The run
        # hit exactly that: a publish correctly refused because the article had been edited, then
        # the operator restored the body, re-signed, pressed Publish again, and got "This Admin
        # action was already submitted" with no way forward.
        #
        # The conditional QUEUED -> PUBLISHING claim inside `publish` is the real guard and it is
        # strictly better, because it is tied to the JOB'S STATE rather than to a request shape.
        # Two simultaneous submits both read QUEUED, both call it, one wins the conditional
        # write and the other returns "another publisher holds this job" having written nothing.
        # A body-hash claim adds no safety on top of that and costs a retry that has to work.
        return _response(200, {'ok': True, **blog_publish.publish(job_id, actor)}, origin)

    if path.endswith('/blog-repetition'):
        batch_id = str(body.get('batchId') or '').strip()
        if not batch_id:
            raise ValueError('batchId is required')
        return _response(200, {
            'ok': True, **blog_repetition.run(batch_id, actor),
        }, origin)

    if path.endswith('/blog-qa/sign-off'):
        # The ONLY route that can make READY_TO_PUBLISH reachable. It does not publish, and no
        # model-writable field reaches it - `gate` is absent from blog_draft.WRITABLE_FIELDS.
        return _response(200, {'ok': True, **blog_qa.sign_off(body, actor)}, origin)
    if path.endswith('/blog-qa/revoke'):
        signoff_ref = str(body.get('signoffId') or '').strip()
        if not signoff_ref:
            raise ValueError('signoffId is required')
        return _response(200, {'ok': True, **blog_qa.revoke(
            signoff_ref, str(body.get('reason') or ''), actor)}, origin)
    if path.endswith('/blog-qa'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        # NOT idempotency-claimed. A QA run is a cheap, deliberately repeatable record - it
        # reads the article and applies rules, with no model call - and an operator must be able
        # to re-run it immediately after an edit, which is exactly when a 409 would bite.
        return _response(200, {'ok': True, **blog_qa.run(source_id, actor)}, origin)

    if path.endswith('/blog-templates/assign'):
        return _response(200, {'ok': True, **blog_templates.assign(
            str(body.get('sourceId') or '').strip(),
            str(body.get('templateId') or '').strip(),
            body.get('version') or 0, actor)}, origin)
    if path.endswith('/blog-templates/deprecate'):
        record_id = str(body.get('recordId') or '').strip()
        if not record_id:
            raise ValueError('recordId is required, naming the exact version')
        return _response(200, {'ok': True, **blog_templates.deprecate(record_id, actor)},
                         origin)
    if path.endswith('/blog-templates'):
        # NOT idempotency-claimed. `save` is itself idempotent in the way that matters: a
        # replayed edit of an unlocked version writes the same fields again, and a replayed
        # edit of a LOCKED version forks - which is the correct outcome either way, whereas a
        # 409 would leave the operator unsure which of the two happened.
        return _response(200, {'ok': True, **blog_templates.save(
            body, actor, tuple(BLOG_CATEGORIES),
            tuple(_quality.ARTICLE_CLASSES) if _quality else ('ARCHIVE_DERIVED',),
        )}, origin)

    if path.endswith('/blog-analysis/review'):
        # The ONLY route that can write `sourceReviewedFully`, and it insists the reviewer
        # names the analysis version they read. No model-writable field reaches here.
        return _response(200, {
            'ok': True, **blog_analysis.record_review(body, actor),
        }, origin)
    if path.endswith('/blog-analysis'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        # NOT idempotency-claimed. Analysis is deliberately versioned and cheap - it reads the
        # extract and runs regular expressions, with no model call - so a double submit
        # producing v2 is harmless, whereas a 409 would leave an operator unable to re-analyse
        # after a re-extraction, which is the one time they must be able to.
        return _response(200, {
            'ok': True, **blog_analysis.analyse(source_id, actor),
        }, origin)

    if path.endswith('/blog-sources/confirm'):
        # NO idempotency claim, deliberately. Confirm is naturally idempotent - it
        # head_objects each key and moves PENDING_UPLOAD to UPLOADED - and a claim would
        # make a legitimate retry after a dropped response return 409 with the sources
        # still unconfirmed.
        return _response(200, {'ok': True, **blog_sources.confirm(body, actor)}, origin)
    if path.endswith('/blog-sources/drain'):
        # RECONCILIATION, not the steady-state path. The queue cannot find a source whose
        # message was never sent or was lost - a record written before the queue existed, a
        # SendMessageBatch that partially failed, a message that aged out. This asks the table
        # what is outstanding, which is the only check that does not assume the queue is right.
        requeue = str(body.get('requeue') or '').lower() not in ('0', 'false', 'no')
        outstanding = [str(row['id']) for row in blog_sources.pending_sources()]
        if requeue and outstanding:
            result = blog_queue.enqueue(outstanding, reason='drain')
            if not result['configured']:
                result = {'queued': 0, 'failed': 0, 'configured': False,
                          'workerStarted': blog_sources.start_worker('drain')}
            return _response(200, {'ok': True, 'outstanding': len(outstanding),
                                   'sourceIds': outstanding[:200], **result}, origin)
        return _response(200, {'ok': True, 'outstanding': len(outstanding),
                               'sourceIds': outstanding[:200], 'queued': 0,
                               'requeued': False}, origin)
    if path.endswith('/blog-sources/redrive'):
        # Explicit on purpose. A message reaches the DLQ after three failures, so the cause is
        # usually not transient - re-driving without reading the source's `error` first is how
        # an unreadable PDF cycles forever.
        return _response(200, {'ok': True, **blog_queue.redrive(
            int(body.get('limit') or 0))}, origin)
    if path.endswith('/blog-sources/retry'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        return _response(200, {'ok': True, **blog_sources.retry(source_id)}, origin)
    if path.endswith('/blog-sources'):
        duplicate = _claim(body, actor, 'seo.blogsource.register', origin)
        if duplicate:
            return duplicate
        return _response(200, {
            'ok': True, **blog_sources.register(body, actor, tuple(BLOG_CATEGORIES)),
        }, origin)
    if path.endswith('/blog-draft'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        # Claimed, because this one costs money per call and a double-submitted button
        # would pay twice for the same article.
        duplicate = _claim({'sourceId': source_id}, actor, 'seo.blogdraft.propose', origin)
        if duplicate:
            return duplicate
        return _response(200, {'ok': True, **blog_draft.propose(source_id, actor)}, origin)
    if path.endswith('/blog-draft-accept'):
        source_id = str(body.get('sourceId') or '').strip()
        if not source_id:
            raise ValueError('sourceId is required')
        return _response(200, {
            'ok': True, **blog_draft.apply_draft(source_id, body, actor),
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
        # A CACHE WITH NO PURGE IS AN OPERATIONAL TRAP, which is the whole reason this
        # route exists rather than the TTL standing alone. Blog content is authored in
        # Wix, OUTSIDE this system, so the person who just published a post has no other
        # way to make it appear before the 5-minute TTL expires - and the first thing they
        # would do is report the new post as missing.
        #
        # Admin-only and idempotent. It clears a per-sandbox dict, so the worst case is
        # that the next request to each warm sandbox re-fetches; there is nothing to
        # corrupt and nothing to roll back. No idempotency claim for the same reason -
        # purging twice is purging once.
        wix.clear_blog_cache()
        logger.info(json.dumps({'event': 'seo_blog_cache_purged', 'actor': actor}))
        return _response(200, {
            'ok': True,
            'purged': True,
            'note': ('Cleared in this execution environment. Other warm sandboxes expire '
                     'on their own TTL, so allow a few minutes for full consistency.'),
        }, origin)
    return _response(404, {'ok': False, 'error': 'SEO route not found'}, origin)


def handler(event: Dict[str, Any], context: Optional[Any]):
    # ── The SQS ingest consumer ──────────────────────────────────────────────────
    #
    # Checked FIRST, before HTTP handling and before the legacy sweep branch, because an SQS
    # batch is not an HTTP request and carries no requestContext at all.
    #
    # NOT AN UNAUTHENTICATED HOLE, for the same reason the worker branch below is not. An API
    # Gateway request cannot produce a top-level `Records` key - its payload arrives under
    # `body` as a JSON string - and `blog_queue.is_queue_event` additionally requires every
    # record to name `eventSource: aws:sqs`, which only the event source mapping can do. That
    # mapping is IAM-gated.
    #
    # The return value is the `batchItemFailures` shape, so ReportBatchItemFailures retries
    # only the messages that actually need it. Exceptions are caught inside `consume`: letting
    # one escape here would redeliver the whole batch, including the documents that succeeded.
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

    if blog_queue.is_queue_event(event):
        try:
            return blog_queue.consume(event)
        except Exception:
            logger.exception('blog ingest batch failed')
            # Report EVERY message as failed rather than swallowing the batch. A failure this
            # far out is infrastructural, so the messages should redeliver and eventually
            # dead-letter rather than vanish.
            return {'batchItemFailures': [
                {'itemIdentifier': str(record.get('messageId') or '')}
                for record in (event.get('Records') or [])
                if record.get('messageId')]}

    # ── The async extraction worker ──────────────────────────────────────────────
    #
    # Checked FIRST, before any HTTP handling, because this is not an HTTP request: it
    # arrives from `blog_sources.start_worker` via InvocationType='Event' and carries no
    # requestContext at all.
    #
    # THIS IS NOT AN UNAUTHENTICATED HOLE, and it is worth being explicit about why. There
    # is no API Gateway route that can produce `blogWorker` in the body - the routes are
    # `ANY /seo-tools` and `ANY /seo-tools/{proxy+}`, and an HTTP request arrives with its
    # payload under `body` as a JSON STRING, never as a top-level key on the event. So the
    # only way to reach this branch is `lambda:InvokeFunction` on this function, which is
    # IAM-gated and held by this function's own role. Same reasoning
    # `lambda_utils.middleware.require_auth` uses to skip internal invokes.
    #
    # The `not event.get('requestContext')` half is belt and braces: even if a future route
    # shape let a caller put arbitrary keys at the top level, an API Gateway event always
    # carries a requestContext, so this branch would still refuse it.
    if event.get('blogWorker') is True and not event.get('requestContext'):
        try:
            return blog_sources.run_worker(event)
        except Exception:
            logger.exception('blog source worker failed')
            # Returned rather than raised: an async invoke that raises is retried twice by
            # Lambda, and a source that fails deterministically would be extracted three
            # times. The per-source status already records the failure durably.
            return {'processed': 0, 'failed': 0, 'error': 'worker failed'}

    origin = extract_origin(event)
    method, path = _method_path(event)
    if method == 'OPTIONS':
        return options_response(origin)

    # Public read surface for the headless site. Wix Blog is the source of truth;
    # drafts, audits, logs and Admin mutation routes remain protected.
    if method == 'GET' and (path.endswith('/blog-public') or '/blog-public/' in path):
        # A FAILED UPSTREAM IS A 503, NOT A 500, and it says so in a Retry-After-able
        # shape. wix.py retries the retryable statuses once and serves a stale corpus
        # when it has one, so reaching this branch means the upstream is genuinely down
        # with nothing cached. generate-sitemap.js reads that distinction: it refuses to
        # write a sitemap rather than publishing one with the blog missing.
        try:
            if '/blog-public/' in path:
                slug = path.split('/blog-public/', 1)[1].strip('/')
                post = wix.get_blog_post_by_slug(slug)
                if not post:
                    return _response(404, {'ok': False, 'error': 'Blog post not found'}, origin)
                # APPROVED FAQ IS ATTACHED HERE, and only on the single-post route.
                #
                # This is the seam between the CMS and the published page: the static export
                # builds by fetching this endpoint per post, and src/pages/post/[slug].tsx
                # already renders post.jsonLd.faqSchema. So the frontend needs no change - the
                # chain existed end to end and was cut only by wix.py hardcoding jsonLd to {}.
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
            posts = wix.list_blog_posts()
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
