"""The single shared Flow-share builder sends only PUBLISHED canonical Flows, by capability.

WHY THIS FILE EXISTS
--------------------
`build_flow_send_envelope` is the ONE way to share/send a WhatsApp Flow by capability. These
tests pin the two guarantees that matter at a customer boundary:

  1. a PUBLISHED capability produces the exact `interactiveData` envelope the outbound lambda
     consumes, with a phone-bound flow_token in the existing
     `{prefix}-{uuid}-waba-{1|2}-ph-{phone}` convention and the correct waba suffix;
  2. a DRAFT or NONE capability, or a phone-less / empty call, is REFUSED — a non-PUBLISHED
     Flow id must never reach a customer.

The DRAFT-refusal test is written so it FAILS if the status gate is removed.

Pure/offline: no boto3, no network. The builder is exec'd straight from the canonical module,
and the token segment is injected so the envelope is deterministic.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))

from lambda_utils.canonical_flows import (  # noqa: E402
    CANONICAL_FLOWS,
    FlowNotSendable,
    build_flow_send_envelope,
)

# Matches flows/common.PHONE1_ID / PHONE2_ID semantics: suffix '1' for phone_number_id_1.
PHONE1 = 'phone-number-id-waba1'
PHONE2 = 'phone-number-id-waba2'


def _build(capability, **kw):
    kw.setdefault('phone', '919812345678')
    kw.setdefault('phone_number_id', PHONE1)
    kw.setdefault('phone_number_id_1', PHONE1)
    kw.setdefault('cta', 'Open')
    kw.setdefault('body', 'hello')
    kw.setdefault('now', lambda: 'TOKEN')
    return build_flow_send_envelope(capability, **kw)


def test_published_subscribe_envelope():
    env = _build('subscribe', cta='Subscribe', body='Join us', footer='WECARE.DIGITAL')
    assert env['flowId'] == '1386523953464380'
    assert env['flowCta'] == 'Subscribe'
    assert env['body'] == 'Join us'
    assert env['footer'] == 'WECARE.DIGITAL'
    assert env['flowAction'] == 'data_exchange'
    # Phone-bound token, waba '1' for phone_number_id_1.
    assert env['flowToken'] == 'subscribe-TOKEN-waba-1-ph-919812345678'
    assert 'header' not in env


def test_published_leave_review_envelope():
    env = _build('leave_review', cta='Leave a review', body='Tell us how we did')
    assert env['flowId'] == '940049388908144'
    assert env['flowToken'].endswith('-ph-919812345678')
    assert env['flowToken'].startswith('leave_review-')


def test_waba_suffix_selects_two_for_other_phone():
    env = _build('subscribe', phone_number_id=PHONE2, phone_number_id_1=PHONE1)
    assert env['flowToken'] == 'subscribe-TOKEN-waba-2-ph-919812345678'


def test_token_prefix_and_header_overrides():
    env = _build('subscribe', token_prefix='sub', header='Welcome')
    assert env['flowToken'].startswith('sub-')
    assert env['header'] == 'Welcome'


def test_default_footer_when_omitted():
    env = _build('subscribe', footer=None)
    assert env['footer'] == 'WECARE.DIGITAL'


def test_random_token_segment_when_no_now():
    a = build_flow_send_envelope(
        'subscribe', phone='91999', phone_number_id=PHONE1,
        phone_number_id_1=PHONE1, cta='x', body='y')
    b = build_flow_send_envelope(
        'subscribe', phone='91999', phone_number_id=PHONE1,
        phone_number_id_1=PHONE1, cta='x', body='y')
    assert a['flowToken'] != b['flowToken']  # uuid4 segment differs


@pytest.mark.parametrize('capability', ['orders', 'drop_docs', 'amend_request', 'shipments'])
def test_draft_capability_is_refused(capability):
    # Guardrail: these are DRAFT in the canonical map and must never be sent to a customer.
    assert CANONICAL_FLOWS[capability][1] == 'DRAFT'
    with pytest.raises(FlowNotSendable):
        _build(capability)


def test_draft_refusal_depends_on_the_status_gate():
    # Make the gate's role explicit: the SAME call that is refused for a DRAFT capability
    # would succeed if that capability were PUBLISHED. If the status gate were removed, the
    # DRAFT send above would NOT raise and those tests would fail — this documents why.
    assert CANONICAL_FLOWS['orders'][0] is not None  # it HAS an id
    assert CANONICAL_FLOWS['orders'][1] != 'PUBLISHED'  # but is not published


@pytest.mark.parametrize('capability', ['track_request', 'vault'])
def test_none_capability_is_refused(capability):
    assert CANONICAL_FLOWS[capability][1] == 'NONE'
    with pytest.raises(FlowNotSendable):
        _build(capability)


def test_unknown_capability_is_refused():
    with pytest.raises(FlowNotSendable):
        _build('does_not_exist')


def test_phone_less_call_is_refused():
    with pytest.raises(FlowNotSendable):
        _build('subscribe', phone='')


def test_empty_capability_is_refused():
    with pytest.raises(FlowNotSendable):
        _build('')
