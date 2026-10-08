"""Tests for WhatsApp Business API Lambda handler."""
import json
import hmac
import hashlib
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))


class TestWebhookSignatureVerification:
    """Test X-Hub-Signature-256 on business API handler."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _verify_webhook_signature
                self.verify = _verify_webhook_signature

    def test_missing_signature_returns_false(self):
        event = {'headers': {}, 'body': '{}'}
        with patch('handler._get_app_secret', return_value='real_secret'):
            assert self.verify(event, 'req-1') is False

    def test_valid_signature(self):
        secret = 'app_secret_123'
        body = '{"encrypted_flow_data":"abc"}'
        sig = 'sha256=' + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._get_app_secret', return_value=secret):
            assert self.verify(event, 'req-2') is True

    def test_invalid_signature(self):
        event = {'headers': {'x-hub-signature-256': 'sha256=wrong'}, 'body': '{"test":1}'}
        with patch('handler._get_app_secret', return_value='real_secret'):
            assert self.verify(event, 'req-3') is False

    def test_no_secret_fails_closed(self):
        """Was `test_no_secret_fails_open`, and it asserted `is True`.

        The implementation it pinned returned True when no app secret was
        configured, commented "fail open only if secret not configured
        (dev/test)". A verifier that trusts everything the moment its key is
        missing inverts its own purpose: a misconfiguration - an unreadable
        secret, a renamed field, a cache that failed to populate - silently turns
        verification off in production rather than making noise.

        The sibling guard in `whatsapp-calling` already failed closed here, and the
        two implementations disagreed. Both now delegate to
        `lambda_utils.meta_signature`, which never fails open.
        """
        event = {'headers': {'x-hub-signature-256': 'sha256=anything'}, 'body': '{}'}
        with patch('handler._get_app_secret', return_value=''), \
             patch('handler._token_cache', {'app_secret_waba2': ''}):
            assert self.verify(event, 'req-4') is False

    def test_second_waba_secret_is_actually_tried(self):
        """`WABA2_IDS` is an empty set in this function, so
        `_get_app_secret(waba_id=...)` can never select the WABA2 key. The
        verifier reads `_token_cache` directly for that reason; this pins it, since
        a callback signed by the second app would otherwise be rejected."""
        secret2 = 'waba2_app_secret'
        body = '{"field":"value"}'
        sig = 'sha256=' + hmac.new(secret2.encode(), body.encode(), hashlib.sha256).hexdigest()
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._get_app_secret', return_value='waba1_app_secret'), \
             patch('handler._token_cache', {'app_secret_waba2': secret2}):
            assert self.verify(event, 'req-5') is True


class TestBusinessProfile:
    """Test business profile CRUD."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _get_business_profile, _update_business_profile
                self.get_profile = _get_business_profile
                self.update_profile = _update_business_profile

    def test_get_profile(self):
        with patch('handler._graph_api', return_value={'data': [{'about': 'Test', 'description': 'Desc'}]}):
            result = self.get_profile('1016149501586345')
            body = json.loads(result['body'])
            assert body['profile']['about'] == 'Test'

    def test_update_profile_empty_payload(self):
        result = self.update_profile('1016149501586345', {})
        assert result['statusCode'] == 400

    def test_update_profile_valid(self):
        with patch('handler._graph_api', return_value={'success': True}):
            result = self.update_profile('1016149501586345', {'about': 'Updated'})
            assert result['statusCode'] == 200


class TestFlows:
    """Test WhatsApp Flows CRUD."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _list_flows, _create_flow, _publish_flow, _delete_flow
                self.list_flows = _list_flows
                self.create_flow = _create_flow
                self.publish_flow = _publish_flow
                self.delete_flow = _delete_flow

    def test_list_flows_requires_waba(self):
        result = self.list_flows('')
        assert result['statusCode'] == 400

    def test_list_flows_success(self):
        with patch('handler._graph_api', return_value={'data': [{'id': 'f1', 'name': 'Flow 1'}]}):
            result = self.list_flows('2094615664435155')
            body = json.loads(result['body'])
            assert len(body['flows']) == 1

    def test_create_flow_requires_name(self):
        result = self.create_flow('2094615664435155', {})
        assert result['statusCode'] == 400

    def test_publish_flow_requires_id(self):
        result = self.publish_flow('')
        assert result['statusCode'] == 400

    def test_delete_flow_requires_id(self):
        result = self.delete_flow('')
        assert result['statusCode'] == 400


class TestTemplateTTL:
    """Test template TTL routes (rules / validate / update)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _get_ttl_rules, _validate_template_ttl_route, _update_template_ttl
                self.get_rules = _get_ttl_rules
                self.validate_route = _validate_template_ttl_route
                self.update_ttl = _update_template_ttl

    def test_rules_returns_categories(self):
        result = self.get_rules()
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'AUTHENTICATION' in body['rules']['categories']

    def test_validate_requires_category(self):
        result = self.validate_route({'ttl': 600})
        assert result['statusCode'] == 400

    def test_validate_ok(self):
        result = self.validate_route({'category': 'AUTHENTICATION', 'ttl': 600})
        body = json.loads(result['body'])
        assert result['statusCode'] == 200
        assert body['ok'] is True

    def test_validate_out_of_range(self):
        result = self.validate_route({'category': 'AUTHENTICATION', 'ttl': 5000})
        body = json.loads(result['body'])
        assert body['ok'] is False

    def test_update_ttl_requires_id(self):
        result = self.update_ttl('', {'ttl': 600})
        assert result['statusCode'] == 400

    def test_update_ttl_requires_ttl(self):
        result = self.update_ttl('tmpl-1', {})
        assert result['statusCode'] == 400

    def test_update_ttl_validates_against_live_category(self):
        # Live template is AUTHENTICATION; 5000 is out of range -> 400, no POST attempted
        with patch('handler._graph_api', return_value={'name': 't', 'category': 'AUTHENTICATION'}):
            result = self.update_ttl('tmpl-1', {'ttl': 5000})
            assert result['statusCode'] == 400

    def test_update_ttl_success(self):
        calls = []

        def fake_graph(endpoint, method='GET', payload=None, params=None, **kw):
            calls.append(method)
            if method == 'GET':
                return {'name': 't', 'category': 'UTILITY'}
            return {'success': True}

        with patch('handler._graph_api', side_effect=fake_graph):
            result = self.update_ttl('tmpl-1', {'ttl': 600})
            body = json.loads(result['body'])
            assert result['statusCode'] == 200
            assert body['success'] is True
            assert body['ttl'] == 600
            assert 'POST' in calls


class TestMedia:
    """Test /wa-business/media routes (upload / get / delete / resumable)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_validate_media_rejects_bad_mime(self):
        assert self.h._validate_media('application/x-evil', 10) is not None

    def test_validate_media_size_limit(self):
        # image limit is 5MB
        assert self.h._validate_media('image/png', 6 * 1024 * 1024) is not None
        assert self.h._validate_media('image/png', 1024) is None

    def test_mask_media_url(self):
        masked = self.h._mask_media_url('https://lookaside.fbsbx.com/abc?token=secret')
        assert 'secret' not in masked
        assert masked.startswith('https://lookaside.fbsbx.com/abc')

    def test_upload_media_requires_source(self):
        res = self.h._upload_media({'phoneId': '123'})
        assert res['statusCode'] == 400

    def test_upload_media_success(self):
        import base64 as b64
        data = b64.b64encode(b'hello').decode()
        with patch.object(self.h, '_graph_media_multipart', return_value={'id': 'media-1'}):
            res = self.h._upload_media({'phoneId': '123', 'fileData': data, 'contentType': 'image/png', 'filename': 'a.png'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert body['mediaId'] == 'media-1'

    def test_get_media_masks_url_and_sets_expiry(self):
        with patch.object(self.h, '_graph_api', return_value={'url': 'https://x/y?token=abc', 'mime_type': 'image/png', 'file_size': 10}):
            res = self.h._get_media('media-1', '123', {})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert 'token=abc' not in body['url']
            assert body['urlExpiresInSeconds'] == self.h.MEDIA_URL_TTL_SECONDS

    def test_delete_media_requires_id(self):
        res = self.h._delete_media('', '123')
        assert res['statusCode'] == 400

    def test_resumable_session_requires_length(self):
        res = self.h._resumable_session({'fileType': 'image/png'})
        assert res['statusCode'] == 400

    def test_resumable_session_validates_mime(self):
        res = self.h._resumable_session({'fileType': 'application/x-evil', 'fileLength': 100})
        assert res['statusCode'] == 400

    def test_resumable_session_ok(self):
        with patch.object(self.h.s3_client, 'put_object', return_value={}):
            res = self.h._resumable_session({'fileType': 'image/png', 'fileLength': 100, 'fileName': 'a.png'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert 'sessionId' in body

    def test_resumable_chunk_unknown_session(self):
        with patch.object(self.h, '_resumable_load_manifest', return_value=None):
            res = self.h._resumable_chunk('nope', {'data': 'AA=='})
            assert res['statusCode'] == 404

    def test_resumable_finish_incomplete(self):
        manifest = {'sessionId': 's1', 'fileName': 'a.png', 'fileType': 'image/png', 'fileLength': 100, 'received': 50}
        with patch.object(self.h, '_resumable_load_manifest', return_value=manifest):
            res = self.h._resumable_finish('s1', {})
            assert res['statusCode'] == 400


class TestFlowAdmin:
    """Test flow assets / migrate / sync (Part 4 A)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_asset_requires_flow_id(self):
        assert self.h._upload_flow_asset('', {'flowJson': {'version': '7.0', 'screens': []}})['statusCode'] == 400

    def test_asset_rejects_bad_json(self):
        res = self.h._upload_flow_asset('f1', {'flowJson': '{not json'})
        assert res['statusCode'] == 400

    def test_asset_requires_flow_keys(self):
        res = self.h._upload_flow_asset('f1', {'flowJson': {'foo': 'bar'}})
        assert res['statusCode'] == 400

    def test_migrate_requires_wabas(self):
        assert self.h._migrate_flows({'sourceWabaId': 'a'})['statusCode'] == 400

    def test_migrate_success(self):
        with patch.object(self.h, '_graph_api', return_value={'migrated_flows': [{'id': '1'}], 'failed_flows': []}):
            res = self.h._migrate_flows({'sourceWabaId': 'a', 'destWabaId': 'b'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert len(body['migratedFlows']) == 1

    def test_sync_requires_waba(self):
        assert self.h._sync_flows({}, {})['statusCode'] == 400

    def test_sync_upserts(self):
        flows = {'data': [{'id': 'f1', 'name': 'Flow 1', 'status': 'PUBLISHED', 'categories': ['SIGN_UP']}]}
        fake_table = MagicMock()
        fake_table.get_item.return_value = {'Item': {}}
        with patch.object(self.h, '_graph_api', return_value=flows):
            with patch.object(self.h.dynamodb, 'Table', return_value=fake_table):
                res = self.h._sync_flows({'wabaId': 'w1'}, {})
                body = json.loads(res['body'])
                assert res['statusCode'] == 200
                assert body['synced'] == 1
                assert fake_table.put_item.called


class TestSendMessages:
    """Test /messages/send/* routes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def _ok_send(self):
        return patch.object(self.h, '_graph_api', return_value={'messages': [{'id': 'wamid.1'}]})

    def test_text_requires_fields(self):
        assert self.h._send_text({'to': '919900000000'})['statusCode'] == 400

    def test_text_success(self):
        with self._ok_send():
            res = self.h._send_text({'to': '919900000000', 'text': 'hi'})
            assert json.loads(res['body'])['messageId'] == 'wamid.1'

    def test_template_requires_name(self):
        assert self.h._send_template_msg({'to': '919900000000'})['statusCode'] == 400

    def test_template_success(self):
        with self._ok_send():
            res = self.h._send_template_msg({'to': '919900000000', 'templateName': 'hello', 'language': 'en'})
            assert res['statusCode'] == 200

    def test_media_requires_valid_type(self):
        assert self.h._send_media_msg({'to': '919900000000', 'mediaType': 'bogus', 'mediaId': 'm1'})['statusCode'] == 400

    def test_media_requires_source(self):
        assert self.h._send_media_msg({'to': '919900000000', 'mediaType': 'image'})['statusCode'] == 400

    def test_media_success(self):
        with self._ok_send():
            res = self.h._send_media_msg({'to': '919900000000', 'mediaType': 'image', 'mediaId': 'm1', 'caption': 'c'})
            assert res['statusCode'] == 200

    def test_the_interactive_route_is_gone_and_says_so(self):
        """`_send_interactive_msg` was deleted on 2026-10-02 with the WhatsApp
        menus. The route is still declared, so it must answer 410 Gone rather than
        fall through to the 404 'Unknown send path' - the route is withdrawn, not
        unknown, and a 404 would send a caller looking for a typo."""
        assert not hasattr(self.h, '_send_interactive_msg')
        res = self.h._route_send_message('/messages/send/interactive', {})
        assert res['statusCode'] == 410
        assert 'interactive messaging removed' in res['body']

    def test_flow_requires_flow_ref(self):
        assert self.h._send_flow_msg({'to': '919900000000'})['statusCode'] == 400

    def test_flow_by_id_success(self):
        with self._ok_send():
            res = self.h._send_flow_msg({'to': '919900000000', 'flowId': 'f1', 'screen': 'WELCOME'})
            assert res['statusCode'] == 200

    def test_flow_draft_mode(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['payload'] = payload
            return {'messages': [{'id': 'x'}]}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            self.h._send_flow_msg({'to': '919900000000', 'flowName': 'f', 'mode': 'draft'})
            params = captured['payload']['interactive']['action']['parameters']
            assert params['mode'] == 'draft'
            assert params['flow_name'] == 'f'

    def test_route_send_dispatch(self):
        with self._ok_send():
            res = self.h._route_send_message('/messages/send/text', {'to': '919900000000', 'text': 'hi'})
            assert res['statusCode'] == 200
        assert self.h._route_send_message('/messages/send/unknown', {})['statusCode'] == 404

    def test_send_requires_to_or_recipient(self):
        assert self.h._send_text({'text': 'hi'})['statusCode'] == 400

    def test_send_by_bsuid_recipient(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['payload'] = payload
            return {'messages': [{'id': 'x'}], 'contacts': [{'user_id': 'US.13491208655302741918'}]}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            res = self.h._send_text({'recipient': 'US.13491208655302741918', 'text': 'hi'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert captured['payload']['recipient'] == 'US.13491208655302741918'
            assert 'to' not in captured['payload']
            assert body['userId'] == 'US.13491208655302741918'

    def test_send_both_to_and_recipient(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['payload'] = payload
            return {'messages': [{'id': 'x'}]}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            self.h._send_text({'to': '919900000000', 'recipient': 'US.123', 'text': 'hi'})
            assert captured['payload']['to'] == '919900000000'
            assert captured['payload']['recipient'] == 'US.123'

    def test_request_contact_info(self):
        with self._ok_send():
            res = self.h._send_request_contact_info({'recipient': 'US.123', 'bodyText': 'Share your number'})
            assert res['statusCode'] == 200

    def test_contacts_requires_fields(self):
        assert self.h._send_contacts_msg({'to': '919900000000'})['statusCode'] == 400

    def test_location_requires_coords(self):
        assert self.h._send_location_msg({'to': '919900000000'})['statusCode'] == 400

    def test_location_success(self):
        with self._ok_send():
            res = self.h._send_location_msg({'to': '919900000000', 'latitude': 22.5, 'longitude': 88.3, 'name': 'HQ'})
            assert res['statusCode'] == 200

    def test_product_single_requires_retailer(self):
        assert self.h._send_product_msg({'to': '919900000000', 'catalogId': 'cat1'})['statusCode'] == 400

    def test_product_single_success(self):
        with self._ok_send():
            res = self.h._send_product_msg({'to': '919900000000', 'catalogId': 'cat1', 'productRetailerId': 'sku1'})
            assert res['statusCode'] == 200

    def test_product_multi_success(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['payload'] = payload
            return {'messages': [{'id': 'x'}]}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            self.h._send_product_msg({'to': '919900000000', 'catalogId': 'cat1', 'sections': [{'title': 'A', 'product_items': [{'product_retailer_id': 'sku1'}]}]})
            assert captured['payload']['interactive']['type'] == 'product_list'


class TestUsername:
    """Test the corrected set-username claim flow."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_validate_username(self):
        assert self.h._validate_wa_username('wecaredigital') is None
        assert self.h._validate_wa_username('ab') is not None          # too short
        assert self.h._validate_wa_username('Caps_Name') is not None   # uppercase
        assert self.h._validate_wa_username('has space') is not None

    def test_claim_requires_username(self):
        assert self.h._claim_username('123', {})['statusCode'] == 400

    def test_claim_rejects_bad_format(self):
        assert self.h._claim_username('123', {'username': 'BAD NAME'})['statusCode'] == 400

    def test_claim_uses_username_endpoint(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['endpoint'] = endpoint
            captured['payload'] = payload
            return {'status': 'reserved'}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            res = self.h._claim_username('1016149501586345', {'username': 'wecaredigital'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert captured['endpoint'] == '1016149501586345/username'
            assert captured['payload']['transfer_action'] == 'none'
            assert body['status'] == 'reserved'

    def test_claim_auto_force_transfer_on_147005(self):
        calls = []

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            calls.append(payload['transfer_action'])
            if payload['transfer_action'] == 'none':
                return {'error': {'code': 147005, 'message': 'transfer required'}}
            return {'success': True}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            res = self.h._claim_username('123', {'username': 'wecaredigital', 'autoForceTransfer': True})
            assert res['statusCode'] == 200
            assert calls == ['none', 'force_transfer']

    def test_claim_147005_without_auto_returns_hint(self):
        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            return {'error': {'code': 147005, 'message': 'transfer required'}}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            res = self.h._claim_username('123', {'username': 'wecaredigital'})
            body = json.loads(res['body'])
            assert res['statusCode'] == 400
            assert 'force_transfer' in body.get('hint', '')


class TestBsuidApis:
    """Contact Book delete + Parent BSUID accounts + BSUID validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_bsuid_validation(self):
        assert self.h._is_valid_bsuid('US.13491208655302741918') is True
        assert self.h._is_valid_bsuid('US.ENT.11815799212886844830') is True
        assert self.h._is_valid_bsuid('13491208655302741918') is False
        assert self.h._is_valid_bsuid('') is False

    def test_contact_book_requires_valid_bsuid(self):
        assert self.h._delete_contact_book('123', 'notabsuid')['statusCode'] == 400

    def test_contact_book_delete_success(self):
        captured = {}

        def fake(endpoint, method='GET', payload=None, params=None, **kw):
            captured['endpoint'] = endpoint
            captured['method'] = method
            captured['params'] = params
            return {'success': True, 'deleted': True}

        with patch.object(self.h, '_graph_api', side_effect=fake):
            res = self.h._delete_contact_book('1016149501586345', 'US.13491208655302741918')
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert body['deleted'] is True
            assert captured['endpoint'] == '1016149501586345/contact_book'
            assert captured['method'] == 'DELETE'
            assert captured['params']['bsuid'] == 'US.13491208655302741918'

    def test_parent_bsuid_requires_business(self):
        assert self.h._get_parent_bsuid_accounts('')['statusCode'] == 400

    def test_parent_bsuid_success(self):
        with patch.object(self.h, '_api_facebook_get', return_value={'parent_bsuid_account_id': 'pba1', 'enrolled_business_portfolios': ['b1', 'b2']}):
            res = self.h._get_parent_bsuid_accounts('biz1')
            body = json.loads(res['body'])
            assert res['statusCode'] == 200
            assert body['parentBsuidAccountId'] == 'pba1'
            assert body['enrolledBusinessPortfolios'] == ['b1', 'b2']


class TestGroups:
    """Test WhatsApp Groups CRUD."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _create_group, _send_group_message
                self.create_group = _create_group
                self.send_group = _send_group_message

    def test_create_group_requires_phone(self):
        result = self.create_group('', {'subject': 'Test'})
        assert result['statusCode'] == 400

    def test_create_group_requires_subject(self):
        result = self.create_group('1016149501586345', {})
        assert result['statusCode'] == 400

    def test_send_group_message_requires_content(self):
        result = self.send_group('1016149501586345', 'group-1', {})
        assert result['statusCode'] == 400


class TestPaymentConfig:
    """Test payment configuration endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _get_payment_config, _check_payment_gateway
                self.get_config = _get_payment_config
                self.check_gateway = _check_payment_gateway

    def test_get_payment_config_phone1(self):
        result = self.get_config('1016149501586345')
        body = json.loads(result['body'])
        assert body['paymentConfig'] is not None
        # 7392 = management, consulting and public relations services, which is
        # what both WABAs actually carry (verified via Graph API, recorded in
        # whatsapp-business-api/handler.py and src/config/constants.ts). The
        # previous expectation of 4722 (travel agencies) appeared nowhere else in
        # the tree, so it was a stale literal in this test rather than a code bug.
        assert body['paymentConfig']['mcc'] == '7392'

    def test_get_payment_config_unknown_phone(self):
        with patch('handler._graph_api', return_value={'error': 'not found'}):
            result = self.get_config('unknown-phone')
            assert result['statusCode'] == 200

    def test_check_gateway(self):
        with patch('handler._graph_api', return_value={'data': []}):
            result = self.check_gateway('2094615664435155')
            body = json.loads(result['body'])
            assert 'gatewayChecks' in body


class TestAssignedUsers:
    """Test WABA assigned users CRUD (GET/POST/DELETE /{WABA-ID}/assigned_users)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _list_assigned_users, _add_assigned_user, _remove_assigned_user
                self.list_users = _list_assigned_users
                self.add_user = _add_assigned_user
                self.remove_user = _remove_assigned_user

    def test_list_requires_business_param(self):
        result = self.list_users('2094615664435155', {})
        assert result['statusCode'] == 400
        assert 'business' in json.loads(result['body'])['error']

    def test_list_success(self):
        with patch('handler._graph_api', return_value={
            'data': [{'id': '123', 'name': 'Test User'}],
            'paging': {'cursors': {'after': 'abc'}},
            'summary': {'total_count': 1},
        }):
            result = self.list_users('2094615664435155', {'business': '999'})
            body = json.loads(result['body'])
            assert len(body['users']) == 1
            assert body['users'][0]['name'] == 'Test User'
            assert body['summary']['total_count'] == 1

    def test_add_requires_user(self):
        result = self.add_user('2094615664435155', {'tasks': ['MANAGE']})
        assert result['statusCode'] == 400

    def test_add_requires_tasks(self):
        result = self.add_user('2094615664435155', {'user': '123'})
        assert result['statusCode'] == 400

    def test_add_success(self):
        with patch('handler._graph_api', return_value={'success': True}):
            result = self.add_user('2094615664435155', {'user': '123', 'tasks': ['MANAGE', 'DEVELOP']})
            body = json.loads(result['body'])
            assert body['success'] is True

    def test_remove_requires_user(self):
        result = self.remove_user('2094615664435155', {})
        assert result['statusCode'] == 400

    def test_remove_success(self):
        with patch('handler._graph_api', return_value={'success': True}):
            result = self.remove_user('2094615664435155', {'user': '123'})
            body = json.loads(result['body'])
            assert body['success'] is True


class TestBotDetails:
    """Test WABA Bot details endpoint (GET /{WABA-Bot-ID})."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _get_bot_details
                self.get_bot = _get_bot_details

    def test_requires_bot_id(self):
        result = self.get_bot('', {})
        assert result['statusCode'] == 400

    def test_success(self):
        # Pilot uses the shared MetaGraphClient: MetaGraphClient().get(...)
        with patch('handler.MetaGraphClient') as MockClient:
            MockClient.return_value.get.return_value = {
                'id': 'bot-123',
                'prompts': ['Hello!', 'How can I help?'],
                'commands': [{'command_name': '/help', 'command_description': 'Get help'}],
                'enable_welcome_message': True,
            }
            MockClient.is_error.return_value = False
            result = self.get_bot('bot-123', {})
            body = json.loads(result['body'])
            assert body['bot']['id'] == 'bot-123'
            assert len(body['bot']['prompts']) == 2
            assert body['bot']['enable_welcome_message'] is True

    def test_custom_fields(self):
        with patch('handler.MetaGraphClient') as MockClient:
            MockClient.return_value.get.return_value = {'id': 'bot-123', 'commands': []}
            MockClient.is_error.return_value = False
            self.get_bot('bot-123', {'fields': 'id,commands'})
            call_args = MockClient.return_value.get.call_args
            assert 'id,commands' in str(call_args)


class TestWebhookSubscribeOverride:
    """Test webhook subscribe with override_callback_uri and verify_token."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _subscribe_webhook
                self.subscribe = _subscribe_webhook

    def test_subscribe_with_override(self):
        with patch('handler._graph_api', return_value={'success': True}) as mock_api:
            result = self.subscribe('2094615664435155', {
                'override_callback_uri': 'https://example.com/webhook',
                'verify_token': 'my_token',
            })
            body = json.loads(result['body'])
            assert body['success'] is True
            payload = mock_api.call_args[1].get('payload') or mock_api.call_args[0][2] if len(mock_api.call_args[0]) > 2 else mock_api.call_args[1].get('payload')
            assert payload['override_callback_uri'] == 'https://example.com/webhook'
            assert payload['verify_token'] == 'my_token'

    def test_subscribe_without_override(self):
        with patch('handler._graph_api', return_value={'success': True}) as mock_api:
            self.subscribe('2094615664435155', {})
            # Should pass None payload when no overrides
            call_kwargs = mock_api.call_args
            payload = call_kwargs[1].get('payload') if call_kwargs[1] else None
            assert payload is None


class TestCallHoursValidation:
    """Test _validate_call_hours per Meta Configure Call Settings rules."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _validate_call_hours
                self.validate = _validate_call_hours

    def test_valid_schedule_passes(self):
        ch = {
            'status': 'ENABLED',
            'timezone_id': 'Asia/Kolkata',
            'weekly_operating_hours': [
                {'day_of_week': 'MONDAY', 'open_time': '0900', 'close_time': '1700'},
            ],
        }
        assert self.validate(ch) is None

    def test_enabled_requires_timezone(self):
        ch = {'status': 'ENABLED', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '0900', 'close_time': '1700'}]}
        assert 'timezone' in (self.validate(ch) or '').lower()

    def test_enabled_requires_non_empty_hours(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': []}
        assert 'empty' in (self.validate(ch) or '').lower()

    def test_open_must_be_before_close(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '1700', 'close_time': '0900'}]}
        assert 'earlier' in (self.validate(ch) or '').lower()

    def test_bad_time_format_rejected(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '9:00', 'close_time': '17:00'}]}
        assert 'HHMM' in (self.validate(ch) or '')

    def test_max_two_entries_per_day(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '0900', 'close_time': '1000'},
            {'day_of_week': 'MONDAY', 'open_time': '1100', 'close_time': '1200'},
            {'day_of_week': 'MONDAY', 'open_time': '1300', 'close_time': '1400'}]}
        assert 'More than 2' in (self.validate(ch) or '')

    def test_overlapping_schedule_rejected(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '0900', 'close_time': '1200'},
            {'day_of_week': 'MONDAY', 'open_time': '1100', 'close_time': '1400'}]}
        assert 'Overlapping' in (self.validate(ch) or '')

    def test_two_non_overlapping_entries_ok(self):
        ch = {'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '0900', 'close_time': '1200'},
            {'day_of_week': 'MONDAY', 'open_time': '1300', 'close_time': '1700'}]}
        assert self.validate(ch) is None

    def test_past_holiday_rejected(self):
        ch = {'status': 'DISABLED', 'weekly_operating_hours': [
            {'day_of_week': 'MONDAY', 'open_time': '0000', 'close_time': '2359'}],
            'holiday_schedule': [{'date': '2020-01-01'}]}
        assert 'past' in (self.validate(ch) or '').lower()

    def test_bad_holiday_date_format_rejected(self):
        ch = {'status': 'DISABLED', 'holiday_schedule': [{'date': '01/01/2030'}]}
        assert 'date format' in (self.validate(ch) or '').lower()

    def test_disabled_24x7_schedule_ok(self):
        # Mirrors the frontend's DISABLED 24/7 payload — must validate cleanly.
        ch = {
            'status': 'DISABLED',
            'timezone_id': 'Asia/Kolkata',
            'weekly_operating_hours': [
                {'day_of_week': d, 'open_time': '0000', 'close_time': '2359'}
                for d in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']
            ],
        }
        assert self.validate(ch) is None


class TestUpdateCallingSettings:
    """Test _update_calling_settings body mapping and validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _update_calling_settings
                self.update = _update_calling_settings

    def test_audio_codecs_mapped(self):
        with patch('handler._graph_api', return_value={'success': True}) as gapi:
            resp = self.update('123', {'audioCodecs': ['PCMA', 'pcmu', 'BAD']})
            assert resp['statusCode'] == 200
            payload = gapi.call_args.kwargs['payload']
            assert payload['calling']['audio']['additional_codecs'] == ['PCMA', 'PCMU']

    def test_call_icons_list_wrapped(self):
        with patch('handler._graph_api', return_value={'ok': 1}) as gapi:
            self.update('123', {'callIcons': ['IN', 'AE']})
            payload = gapi.call_args.kwargs['payload']
            assert payload['calling']['call_icons'] == {'restrict_to_user_countries': ['IN', 'AE']}

    def test_callback_permission_mapped(self):
        with patch('handler._graph_api', return_value={'ok': 1}) as gapi:
            self.update('123', {'callbackPermissionStatus': 'ENABLED'})
            payload = gapi.call_args.kwargs['payload']
            assert payload['calling']['callback_permission_status'] == 'ENABLED'

    def test_invalid_call_hours_rejected_before_api(self):
        with patch('handler._graph_api') as gapi:
            resp = self.update('123', {'callHours': {
                'status': 'ENABLED', 'timezone_id': 'Asia/Kolkata',
                'weekly_operating_hours': [
                    {'day_of_week': 'MONDAY', 'open_time': '1700', 'close_time': '0900'}]}})
            assert resp['statusCode'] == 400
            gapi.assert_not_called()

    def test_empty_body_rejected(self):
        resp = self.update('123', {})
        assert resp['statusCode'] == 400

    def test_voicemail_passthrough(self):
        with patch('handler._graph_api', return_value={'ok': 1}) as gapi:
            vm = {'status': 'ENABLED', 'timeout_seconds': 30}
            self.update('123', {'voicemail': vm})
            payload = gapi.call_args.kwargs['payload']
            assert payload['calling']['voicemail'] == vm

    def test_voicemail_non_object_rejected(self):
        with patch('handler._graph_api') as gapi:
            resp = self.update('123', {'voicemail': 'ENABLED'})
            assert resp['statusCode'] == 400
            gapi.assert_not_called()

    def test_voicemail_empty_object_omitted(self):
        # An empty {} voicemail should not be forwarded, and with no other fields → 400
        resp = self.update('123', {'voicemail': {}})
        assert resp['statusCode'] == 400


class TestFlattenPaymentConfigurations:
    """The live `GET /{waba}/payment_configurations` edge nests configs one level down under
    data[].payment_configurations[]. _flatten_payment_configurations must normalise that to the
    flat {data:[config,...]} shape payment_readiness.evaluate consumes. Measured 2026-10-08."""

    def _handler(self):
        from handler import _flatten_payment_configurations
        return _flatten_payment_configurations

    def test_flattens_the_real_nested_live_shape(self):
        flat = self._handler()({
            'data': [{'payment_configurations': [
                {'configuration_name': 'WECAREUPI', 'status': 'Active'},
                {'configuration_name': 'WECAREDIGITAL', 'status': 'Active',
                 'provider_mid': 'acc_TTFSyolquKEZEy', 'provider_name': 'Razorpay'},
            ]}]
        })
        names = [c['configuration_name'] for c in flat['data']]
        assert names == ['WECAREUPI', 'WECAREDIGITAL']
        assert flat['data'][1]['provider_mid'] == 'acc_TTFSyolquKEZEy'

    def test_passes_an_error_response_through_unchanged(self):
        err = {'error': {'message': 'boom', 'code': 100}}
        assert self._handler()(err) == err

    def test_already_flat_list_is_preserved(self):
        flat = self._handler()({'data': [{'configuration_name': 'WECAREDIGITAL'}]})
        assert flat['data'] == [{'configuration_name': 'WECAREDIGITAL'}]

    def test_empty_data_stays_empty(self):
        assert self._handler()({'data': []}) == {'data': []}
