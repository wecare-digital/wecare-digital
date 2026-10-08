"""Limited-time-offer (LTO) templates — validation and send payload.

Two halves, and they fail for opposite reasons before this change:

  * Validation. An LTO component is HARD-BLOCKED today: `validate_components`' else
    arm returns "Unknown component type: LIMITED_TIME_OFFER", and `_create_template`
    refuses on any error, so the request never reaches Meta. Test 1 is the
    load-bearing one.
  * Send. The expiry travels per message, as an integer epoch-ms value coerced
    through `Decimal(str(v))` and failing closed. Tests 10 and 11 drive `handler()`
    rather than the builder on purpose — a builder-level test would pass even if
    `handler()` never forwarded the value, and cannot express a status code at all.

An offer code is a Meta coupon-code string. There is no amount, no discount
arithmetic and no gateway anywhere in this file.
"""
import json
import os
import sys

import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))

from lambda_utils import template_presets as tp  # noqa: E402
from lambda_utils import template_validation as tv  # noqa: E402
from lambda_utils import whatsapp_types as wt  # noqa: E402


# ── fixtures expressed as builders, so each test varies one thing ───────────────

def _lto_component(text='Expiring offer!', has_expiration=True):
    offer = {'text': text}
    if has_expiration is not None:
        offer['has_expiration'] = has_expiration
    return {'type': wt.LTO_COMPONENT_TYPE, 'limited_time_offer': offer}


def _buttons(*types):
    buttons = []
    for t in types:
        if t == 'COPY_CODE':
            buttons.append({'type': 'COPY_CODE', 'example': 'SUMMER20'})
        elif t == 'URL':
            buttons.append({'type': 'URL', 'text': 'Shop now', 'url': 'https://wecare.digital/shop'})
        else:
            buttons.append({'type': t, 'text': t.title()})
    return {'type': 'BUTTONS', 'buttons': buttons}


def _definition(category='MARKETING', header='IMAGE', lto=None,
                buttons=('COPY_CODE', 'URL'), extra=()):
    components = []
    if header == 'IMAGE':
        components.append({'type': 'HEADER', 'format': 'IMAGE',
                           'example': {'header_url': ['https://wecare.digital/x.png']}})
    elif header == 'TEXT':
        components.append({'type': 'HEADER', 'format': 'TEXT', 'text': 'Sale is here'})
    components.append({'type': 'BODY', 'text': 'Hi {{1}}, your offer ends soon.',
                       'example': {'body_text': [['Asha']]}})
    components.extend([_lto_component()] if lto is None else lto)
    if buttons is not None:
        components.append(_buttons(*buttons))
    components.extend(extra)
    return {'name': 'wd_offer', 'language': 'en', 'category': category,
            'components': components}


# ── 1. the load-bearing case ───────────────────────────────────────────────────

def test_a_valid_lto_definition_validates():
    """Fails before this change with 'Unknown component type: LIMITED_TIME_OFFER'."""
    res = tv.validate_template(_definition())
    assert res['ok'] is True, res['errors']
    assert res['errors'] == []


# ── 2 / 2a. the cap, and why it is a warning ───────────────────────────────────

def test_lto_text_cap_reads_the_constant():
    """The over-long label is built FROM the constant, so correcting the cap costs
    one line in whatsapp_types and zero test edits."""
    too_long = 'x' * (wt.LTO_TEXT_MAX + 1)
    res = tv.validate_template(_definition(lto=[_lto_component(text=too_long)]))
    assert any(str(wt.LTO_TEXT_MAX) in w for w in res['warnings'])
    assert res['ok'] is True, 'the cap is believed, not measured — see test 2a'


def test_the_unconfirmable_rules_are_warnings_not_errors():
    """DELIBERATE, and this test exists to stop a later sweep 'finishing the job'.

    The label cap and the media-header requirement are believed to be Meta's and are
    not confirmable from this repository or this account. `_create_template` refuses
    on any error, so enforcing a guess would stop the only request that could ever
    disprove it — the rule becomes unfalsifiable. As warnings, Meta's own answer is
    the measurement, and the cost of being wrong is one readable Meta error.

    Promoting either to an error means answering that argument first.
    """
    res = tv.validate_template(_definition(
        header=None, lto=[_lto_component(text='x' * (wt.LTO_TEXT_MAX + 1))]))
    assert res['ok'] is True
    assert len(res['warnings']) >= 2
    assert res['errors'] == []


# ── 3. category ────────────────────────────────────────────────────────────────

def test_lto_requires_marketing():
    res = tv.validate_template(_definition(category='UTILITY'))
    assert res['ok'] is False
    assert any('MARKETING' in e for e in res['errors'])


# ── 4. header ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('header', ['TEXT', None])
def test_lto_requires_a_media_header(header):
    res = tv.validate_template(_definition(header=header))
    assert any('HEADER' in w for w in res['warnings'])
    assert res['ok'] is True, 'believed to be Meta\'s rule — see test 2a'


# ── 5. buttons, including the absent-BUTTONS case ──────────────────────────────

@pytest.mark.parametrize('buttons,missing', [
    (('COPY_CODE',), 'URL'),
    (('URL',), 'COPY_CODE'),
    ((), None),
    (None, None),          # no BUTTONS component at all
])
def test_lto_requires_copy_code_and_url(buttons, missing):
    """An ABSENT BUTTONS component must produce the SAME diagnostics as a BUTTONS
    component carrying neither. The two cases are indistinguishable to a user ("my
    offer has no code button"), so they must not read differently."""
    res = tv.validate_template(_definition(buttons=buttons))
    assert res['ok'] is False
    if missing:
        assert any(f'1 {missing} button' in e for e in res['errors'])
    else:
        assert any('1 COPY_CODE button' in e for e in res['errors'])
        assert any('1 URL button' in e for e in res['errors'])


def test_the_absent_buttons_component_reads_identically_to_an_empty_one():
    absent = tv.validate_template(_definition(buttons=None))['errors']
    empty = tv.validate_template(_definition(buttons=()))['errors']
    assert absent == empty


# ── 6. exactly one offer ───────────────────────────────────────────────────────

def test_two_lto_components_are_refused():
    res = tv.validate_template(_definition(lto=[_lto_component(), _lto_component()]))
    assert res['ok'] is False
    assert any('at most 1' in e for e in res['errors'])


# ── 7. mutually exclusive layouts ──────────────────────────────────────────────

def test_lto_and_carousel_are_mutually_exclusive():
    carousel = {'type': 'CAROUSEL', 'cards': [
        {'components': [{'type': 'BODY', 'text': 'Card one'}]}]}
    res = tv.validate_template(_definition(extra=[carousel]))
    assert res['ok'] is False
    assert any('mutually exclusive' in e for e in res['errors'])


def test_a_marketing_carousel_is_not_told_every_card_needs_an_offer():
    """The recursion guard. Cross-component rules are statements about a TEMPLATE;
    run per carousel card they would demand an IMAGE header, a COPY_CODE button and
    an offer component on every card."""
    res = tv.validate_template({
        'name': 'wd_cards', 'language': 'en', 'category': 'MARKETING',
        'components': [
            {'type': 'BODY', 'text': 'Browse our picks'},
            {'type': 'CAROUSEL', 'cards': [
                {'components': [{'type': 'BODY', 'text': 'Card one'},
                                _buttons('QUICK_REPLY')]}]},
        ]})
    assert res['ok'] is True, res['errors']
    assert res['warnings'] == []


# ── 8 / 9. the offer label and the expiration flag ─────────────────────────────

def test_lto_text_rejects_a_placeholder():
    res = tv.validate_template(_definition(lto=[_lto_component(text='Save {{1}}')]))
    assert res['ok'] is False
    assert any('variables' in e for e in res['errors'])


def test_lto_text_is_required():
    res = tv.validate_template(_definition(lto=[_lto_component(text='')]))
    assert res['ok'] is False
    assert any('required' in e for e in res['errors'])


@pytest.mark.parametrize('value', ['true', 1, 'yes'])
def test_has_expiration_must_be_a_bool(value):
    """A truthy string silently means the wrong thing — the same refusal the OTP
    validator applies to zero_tap_terms_accepted."""
    res = tv.validate_template(_definition(lto=[_lto_component(has_expiration=value)]))
    assert res['ok'] is False
    assert any('boolean' in e for e in res['errors'])


# ── the send path. Drives handler(), never the builder. ────────────────────────

SENDER = 'phone-number-id-waba1-direct-1016149501586345'


class TestLtoSendPath:
    """handler() end to end, with the Graph boundary patched and counted."""

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

    def _event(self, **extra):
        body = {'contactId': 'contact-1', 'content': '', 'phoneNumberId': SENDER,
                'showTyping': False, 'isTemplate': True, 'templateName': 'wd_offer',
                'templateParams': ['en', 'Asha'], 'isLtoTemplate': True,
                'ltoOfferCode': 'SUMMER20'}
        body.update(extra)
        return {'requestContext': {'http': {'method': 'POST', 'path': '/whatsapp/send'}},
                'headers': {}, 'body': json.dumps(body)}

    def _run(self, **extra):
        sender = (lambda pid, mj: self.sent.append(json.loads(mj)) or
                  {'messageId': 'wamid.OUT', 'waId': '918100640044'})
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch.object(self.h, '_send_direct_api', side_effect=sender):
                return self.h.handler(self._event(**extra), None)

    @staticmethod
    def _component(payload, ctype):
        return [c for c in payload['template']['components'] if c['type'] == ctype]

    # ── 10 ──────────────────────────────────────────────────────────────────

    def test_send_payload_emits_integer_expiration(self):
        """A STRING goes in; an int must come out. Not a float — `int(Decimal(str(v)))`
        rather than `float(v)`, the same discipline the paise rule imposes, because the
        failure mode is the same class: a value that looks right and is off by a unit."""
        resp = self._run(ltoExpirationTimeMs='1767225600000')
        assert resp['statusCode'] == 200
        assert len(self.sent) == 1
        offer = self._component(self.sent[0], 'limited_time_offer')
        assert offer == [{
            'type': 'limited_time_offer',
            'parameters': [{'type': 'limited_time_offer',
                            'limited_time_offer': {'expiration_time_ms': 1767225600000}}]}]
        value = offer[0]['parameters'][0]['limited_time_offer']['expiration_time_ms']
        assert isinstance(value, int) and not isinstance(value, bool)
        assert not isinstance(value, float)

    def test_send_payload_emits_the_offer_code_button(self):
        self._run(ltoExpirationTimeMs=1767225600000, ltoCopyCodeIndex=1)
        button = self._component(self.sent[0], 'button')
        assert button == [{'type': 'button', 'sub_type': 'copy_code', 'index': 1,
                           'parameters': [{'type': 'coupon_code',
                                           'coupon_code': 'SUMMER20'}]}]

    def test_an_absent_offer_code_still_emits_the_offer_component(self):
        self._run(ltoExpirationTimeMs=1767225600000, ltoOfferCode='')
        assert self._component(self.sent[0], 'limited_time_offer')
        assert self._component(self.sent[0], 'button') == []

    def test_body_params_travel_alongside_the_offer(self):
        """The chain is elif-ordered, so the LTO branch handles body params itself."""
        self._run(ltoExpirationTimeMs=1767225600000)
        body = self._component(self.sent[0], 'body')
        assert body == [{'type': 'body',
                         'parameters': [{'type': 'text', 'text': 'Asha'}]}]

    # ── 11 ──────────────────────────────────────────────────────────────────

    def test_send_refuses_a_non_numeric_expiration(self):
        resp = self._run(ltoExpirationTimeMs='soon')
        assert resp['statusCode'] == 400
        assert json.loads(resp['body'])['error'] == (
            'ltoExpirationTimeMs must be an integer epoch milliseconds value')
        assert self.sent == [], 'the Graph boundary must not have been reached'

    def test_a_missing_expiration_is_refused(self):
        resp = self._run()
        assert resp['statusCode'] == 400
        assert self.sent == []

    @pytest.mark.parametrize('value', [0, -1])
    def test_a_non_positive_expiration_is_refused(self, value):
        resp = self._run(ltoExpirationTimeMs=value)
        assert resp['statusCode'] == 400
        assert json.loads(resp['body'])['error'] == 'ltoExpirationTimeMs must be positive'
        assert self.sent == []

    # ── 11a ─────────────────────────────────────────────────────────────────

    def test_the_builder_never_returns_an_http_envelope(self):
        """`_build_message_payload` returns a message payload and nothing else. An
        `_error_response` returned from there would be POSTed to Meta AS the WhatsApp
        message, because its one caller inspects the result and sends it. The 400s
        above are decided in handler(), where that is the correct return type."""
        import inspect
        source = inspect.getsource(self.h._build_message_payload)
        assert '_error_response' not in source
        assert 'statusCode' not in source

    # ── 12 ──────────────────────────────────────────────────────────────────

    def test_copy_code_component_is_one_shape(self):
        """Meta spells the parameter `coupon_code` for both an OTP and an offer code.
        One helper, so a field-name correction cannot land in one place only."""
        otp = self.h._build_message_payload(
            '+918100640044', '', None, None, True, 'wd_auth', ['en'],
            is_otp_template=True, otp_code='SUMMER20', otp_button_type='copy_code')
        lto = self.h._build_message_payload(
            '+918100640044', '', None, None, True, 'wd_offer', ['en'],
            is_lto_template=True, lto_expiration_ms=1767225600000,
            lto_offer_code='SUMMER20', lto_copy_code_index=0)
        otp_button = [c for c in otp['template']['components']
                      if c.get('sub_type') == 'copy_code']
        lto_button = [c for c in lto['template']['components']
                      if c.get('sub_type') == 'copy_code']
        assert otp_button == lto_button
        assert otp_button == [self.h._copy_code_button_component(0, 'SUMMER20')]


# ── 13 ─────────────────────────────────────────────────────────────────────────

def test_the_preset_validates():
    """A stronger gate already exists: tests/test_template_validation.py loops every
    registered preset through validate_template. This is the named, readable version."""
    preset = tp.get_preset('limited_time_offer')
    assert preset is not None
    assert preset['category'] == 'MARKETING'
    res = tv.validate_template(preset)
    assert res['ok'] is True, res['errors']


def test_the_preset_carries_no_amount_or_discount_arithmetic():
    """An offer code is a Meta coupon string, not a payment instrument."""
    preset = tp.get_preset('limited_time_offer')
    offer = [c for c in preset['components']
             if c['type'] == wt.LTO_COMPONENT_TYPE][0]['limited_time_offer']
    assert set(offer) == {'text', 'has_expiration'}
