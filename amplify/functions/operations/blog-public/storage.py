"""Durable DynamoDB persistence for SEO audits and AI request logs."""


import os


import re


import uuid


from datetime import datetime, timezone


from decimal import Decimal


from typing import Any, Dict, Iterable, List, Optional


import boto3


from boto3.dynamodb.conditions import Key


from botocore.exceptions import ClientError


TABLE_NAME = os.environ.get('SEO_TOOLS_TABLE', 'stack-wecare-digital-SeoToolsTable')


_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource(
            'dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1')
        ).Table(TABLE_NAME)
    return _table


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def query_index(index_name: str, key_name: str, key_value: str, limit: int = 0,
                newest_first: bool = False) -> List[Dict[str, Any]]:
    """Every item on a GSI partition, paginated, with NO 500-item ceiling.

    WHY THIS EXISTS ALONGSIDE `list_records`.

    `list_records` clamps to `min(max(limit, 1), 500)`, which is right for the audit and log
    surfaces it was written for - nobody reads past 500 audits. It is wrong for Blog
    Production, where a single batch is specified to hold thousands of independently tracked
    records. With the clamp, a 2,500-source batch reported rollups for 500 of them and the
    worker stopped finding work at 500 - both silently, and both while looking healthy.

    `limit=0` means "all of it". Ascending by default, because a work queue should drain
    oldest-first; `list_records` sorts newest-first for a different reason, which is that a
    human reading a log wants the last thing that happened.
    """
    kwargs: Dict[str, Any] = {
        'IndexName': index_name,
        'KeyConditionExpression': Key(key_name).eq(key_value),
        'ScanIndexForward': not newest_first,
    }
    items: List[Dict[str, Any]] = []
    while True:
        response = table().query(**kwargs)
        items.extend(response.get('Items', []))
        if limit and len(items) >= limit:
            break
        last = response.get('LastEvaluatedKey')
        if not last:
            break
        kwargs['ExclusiveStartKey'] = last
    result = items[:limit] if limit else items
    return [_json_safe(item) for item in result]


def list_slug_records(slug: str) -> List[Dict[str, Any]]:
    kwargs: Dict[str, Any] = {
        'IndexName': 'slug-createdAt-index',
        'KeyConditionExpression': Key('slug').eq(slug),
        'ScanIndexForward': False,
    }
    items: List[Dict[str, Any]] = []
    while True:
        response = table().query(**kwargs)
        items.extend(response.get('Items', []))
        if 'LastEvaluatedKey' not in response:
            break
        kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
    return [_json_safe(item) for item in items]


BLOG_RECORD_TYPE = 'blogPost'


PUBLIC_SITE_URL = os.environ.get('PUBLIC_SITE_URL', 'https://wecare.digital').rstrip('/')


def _blog_view(item: Dict[str, Any], include_content: bool = True) -> Dict[str, Any]:
    post = _json_safe(item)
    json_ld = post.get('jsonLd') or {}
    schemas = [value for value in json_ld.values() if isinstance(value, dict) and value]
    result = {
        'id': post.get('publicId') or post.get('id', ''),
        'title': post.get('title', ''),
        'slug': post.get('slug', ''),
        'excerpt': post.get('excerpt', ''),
        'url': post.get('url') or f"{PUBLIC_SITE_URL}/post/{post.get('slug', '')}",
        'seoTitle': post.get('seoTitle', ''),
        'metaDescription': post.get('metaDescription', ''),
        'focusKeyword': post.get('focusKeyword', ''),
        'keywords': post.get('secondaryKeywords', post.get('keywords', post.get('tags', []))) or [],
        'jsonLd': json_ld,
        'jsonLdCount': len(schemas),
        'hasCustomSeo': bool(post.get('seoTitle') or post.get('metaDescription') or schemas),
        'tagCount': len(post.get('tags', []) or []),
        'publishedDate': post.get('publishedAt', ''),
        'modifiedDate': post.get('updatedAt', ''),
        'coverImage': post.get('coverImage', ''),
        'status': post.get('status', 'draft'),
        'category': post.get('category', ''),
        'tags': post.get('tags', []) or [],
        'hashtags': post.get('hashtags', []) or [],
        'authorName': post.get('authorName', 'WECARE.DIGITAL'),
        'robots': post.get('robots', 'index, follow, max-image-preview:large'),
    }
    if include_content:
        result['content'] = post.get('content', '')
        result['contentText'] = post.get('content', '')
        result['richContent'] = post.get('richContent') or {}
    return result


def list_blog_posts(published_only: bool = False, limit: int = 0, include_content: bool = True) -> List[Dict[str, Any]]:
    posts = query_index('recordType-createdAt-index', 'recordType', BLOG_RECORD_TYPE, limit=0, newest_first=True)
    if published_only:
        posts = [post for post in posts if post.get('status') == 'published']
    return [_blog_view(post, include_content=include_content) for post in (posts[:limit] if limit else posts)]


def get_blog_post(slug: str, published_only: bool = False) -> Optional[Dict[str, Any]]:
    wanted = str(slug or '').strip().strip('/')
    if not wanted:
        return None
    exact = table().get_item(Key={'id': 'BLOG#' + wanted}, ConsistentRead=True).get('Item')
    candidates = [exact] if exact else list_slug_records(wanted)
    for item in candidates:
        if item.get('recordType') != BLOG_RECORD_TYPE:
            continue
        if published_only and item.get('status') != 'published':
            continue
        return _blog_view(item, include_content=True)
    return None
