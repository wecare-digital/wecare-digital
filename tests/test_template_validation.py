"""Tests for the decomposed template validation service + presets."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))

from lambda_utils import template_validation as tv  # noqa: E402


def _valid_body(text='Hi {{1}}', example=None):
    comp = {'type': 'BODY', 'text': text}
    if example is not None:
        comp['example'] = example
    elif '{{' in text:
        comp['example'] = {'body_text': [['Asha']]}
    return comp


# ── parameter format detection ──

def test_detect_parameter_format():
    assert tv.detect_parameter_format('hello') == 'NONE'
    assert tv.detect_parameter_format('hi {{1}} {{2}}') == 'POSITIONAL'
    assert tv.detect_parameter_format('hi {{name}}') == 'NAMED'
    assert tv.detect_parameter_format('hi {{1}} {{name}}') == 'MIXED'


# ── root ──

def test_validate_root_name_format():
    errs, _ = tv.validate_root({'name': 'Bad Name', 'language': 'en', 'category': 'UTILITY'})
    assert any('lowercase' in e for e in errs)


def test_validate_root_missing_category():
    errs, _ = tv.validate_root({'name': 'ok_name', 'language': 'en'})
    assert any('category' in e for e in errs)


def test_validate_root_ttl_enforced():
    errs, _ = tv.validate_root({'name': 'n', 'language': 'en', 'category': 'AUTHENTICATION', 'message_send_ttl_seconds': 5000})
    assert any('TTL' in e for e in errs)


# ── header ──

def test_text_header_too_long():
    errs, _ = tv.validate_header({'type': 'HEADER', 'format': 'TEXT', 'text': 'x' * 61}, 'UTILITY')
    assert any('60' in e for e in errs)


def test_text_header_multiple_params():
    errs, _ = tv.validate_header({'type': 'HEADER', 'format': 'TEXT', 'text': '{{1}} {{2}}'}, 'UTILITY')
    assert any('1 parameter' in e for e in errs)


def test_location_header_auth_blocked():
    errs, _ = tv.validate_header({'type': 'HEADER', 'format': 'LOCATION'}, 'AUTHENTICATION')
    assert any('LOCATION' in e for e in errs)


# ── body / examples ──

def test_body_requires_example_for_placeholder():
    errs, _ = tv.validate_body({'type': 'BODY', 'text': 'Hi {{1}}'})
    assert any('example' in e for e in errs)


def test_body_positional_must_be_sequential():
    errs, _ = tv.validate_body({'type': 'BODY', 'text': 'Hi {{2}}', 'example': {'body_text': [['x']]}})
    assert any('sequential' in e for e in errs)


def test_body_mixed_params_rejected():
    errs, _ = tv.validate_body({'type': 'BODY', 'text': 'Hi {{1}} {{name}}', 'example': {'body_text': [['a']]}})
    assert any('mixes' in e for e in errs)


def test_body_too_long():
    errs, _ = tv.validate_body({'type': 'BODY', 'text': 'x' * 1025})
    assert any('1024' in e for e in errs)


# ── footer ──

def test_footer_no_variables():
    errs, _ = tv.validate_footer({'type': 'FOOTER', 'text': 'bye {{1}}'})
    assert any('variables' in e for e in errs)


# ── buttons ──

def test_buttons_url_limit():
    errs, _ = tv.validate_buttons([{'type': 'URL', 'text': 'a', 'url': 'u'}] * 3)
    assert any('2 URL' in e for e in errs)


def test_buttons_quick_reply_grouping():
    bad = [{'type': 'QUICK_REPLY', 'text': 'a'},
           {'type': 'URL', 'text': 'u', 'url': 'https://x'},
           {'type': 'QUICK_REPLY', 'text': 'b'}]
    err = tv.validate_button_grouping(bad)
    assert err is not None


def test_buttons_four_plus_warns():
    _, warns = tv.validate_buttons([{'type': 'QUICK_REPLY', 'text': str(i)} for i in range(4)])
    assert any('desktop' in w for w in warns)


# ── flow button ──

def test_flow_button_requires_reference():
    errs = tv.validate_flow_button({'type': 'FLOW', 'text': 'Go'})
    assert any('flow_id' in e for e in errs)


def test_flow_button_navigate_requires_screen():
    errs = tv.validate_flow_button({'type': 'FLOW', 'text': 'Go', 'flow_name': 'f', 'flow_action': 'navigate'})
    assert any('navigate_screen' in e for e in errs)


def test_flow_button_valid():
    errs = tv.validate_flow_button({'type': 'FLOW', 'text': 'Go', 'flow_name': 'f', 'flow_action': 'navigate', 'navigate_screen': 'WELCOME'})
    assert errs == []


# ── full template ──

def test_validate_template_requires_body():
    res = tv.validate_template({'name': 'n', 'language': 'en', 'category': 'UTILITY', 'components': [
        {'type': 'FOOTER', 'text': 'hi'}]})
    assert res['ok'] is False
    assert any('BODY' in e for e in res['errors'])


def test_validate_template_ok():
    res = tv.validate_template({'name': 'order_ok', 'language': 'en', 'category': 'UTILITY',
                                'components': [_valid_body('Hi {{1}}')]})
    assert res['ok'] is True
