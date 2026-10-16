"""Public reader source ownership, HTTP read boundary and reproducible packaging."""
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reader():
    storage = SimpleNamespace(list_blog_posts=Mock(return_value=[{
        'slug': 'example', 'title': 'Example', 'content': 'Body', 'internalNote': 'private',
    }]), get_blog_post=Mock(return_value=None), list_slug_records=Mock(return_value=[]))
    faq = SimpleNamespace(attach=Mock(side_effect=lambda post, records: post))
    spec = importlib.util.spec_from_file_location('dedicated_blog_reader',
        ROOT / 'amplify/functions/operations/blog-public/handler.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'storage': storage, 'faq': faq}):
        spec.loader.exec_module(module)
        yield module, storage


def event(method='GET', path='/seo-tools/blog-public', **extra):
    return {'rawPath': path, 'requestContext': {'http': {'method': method}}, **extra}


def test_list_excludes_private_and_full_body_fields(reader):
    module, storage = reader
    response = module.handler(event(), None)
    assert response['statusCode'] == 200
    assert json.loads(response['body'])['posts'] == [{'slug': 'example', 'title': 'Example'}]
    storage.list_blog_posts.assert_called_once_with(published_only=True, include_content=False)


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_http_mutations_are_rejected_before_storage(reader, method):
    module, storage = reader
    assert module.handler(event(method), None)['statusCode'] == 405
    storage.list_blog_posts.assert_not_called()
    storage.get_blog_post.assert_not_called()


def test_unknown_route_and_invalid_slug_cannot_reach_storage(reader):
    module, storage = reader
    for path in ['/seo-tools/admin', '/seo-tools/blog-public/../../private']:
        assert module.handler(event(path=path), None)['statusCode'] == 404
    storage.get_blog_post.assert_not_called()


def test_detail_is_published_only_and_filters_private_fields(reader):
    module, storage = reader
    storage.get_blog_post.return_value = {'slug': 'example', 'content': 'Body', 'internalNote': 'private'}
    response = module.handler(event(path='/seo-tools/blog-public/example'), None)
    assert json.loads(response['body'])['post'] == {'slug': 'example', 'content': 'Body'}
    storage.get_blog_post.assert_called_once_with('example', published_only=True)


def test_http_event_cannot_enter_private_integrity_audit(reader):
    module, storage = reader
    module.handler(event(integrityAudit=True), None)
    storage.list_blog_posts.assert_called_once_with(published_only=True, include_content=False)


def test_etag_304_preserves_empty_body(reader):
    module, _ = reader
    first = module.handler(event(), None)
    second = module.handler(event(headers={'if-none-match': first['headers']['ETag']}), None)
    assert second['statusCode'] == 304
    assert second['body'] == ''


@pytest.mark.parametrize('header', ['"other", {etag}', ' W/{etag} ', '*'])
def test_conditional_get_handles_etag_lists_weak_comparison_and_wildcard(reader, header):
    module, _ = reader
    first = module.handler(event(), None)
    value = header.format(etag=first['headers']['ETag'])
    assert module.handler(event(headers={'If-None-Match': value}), None)['statusCode'] == 304


def test_storage_package_has_no_write_api():
    import ast
    path = ROOT / 'amplify/functions/operations/blog-public/storage.py'
    tree = ast.parse(path.read_text())
    forbidden = {'put_item', 'update_item', 'delete_item', 'batch_writer', 'transact_write_items'}
    assert not {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} & forbidden
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {'list_blog_posts', 'get_blog_post', 'list_slug_records'} <= functions
    assert not functions & {'create_blog_post', 'publish_native_post', 'apply_blog_audit', 'delete_slug_audits'}


def test_package_is_reproducible_and_has_no_admin_or_ingestion_bundle():
    from scripts.build_blog_public import package
    assert package() == package()
    with zipfile.ZipFile(io.BytesIO(package())) as archive:
        assert set(archive.namelist()) == {'handler.py', 'storage.py', 'faq.py'}
        for member in archive.namelist():
            assert archive.read(member) == (ROOT / 'amplify/functions/operations/blog-public' / member).read_bytes()
