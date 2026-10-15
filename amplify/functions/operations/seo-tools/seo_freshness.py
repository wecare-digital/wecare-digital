"""Do not pay Bedrock twice for the same content.

THE LEAK THIS CLOSES. `_run_audit` called `ai.invoke_seo` unconditionally. Auditing a post,
then auditing it again an hour later with nothing changed, invoked the model a second time and
produced the same answer at the same price. Nothing compared the content first.

The repository already hashes content for exactly this purpose elsewhere -
`blog_pipeline.content_hash`, `blog_gate.body_sha256`, `blog_sources.sourceSha256`,
`blog_publish` - so change detection is an established pattern here and the SEO audit path was
the one place that skipped it.

    audit #1   hash differs (or absent)  ->  call the model, store the hash
    audit #2   hash matches              ->  return the stored audit, ZERO model calls
    audit #3   hash matches              ->  same
    content edited, audit #4             ->  hash differs, call the model

READ ONLY, AND THAT IS THE ENTIRE POINT OF HASHING RATHER THAN TIMESTAMPING. The hash is
computed FROM source content and stored on the DERIVED audit record. Source content is never
written, and in particular no `updatedAt` on a page or post is touched - a freshness check that
stamped the thing it checked would corrupt the sitemap's lastmod and make every check look like
an edit.

WHY NOT TRUST `updatedAt` ALONE. It is available on a post, and it is the wrong signal: a CMS
can rewrite it for a tag change, a republish, or a migration, none of which change a word of
what the model would read. A content hash changes when the content changes. It is also the only
option for the page audit path, where there is no body and no reliable timestamp at all.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

#: The fields a re-audit would actually read. If every one of these is byte-identical, the model
#: has already been asked this exact question and answered it.
#:
#: `content` is included for blog posts and absent for pages - a page audit reads the page's SEO
#: values from the public build inputs (`page_catalog.page_seo`) rather than a body. Missing keys
#: hash as empty, so a page and a post with the same title do not collide: `pageType` is part of
#: the payload.
_FIELDS = ('title', 'content', 'excerpt', 'seoTitle', 'metaDescription', 'category')


def source_hash(page: Dict[str, Any], page_type: str) -> str:
    """A stable sha256 over the source fields an audit reads.

    json.dumps with sort_keys so key order cannot change the digest, and `default=str` so a
    Decimal from DynamoDB or a datetime does not raise. Values are normalised to strings because
    DynamoDB returns numbers as Decimal and a Decimal('1') and an int 1 are the same content.
    """
    payload = {'pageType': str(page_type)}
    for field in _FIELDS:
        value = page.get(field)
        payload[field] = '' if value is None else str(value)
    encoded = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def unchanged_audit(
    records: List[Dict[str, Any]], current_hash: str,
) -> Optional[Dict[str, Any]]:
    """The newest audit whose stored hash equals `current_hash`, or None.

    A MISSING hash never matches. Audits written before this existed carry no `sourceHash`, and
    treating absent as equal would suppress the first audit of every one of them - turning a cost
    fix into a silent feature removal.

    Status is deliberately NOT filtered. A pending_review audit for identical content is still
    the answer to this question, and re-running the model would produce another pending_review
    beside it rather than anything new. Whether that content may be PUBLISHED is a separate
    decision, made in faq.py, which does filter on status.
    """
    if not current_hash:
        return None
    matches = [
        record for record in records
        if isinstance(record, dict)
        and record.get('recordType') == 'audit'
        and str(record.get('sourceHash') or '') == current_hash
    ]
    if not matches:
        return None
    matches.sort(key=lambda record: str(record.get('createdAt') or ''), reverse=True)
    return matches[0]


def skip_log(audit: Dict[str, Any], page_type: str) -> Dict[str, Any]:
    """The log shape a skipped audit reports, so a caller can tell a skip from a fresh run.

    Zero tokens and zero cost, stated explicitly rather than omitted: a reader comparing two
    responses should be able to see that one of them did not call a model.
    """
    return {
        'inputTokens': 0,
        'outputTokens': 0,
        'costEstimate': 0,
        'durationMs': 0,
        'model': str(audit.get('aiModel') or ''),
        'skipped': True,
        'skippedReason': 'source content unchanged since the stored audit',
        'sourceHash': str(audit.get('sourceHash') or ''),
        'pageType': page_type,
    }


def decide(
    page: Dict[str, Any], page_type: str, records: List[Dict[str, Any]], force: bool = False,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """(hash, reusable audit or None). `force` re-runs a model call deliberately.

    `force` exists because the hash covers the CONTENT and not the prompt: when ai.py's system
    prompt or the model chain changes, identical content should legitimately be re-audited.
    Without an escape hatch the only way to re-run would be editing the post, which is exactly
    the source mutation this architecture forbids.
    """
    current = source_hash(page, page_type)
    if force:
        return current, None
    return current, unchanged_audit(records, current)
