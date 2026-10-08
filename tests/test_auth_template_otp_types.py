"""One-tap / zero-tap authentication templates — validation and send mapping.

The defect here is the OPPOSITE of the limited-time-offer one. `OTP` was already in
BUTTON_TYPES, so validate_buttons ACCEPTED an OTP button and then did nothing with
it: a button with no otp_type, a misspelled otp_type, a missing package_name or
unaccepted zero-tap terms all validated clean and went to Meta to be rejected there.
A silent accept is the more dangerous of the two, because there is no local error to
read. Test 8a is what proves the hole was real rather than asserted.

CAPABILITY is owner-gated and that is deliberate. A one-tap or zero-tap template is
only functional once Meta can verify a real signed Android app, and native packaging
is POST-PROJECT; zero-tap additionally needs the owner to accept Meta's terms in the
console, which is not an API action. This file therefore tests representation,
validation and send mapping against fixtures, and invents no app identity — the
package names and hashes below are test fixtures and appear in no shipped module,
which test 12 asserts.
"""
import json
import os
import sys

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))

from lambda_utils import template_validation as tv  # noqa: E402
from lambda_utils import whatsapp_types as wt  # noqa: E402

# Test fixtures only. Nothing here is this project's app identity, and nothing here
# is written into whatsapp_types.py or template_presets.py — see test 12.
FIXTURE_PACKAGE = 'com.example.app'
FIXTURE_HASH = 'K1Xy9Zq2Ab3'          # 11 chars, the documented length
assert len(FIXTURE_HASH) == wt.SIGNATURE_HASH_LEN


def _otp_button(**overrides):
    button = {'type': 'OTP', 'otp_type': 'COPY_CODE', 'text': 'Copy code'}
    button.update(overrides)
    return button


def _auth_template(buttons, category='AUTHENTICATION'):
    return {'name': 'wd_auth', 'language': 'en', 'category': category, 'components': [
        {'type': 'BODY', 'text': 'Your code is {{1}}', 'example': {'body_text': [['123456']]}},
        {'type': 'BUTTONS', 'buttons': buttons},
    ]}


# ── 1. the baseline that must keep working ─────────────────────────────────────

def test_copy_code_otp_button_validates():
    """COPY_CODE needs no package name and no signature hash."""
    res = tv.validate_template(_auth_template([_otp_button()]))
    assert res['ok'] is True, res['errors']


# ── 2 / 3 / 4. app identity for the autofill types ─────────────────────────────

@pytest.mark.parametrize('extra', [
    {},                                        # neither
    {'package_name': FIXTURE_PACKAGE},         # package only
    {'signature_hash': FIXTURE_HASH},          # hash only
])
def test_one_tap_requires_package_and_hash(extra):
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', autofill_text='Autofill', **extra))
    assert any('package_name and signature_hash' in e for e in errs)


def test_one_tap_accepts_supported_apps_instead():
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', autofill_text='Autofill',
        supported_apps=[{'package_name': FIXTURE_PACKAGE, 'signature_hash': FIXTURE_HASH}]))
    assert errs == []


def test_supported_apps_entry_missing_a_hash_is_refused():
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', autofill_text='Autofill',
        supported_apps=[{'package_name': FIXTURE_PACKAGE, 'signature_hash': FIXTURE_HASH},
                        {'package_name': 'com.example.other'}]))
    assert any('package_name and signature_hash' in e for e in errs)


def test_both_forms_together_are_accepted():
    """Meta decides which form wins; our validator is not the arbiter."""
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', autofill_text='Autofill',
        package_name=FIXTURE_PACKAGE, signature_hash=FIXTURE_HASH,
        supported_apps=[{'package_name': FIXTURE_PACKAGE, 'signature_hash': FIXTURE_HASH}]))
    assert errs == []


# ── 5. zero-tap terms ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('terms', [None, False, 'true', 1])
def test_zero_tap_requires_terms_accepted_exactly_true(terms):
    """A truthy string means "we think we accepted the terms". Refused."""
    extra = {} if terms is None else {'zero_tap_terms_accepted': terms}
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ZERO_TAP', autofill_text='Autofill',
        package_name=FIXTURE_PACKAGE, signature_hash=FIXTURE_HASH, **extra))
    assert any('zero_tap_terms_accepted' in e for e in errs)


def test_zero_tap_with_terms_accepted_validates():
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ZERO_TAP', autofill_text='Autofill',
        package_name=FIXTURE_PACKAGE, signature_hash=FIXTURE_HASH,
        zero_tap_terms_accepted=True))
    assert errs == []


# ── 6. the type itself ─────────────────────────────────────────────────────────

def test_unknown_otp_type_is_refused():
    errs, _ = tv.validate_otp_button(_otp_button(otp_type='ONETAP'))
    assert any('Invalid otp_type' in e for e in errs)


def test_autofill_text_cap_reads_the_constant():
    errs, _ = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', package_name=FIXTURE_PACKAGE, signature_hash=FIXTURE_HASH,
        autofill_text='x' * (wt.OTP_AUTOFILL_TEXT_MAX + 1)))
    assert any(str(wt.OTP_AUTOFILL_TEXT_MAX) in e for e in errs)


def test_otp_button_text_is_length_checked_inside_the_otp_validator():
    """Enforced here rather than by widening validate_buttons' existing tuple, whose
    membership is load-bearing for four other button types."""
    errs, _ = tv.validate_otp_button(_otp_button(text='x' * (wt.BUTTON_TEXT_MAX + 1)))
    assert any(str(wt.BUTTON_TEXT_MAX) in e for e in errs)


# ── 7. category, and the deliberate skip when it is unknown ────────────────────

def test_otp_button_outside_authentication_is_refused():
    res = tv.validate_template(_auth_template([_otp_button()], category='UTILITY'))
    assert res['ok'] is False
    assert any('AUTHENTICATION' in e for e in res['errors'])


def test_an_otp_button_with_no_category_supplied_is_not_refused():
    """Skip-when-unknown. A caller who supplied no category has not told us the
    template is not an AUTHENTICATION one, and inventing that answer would make the
    validator wrong in the silent direction this item exists to close."""
    errs, _ = tv.validate_buttons([_otp_button()])
    assert not any('AUTHENTICATION' in e for e in errs)


# ── 8 / 8a / 8b ────────────────────────────────────────────────────────────────

def test_two_otp_buttons_are_refused():
    errs, _ = tv.validate_buttons([_otp_button(), _otp_button()], 'AUTHENTICATION')
    assert any('At most 1 OTP button' in e for e in errs)


def test_an_unvalidated_otp_button_no_longer_passes():
    """THE LOAD-BEARING TEST. An OTP button carrying no otp_type at all validated
    CLEAN before this change: OTP was in BUTTON_TYPES and nothing inspected it."""
    errs, _ = tv.validate_buttons([{'type': 'OTP', 'text': 'Copy code'}], 'AUTHENTICATION')
    assert any('otp_type' in e for e in errs)

    res = tv.validate_template(_auth_template([{'type': 'OTP', 'text': 'Copy code'}]))
    assert res['ok'] is False


def test_validate_buttons_still_takes_one_positional_argument():
    """Pins the compatibility promise that lets the new `category` parameter exist.
    Called exactly as tests/test_template_validation.py already calls it."""
    out = tv.validate_buttons([{'type': 'URL', 'text': 'a', 'url': 'u'}])
    assert isinstance(out, tuple) and len(out) == 2
    errors, warnings = out
    assert isinstance(errors, list) and isinstance(warnings, list)


# ── 9. the deliberate warning ──────────────────────────────────────────────────

def test_a_wrong_length_signature_hash_warns_but_validates():
    """DELIBERATE. Nothing in this account can produce a real Android signature hash,
    because there is no signed Android app — native packaging is POST-PROJECT. A hard
    length check would be a rule written against a value nobody here has ever held.

    Hardening this to an error means answering that first.
    """
    errs, warns = tv.validate_otp_button(_otp_button(
        otp_type='ONE_TAP', autofill_text='Autofill',
        package_name=FIXTURE_PACKAGE, signature_hash='TOOSHORT'))
    assert errs == []
    assert any(str(wt.SIGNATURE_HASH_LEN) in w for w in warns)


# ── 10 / 11. the send path ─────────────────────────────────────────────────────

SENDER = 'phone-number-id-waba1-direct-1016149501586345'


class TestOtpSendSubtypes:
    """All three OTP types deliver the code through the URL button sub_type. The
    variation lives in the TEMPLATE definition, not in the send payload."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify',
                                        'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
        self.h = h
        self.sent = []
        monkeypatch.setattr(h, 'require_auth', lambda *a, **k: None)
        monkeypatch.setattr(h, '_check_rate_limit', lambda *a, **k: True)
        monkeypatch.setattr(h, '_get_contact', lambda cid: {
            'id': cid, 'phone': '+918100640044'})
        monkeypatch.setattr(h, '_store_message_record', lambda **kw: None)
        monkeypatch.setattr(h, '_emit_delivery_metric', lambda *a, **k: None)
        monkeypatch.setattr(h, '_enrich_contact_identity', lambda *a, **k: None)
        monkeypatch.setattr(h.dynamodb, 'Table', lambda *a, **k: MagicMock(
            get_item=MagicMock(return_value={})))

    def _run(self, otp_button_type):
        sender = (lambda pid, mj: self.sent.append(json.loads(mj)) or
                  {'messageId': 'wamid.OUT', 'waId': '918100640044'})
        body = {'contactId': 'contact-1', 'content': '', 'phoneNumberId': SENDER,
                'showTyping': False, 'isTemplate': True, 'templateName': 'wd_auth',
                'templateParams': ['en'], 'isOtpTemplate': True,
                'otpCode': '123456', 'otpButtonType': otp_button_type}
        event = {'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
                 'headers': {}, 'body': json.dumps(body)}
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch.object(self.h, '_send_direct_api', side_effect=sender):
                return self.h.handler(event, None)

    def _button(self):
        return [c for c in self.sent[-1]['template']['components'] if c['type'] == 'button']

    @pytest.mark.parametrize('otp_button_type', ['one_tap', 'zero_tap'])
    def test_one_tap_and_zero_tap_send_the_url_subtype(self, otp_button_type):
        assert self._run(otp_button_type)['statusCode'] == 200
        assert self._button() == [{'type': 'button', 'sub_type': 'url', 'index': 0,
                                   'parameters': [{'type': 'text', 'text': '123456'}]}]

    def test_the_url_case_is_byte_identical(self):
        self._run('url')
        url_case = self._button()
        self.sent.clear()
        self._run('one_tap')
        assert self._button() == url_case

    def test_the_default_is_still_copy_code(self):
        """`otpButtonType` defaults to 'copy_code', so no existing caller changes
        behaviour, and the copy-code arm routes through the shared helper."""
        self._run(None)
        assert self._button() == [self.h._copy_code_button_component(0, '123456')]

    def test_the_logged_otp_button_type_keeps_the_callers_spelling(self):
        """`one_tap`, not `url` — so the three stay separable in CloudWatch."""
        with patch.object(self.h.logger, 'info') as info:
            self._run('one_tap')
        events = [json.loads(c.args[0]) for c in info.call_args_list
                  if c.args and isinstance(c.args[0], str) and c.args[0].startswith('{')]
        built = [e for e in events if e.get('event') == 'otp_template_payload_built']
        assert built and built[0]['otpButtonType'] == 'one_tap'


# ── 12. no fake app identity enters the tree ───────────────────────────────────

def test_no_placeholder_package_name_ships():
    """The gating decision, pinned. This item delivers representation, validation and
    send mapping; it does NOT invent an app identity to make a demo work."""
    root = os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared',
                        'lambda_utils')
    for name in ('whatsapp_types.py', 'template_presets.py'):
        with open(os.path.join(root, name), 'r', encoding='utf-8') as fh:
            source = fh.read()
        assert 'com.wecare' not in source, name
        assert FIXTURE_PACKAGE not in source, name
        assert FIXTURE_HASH not in source, name
        assert 'signature_hash' not in source.replace('SIGNATURE_HASH_LEN', ''), name
