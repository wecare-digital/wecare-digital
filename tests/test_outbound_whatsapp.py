"""Tests for outbound WhatsApp Lambda handler — message payload building."""
import io
import json
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))


class TestBuildMessagePayload:
    """Test _build_message_payload for all message types."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        """Mock AWS clients before importing handler."""
        with patch.dict(os.environ, {
            'AWS_REGION': 'us-east-1',
            'SEND_MODE': 'DRY_RUN',
        }):
            with patch('boto3.resource'), \
                 patch('boto3.client'):
                from handler import _build_message_payload, _normalize_phone_number
                self.build = _build_message_payload
                self.normalize = _normalize_phone_number

    def test_text_message(self):
        payload = self.build('+919330994400', 'Hello world', None, None, False, None, [])
        assert payload['type'] == 'text'
        assert payload['text']['body'] == 'Hello world'
        assert payload['messaging_product'] == 'whatsapp'

    def test_text_with_url_preview(self):
        payload = self.build('+919330994400', 'Check https://example.com', None, None, False, None, [])
        assert payload['text']['preview_url'] is True

    def test_text_without_url_preview(self):
        payload = self.build('+919330994400', 'No links here', None, None, False, None, [])
        assert payload['text']['preview_url'] is False

    def test_image_message(self):
        payload = self.build('+919330994400', 'Caption', 'image/jpeg', 'media-123', False, None, [])
        assert payload['type'] == 'image'
        assert payload['image']['id'] == 'media-123'
        assert payload['image']['caption'] == 'Caption'

    def test_video_message(self):
        payload = self.build('+919330994400', '', 'video/mp4', 'media-456', False, None, [])
        assert payload['type'] == 'video'
        assert payload['video']['id'] == 'media-456'

    def test_audio_message(self):
        payload = self.build('+919330994400', '', 'audio/ogg', 'media-789', False, None, [])
        assert payload['type'] == 'audio'

    def test_document_message_with_filename(self):
        payload = self.build('+919330994400', '', 'document/pdf', 'media-doc', False, None, [], filename='report.pdf')
        assert payload['type'] == 'document'
        assert payload['document']['filename'] == 'report.pdf'

    def test_sticker_message(self):
        payload = self.build('+919330994400', '', 'sticker', 'sticker-id', False, None, [])
        assert payload['type'] == 'sticker'

    def test_invalid_media_type_fallback(self):
        payload = self.build('+919330994400', '', 'application/zip', 'media-zip', False, None, [])
        assert payload['type'] == 'document'

    def test_template_message_basic(self):
        payload = self.build('+919330994400', '', None, None, True, 'hello_world', ['en'])
        assert payload['type'] == 'template'
        assert payload['template']['name'] == 'hello_world'
        assert payload['template']['language']['code'] == 'en'

    def test_template_with_params(self):
        payload = self.build('+919330994400', '', None, None, True, 'order_update', ['en', 'John', 'ORD-123'])
        assert payload['type'] == 'template'
        components = payload['template']['components']
        body_comp = [c for c in components if c['type'] == 'body']
        assert len(body_comp) == 1
        assert len(body_comp[0]['parameters']) == 2

    def test_otp_template_copy_code(self):
        payload = self.build('+919330994400', '', None, None, True, 'auth_otp', ['en', '123456'],
                           is_otp_template=True, otp_code='123456', otp_button_type='copy_code')
        assert payload['type'] == 'template'
        components = payload['template']['components']
        btn = [c for c in components if c['type'] == 'button']
        assert len(btn) == 1
        assert btn[0]['sub_type'] == 'copy_code'

    def test_otp_template_url(self):
        payload = self.build('+919330994400', '', None, None, True, 'auth_otp', ['en'],
                           is_otp_template=True, otp_code='654321', otp_button_type='url')
        btn = [c for c in payload['template']['components'] if c['type'] == 'button']
        assert btn[0]['sub_type'] == 'url'

    def test_contact_message(self):
        contact_data = json.dumps({
            '_type': 'contacts',
            'contacts': [{'name': {'formatted_name': 'John Doe'}, 'phones': [{'phone': '+1234567890'}]}]
        })
        payload = self.build('+919330994400', contact_data, None, None, False, None, [])
        assert payload['type'] == 'contacts'
        assert len(payload['contacts']) == 1

    def test_location_message(self):
        loc_data = json.dumps({
            '_type': 'location',
            'latitude': 37.4847,
            'longitude': -122.1477,
            'name': 'Meta HQ',
            'address': '1 Hacker Way'
        })
        payload = self.build('+919330994400', loc_data, None, None, False, None, [])
        assert payload['type'] == 'location'
        assert payload['location']['name'] == 'Meta HQ'

    def test_location_request_message(self):
        req_data = json.dumps({
            '_type': 'location_request',
            'body': 'Share your delivery location'
        })
        payload = self.build('+919330994400', req_data, None, None, False, None, [])
        assert payload['type'] == 'interactive'
        assert payload['interactive']['type'] == 'location_request_message'

    def test_address_message(self):
        addr_data = json.dumps({
            '_type': 'address',
            'body': 'Provide your shipping address',
            'parameters': {'country': 'IN'}
        })
        payload = self.build('+919330994400', addr_data, None, None, False, None, [])
        assert payload['type'] == 'interactive'
        assert payload['interactive']['type'] == 'address_message'

    def test_bsuid_recipient(self):
        payload = self.build('', 'Hello', None, None, False, None, [],
                           recipient_bsuid='US.13491208655302741918')
        assert payload.get('recipient') == 'US.13491208655302741918'

    def test_phone_normalization(self):
        normalized = self.normalize('+91 9330-994400')
        assert normalized.isdigit()
        assert '919330994400' in normalized


class TestMetaMessageErrors:
    """Test that error code mapping is complete."""

    def test_error_map_exists(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import META_MESSAGE_ERRORS
                assert 131056 in META_MESSAGE_ERRORS  # Pair rate limit
                assert 131047 in META_MESSAGE_ERRORS  # Window
                assert 132001 in META_MESSAGE_ERRORS  # Template not found
                assert 131049 in META_MESSAGE_ERRORS  # Not on WhatsApp

    def test_all_errors_have_required_fields(self):
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import META_MESSAGE_ERRORS
                for code, info in META_MESSAGE_ERRORS.items():
                    assert 'msg' in info, f"Error {code} missing 'msg'"
                    assert 'action' in info, f"Error {code} missing 'action'"
                    assert 'retry' in info, f"Error {code} missing 'retry'"


def _mk_urlopen(response_dict):
    """Build a urlopen context-manager mock returning the given JSON."""
    cm = MagicMock()
    cm.read.return_value = json.dumps(response_dict).encode()
    ctx = MagicMock()
    ctx.__enter__.return_value = cm
    ctx.__exit__.return_value = False
    return ctx


class TestOutboundAutoThumbReaction:
    """Auto 👍 reaction on every outbound message/template via the _send_direct_api choke point."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h
                # Seed the token cache so _send_direct_api skips Secrets Manager.
                h._direct_api_cache['token'] = 'tok'
                h._direct_api_cache['app_secret'] = ''
                # Reset the auto-thumb config cache between tests.
                h._auto_thumb_cache['value'] = None
                h._auto_thumb_cache['ts'] = 0.0

    PHONE = 'phone-number-id-waba1-direct-1016149501586345'

    def test_reaction_triggered_for_text(self):
        with patch.object(self.h, '_auto_thumb_enabled', return_value=True):
            with patch.object(self.h, '_post_reaction_direct') as react:
                with patch('urllib.request.urlopen', return_value=_mk_urlopen({'messages': [{'id': 'wamid.OUT'}], 'contacts': [{'wa_id': '9199'}]})):
                    resp = self.h._send_direct_api(self.PHONE, json.dumps({'type': 'text', 'to': '919812345678', 'text': {'body': 'hi'}}))
                assert resp['messageId'] == 'wamid.OUT'
                react.assert_called_once()
                args = react.call_args.args
                assert args[0] == '1016149501586345'   # meta_phone_id (same WABA)
                assert args[3] == '919812345678'        # to
                assert args[4] == 'wamid.OUT'           # message_id

    def test_reaction_triggered_for_template(self):
        with patch.object(self.h, '_auto_thumb_enabled', return_value=True):
            with patch.object(self.h, '_post_reaction_direct') as react:
                with patch('urllib.request.urlopen', return_value=_mk_urlopen({'messages': [{'id': 'wamid.TMPL'}]})):
                    self.h._send_direct_api(self.PHONE, json.dumps({'type': 'template', 'to': '919812345678', 'template': {'name': 'some_template'}}))
                react.assert_called_once()
                assert react.call_args.args[4] == 'wamid.TMPL'

    def test_no_reaction_for_reaction_payload(self):
        with patch.object(self.h, '_auto_thumb_enabled', return_value=True):
            with patch.object(self.h, '_post_reaction_direct') as react:
                with patch('urllib.request.urlopen', return_value=_mk_urlopen({'messages': [{'id': 'wamid.R'}]})):
                    self.h._send_direct_api(self.PHONE, json.dumps({'type': 'reaction', 'to': '919', 'reaction': {'message_id': 'x', 'emoji': '\U0001F44D'}}))
                react.assert_not_called()

    def test_no_reaction_when_send_returns_no_id(self):
        with patch.object(self.h, '_auto_thumb_enabled', return_value=True):
            with patch.object(self.h, '_post_reaction_direct') as react:
                with patch('urllib.request.urlopen', return_value=_mk_urlopen({'messages': [{}]})):
                    self.h._send_direct_api(self.PHONE, json.dumps({'type': 'text', 'to': '919', 'text': {'body': 'hi'}}))
                react.assert_not_called()

    def test_disabled_toggle_skips(self):
        with patch.object(self.h, '_auto_thumb_enabled', return_value=False):
            with patch.object(self.h, '_post_reaction_direct') as react:
                with patch('urllib.request.urlopen', return_value=_mk_urlopen({'messages': [{'id': 'wamid.O'}]})):
                    self.h._send_direct_api(self.PHONE, json.dumps({'type': 'text', 'to': '919', 'text': {'body': 'hi'}}))
                react.assert_not_called()

    def test_post_reaction_direct_builds_payload(self):
        captured = {}

        def fake_urlopen(req, timeout=10):
            captured['url'] = req.full_url
            captured['data'] = req.data
            return _mk_urlopen({})

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            self.h._post_reaction_direct('1016149501586345', 'tok', '', '919812345678', 'wamid.X')
        body = json.loads(captured['data'].decode())
        assert body['type'] == 'reaction'
        assert body['reaction']['message_id'] == 'wamid.X'
        assert body['reaction']['emoji'] == '\U0001F44D'
        assert body['to'] == '919812345678'
        assert '/1016149501586345/messages' in captured['url']

    def test_post_reaction_direct_skips_empty_args(self):
        with patch('urllib.request.urlopen') as uo:
            self.h._post_reaction_direct('1016149501586345', 'tok', '', '919', '')
            uo.assert_not_called()

    def test_auto_thumb_enabled_reads_config_false(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'configValue': 'false'}}
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table):
            assert self.h._auto_thumb_enabled() is False

    def test_auto_thumb_enabled_caches_within_ttl(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'configValue': 'true'}}
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table) as t:
            assert self.h._auto_thumb_enabled() is True
            assert self.h._auto_thumb_enabled() is True
            t.assert_called_once()  # second call served from cache

    def test_auto_thumb_enabled_defaults_when_unset(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # no Item → fall back to env default (True)
        with patch.object(self.h.dynamodb, 'Table', return_value=mock_table):
            assert self.h._auto_thumb_enabled() is True


# ==========================================================================
# Direct Send — the outside-window utility fallback (P2-C)
# ==========================================================================
#
# Today a plain-text send outside the 24-hour service window is refused with a
# 403. With Direct Send enabled for the sender's WABA, that same send goes out as
# `category: 'utility'` instead. Two properties carry the whole safety argument:
#
#   1. With the flag empty, the request body is BYTE-IDENTICAL to today's. An
#      absent `category` is Meta's own definition of a service message, so "off"
#      is not an approximation of today, it is today.
#   2. On any Direct-Send-specific error, the customer-facing response is
#      IDENTICAL to the flag-off response. Enabling the flag can never make a
#      failure worse than not having it.
#
# `category` is injected by `_build_message_payload` and only for a built payload
# whose `type` is `text` and which has a `to`. That is an allowlist of one branch,
# not a denylist, because a `content` string starting with `{` is parsed as JSON
# and can route a text-looking request into contacts or location — something the
# handler cannot see and the builder can.

FLAG = 'DIRECT_SEND_ENABLED_WABAS'
WABA1 = '2094615664435155'
WABA2 = '2513394156072604'
SENDER1 = 'phone-number-id-waba1-direct-1016149501586345'  # -> WABA1
SENDER2 = 'phone-number-id-waba-t-direct-1055232054343117'  # -> WABA2


class TestDirectSendCategoryInjection:
    """`_build_message_payload` is the single arbiter of category injection."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _build_message_payload
                self.build = _build_message_payload

    # ── flag off: byte-identical to today ───────────────────────────────────

    def test_flag_off_plain_text_is_byte_identical_to_the_golden_payload(self):
        """The golden payload. No `category`, no `ttl_seconds`, no
        `direct_send_config` — and `preview_url` still present, because today's
        service message renders a URL preview."""
        golden = self.build('+919330994400', 'Your order has shipped', None, None,
                            False, None, [])
        with_param = self.build('+919330994400', 'Your order has shipped', None,
                                None, False, None, [], direct_send_category=None)
        assert golden == with_param
        assert 'category' not in golden
        assert 'ttl_seconds' not in golden
        assert 'direct_send_config' not in golden
        assert golden['text']['preview_url'] is False

    def test_the_new_parameter_is_keyword_only_so_no_caller_can_pass_it_by_position(self):
        """Existing positional callers must be impossible to break by argument
        drift. Every current call site passes positionally up to template_params."""
        import inspect
        sig = inspect.signature(self.build)
        assert sig.parameters['direct_send_category'].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters['direct_send_category'].default is None

    # ── flag on: category at the top level, preview_url gone ────────────────

    def test_flag_on_plain_text_gets_a_top_level_utility_category(self):
        payload = self.build('+919330994400', 'Your order has shipped', None, None,
                             False, None, [], direct_send_category='utility')
        assert payload['category'] == 'utility'
        assert payload['type'] == 'text'
        # A SIBLING of `type`, never nested inside `text`.
        assert 'category' not in payload['text']

    def test_preview_url_is_removed_because_direct_send_does_not_support_it(self):
        payload = self.build('+919330994400', 'See https://wecare.digital', None,
                             None, False, None, [], direct_send_category='utility')
        assert 'preview_url' not in payload['text']
        assert payload['text']['body'] == 'See https://wecare.digital'

    def test_preview_url_survives_when_direct_send_is_off(self):
        payload = self.build('+919330994400', 'See https://wecare.digital', None,
                             None, False, None, [])
        assert payload['text']['preview_url'] is True

    # ── the allowlist: every other branch gets no category ──────────────────

    def test_template_gets_no_category(self):
        payload = self.build('+919330994400', '', None, None, True, 'hello_world',
                             ['en'], direct_send_category='utility')
        assert payload['type'] == 'template'
        assert 'category' not in payload

    @pytest.mark.parametrize('media_type,media_id', [
        ('image/jpeg', 'media-1'),
        ('video/mp4', 'media-2'),
        ('audio/ogg', 'media-3'),
        ('document/pdf', 'media-4'),
        ('sticker', 'media-5'),
    ])
    def test_media_gets_no_category(self, media_type, media_id):
        payload = self.build('+919330994400', 'Caption', media_type, media_id,
                             False, None, [], direct_send_category='utility')
        assert payload['type'] != 'text'
        assert 'category' not in payload

    def test_contacts_json_content_gets_no_category(self):
        """The case the handler's pre-check cannot see: `content` is a plain
        string as far as the request is concerned, and becomes a contacts
        message here. Without the built-type check this would have left the
        service window as a free-form non-text message."""
        content = json.dumps({'_type': 'contacts', 'contacts': [
            {'name': {'formatted_name': 'John Doe'}}]})
        payload = self.build('+919330994400', content, None, None, False, None, [],
                             direct_send_category='utility')
        assert payload['type'] == 'contacts'
        assert 'category' not in payload

    def test_location_json_content_gets_no_category(self):
        content = json.dumps({'_type': 'location', 'latitude': 1, 'longitude': 2})
        payload = self.build('+919330994400', content, None, None, False, None, [],
                             direct_send_category='utility')
        assert payload['type'] == 'location'
        assert 'category' not in payload

    def test_location_request_json_content_gets_no_category(self):
        content = json.dumps({'_type': 'location_request', 'body': 'Where are you?'})
        payload = self.build('+919330994400', content, None, None, False, None, [],
                             direct_send_category='utility')
        assert payload['type'] == 'interactive'
        assert 'category' not in payload

    def test_address_json_content_gets_no_category(self):
        content = json.dumps({'_type': 'address', 'body': 'Your address?'})
        payload = self.build('+919330994400', content, None, None, False, None, [],
                             direct_send_category='utility')
        assert payload['type'] == 'interactive'
        assert 'category' not in payload

    def test_payment_order_details_gets_no_category(self):
        order_details = {
            'reference_id': 'WD-TEST-1',
            'itemName': 'Service',
            'order': {'subtotal': {'value': 10000, 'offset': 100},
                      'items': [{'name': 'Service', 'amount': {'value': 10000, 'offset': 100},
                                 'quantity': 1}]},
        }
        payload = self.build('+919330994400', '', None, None, False, None, [],
                             is_interactive_payment=True, order_details=order_details,
                             phone_number_id=SENDER1,
                             direct_send_category='utility')
        assert payload['type'] != 'text'
        assert 'category' not in payload

    def test_bsuid_only_recipient_gets_no_category(self):
        """`authentication` may not address a business-scoped user id, and
        utility-via-BSUID is untested here. A BSUID-only send has no `to`, so
        requiring `to` excludes it by the same condition."""
        payload = self.build('', 'Hello', None, None, False, None, [],
                             recipient_bsuid='US.13491208655302741918',
                             direct_send_category='utility')
        assert not payload.get('to')
        assert 'category' not in payload


class TestDirectSendDecisionSite:
    """The handler end to end: who gets a Direct Send attempt, and what happens
    when Meta refuses it."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
        self.h = h
        self.sent = []
        self.stored = []
        self.metrics = []
        # No auth, no rate limit, no DynamoDB, and nothing that could reach a
        # network. The contact deliberately has NO lastInboundMessageAt, so the
        # service window is closed - which is the whole point of this path.
        monkeypatch.setattr(h, 'require_auth', lambda *a, **k: None)
        monkeypatch.setattr(h, '_check_rate_limit', lambda *a, **k: True)
        monkeypatch.setattr(h, '_get_contact', lambda cid: {
            'id': cid, 'phone': '+919812345678'})
        monkeypatch.setattr(h, '_store_message_record',
                            lambda **kw: self.stored.append(kw))
        monkeypatch.setattr(h, '_emit_delivery_metric',
                            lambda *a, **k: self.metrics.append(a))
        monkeypatch.setattr(h, '_enrich_contact_identity', lambda *a, **k: None)
        # Idempotency check reads MessagesTable; make it a miss.
        monkeypatch.setattr(h.dynamodb, 'Table', lambda *a, **k: MagicMock(
            get_item=MagicMock(return_value={})))

    def _event(self, content='Your order has shipped', sender=SENDER1, **extra):
        body = {'contactId': 'contact-1', 'content': content,
                'phoneNumberId': sender, 'showTyping': False}
        body.update(extra)
        return {'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
                'headers': {}, 'body': json.dumps(body)}

    def _run(self, flag_value, event=None, send=None):
        """Drive handler() with the flag set to `flag_value`."""
        env = {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE', FLAG: flag_value}
        sender = send or (lambda pid, mj: self.sent.append(json.loads(mj)) or
                          {'messageId': 'wamid.OUT', 'waId': '919812345678'})
        with patch.dict(os.environ, env):
            with patch.object(self.h, '_send_direct_api', side_effect=sender):
                return self.h.handler(event or self._event(), None)

    @staticmethod
    def _http_error(code, details='', message='Invalid parameter'):
        """A constructed Meta error envelope, so no test can reach the network."""
        import urllib.error
        err = {'code': code, 'message': message}
        if details:
            err['error_data'] = {'details': details}
        body = json.dumps({'error': err}).encode()

        def raiser(pid, mj):
            raise urllib.error.HTTPError(
                'https://graph.facebook.com/x', 400, 'Bad Request', {},
                io.BytesIO(body))
        return raiser

    NOT_ENABLED_DETAILS = ('Sending with the category parameter requires Direct '
                           'Send. Use an approved template instead.')

    # ── flag off: the 403 is unchanged ──────────────────────────────────────

    def test_flag_empty_outside_window_plain_text_still_returns_the_same_403(self):
        resp = self._run('')
        assert resp['statusCode'] == 403
        assert json.loads(resp['body'])['error'] == \
            'Outside 24h service window — only template messages allowed'
        assert self.sent == [], 'nothing should have been sent'

    def test_flag_empty_writes_no_message_row_and_no_metric(self):
        """Off must be byte-identical to today in DynamoDB and in metrics too,
        not just on the wire."""
        self._run('')
        assert self.stored == []
        assert self.metrics == []

    def test_flag_set_to_the_other_waba_does_not_enable_this_sender(self):
        """Per-WABA, at the decision site. WABA2 enabled, sending from WABA1."""
        resp = self._run(WABA2)
        assert resp['statusCode'] == 403
        assert self.sent == []

    # ── flag on: the send goes out as utility ───────────────────────────────

    def test_flag_on_outside_window_plain_text_sends_with_category_utility(self):
        resp = self._run(WABA1)
        assert resp['statusCode'] == 200
        assert len(self.sent) == 1
        assert self.sent[0]['category'] == 'utility'
        assert self.sent[0]['type'] == 'text'
        assert 'preview_url' not in self.sent[0]['text']

    def test_a_successful_direct_send_is_recorded_with_directSend_true(self):
        self._run(WABA1)
        assert len(self.stored) == 1
        assert self.stored[0]['is_direct_send'] is True

    def test_a_normal_send_is_recorded_without_the_direct_send_marker(self):
        """Inside the window, nothing changes: no category, and no new attribute
        on the row."""
        self.h_contact_window = None
        with patch.object(self.h, '_get_contact', return_value={
                'id': 'contact-1', 'phone': '+919812345678',
                'lastInboundMessageAt': int(__import__('time').time())}):
            resp = self._run(WABA1)
        assert resp['statusCode'] == 200
        assert 'category' not in self.sent[0], \
            'an open window must not send a utility message'
        assert self.stored[0]['is_direct_send'] is False

    def test_a_template_outside_the_window_is_untouched(self):
        resp = self._run(WABA1, event=self._event(
            content='', isTemplate=True, templateName='hello_world',
            templateParams=['en']))
        assert resp['statusCode'] == 200
        assert 'category' not in self.sent[0]

    def test_json_content_outside_the_window_falls_back_to_the_403(self):
        """The handler's pre-check thinks this is plain text; the builder knows
        better. The two disagreeing must fail closed to today's refusal, not send
        a contacts message out of the service window."""
        content = json.dumps({'_type': 'contacts', 'contacts': [
            {'name': {'formatted_name': 'John Doe'}}]})
        resp = self._run(WABA1, event=self._event(content=content))
        assert resp['statusCode'] == 403
        assert self.sent == [], 'a non-text message left the service window'

    def test_an_unresolvable_sender_is_treated_as_not_enabled(self):
        """Never guess a WABA. An unmappable sender keeps today's behaviour."""
        resp = self._run(WABA1, event=self._event(sender='some-unknown-phone-id'))
        assert resp['statusCode'] == 403
        assert self.sent == []

    # ── fallback: any Direct-Send-specific error returns today's 403 ─────────

    def test_code_100_not_onboarded_falls_back_to_the_403(self):
        resp = self._run(WABA1, send=self._http_error(100, self.NOT_ENABLED_DETAILS))
        assert resp['statusCode'] == 403
        assert json.loads(resp['body'])['error'] == \
            'Outside 24h service window — only template messages allowed'

    def test_code_100_not_onboarded_logs_a_filterable_event(self):
        with patch.object(self.h.logger, 'warning') as warn:
            self._run(WABA1, send=self._http_error(100, self.NOT_ENABLED_DETAILS))
        logged = ' '.join(str(c) for c in warn.call_args_list)
        assert 'direct_send_not_onboarded' in logged

    @pytest.mark.parametrize('code', [139200, 131064])
    def test_restricted_codes_fall_back_and_log_at_error(self, code):
        with patch.object(self.h.logger, 'error') as err:
            resp = self._run(WABA1, send=self._http_error(code))
        assert resp['statusCode'] == 403
        logged = ' '.join(str(c) for c in err.call_args_list)
        assert 'direct_send_restricted' in logged

    def test_an_unclassified_100_falls_back_and_logs_the_full_error(self):
        with patch.object(self.h.logger, 'error') as err:
            resp = self._run(WABA1, send=self._http_error(100, 'Invalid parameter'))
        assert resp['statusCode'] == 403
        logged = ' '.join(str(c) for c in err.call_args_list)
        assert 'direct_send_rejected' in logged
        assert 'Invalid parameter' in logged

    def test_a_direct_send_failure_writes_no_failed_row_and_no_failed_metric(self):
        """Returning before the failed-row store is what makes the fallback
        identical to flag-off in DynamoDB and in metrics, not just on the wire."""
        self._run(WABA1, send=self._http_error(100, self.NOT_ENABLED_DETAILS))
        assert self.stored == []
        assert self.metrics == []

    def test_a_non_direct_send_error_keeps_todays_handling(self):
        """131047 is an ordinary window rejection, not a Direct Send condition. It
        must still produce the existing 400 with the failed row and the metric."""
        resp = self._run(WABA1, send=self._http_error(
            131047, message='Message undeliverable'))
        assert resp['statusCode'] == 400
        assert len(self.stored) == 1
        assert self.stored[0]['status'] == 'failed'
        assert self.metrics == [('failed', False)]

    # ── the critical one ────────────────────────────────────────────────────

    @pytest.mark.parametrize('code,details', [
        (100, NOT_ENABLED_DETAILS),
        (139200, ''),
        (131064, ''),
        (100, 'Invalid parameter'),
    ])
    def test_a_fallback_response_is_identical_to_the_flag_off_response(self, code, details):
        """THE anchor test. Enabling the flag must never be able to make a failure
        worse than today: status, headers and body all identical."""
        off = self._run('')
        self.sent, self.stored, self.metrics = [], [], []
        on = self._run(WABA1, send=self._http_error(code, details))
        assert on == off, 'a Direct Send fallback diverged from today\'s refusal'
