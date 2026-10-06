"""Tests for inbound WhatsApp content extraction module."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'inbound-whatsapp-handler'))

from modules.content import (
    extract_content,
    extract_unsupported_content,
    extract_contacts_payload,
    KNOWN_TYPES,
    MAX_CONTACTS,
    MAX_ITEMS,
    MAX_STR,
    UNSUPPORTED_UNKNOWN,
)


class TestExtractContent:
    def test_text(self):
        msg = {'text': {'body': 'Hello world'}}
        assert extract_content(msg, 'text') == 'Hello world'

    def test_image_with_caption(self):
        msg = {'image': {'caption': 'My photo'}}
        assert extract_content(msg, 'image') == 'My photo'

    def test_image_no_caption(self):
        msg = {'image': {}}
        assert extract_content(msg, 'image') == '[Image]'

    def test_audio(self):
        assert extract_content({}, 'audio') == '[Audio]'

    def test_document(self):
        msg = {'document': {'filename': 'report.pdf'}}
        assert extract_content(msg, 'document') == 'report.pdf'

    def test_location(self):
        msg = {'location': {'latitude': 22.5, 'longitude': 88.3}}
        assert 'Location' in extract_content(msg, 'location')

    def test_sticker(self):
        assert extract_content({}, 'sticker') == '[Sticker]'

    def test_reaction(self):
        msg = {'reaction': {'emoji': '👍'}}
        assert extract_content(msg, 'reaction') == '👍'

    def test_interactive_button_reply(self):
        msg = {'interactive': {'type': 'button_reply', 'button_reply': {'id': 'opt_yes', 'title': 'Yes'}}}
        assert extract_content(msg, 'interactive') == 'opt_yes'

    def test_interactive_list_reply(self):
        msg = {'interactive': {'type': 'list_reply', 'list_reply': {'id': 'custom', 'title': 'My Choice'}}}
        assert extract_content(msg, 'interactive') == 'My Choice'

    def test_button(self):
        msg = {'button': {'text': 'Quick Reply'}}
        assert extract_content(msg, 'button') == 'Quick Reply'

    def test_order(self):
        assert extract_content({}, 'order') == '[Order]'

    def test_system(self):
        msg = {'system': {'body': 'Group created'}}
        assert extract_content(msg, 'system') == 'Group created'

    def test_request_welcome(self):
        assert 'conversation' in extract_content({}, 'request_welcome').lower()

    def test_poll(self):
        msg = {'poll': {'question': 'Favorite color?'}}
        assert 'Favorite color' in extract_content(msg, 'poll')

    def test_edit_with_text(self):
        msg = {'text': {'body': 'new text'}, 'context': {'id': 'wamid.xxx'}}
        result = extract_content(msg, 'edit')
        assert result == '[Edited] new text'

    def test_edit_no_text(self):
        msg = {'context': {'id': 'wamid.abc123'}}
        result = extract_content(msg, 'edit')
        assert result == '[Message edited: wamid.abc123]'

    def test_edit_empty(self):
        result = extract_content({}, 'edit')
        assert result == '[Message edited]'

    def test_revoke(self):
        result = extract_content({}, 'revoke')
        assert result == '[Message deleted by sender]'

    def test_unknown_type(self):
        result = extract_content({}, 'some_new_type')
        assert result == '[some_new_type]'


class TestExtractUnsupported:
    def test_the_measured_131051_payload_does_not_quote_meta(self):
        """The real shape Meta sends: detail under errors[].error_data.details.

        125 of 128 measured payloads look exactly like this. The negative assertion
        is the one that matters — asserting only the sentinel would also pass on
        Meta's own error title, which is what an agent was being shown.
        """
        msg = {
            'type': 'unsupported',
            'unsupported': {'type': 'unknown', 'raw_type': 'unknown'},
            'errors': [{
                'code': 131051,
                'title': 'Message type unknown',
                'message': 'Message type unknown',
                'error_data': {'details': 'Message type is currently not supported.'},
            }],
        }
        result = extract_unsupported_content(msg)
        assert result == UNSUPPORTED_UNKNOWN
        assert 'Message type unknown' not in result
        assert 'not supported.' not in result

    def test_131051_with_a_top_level_detail_still_reads(self):
        """Legacy shape: a top-level `details`. The `or` keeps it working."""
        msg = {'errors': [{'code': 131051, 'details': 'Live location'}],
               'unsupported': {'type': 'live_location'}}
        assert 'Live location' in extract_unsupported_content(msg)

    def test_131060_says_the_message_is_gone(self):
        msg = {
            'type': 'unsupported',
            'errors': [{
                'code': 131060,
                'title': 'Message is not available',
                'error_data': {'details': 'This message is currently unavailable.'},
            }],
        }
        result = extract_unsupported_content(msg)
        assert result == '[Unsupported: This message is no longer available]'
        assert 'currently unavailable' not in result

    def test_otp_branch_fires_off_error_data_details(self):
        """Proof the old top-level-only read made this branch unreachable."""
        msg = {
            'type': 'unsupported',
            'unsupported': {'type': 'unknown'},
            'errors': [{
                'code': 131051,
                'title': 'Message type unknown',
                'error_data': {'details': 'Authentication template content is hidden.'},
            }],
        }
        assert 'OTP or authentication' in extract_unsupported_content(msg)

    def test_contacts_nested_under_unsupported_carries_the_data(self):
        msg = {
            'type': 'unsupported',
            'contacts': [{'name': {'formatted_name': 'Punit Kumar'},
                          'phones': [{'phone': '+91 80318 30030'}]}],
        }
        result = extract_unsupported_content(msg)
        assert result.startswith('[Contact Card]')
        assert 'Punit Kumar' in result
        assert '+91 80318 30030' in result

    def test_with_referral(self):
        msg = {'referral': {'source_type': 'ad'}}
        assert 'ad' in extract_unsupported_content(msg)

    def test_with_text_body(self):
        msg = {'text': {'body': 'hidden text'}}
        assert extract_unsupported_content(msg) == 'hidden text'

    def test_fallback(self):
        assert 'not supported' in extract_unsupported_content({})


class TestContactsLabel:
    def test_a_full_card_carries_name_and_phone(self):
        msg = {'contacts': [{
            'name': {'formatted_name': 'Punit Kumar', 'first_name': 'Punit'},
            'phones': [{'phone': '+918100640044', 'type': 'CELL'}],
        }]}
        result = extract_content(msg, 'contacts')
        assert result.startswith('[Contact Card]')
        assert 'Punit Kumar' in result
        assert '+918100640044' in result

    def test_a_card_with_no_phone_has_no_trailing_separator(self):
        msg = {'contacts': [{'name': {'formatted_name': 'Punit Kumar'}, 'phones': []}]}
        assert extract_content(msg, 'contacts') == '[Contact Card] Punit Kumar'

    def test_a_card_with_only_first_and_last_name(self):
        msg = {'contacts': [{'name': {'first_name': 'Punit', 'last_name': 'Kumar'}}]}
        assert extract_content(msg, 'contacts') == '[Contact Card] Punit Kumar'

    def test_an_empty_array_is_the_bare_label(self):
        assert extract_content({'contacts': []}, 'contacts') == '[Contact Card]'

    def test_an_absent_array_is_the_bare_label(self):
        assert extract_content({}, 'contacts') == '[Contact Card]'

    def test_malformed_shapes_never_raise(self):
        for msg in ({'contacts': 'nonsense'}, {'contacts': [None]},
                    {'contacts': [{'name': 'flat'}]}, {'contacts': [{'phones': 'x'}]}):
            assert extract_content(msg, 'contacts') == '[Contact Card]'


class TestExtractContactsPayload:
    def test_a_full_payload_round_trips(self):
        msg = {'contacts': [{
            'name': {'formatted_name': 'Punit Kumar', 'first_name': 'Punit', 'last_name': 'Kumar'},
            'phones': [{'phone': '+918100640044', 'type': 'CELL', 'wa_id': '918100640044'}],
            'emails': [{'email': 'punit@example.com', 'type': 'WORK'}],
            'org': {'company': 'WeCare', 'title': 'Partner'},
        }]}
        payload = extract_contacts_payload(msg)
        assert payload == [{
            'name': {'formatted_name': 'Punit Kumar', 'first_name': 'Punit', 'last_name': 'Kumar'},
            'phones': [{'phone': '+918100640044', 'type': 'CELL', 'wa_id': '918100640044'}],
            'emails': [{'email': 'punit@example.com', 'type': 'WORK'}],
            'org': {'company': 'WeCare', 'title': 'Partner'},
        }]

    def test_only_the_fields_meta_sent_are_emitted(self):
        msg = {'contacts': [{'name': {'formatted_name': 'Punit'},
                             'phones': [{'phone': '+9181'}]}]}
        assert extract_contacts_payload(msg) == [
            {'name': {'formatted_name': 'Punit'}, 'phones': [{'phone': '+9181'}]}
        ]

    def test_malformed_input_returns_none_without_raising(self):
        for msg in (None, {}, {'contacts': 'nonsense'}, {'contacts': []},
                    {'contacts': [None]}, {'contacts': [{}]},
                    {'contacts': [{'name': 'flat', 'phones': 7}]}, 'not a dict', 42):
            assert extract_contacts_payload(msg) is None

    def test_the_payload_is_size_bounded(self):
        """A DynamoDB item caps at 400 KB and a forwarded vCard is sender-controlled."""
        msg = {'contacts': [{
            'name': {'formatted_name': 'x' * 10_000},
            'phones': [{'phone': str(i) * 10_000} for i in range(200)],
            'emails': [{'email': 'e' * 10_000} for _ in range(200)],
        } for _ in range(200)]}
        payload = extract_contacts_payload(msg)
        assert len(payload) == MAX_CONTACTS
        for entry in payload:
            assert len(entry['phones']) == MAX_ITEMS
            assert len(entry['emails']) == MAX_ITEMS
            assert len(entry['name']['formatted_name']) == MAX_STR
            assert all(len(p['phone']) <= MAX_STR for p in entry['phones'])


class TestKnownTypes:
    def test_known_types_is_the_dispatch_table(self):
        assert 'revoke' in KNOWN_TYPES
        assert 'edit' in KNOWN_TYPES
        assert 'contacts' in KNOWN_TYPES
        # `unknown` must stay out, or the measured 125-of-128 case would be
        # "recovered" into a type with no extractor.
        assert 'unknown' not in KNOWN_TYPES
