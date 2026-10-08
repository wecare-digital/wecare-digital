"""Focused Task 12 tests for the durable Admin SEO service."""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
SEO_DIR = ROOT / 'amplify' / 'functions' / 'operations' / 'seo-tools'
for location in (SHARED, SEO_DIR):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))


def load_handler():
    spec = importlib.util.spec_from_file_location('task12_seo_handler', SEO_DIR / 'handler.py')
    module = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(module)
    return module


@pytest.fixture
def seo_handler():
    return load_handler()


def request(path, body=None):
    event = {
        'requestContext': {
            'apiId': 'api-1',
            'http': {'method': 'POST', 'path': path, 'sourceIp': '127.0.0.1'},
        },
        'rawPath': path,
        '_auth': {'username': 'server-admin'},
    }
    if body is not None:
        event['body'] = json.dumps(body)
    return event


def payload(response):
    return json.loads(response['body'])


def test_seo_routes_require_admin(seo_handler):
    denied = {'statusCode': 403, 'body': '{}'}
    event = request('/seo-tools/blog-create', {'title': 'Title', 'content': 'Body'})
    with patch.object(seo_handler, 'require_auth', return_value=denied) as auth, \
            patch.object(seo_handler.storage, 'create_blog_post') as create:
        response = seo_handler.handler(event, None)
    assert response is denied
    auth.assert_called_once_with(event, required_role='Admin')
    create.assert_not_called()


def test_create_claim_success_writes_aws_blog(seo_handler):
    event = request('/seo-tools/blog-create', {'title': 'Title', 'content': 'Body'})
    with patch.object(seo_handler, 'require_auth', return_value=None), \
            patch.object(seo_handler, 'claim_admin_action', return_value=True), \
            patch.object(seo_handler.storage, 'create_blog_post', return_value={
                'postId': 'post-1', 'slug': 'title', 'title': 'Title',
            }) as create:
        response = seo_handler.handler(event, None)
    assert response['statusCode'] == 200
    assert payload(response)['postId'] == 'post-1'
    create.assert_called_once_with({'title': 'Title', 'content': 'Body'}, 'server-admin')


def test_create_duplicate_does_not_write_blog(seo_handler):
    event = request('/seo-tools/blog-create', {'title': 'Title', 'content': 'Body'})
    with patch.object(seo_handler, 'require_auth', return_value=None), \
            patch.object(seo_handler, 'claim_admin_action', return_value=False), \
            patch.object(seo_handler.storage, 'create_blog_post') as create:
        response = seo_handler.handler(event, None)
    assert response['statusCode'] == 409
    create.assert_not_called()


def test_create_claim_storage_failure_fails_closed(seo_handler):
    event = request('/seo-tools/blog-create', {'title': 'Title', 'content': 'Body'})
    with patch.object(seo_handler, 'require_auth', return_value=None), \
            patch.object(seo_handler, 'claim_admin_action', side_effect=RuntimeError('down')), \
            patch.object(seo_handler.storage, 'create_blog_post') as create:
        response = seo_handler.handler(event, None)
    assert response['statusCode'] == 503
    create.assert_not_called()


def test_review_uses_server_actor_and_conditional_transition(seo_handler):
    body = {'auditId': 'audit-1', 'action': 'approve', 'reviewedBy': 'browser-user'}
    with patch.object(seo_handler.storage, 'get_audit', return_value={
        'id': 'audit-1', 'recordType': 'audit', 'status': 'pending_review',
    }), patch.object(seo_handler.storage, 'transition_audit', return_value={
        'id': 'audit-1', 'status': 'approved', 'reviewedBy': 'server-admin',
    }) as transition:
        response = seo_handler._review(body, 'server-admin', '')
    assert response['statusCode'] == 200
    transition.assert_called_once_with(
        'audit-1', ['pending_review'], 'approved', 'server-admin',
    )
    assert payload(response)['audit']['reviewedBy'] == 'server-admin'


def test_audit_records_include_required_storage_fields(seo_handler):
    generated = {
        'model': 'model-1', 'inputTokens': 10, 'outputTokens': 20,
        'result': {
            'seoTitle': 'SEO title', 'metaDescription': 'SEO description',
            'focusKeyword': 'focus', 'secondaryKeywords': ['secondary'],
            'jsonLd': {}, 'internalLinks': [], 'imageAltText': [],
            'seoScoreBefore': 10, 'seoScoreAfter': 90,
            'scoreBreakdown': {}, 'warnings': [],
        },
    }
    records = []
    with patch.object(seo_handler.ai, 'invoke_seo', return_value=generated), \
            patch.object(seo_handler.storage, 'put_record', side_effect=records.append):
        audit, log = seo_handler._run_audit({
            'id': 'post-1', 'slug': 'post-slug', 'title': 'Post',
            'seoTitle': '', 'metaDescription': '',
        }, 'blog')
    assert {record['recordType'] for record in records} == {'audit', 'log'}
    for record in records:
        assert record['id']
        assert record['createdAt']
        assert record['slug'] == 'post-slug'
    assert audit['status'] == 'pending_review'
    assert log['model'] == 'model-1'


def test_scope_filter_paginates_until_matching_record(seo_handler):
    table = MagicMock()
    table.query.side_effect = [
        {
            'Items': [{'id': 'blog', 'recordType': 'audit', 'pageType': 'blog'}],
            'LastEvaluatedKey': {'id': 'blog'},
        },
        {'Items': [{'id': 'page', 'recordType': 'audit', 'pageType': 'page'}]},
    ]
    with patch.object(seo_handler.storage, 'table', return_value=table):
        records = seo_handler.storage.list_records('audit', 'pages', limit=1)
    assert [record['id'] for record in records] == ['page']
    assert table.query.call_count == 2


def test_non_blog_apply_returns_501_without_blog_write(seo_handler):
    with patch.object(seo_handler.storage, 'get_audit', return_value={
        'id': 'audit-page', 'pageType': 'page', 'status': 'approved',
    }), patch.object(seo_handler, 'claim_admin_action') as claim, \
            patch.object(seo_handler.storage, 'apply_blog_audit') as apply:
        response = seo_handler._review(
            {'auditId': 'audit-page', 'action': 'apply'}, 'server-admin', '',
        )
    assert response['statusCode'] == 501
    claim.assert_not_called()
    apply.assert_not_called()


def test_blog_apply_uses_applying_transition(seo_handler):
    approved = {'id': 'audit-blog', 'pageType': 'blog', 'status': 'approved'}
    applying = {**approved, 'status': 'applying', 'blogPostId': 'post-1'}
    applied = {**approved, 'status': 'applied'}
    with patch.object(seo_handler.storage, 'get_audit', return_value=approved), \
            patch.object(seo_handler, 'claim_admin_action', return_value=True), \
            patch.object(seo_handler.storage, 'transition_audit', side_effect=[
                applying, applied,
            ]) as transition, \
            patch.object(seo_handler.storage, 'apply_blog_audit') as apply:
        response = seo_handler._review(
            {'auditId': 'audit-blog', 'action': 'apply'}, 'server-admin', '',
        )
    assert response['statusCode'] == 200
    assert transition.call_args_list[0].args[:4] == (
        'audit-blog', ['approved'], 'applying', 'server-admin',
    )
    assert transition.call_args_list[1].args[:4] == (
        'audit-blog', ['applying'], 'applied', 'server-admin',
    )
    apply.assert_called_once_with(applying, 'server-admin')


def test_failed_blog_apply_restores_approved_state(seo_handler):
    approved = {'id': 'audit-blog', 'pageType': 'blog', 'status': 'approved'}
    applying = {**approved, 'status': 'applying', 'blogPostId': 'post-1'}
    restored = {**approved, 'applicationError': 'Blog SEO apply failed'}
    with patch.object(seo_handler.storage, 'get_audit', return_value=approved), \
            patch.object(seo_handler, 'claim_admin_action', return_value=True), \
            patch.object(seo_handler.storage, 'transition_audit', side_effect=[
                applying, restored,
            ]) as transition, \
            patch.object(seo_handler.storage, 'apply_blog_audit', side_effect=RuntimeError('failed')):
        response = seo_handler._review(
            {'auditId': 'audit-blog', 'action': 'apply'}, 'server-admin', '',
        )
    assert response['statusCode'] == 502
    assert transition.call_args_list[1].args[:4] == (
        'audit-blog', ['applying'], 'approved', 'server-admin',
    )
    assert payload(response)['error'] == 'Blog SEO apply failed; audit remains approved'

def test_public_blog_endpoint_returns_wix_posts_without_auth(seo_handler):
    event = {
        'requestContext': {
            'apiId': 'api-1',
            'http': {'method': 'GET', 'path': '/seo-tools/blog-public', 'sourceIp': '127.0.0.1'},
        },
        'rawPath': '/seo-tools/blog-public',
    }
    published = [{
        'id': 'blog-1', 'slug': 'hello', 'title': 'Hello',
        'url': 'https://wecare.digital/post/hello/',
    }]
    with patch.object(seo_handler.wix, 'list_blog_posts', return_value=published) as posts, \
            patch.object(seo_handler, 'require_auth') as auth:
        response = seo_handler.handler(event, None)
    assert response['statusCode'] == 200
    assert payload(response)['posts'] == published
    posts.assert_called_once_with()
    auth.assert_not_called()


def test_public_blog_detail_reads_wix_by_slug(seo_handler):
    event = {
        'requestContext': {
            'apiId': 'api-1',
            'http': {
                'method': 'GET',
                'path': '/seo-tools/blog-public/integrity-and-balance',
                'sourceIp': '127.0.0.1',
            },
        },
        'rawPath': '/seo-tools/blog-public/integrity-and-balance',
    }
    post = {
        'id': 'blog-1',
        'slug': 'integrity-and-balance',
        'title': 'Integrity',
        'coverImage': '',
    }
    with patch.object(
        seo_handler.wix, 'get_blog_post_by_slug', return_value=post
    ) as get_post, patch.object(seo_handler, 'require_auth') as auth:
        response = seo_handler.handler(event, None)
    assert response['statusCode'] == 200
    assert payload(response)['post'] == post
    get_post.assert_called_once_with('integrity-and-balance')
    auth.assert_not_called()


def test_wix_public_blog_never_uses_admin_request_path(seo_handler):
    categories = {
        'categories': [{'id': 'cat-1', 'label': 'Conversations'}],
    }
    tags = {
        'tags': [{'id': 'tag-1', 'label': 'Integrity'}],
    }

    def public_call(method, path, body=None):
        if path == '/blog/v3/categories/query':
            return categories
        if path == '/v3/tags/query':
            return tags
        if path == '/v3/posts/query':
            return {
                'posts': [{
                    'id': 'post-1',
                    'title': 'Integrity',
                    'slug': 'integrity-and-balance',
                    'categoryIds': ['cat-1'],
                    'tagIds': ['tag-1'],
                }],
                'pagingMetadata': {'cursors': {}},
            }
        raise AssertionError(path)

    with patch.object(
        seo_handler.wix, 'public_blog_request', side_effect=public_call
    ) as public_request, patch.object(
        seo_handler.wix, 'request'
    ) as admin_request:
        posts = seo_handler.wix.list_blog_posts()

    assert posts[0]['category'] == 'Conversations'
    assert posts[0]['tags'] == ['Integrity']
    assert posts[0]['authorName'] == 'Anew by WECARE.DIGITAL'
    admin_request.assert_not_called()
    assert public_request.call_count == 3


def test_blog_audit_reads_aws_post_not_wix(seo_handler):
    with patch.object(seo_handler, 'claim_admin_action', return_value=True), \
            patch.object(seo_handler, 'release_admin_audit'), \
            patch.object(seo_handler.storage, 'get_blog_post', return_value={
                'id': 'blog-1', 'slug': 'hello', 'title': 'Hello',
            }) as get_post, \
            patch.object(seo_handler, '_run_audit', return_value=(
                {'id': 'audit-1'}, {'model': 'model-1'},
            )):
        response = seo_handler._blog_audit({'slug': 'hello'}, 'server-admin', '')
    assert response['statusCode'] == 200
    get_post.assert_called_once_with('hello')
