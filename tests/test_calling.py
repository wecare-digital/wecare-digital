"""Tests for WhatsApp Calling webhook handler."""
import json
import pytest
import hmac
import hashlib
import time
from unittest.mock import patch, MagicMock
from decimal import Decimal
from pathlib import Path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))


class TestWebhookSignatureVerification:
    """Test X-Hub-Signature-256 verification on calling webhooks."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test_token'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _verify_webhook_signature
                self.verify = _verify_webhook_signature

    def test_missing_signature_returns_false(self):
        event = {'headers': {}, 'body': '{}'}
        assert self.verify(event, 'req-1') is False

    def test_valid_signature_returns_true(self):
        secret = 'test_secret'
        body = '{"test": true}'
        sig = 'sha256=' + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': secret, 'app_secret2': ''}):
            assert self.verify(event, 'req-2') is True

    def test_invalid_signature_returns_false(self):
        event = {'headers': {'x-hub-signature-256': 'sha256=invalid'}, 'body': '{}'}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': 'real_secret', 'app_secret2': ''}):
            assert self.verify(event, 'req-3') is False

    def test_no_app_secret_fails_closed(self):
        """P0 Security: No app secrets configured → reject (never fail open)."""
        event = {'headers': {'x-hub-signature-256': 'sha256=anything'}, 'body': '{}'}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': '', 'app_secret2': ''}):
            assert self.verify(event, 'req-4') is False


class TestWebhookTimestampValidation:
    """Test replay protection via timestamp validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _validate_webhook_timestamp
                self.validate = _validate_webhook_timestamp

    def test_recent_timestamp_valid(self):
        now = int(time.time())
        body = {'entry': [{'time': str(now - 10)}]}
        assert self.validate(body, 'req-1') is True

    def test_stale_timestamp_rejected(self):
        old = int(time.time()) - 600  # 10 minutes ago
        body = {'entry': [{'time': str(old)}]}
        assert self.validate(body, 'req-2') is False

    def test_no_timestamp_passes(self):
        body = {'entry': [{'changes': [{'value': {}}]}]}
        assert self.validate(body, 'req-3') is True

    def test_stale_call_timestamp_rejected(self):
        old = int(time.time()) - 400
        body = {'entry': [{'changes': [{'value': {'calls': [{'timestamp': str(old)}]}}]}]}
        assert self.validate(body, 'req-4') is False


class TestWebhookVerification:
    """Test GET webhook verification (hub.challenge)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test_verify'}):
            with patch('boto3.resource'), patch('boto3.client'):
                # Force reload to pick up env var
                import importlib
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                from handler import _verify_webhook
                self.verify_webhook = _verify_webhook

    def test_valid_verification(self):
        with patch('handler._get_verify_token', return_value='test_verify'):
            params = {'hub.mode': 'subscribe', 'hub.verify_token': 'test_verify', 'hub.challenge': '12345'}
            result = self.verify_webhook(params, 'req-1')
            assert result['statusCode'] == 200
            assert result['body'] == '12345'

    def test_invalid_token(self):
        with patch('handler._get_verify_token', return_value='test_verify'):
            params = {'hub.mode': 'subscribe', 'hub.verify_token': 'wrong', 'hub.challenge': '12345'}
            result = self.verify_webhook(params, 'req-2')
            assert result['statusCode'] == 403

    def test_no_configured_token_refuses_instead_of_echoing_the_challenge(self):
        """The old form compared against a possibly-empty module constant, so a
        request that simply omitted hub.verify_token matched and got the
        challenge back. Absent configuration must fail closed."""
        with patch('handler._get_verify_token', return_value=''):
            params = {'hub.mode': 'subscribe', 'hub.challenge': '12345'}
            result = self.verify_webhook(params, 'req-3')
            assert result['statusCode'] == 403
            assert '12345' not in str(result.get('body', ''))

    def test_token_is_read_from_secrets_manager_not_the_environment(self):
        """Guards the reason for the change: no VERIFY_TOKEN env var may be read,
        because that puts the live value in the function configuration."""
        import handler
        src = Path(handler.__file__).read_text()
        assert "os.environ.get('VERIFY_TOKEN'" not in src
        assert 'os.environ.get("VERIFY_TOKEN"' not in src
        assert not hasattr(handler, 'VERIFY_TOKEN')


class TestCallEventHandling:
    """Test call event processing."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test'}):
            with patch('boto3.resource') as mock_res, patch('boto3.client'):
                self.mock_table = MagicMock()
                mock_res.return_value.Table.return_value = self.mock_table
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                from handler import _handle_call_event
                self.handle_event = _handle_call_event

    def test_connect_event_stores_log(self):
        call = {
            'event': 'connect',
            'id': 'call-123',
            'from': '+919330994400',
            'to': '+919903300044',
            'direction': 'USER_INITIATED',
            'session': {'sdp': 'v=0\r\n...', 'sdp_type': 'offer'},
            'timestamp': str(int(time.time())),
        }
        metadata = {'phone_number_id': '1016149501586345', 'display_phone_number': '919330994400'}
        with patch('handler._store_call_log') as mock_store, \
             patch('handler._send_call_whatsapp_notification'), \
             patch('handler._is_auto_pickup_enabled', return_value=False):
            self.handle_event('waba-1', call, metadata, [], 'req-1')
            # connect now also auto-grants permission (2nd store); first store is the connect log
            assert mock_store.called
            stored = mock_store.call_args_list[0].args[0]
            assert stored['callId'] == 'call-123'
            assert stored['status'] == 'ringing'

    def test_terminate_event_stores_log(self):
        call = {
            'event': 'terminate',
            'id': 'call-456',
            'from': '+919330994400',
            'reason': 'caller_hangup',
            'duration': 45,
            'timestamp': str(int(time.time())),
        }
        metadata = {'phone_number_id': '1016149501586345'}
        with patch('handler._store_call_log') as mock_store, \
             patch('handler._send_post_call_reaction'), \
             patch('handler._is_sms_on_call_enabled', return_value=False):
            self.handle_event('waba-1', call, metadata, [], 'req-2')
            assert mock_store.called
            stored = mock_store.call_args_list[0].args[0]
            assert stored['status'] == 'ended'
            assert stored['duration'] == 45

    def test_permission_event_not_stored(self):
        # call_permission_status is now log-only (permission is auto-granted post-call),
        # so it no longer writes a call-log row.
        call = {
            'event': 'call_permission_status',
            'status': 'GRANTED',
            'from': '+919330994400',
            'timestamp': str(int(time.time())),
        }
        metadata = {'phone_number_id': '1016149501586345'}
        with patch('handler._store_call_log') as mock_store:
            self.handle_event('waba-1', call, metadata, [], 'req-3')
            mock_store.assert_not_called()

    def test_bsuid_extraction_from_contacts(self):
        call = {
            'event': 'connect',
            'id': 'call-789',
            'from': '+919330994400',
            'direction': 'USER_INITIATED',
            'session': {'sdp': 'v=0\r\n'},
            'timestamp': str(int(time.time())),
        }
        contacts = [{'profile': {'name': 'Test User', 'username': '@testuser'}, 'user_id': 'IN.123456'}]
        metadata = {'phone_number_id': '1016149501586345'}
        with patch('handler._store_call_log') as mock_store, \
             patch('handler._send_call_whatsapp_notification'), \
             patch('handler._is_auto_pickup_enabled', return_value=False):
            self.handle_event('waba-1', call, metadata, contacts, 'req-4')
            stored = mock_store.call_args_list[0].args[0]  # connect log
            assert stored['callerName'] == 'Test User'
            assert stored.get('callerUsername') == '@testuser'


class TestCredentialRouting:
    """Test that credentials are resolved correctly per phone_number_id."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test'}):
            with patch('boto3.resource'), patch('boto3.client'):
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                import handler
                self.handler = handler

    def test_waba1_uses_token1(self):
        """WABA1 phone (1016149501586345) should resolve to token1."""
        with patch.object(self.handler, '_token_cache', {
            'loaded': True, 'token1': 'tok_waba1', 'token2': 'tok_waba2',
            'app_secret1': 'sec1', 'app_secret2': 'sec2',
        }):
            assert self.handler._get_meta_token('1016149501586345') == 'tok_waba1'
            assert self.handler._get_app_secret('1016149501586345') == 'sec1'

    def test_waba2_phone_resolves_to_token1_after_single_app_migration(self):
        """WABA2 phone now uses the WECARE.DIGITAL app (token1) — WABA2_IDS is empty."""
        with patch.object(self.handler, '_token_cache', {
            'loaded': True, 'token1': 'tok_waba1', 'token2': 'tok_waba2',
            'app_secret1': 'sec1', 'app_secret2': 'sec2',
        }):
            assert self.handler._get_meta_token('997428863451102') == 'tok_waba1'
            assert self.handler._get_app_secret('997428863451102') == 'sec1'

    def test_waba2_id_resolves_to_token1_after_single_app_migration(self):
        """WABA2 ID also uses token1 now (single-app architecture)."""
        with patch.object(self.handler, '_token_cache', {
            'loaded': True, 'token1': 'tok_waba1', 'token2': 'tok_waba2',
            'app_secret1': 'sec1', 'app_secret2': 'sec2',
        }):
            assert self.handler._get_meta_token('2513394156072604') == 'tok_waba1'

    def test_unknown_phone_defaults_to_token1(self):
        """Unknown phone_number_id should default to token1."""
        with patch.object(self.handler, '_token_cache', {
            'loaded': True, 'token1': 'tok_waba1', 'token2': 'tok_waba2',
            'app_secret1': 'sec1', 'app_secret2': 'sec2',
        }):
            assert self.handler._get_meta_token('999999999') == 'tok_waba1'

    def test_none_phone_defaults_to_token1(self):
        """None phone_number_id should default to token1."""
        with patch.object(self.handler, '_token_cache', {
            'loaded': True, 'token1': 'tok_waba1', 'token2': 'tok_waba2',
            'app_secret1': 'sec1', 'app_secret2': 'sec2',
        }):
            assert self.handler._get_meta_token(None) == 'tok_waba1'


class TestMultiSecretWebhookVerification:
    """Test webhook signature verification with multiple app secrets."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test'}):
            with patch('boto3.resource'), patch('boto3.client'):
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                from handler import _verify_webhook_signature
                self.verify = _verify_webhook_signature

    def _sign(self, body: str, secret: str) -> str:
        return 'sha256=' + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    def test_signature_matches_secret1(self):
        body = '{"object":"whatsapp_business_account"}'
        sig = self._sign(body, 'secret_app1')
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': 'secret_app1', 'app_secret2': 'secret_app2'}):
            assert self.verify(event, 'req-1') is True

    def test_signature_matches_secret2(self):
        body = '{"object":"whatsapp_business_account"}'
        sig = self._sign(body, 'secret_app2')
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': 'secret_app1', 'app_secret2': 'secret_app2'}):
            assert self.verify(event, 'req-2') is True

    def test_signature_matches_neither_secret(self):
        body = '{"object":"whatsapp_business_account"}'
        sig = self._sign(body, 'wrong_secret')
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': 'secret_app1', 'app_secret2': 'secret_app2'}):
            assert self.verify(event, 'req-3') is False

    def test_only_secret2_configured(self):
        body = '{"test": true}'
        sig = self._sign(body, 'only_secret2')
        event = {'headers': {'x-hub-signature-256': sig}, 'body': body}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': '', 'app_secret2': 'only_secret2'}):
            assert self.verify(event, 'req-4') is True

    def test_base64_encoded_body(self):
        import base64
        body = '{"object":"whatsapp_business_account"}'
        encoded = base64.b64encode(body.encode()).decode()
        sig = self._sign(body, 'test_secret')
        event = {'headers': {'x-hub-signature-256': sig}, 'body': encoded, 'isBase64Encoded': True}
        with patch('handler._token_cache', {'loaded': True, 'app_secret1': 'test_secret', 'app_secret2': ''}):
            assert self.verify(event, 'req-5') is True


class TestIVRAutoPickup:
    """Test IVR auto-pickup flow — all phones use Direct API."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test'}):
            with patch('boto3.resource'), patch('boto3.client'):
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                import handler
                self.handler = handler

    def test_all_phones_use_direct_api_full_flow(self):
        """All phones should pre_accept → accept → audio greeting → terminate via Direct API."""
        with patch.object(self.handler, '_update_call_status'), \
             patch.object(self.handler, '_send_audio_to_caller') as mock_audio, \
             patch.object(self.handler, '_meta_api_call', return_value={'success': True}) as mock_api, \
             patch('time.sleep'):
            self.handler._auto_pickup_and_play('call-1', '1016149501586345', '+919876543210', 'sdp')
            actions = [c.args[2].get('action') for c in mock_api.call_args_list
                       if len(c.args) >= 3 and isinstance(c.args[2], dict)]
            assert 'pre_accept' in actions
            assert 'terminate' in actions
            mock_audio.assert_called_once()

    def test_direct_api_phone2_full_flow(self):
        """Phone 2 (WABA-T) should also run the full Direct API flow on its own phone id."""
        with patch.object(self.handler, '_update_call_status'), \
             patch.object(self.handler, '_send_audio_to_caller'), \
             patch.object(self.handler, '_meta_api_call', return_value={'success': True}) as mock_api, \
             patch('time.sleep'):
            self.handler._auto_pickup_and_play('call-2', '1055232054343117', '+919876543210', 'sdp')
            endpoints = [c.args[0] for c in mock_api.call_args_list]
            actions = [c.args[2].get('action') for c in mock_api.call_args_list
                       if len(c.args) >= 3 and isinstance(c.args[2], dict)]
            assert all(e == '1055232054343117/calls' for e in endpoints)
            assert 'pre_accept' in actions and 'terminate' in actions

    def test_waba2_phone_uses_direct_api(self):
        """WABA2 phone should also use the full Direct API flow (not skipped)."""
        with patch.object(self.handler, '_update_call_status'), \
             patch.object(self.handler, '_send_audio_to_caller'), \
             patch.object(self.handler, '_meta_api_call', return_value={'success': True}) as mock_api, \
             patch('time.sleep'):
            self.handler._auto_pickup_and_play('call-3', '997428863451102', '+919876543210', 'sdp')
            actions = [c.args[2].get('action') for c in mock_api.call_args_list
                       if len(c.args) >= 3 and isinstance(c.args[2], dict)]
            assert 'pre_accept' in actions and 'terminate' in actions

    def test_auto_pickup_enabled_triggers_ivr(self):
        """When auto-pickup is enabled, _handle_call_event should call _auto_pickup_and_play."""
        call = {
            'event': 'connect', 'id': 'call-ivr-1', 'from': '+919876543210',
            'direction': 'USER_INITIATED', 'session': {'sdp': 'v=0\r\n'},
            'timestamp': str(int(time.time())),
        }
        metadata = {'phone_number_id': '1016149501586345', 'display_phone_number': '919330994400'}
        with patch.object(self.handler, '_store_call_log'), \
             patch.object(self.handler, '_send_call_whatsapp_notification'), \
             patch.object(self.handler, '_is_auto_pickup_enabled', return_value=True), \
             patch.object(self.handler, '_auto_pickup_and_play') as mock_ivr:
            self.handler._handle_call_event('waba-1', call, metadata, [], 'req-1')
            mock_ivr.assert_called_once_with('call-ivr-1', '1016149501586345', '+919876543210', 'v=0\r\n')

    def test_auto_pickup_disabled_does_not_trigger_ivr(self):
        """When auto-pickup is disabled, _handle_call_event should NOT call _auto_pickup_and_play."""
        call = {
            'event': 'connect', 'id': 'call-man-1', 'from': '+919876543210',
            'direction': 'USER_INITIATED', 'session': {'sdp': 'v=0\r\n'},
            'timestamp': str(int(time.time())),
        }
        metadata = {'phone_number_id': '1016149501586345', 'display_phone_number': '919330994400'}
        with patch.object(self.handler, '_store_call_log'), \
             patch.object(self.handler, '_send_call_whatsapp_notification'), \
             patch.object(self.handler, '_is_auto_pickup_enabled', return_value=False), \
             patch.object(self.handler, '_auto_pickup_and_play') as mock_ivr:
            self.handler._handle_call_event('waba-1', call, metadata, [], 'req-2')
            mock_ivr.assert_not_called()


class TestTheIvrButtonMenuIsGone:
    """The IVR button menu was deleted on 2026-10-02.

    This class used to assert PARITY between the two phones' IVR button menus and
    that every button had a reply. There is no button menu now, so those four
    assertions were replaced by their opposite: the five symbols must be absent.

    `test_all_phones_use_direct_api` is carried over word for word - it was never
    about a menu, and the Direct API fact it pins is still true.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test'}):
            with patch('boto3.resource'), patch('boto3.client'):
                if 'handler' in sys.modules:
                    del sys.modules['handler']
                import handler
                self.handler = handler

    @pytest.mark.parametrize('name', [
        '_SHARED_IVR_MENU', 'IVR_MENUS', 'IVR_DEFAULT_MENU', 'IVR_RESPONSES',
        '_get_ivr_menu',
    ])
    def test_the_menu_symbol_is_deleted(self, name):
        assert not hasattr(self.handler, name), f'{name} is back in whatsapp-calling'

    def test_the_audio_greeting_is_a_plain_constant(self):
        """The Polly greeting used to be read out of the menu's 'greeting' key. It is
        a module constant now, so the IVR audio still has words to say."""
        assert isinstance(self.handler.IVR_GREETING_TEXT, str)
        assert self.handler.IVR_GREETING_TEXT.strip()
        assert 'menu' not in self.handler.IVR_GREETING_TEXT.lower()

    def test_all_phones_use_direct_api(self):
        """All phones should be in DIRECT_API_META_PHONE_IDS."""
        assert self.handler.PHONE1_META_ID in self.handler.DIRECT_API_META_PHONE_IDS
        assert self.handler.PHONE2_META_ID in self.handler.DIRECT_API_META_PHONE_IDS


class TestAccountSettingsUpdate:
    """Test _process_account_settings_update persists settings + restriction events."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test_token'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _process_account_settings_update
                self.process = _process_account_settings_update

    def test_settings_update_stored(self):
        value = {'calling': {'status': 'ENABLED'}, 'phone_number_id': '1016149501586345'}
        with patch('handler._store_call_log') as store:
            self.process('WABA1', value, 'req-1')
            assert store.called
            logged = store.call_args_list[0].args[0]
            assert logged['eventType'] == 'settings_update'
            assert logged['status'] == 'ENABLED'

    def test_restriction_event_stored_separately(self):
        value = {'calling': {'status': 'DISABLED', 'restrictions': [{'type': 'ACCOUNT_RESTRICTION'}]}}
        with patch('handler._store_call_log') as store:
            self.process('WABA1', value, 'req-2')
            event_types = [c.args[0]['eventType'] for c in store.call_args_list]
            assert 'settings_update' in event_types
            assert 'calling_restriction' in event_types

    def test_non_dict_value_safe(self):
        with patch('handler._store_call_log') as store:
            self.process('WABA1', 'not-a-dict', 'req-3')
            assert not store.called


class TestAutoThumbReaction:
    """Test _react_thumbs_up — auto 👍 on call-related WhatsApp messages, both WABAs."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test_token'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _react_thumbs_up
                self.react = _react_thumbs_up

    def test_reaction_sent_from_same_waba(self):
        with patch('handler._is_auto_thumb_reaction_enabled', return_value=True):
            with patch('handler._meta_api_call', return_value={'messages': [{'id': 'r1'}]}) as api:
                ok = self.react('WABA2_PHONE', '+919812345678', 'wamid.ABC', 'req-1')
                assert ok is True
                # Must POST to the SAME meta_id that sent the original message
                assert api.call_args.args[0] == 'WABA2_PHONE/messages'
                assert api.call_args.kwargs['phone_number_id'] == 'WABA2_PHONE'
                payload = api.call_args.args[2]
                assert payload['type'] == 'reaction'
                assert payload['reaction']['message_id'] == 'wamid.ABC'
                assert payload['reaction']['emoji'] == '\U0001F44D'
                assert payload['to'] == '919812345678'  # + stripped

    def test_missing_message_id_skips(self):
        with patch('handler._meta_api_call') as api:
            assert self.react('WABA1_PHONE', '+919812345678', '', 'req-2') is False
            api.assert_not_called()

    def test_missing_meta_id_skips(self):
        with patch('handler._meta_api_call') as api:
            assert self.react('', '+919812345678', 'wamid.X', 'req-3') is False
            api.assert_not_called()

    def test_disabled_toggle_skips(self):
        with patch('handler._is_auto_thumb_reaction_enabled', return_value=False):
            with patch('handler._meta_api_call') as api:
                assert self.react('WABA1_PHONE', '+91981', 'wamid.X', 'req-4') is False
                api.assert_not_called()

    def test_meta_error_returns_false(self):
        with patch('handler._is_auto_thumb_reaction_enabled', return_value=True):
            with patch('handler._meta_api_call', return_value={'error': 'message not found'}):
                assert self.react('WABA1_PHONE', '+91981', 'wamid.X', 'req-5') is False

    def test_api_exception_is_swallowed(self):
        with patch('handler._is_auto_thumb_reaction_enabled', return_value=True):
            with patch('handler._meta_api_call', side_effect=RuntimeError('boom')):
                assert self.react('WABA1_PHONE', '+91981', 'wamid.X', 'req-6') is False


class TestCallingAutoThumbConfig:
    """Unified runtime toggle: _get_config exposes autoThumb, _update_config writes
    the unified key, and _is_auto_thumb_reaction_enabled reads it."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test_token'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_reader_uses_unified_key(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'configValue': 'false'}}
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table):
            assert self.h._is_auto_thumb_reaction_enabled() is False
            mock_table.get_item.assert_called_with(Key={'id': 'whatsapp_auto_thumb'})

    def test_reader_defaults_true_when_unset(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table):
            assert self.h._is_auto_thumb_reaction_enabled() is True

    def test_get_config_includes_auto_thumb(self):
        with patch.object(self.h, '_is_auto_pickup_enabled', return_value=True), \
             patch.object(self.h, '_get_auto_pickup_audio_url', return_value='u'), \
             patch.object(self.h, '_is_sms_on_call_enabled', return_value=True), \
             patch.object(self.h, '_is_postcall_wa_enabled', return_value=True), \
             patch.object(self.h, '_is_auto_thumb_reaction_enabled', return_value=True):
            resp = self.h._get_config('req-1')
            body = json.loads(resp['body'])
            assert body['autoThumb'] is True

    def test_update_config_writes_unified_key(self):
        mock_table = MagicMock()
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table):
            resp = self.h._update_config({'body': json.dumps({'autoThumb': False})}, 'req-2')
            assert resp['statusCode'] == 200
            keys_written = [c.kwargs['Item']['id'] for c in mock_table.put_item.call_args_list]
            assert 'whatsapp_auto_thumb' in keys_written


class TestCallingRouteAuthorization:
    """Exact Meta callback is public; all calling management routes are Admin-only."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'VERIFY_TOKEN': 'test-token'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_exact_get_callback_skips_cognito_auth(self):
        event = {
            'requestContext': {
                'apiId': 'api-1',
                'http': {'method': 'GET', 'path': '/whatsapp', 'sourceIp': '127.0.0.1'},
            },
            'queryStringParameters': {},
        }
        expected = {'statusCode': 200, 'body': 'challenge'}
        with patch.object(self.h, '_verify_webhook', return_value=expected), \
                patch.object(self.h, 'require_auth') as require_auth:
            assert self.h.handler(event, None) is expected
        require_auth.assert_not_called()

    def test_management_get_requires_admin(self):
        event = {
            'requestContext': {
                'apiId': 'api-1',
                'http': {'method': 'GET', 'path': '/whatsapp/config', 'sourceIp': '127.0.0.1'},
            },
        }
        denied = {'statusCode': 403, 'body': '{}'}
        with patch.object(self.h, 'require_auth', return_value=denied) as require_auth, \
                patch.object(self.h, '_get_config') as get_config:
            assert self.h.handler(event, None) is denied
        require_auth.assert_called_once_with(event, required_role='Admin')
        get_config.assert_not_called()

    def test_internal_iam_action_remains_before_http_auth(self):
        event = {'action': 'cert_check'}
        expected = {'statusCode': 200, 'body': '{}'}
        with patch.object(self.h, '_handle_cert_check', return_value=expected), \
                patch.object(self.h, 'require_auth') as require_auth:
            assert self.h.handler(event, None) is expected
        require_auth.assert_not_called()

def test_post_call_whatsapp_cannot_be_disabled_by_legacy_config():
    import importlib
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-calling'))
    with patch('boto3.resource'), patch('boto3.client'):
        module = importlib.import_module('handler')
    with patch.object(module, 'dynamodb') as db:
        db.Table.return_value.get_item.return_value = {'Item': {'configValue': 'false'}}
        assert module._is_postcall_wa_enabled() is True
        db.Table.assert_not_called()
