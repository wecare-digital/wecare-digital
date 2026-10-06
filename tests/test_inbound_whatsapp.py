"""Tests for inbound WhatsApp handler — webhook processing and deduplication."""
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler', 'modules'))


def _make_sns_event(webhook_entry: dict) -> dict:
    """Build a minimal SNS event wrapping a WhatsApp webhook entry."""
    return {
        'Records': [{
            'Sns': {
                'Message': json.dumps({
                    'context': {
                        'MetaWabaIds': ['2094615664435155'],
                        'MetaPhoneNumberIds': ['1016149501586345'],
                    },
                    'whatsAppWebhookEntry': json.dumps(webhook_entry),
                    'messageId': 'test-msg-id',
                })
            }
        }]
    }


def _make_text_webhook(from_phone='919330994400', text='Hello', msg_id='wamid.test123'):
    """Build a WhatsApp text message webhook entry."""
    return {
        'changes': [{
            'value': {
                'messaging_product': 'whatsapp',
                'metadata': {
                    'display_phone_number': '919330994400',
                    'phone_number_id': '1016149501586345',
                },
                'contacts': [{
                    'profile': {'name': 'Test User'},
                    'wa_id': from_phone,
                    'user_id': 'IN.testbsuid123',
                }],
                'messages': [{
                    'from': from_phone,
                    'id': msg_id,
                    'timestamp': '1700000000',
                    'type': 'text',
                    'text': {'body': text},
                }],
            },
            'field': 'messages',
        }]
    }


def _make_status_webhook(msg_id='wamid.test123', status='delivered'):
    """Build a WhatsApp status update webhook entry."""
    return {
        'changes': [{
            'value': {
                'messaging_product': 'whatsapp',
                'metadata': {
                    'display_phone_number': '919330994400',
                    'phone_number_id': '1016149501586345',
                },
                'statuses': [{
                    'id': msg_id,
                    'status': status,
                    'timestamp': '1700000001',
                    'recipient_id': '919876543210',
                }],
            },
            'field': 'messages',
        }]
    }


class TestWebhookPayloadParsing:
    """Test that webhook payloads are correctly parsed."""

    def test_text_webhook_structure(self):
        entry = _make_text_webhook()
        changes = entry['changes']
        assert len(changes) == 1
        messages = changes[0]['value']['messages']
        assert len(messages) == 1
        assert messages[0]['type'] == 'text'
        assert messages[0]['text']['body'] == 'Hello'

    def test_status_webhook_structure(self):
        entry = _make_status_webhook(status='read')
        statuses = entry['changes'][0]['value']['statuses']
        assert len(statuses) == 1
        assert statuses[0]['status'] == 'read'

    def test_contacts_array_parsing(self):
        entry = _make_text_webhook()
        contacts = entry['changes'][0]['value']['contacts']
        assert contacts[0]['profile']['name'] == 'Test User'
        assert contacts[0]['user_id'] == 'IN.testbsuid123'

    def test_metadata_extraction(self):
        entry = _make_text_webhook()
        metadata = entry['changes'][0]['value']['metadata']
        assert metadata['display_phone_number'] == '919330994400'
        assert metadata['phone_number_id'] == '1016149501586345'


class TestSNSEventWrapping:
    """Test SNS event format matches what Lambda receives."""

    def test_sns_event_has_records(self):
        event = _make_sns_event(_make_text_webhook())
        assert 'Records' in event
        assert len(event['Records']) == 1

    def test_sns_message_is_json(self):
        event = _make_sns_event(_make_text_webhook())
        sns_msg = json.loads(event['Records'][0]['Sns']['Message'])
        assert 'whatsAppWebhookEntry' in sns_msg
        assert 'context' in sns_msg

    def test_webhook_entry_is_nested_json(self):
        event = _make_sns_event(_make_text_webhook())
        sns_msg = json.loads(event['Records'][0]['Sns']['Message'])
        entry = json.loads(sns_msg['whatsAppWebhookEntry'])
        assert 'changes' in entry


class TestWebhookFieldTypes:
    """Test different webhook field types are recognized."""

    def test_template_status_field(self):
        entry = {
            'changes': [{
                'value': {
                    'event': 'APPROVED',
                    'message_template_id': 123,
                    'message_template_name': 'test_template',
                },
                'field': 'message_template_status_update',
            }]
        }
        assert entry['changes'][0]['field'] == 'message_template_status_update'

    def test_phone_quality_field(self):
        entry = {
            'changes': [{
                'value': {
                    'display_phone_number': '919330994400',
                    'current_limit': 'TIER_1K',
                },
                'field': 'phone_number_quality_update',
            }]
        }
        assert entry['changes'][0]['field'] == 'phone_number_quality_update'

    def test_account_update_field(self):
        entry = {
            'changes': [{
                'value': {
                    'phone_number': '919330994400',
                    'event': 'ACCOUNT_VIOLATION',
                },
                'field': 'account_update',
            }]
        }
        assert entry['changes'][0]['field'] == 'account_update'

    def test_user_id_update_field(self):
        entry = {
            'changes': [{
                'value': {
                    'user_id_update': [{
                        'user_id': 'IN.newbsuid',
                        'wa_id': '919330994400',
                    }],
                },
                'field': 'user_id_update',
            }]
        }
        assert entry['changes'][0]['field'] == 'user_id_update'


class TestMessageTypes:
    """Test all WhatsApp message types are handled in webhook format."""

    def _make_msg(self, msg_type, extra=None):
        msg = {
            'from': '919330994400',
            'id': f'wamid.{msg_type}_test',
            'timestamp': '1700000000',
            'type': msg_type,
        }
        if extra:
            msg.update(extra)
        return msg

    def test_text_message(self):
        msg = self._make_msg('text', {'text': {'body': 'Hello'}})
        assert msg['type'] == 'text'

    def test_image_message(self):
        msg = self._make_msg('image', {'image': {'id': 'img-123', 'mime_type': 'image/jpeg'}})
        assert msg['type'] == 'image'

    def test_video_message(self):
        msg = self._make_msg('video', {'video': {'id': 'vid-123', 'mime_type': 'video/mp4'}})
        assert msg['type'] == 'video'

    def test_audio_message(self):
        msg = self._make_msg('audio', {'audio': {'id': 'aud-123', 'mime_type': 'audio/ogg'}})
        assert msg['type'] == 'audio'

    def test_document_message(self):
        msg = self._make_msg('document', {'document': {'id': 'doc-123', 'filename': 'test.pdf'}})
        assert msg['type'] == 'document'

    def test_sticker_message(self):
        msg = self._make_msg('sticker', {'sticker': {'id': 'stk-123'}})
        assert msg['type'] == 'sticker'

    def test_location_message(self):
        msg = self._make_msg('location', {'location': {'latitude': 37.48, 'longitude': -122.14}})
        assert msg['type'] == 'location'

    def test_contacts_message(self):
        msg = self._make_msg('contacts', {'contacts': [{'name': {'formatted_name': 'John'}}]})
        assert msg['type'] == 'contacts'

    def test_reaction_message(self):
        msg = self._make_msg('reaction', {'reaction': {'message_id': 'wamid.orig', 'emoji': '👍'}})
        assert msg['type'] == 'reaction'

    def test_interactive_message(self):
        msg = self._make_msg('interactive', {
            'interactive': {'type': 'button_reply', 'button_reply': {'id': 'btn1', 'title': 'Yes'}}
        })
        assert msg['type'] == 'interactive'

    def test_order_message(self):
        msg = self._make_msg('order', {'order': {'catalog_id': 'cat-1', 'product_items': []}})
        assert msg['type'] == 'order'

    def test_unsupported_message(self):
        # The measured shape: Meta puts the detail under errors[].error_data.details
        # and never at the top level. This test only asserts on the type, but a
        # fixture Meta never sends sitting beside tests that now depend on the real
        # one is how the top-level-only read survived as long as it did.
        msg = self._make_msg('unsupported', {
            'unsupported': {'type': 'unknown', 'raw_type': 'unknown'},
            'errors': [{
                'code': 131051,
                'title': 'Message type unknown',
                'error_data': {'details': 'Message type is currently not supported.'},
            }],
        })
        assert msg['type'] == 'unsupported'


class TestBsuidWebhookProcessing:
    """Exercise the BSUID/username webhook processors in the inbound handler."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def test_business_username_update_stores_event(self):
        seen = []
        with patch.object(self.h, '_store_system_event', side_effect=lambda et, *a, **k: seen.append(et)):
            with patch.object(self.h.dynamodb, 'Table', return_value=MagicMock()):
                self.h._process_business_username_update(
                    {'display_phone_number': '15550783881', 'username': 'wecaredigital', 'status': 'approved'}, 'req1')
        assert 'business_username_updates' in seen

    def test_user_id_update_updates_contact(self):
        fake_table = MagicMock()
        fake_table.query.return_value = {'Items': [{'id': 'c1', 'bsuid': 'IN.old'}]}
        with patch.object(self.h.dynamodb, 'Table', return_value=fake_table):
            self.h._process_user_id_update(
                {'user_id': {'previous': 'IN.old', 'current': 'IN.new'}, 'parent_user_id': {'current': 'IN.ENT.x'}},
                {}, 'req1')
        assert fake_table.update_item.called
        # the new BSUID must be written
        kwargs = fake_table.update_item.call_args.kwargs
        assert kwargs['ExpressionAttributeValues'][':new_bsuid'] == 'IN.new'
        assert kwargs['ExpressionAttributeValues'][':new_parent'] == 'IN.ENT.x'

    def test_user_id_update_missing_ids_noop(self):
        fake_table = MagicMock()
        with patch.object(self.h.dynamodb, 'Table', return_value=fake_table):
            self.h._process_user_id_update({'user_id': {}}, {}, 'req1')
        assert not fake_table.update_item.called

    def test_user_id_update_contact_not_found_noop(self):
        fake_table = MagicMock()
        fake_table.query.return_value = {'Items': []}
        with patch.object(self.h.dynamodb, 'Table', return_value=fake_table):
            self.h._process_user_id_update(
                {'user_id': {'previous': 'IN.old', 'current': 'IN.new'}}, {}, 'req1')
        assert not fake_table.update_item.called


class TestInboundAutoThumbReaction:
    """Auto 👍 on messages SENT from the inbound handler (auto-replies/IVR), with loop guard."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h

    def _run(self, payload, send_fn='message', enabled=True):
        sent = []

        def fake_urlopen(req, timeout=30):
            sent.append(json.loads(req.data.decode()))
            cm = MagicMock()
            cm.read.return_value = json.dumps({'messages': [{'id': 'wamid.IN'}]}).encode()
            ctx = MagicMock()
            ctx.__enter__.return_value = cm
            ctx.__exit__.return_value = False
            return ctx

        with patch.object(self.h, '_load_direct_api_token', return_value='tok'):
            with patch.object(self.h, '_auto_thumb_enabled', return_value=enabled):
                self.h._direct_api_token_cache['app_secret'] = ''
                with patch('urllib.request.urlopen', side_effect=fake_urlopen):
                    if send_fn == 'message':
                        self.h._send_direct_api_message('919812345678', payload, meta_phone_id='1016149501586345')
                    else:
                        self.h._send_direct_api_reaction('919812345678', 'wamid.ORIG')
        return sent

    def test_outbound_text_gets_auto_reaction(self):
        sent = self._run({'type': 'text', 'text': {'body': 'hi'}})
        assert len(sent) == 2
        assert sent[0]['type'] == 'text'
        assert sent[1]['type'] == 'reaction'
        assert sent[1]['reaction']['message_id'] == 'wamid.IN'

    def test_reaction_send_does_not_recurse(self):
        # Sending a reaction must NOT trigger another reaction (loop guard).
        sent = self._run(None, send_fn='reaction')
        assert len(sent) == 1
        assert sent[0]['type'] == 'reaction'

    def test_disabled_toggle_skips(self):
        sent = self._run({'type': 'text', 'text': {'body': 'hi'}}, enabled=False)
        assert len(sent) == 1
        assert sent[0]['type'] == 'text'


class TestContactsPayloadAndRevokeStorage:
    """The ingest path must keep what a shared contact card carried.

    Puneet's card arrived, was stored and was acknowledged — and the handler threw
    the name and the number away, so an agent had to ask the customer to retype the
    number. These tests assert on the stored Item, not on "put_item was called":
    a write that succeeds while dropping the one field that mattered is exactly
    what happened.
    """

    @pytest.fixture
    def h(self):
        """Load THIS handler by path, under a name nothing else uses.

        `import handler` is ambiguous across the full suite — every Lambda in this
        repo has a `handler.py` and the first import wins `sys.modules['handler']`
        for the rest of the run.
        """
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / \
            'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'
        spec = importlib.util.spec_from_file_location(
            'inbound_whatsapp_handler_contacts', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            with patch('boto3.resource'), patch('boto3.client'):
                spec.loader.exec_module(module)
        return module

    def _run(self, h, message):
        """Process one message; return (tables_by_name, put_message_kwargs)."""
        tables = {}

        def _table(name):
            return tables.setdefault(name, MagicMock())

        put_message_calls = []
        # claim_event keeps an in-process cache, so a second test reusing a wamid
        # would be skipped as a duplicate. Dedup is not what these tests measure.
        with patch('lambda_utils.webhook_dedup.claim_event', return_value=True), \
                patch.object(h.dynamodb, 'Table', side_effect=_table), \
                patch.object(h, '_message_exists', return_value=False), \
                patch.object(h, '_get_or_create_contact',
                             return_value={'contactId': 'c-1', 'welcomeSent': True}), \
                patch.object(h, '_update_contact_timestamp'), \
                patch.object(h, 'put_message',
                             side_effect=lambda **kw: put_message_calls.append(kw)):
            h._process_message(
                message,
                {'display_phone_number': '919330994400',
                 'phone_number_id': '1016149501586345'},
                'req-1',
                '919330994400',
                '1016149501586345',
                ['2094615664435155'],
            )
        return tables, put_message_calls

    def _stored_item(self, h, tables):
        table = tables[h.MESSAGES_TABLE]
        assert table.put_item.called, 'the message row was never written'
        return table.put_item.call_args.kwargs['Item']

    def _card_message(self, origin=None):
        msg = {
            'id': 'wamid.CARD1',
            'from': '918100640044',
            'timestamp': '1760000000',
            'type': 'contacts',
            'contacts': [{
                'name': {'formatted_name': 'Punit Kumar',
                         'first_name': 'Punit', 'last_name': 'Kumar'},
                'phones': [{'phone': '+918031830030', 'type': 'CELL'}],
            }],
        }
        if origin:
            msg['origin'] = origin
        return msg

    def test_a_shared_card_stores_its_payload_on_both_writes(self, h):
        tables, put_message_calls = self._run(h, self._card_message())
        item = self._stored_item(h, tables)

        assert item['content'].startswith('[Contact Card]')
        assert 'Punit Kumar' in item['content']
        payload = item['contactsPayload']
        assert payload[0]['name']['formatted_name'] == 'Punit Kumar'
        assert payload[0]['phones'][0]['phone'] == '+918031830030'

        # The dual-write into the canonical MessagesTable has to carry it too, or
        # the unified inbox renders a label while the WhatsApp inbox renders a card.
        assert len(put_message_calls) == 1
        assert put_message_calls[0]['contacts_payload'] == payload

    def test_a_non_contacts_message_adds_no_attribute(self, h):
        tables, _ = self._run(h, {
            'id': 'wamid.TEXT1', 'from': '918100640044',
            'timestamp': '1760000000', 'type': 'text',
            'text': {'body': 'hello'},
        })
        # put_item filters None out, so the attribute must be absent rather than null.
        assert 'contactsPayload' not in self._stored_item(h, tables)

    def test_the_contact_request_branch_is_untouched(self, h):
        """REQUEST_CONTACT_INFO still writes the shared phone onto ContactsTable.

        This branch serves Meta's BSUID flow and must keep behaving identically —
        widening it would write arbitrary forwarded numbers onto a contact record.
        """
        tables, _ = self._run(h, self._card_message(origin='contact_request/other'))
        contacts_table = tables[h.CONTACTS_TABLE]
        assert contacts_table.update_item.called
        kwargs = contacts_table.update_item.call_args.kwargs
        assert kwargs['Key'] == {'id': 'c-1'}
        assert kwargs['ExpressionAttributeValues'][':p'] == '+918031830030'

    def test_a_revoke_is_recovered_from_the_unsupported_envelope(self, h):
        """Meta names the real type in `unsupported.type`.

        Without reading it the `revoke` extractor was unreachable dispatch-table
        code and a deletion stored Meta's error text instead.
        """
        tables, put_message_calls = self._run(h, {
            'id': 'wamid.REVOKE1',
            'from': '918100640044',
            'timestamp': '1760000000',
            'type': 'unsupported',
            'unsupported': {'type': 'revoke', 'raw_type': 'revoke'},
            'errors': [{
                'code': 131051,
                'title': 'Message type unknown',
                'error_data': {'details': 'Message type is currently not supported.'},
            }],
        })
        item = self._stored_item(h, tables)
        assert item['messageType'] == 'revoke'
        assert item['content'] == '[Message deleted by sender]'
        assert put_message_calls[0]['message_type'] == 'revoke'

    def test_an_unknown_unsupported_type_is_not_recovered(self, h):
        """125 of 128 measured payloads. `unknown` has no extractor, so it must
        fall through to extract_unsupported_content and get the stable sentinel."""
        tables, _ = self._run(h, {
            'id': 'wamid.UNK1',
            'from': '918100640044',
            'timestamp': '1760000000',
            'type': 'unsupported',
            'unsupported': {'type': 'unknown', 'raw_type': 'unknown'},
            'errors': [{
                'code': 131051,
                'title': 'Message type unknown',
                'error_data': {'details': 'Message type is currently not supported.'},
            }],
        })
        item = self._stored_item(h, tables)
        assert item['messageType'] == 'unsupported'
        assert item['content'] == '[Unsupported: WhatsApp did not say what this message was]'
        assert 'Message type unknown' not in item['content']
