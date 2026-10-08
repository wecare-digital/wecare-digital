"""Payments are enabled only by a live readback, never by a constant in source.

The case that motivated this module is the first test below: on 2026-09-30 the live
`GET /{waba}/payment_configurations` returned HTTP 200 with **zero** configurations, while the
repository held four configuration names across three files and a doc recording two of them as
verified. So the send path was ready to name a configuration that does not exist, and Meta's
documentation says an invalid `configuration_name` leaves the customer simply unable to pay.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..',
                                                'amplify', 'functions', 'shared')))

from lambda_utils import payment_readiness as pr  # noqa: E402

WABA = '2094615664435155'
CONFIG = 'WECAREDIGITAL'
# Authoritative as of 2026-09-30 (owner-confirmed against the live Meta dashboard): this is the
# Payment gateway MID Meta reports for WECAREDIGITAL. The previously-assumed acc_RETIRED_FIXTURE
# was the stale env value, not what the configuration points at. See payment_readiness.py.
MID = 'acc_TTFSyolquKEZEy'


def _configuration(**overrides):
    base = {
        'configuration_name': CONFIG,
        'status': 'active',
        'payment_gateway': {'type': 'razorpay', 'merchant_id': MID},
        'merchant_category_code': '7392',
        'purpose_code': '03',
    }
    base.update(overrides)
    return base


def _fetcher(response):
    def fetch(waba_id):
        assert waba_id == WABA
        return response
    return fetch


def _evaluate(response, *, config=CONFIG, mid=MID, waba=WABA):
    return pr.evaluate(
        expected_waba_id=waba,
        expected_configuration_name=config,
        expected_provider_mid=mid,
        fetch_configurations=_fetcher(response),
    )


@pytest.fixture(autouse=True)
def _no_kill_switch(monkeypatch):
    monkeypatch.delenv('WA_PAYMENTS_DISABLED', raising=False)


# ── the seven required cases ────────────────────────────────────────────────────

def test_zero_configurations_blocks_payment():
    """The measured live state on 2026-09-30."""
    verdict = _evaluate({'data': []})
    assert verdict.state == pr.PAYMENT_CONFIG_MISSING
    assert not verdict.ready and not verdict


def test_a_named_constant_with_no_provider_config_blocks_payment():
    """§5. The name exists in source; Meta reports something else entirely."""
    verdict = _evaluate({'data': [_configuration(configuration_name='SOMETHING-ELSE')]})
    assert verdict.state == pr.PAYMENT_CONFIG_NAME_UNKNOWN
    assert 'SOMETHING-ELSE' in verdict.checked_configurations


def test_a_mid_mismatch_blocks_payment():
    """A disagreement means payments settle into an account we are not reconciling against.
    The reported MID here is the now-stale acc_RETIRED_FIXTURE; expected is the authoritative
    acc_TTFSyolquKEZEy, so this must block."""
    verdict = _evaluate({'data': [_configuration(
        payment_gateway={'type': 'razorpay', 'merchant_id': 'acc_RETIRED_FIXTURE'})]})
    assert verdict.state == pr.RAZORPAY_MID_MISMATCH
    assert verdict.provider_mid == 'acc_RETIRED_FIXTURE'


def test_a_configuration_on_the_wrong_waba_blocks_payment():
    verdict = _evaluate({'data': [_configuration(waba_id='2513394156072604')]})
    assert verdict.state == pr.PAYMENT_CONFIG_WABA_MISMATCH


@pytest.mark.parametrize('status', ['pending', 'disabled', 'inactive', '', 'ACTIVE_LATER'])
def test_a_non_active_configuration_blocks_payment(status):
    verdict = _evaluate({'data': [_configuration(status=status)]})
    assert verdict.state == pr.PAYMENT_CONFIG_INACTIVE


def test_meta_being_unavailable_fails_closed():
    def explode(_waba):
        raise TimeoutError('graph unreachable')

    verdict = pr.evaluate(
        expected_waba_id=WABA, expected_configuration_name=CONFIG,
        expected_provider_mid=MID, fetch_configurations=explode)
    assert verdict.state == pr.META_UNAVAILABLE
    assert not verdict.ready


def test_a_verified_active_razorpay_configuration_enables_payment():
    verdict = _evaluate({'data': [_configuration()]})
    assert verdict.state == pr.PAYMENT_READY
    assert verdict.ready and verdict
    assert verdict.configuration_name == CONFIG
    assert verdict.provider_mid == MID
    assert verdict.gateway == 'razorpay'


# ── the readback must actually answer the question ─────────────────────────────

def test_an_absent_data_field_is_not_an_empty_list():
    """One means Meta did not answer; the other means it answered 'none'. Reporting a missing
    key as MISSING would claim knowledge we do not have."""
    assert _evaluate({}).state == pr.META_UNAVAILABLE
    assert _evaluate({'paging': {}}).state == pr.META_UNAVAILABLE
    assert _evaluate({'data': []}).state == pr.PAYMENT_CONFIG_MISSING


def test_a_graph_error_object_fails_closed():
    assert _evaluate({'error': {'message': 'nope', 'code': 190}}).state == pr.META_UNAVAILABLE


@pytest.mark.parametrize('response', [None, 'data', 42, [], {'data': 'not-a-list'}])
def test_a_malformed_readback_fails_closed(response):
    assert _evaluate(response).state == pr.META_UNAVAILABLE


# ── the gate cannot be bypassed ────────────────────────────────────────────────

def test_a_missing_expected_mid_does_not_skip_the_check():
    """'We did not compare the merchant id' must never read the same as 'it matched'."""
    verdict = _evaluate({'data': [_configuration()]}, mid='')
    assert verdict.state == pr.CONFIGURATION_UNVERIFIED


def test_a_configuration_reporting_no_mid_is_unverified_not_ready():
    verdict = _evaluate({'data': [_configuration(
        payment_gateway={'type': 'razorpay'})]})
    assert verdict.state == pr.CONFIGURATION_UNVERIFIED


def test_a_non_razorpay_gateway_blocks_payment():
    """Razorpay is the only gateway; PayU is retired and its secret is permanently deleted."""
    for gateway in ('payu', 'billdesk', 'zaakpay', ''):
        verdict = _evaluate({'data': [_configuration(
            payment_gateway={'type': gateway, 'merchant_id': MID})]})
        assert verdict.state == pr.PAYMENT_CONFIG_INACTIVE


@pytest.mark.parametrize('missing', ['waba', 'config'])
def test_missing_expectations_block_rather_than_default(missing):
    kwargs = {'waba': WABA, 'config': CONFIG}
    kwargs[missing] = ''
    verdict = _evaluate({'data': [_configuration()]}, **kwargs)
    assert verdict.state == pr.CONFIGURATION_UNVERIFIED


def test_the_kill_switch_can_only_tighten(monkeypatch):
    """There is deliberately no env var that turns readiness ON: the only route to
    PAYMENT_READY is a successful live readback."""
    monkeypatch.setenv('WA_PAYMENTS_DISABLED', 'true')
    assert _evaluate({'data': [_configuration()]}).state == pr.CONFIGURATION_UNVERIFIED

    monkeypatch.setenv('WA_PAYMENTS_DISABLED', 'false')
    assert _evaluate({'data': [_configuration()]}).state == pr.PAYMENT_READY


def test_no_environment_variable_can_force_readiness():
    """A grep-level guarantee: the module must not read a 'payments enabled' style flag that
    could short-circuit the readback."""
    import inspect
    source = inspect.getsource(pr)
    assert 'WA_PAYMENTS_ENABLED' not in source
    assert source.count('os.environ') == 1, \
        'the only env read should be the tightening kill switch'


def test_every_blocking_state_is_falsy_and_enumerated():
    assert pr.PAYMENT_READY not in pr.BLOCKING_STATES
    assert pr.ALL_STATES == pr.BLOCKING_STATES | {pr.PAYMENT_READY}
    for state in pr.BLOCKING_STATES:
        assert not pr.PaymentReadiness(state, 'x').ready
        assert not pr.PaymentReadiness(state, 'x')


def test_an_unknown_state_is_refused():
    with pytest.raises(ValueError):
        pr.PaymentReadiness('PROBABLY_FINE', 'x')


# ── what a customer may be told ────────────────────────────────────────────────

def test_the_customer_message_leaks_no_internals():
    """§39. A shopper must not learn our WABA id, MID or configuration name from an error."""
    verdicts = [
        _evaluate({'data': []}),
        _evaluate({'data': [_configuration(
            payment_gateway={'type': 'razorpay', 'merchant_id': 'acc_OTHER'})]}),
        _evaluate({'data': [_configuration(waba_id='2513394156072604')]}),
    ]
    for verdict in verdicts:
        message = verdict.customer_message()
        assert message
        for secret_ish in (WABA, MID, CONFIG, 'acc_OTHER', 'WABA', 'merchant'):
            assert secret_ish not in message


def test_the_customer_message_is_identical_across_blocking_states():
    """Distinguishing causes here would leak configuration state to anyone opening checkout."""
    messages = {
        _evaluate({'data': []}).customer_message(),
        _evaluate({'data': [_configuration(status='pending')]}).customer_message(),
        _evaluate({'data': [_configuration(configuration_name='OTHER')]}).customer_message(),
    }
    assert len(messages) == 1


def test_a_ready_verdict_has_no_customer_message():
    assert _evaluate({'data': [_configuration()]}).customer_message() == ''


def test_the_operator_view_carries_the_detail():
    verdict = _evaluate({'data': [_configuration()]})
    detail = verdict.as_dict()
    assert detail['ready'] is True
    assert detail['wabaId'] == WABA
    assert detail['providerMid'] == MID
    assert detail['checkedConfigurations'] == [CONFIG]


# ── require_ready ──────────────────────────────────────────────────────────────

def test_require_ready_raises_for_a_blocked_verdict():
    verdict = _evaluate({'data': []})
    with pytest.raises(pr.PaymentNotReady) as caught:
        pr.require_ready(verdict)
    assert caught.value.readiness.state == pr.PAYMENT_CONFIG_MISSING


def test_require_ready_is_silent_when_ready():
    pr.require_ready(_evaluate({'data': [_configuration()]}))


# ══════════════════════════════════════════════════════════════════════════════
# the 24-hour window, and delivery readiness as a SEPARATE question
# ══════════════════════════════════════════════════════════════════════════════

NOW = 1_700_000_000


def test_the_window_is_open_inside_24_hours():
    assert pr.window_is_open(NOW - 3600, now=NOW)
    assert pr.window_is_open(NOW - (24 * 3600) + 1, now=NOW)


def test_the_window_is_closed_at_and_past_24_hours():
    assert not pr.window_is_open(NOW - (24 * 3600), now=NOW)
    assert not pr.window_is_open(NOW - (48 * 3600), now=NOW)


@pytest.mark.parametrize('unknown', [None, 0, ''])
def test_an_unknown_last_inbound_counts_as_closed(unknown):
    """Conservative, and correct: a free-form order_details outside the window is rejected by
    Meta or billed as a new conversation, so assuming open turns a missing record into a failed
    checkout."""
    assert not pr.window_is_open(unknown, now=NOW)
    assert pr.template_required(unknown, now=NOW)


def _delivery(response, **kw):
    params = dict(
        expected_waba_id=WABA, expected_configuration_name=CONFIG,
        expected_provider_mid=MID, fetch_configurations=_fetcher(response),
    )
    return pr.evaluate_for_delivery(now=NOW, **{**params, **kw})


def test_account_readiness_does_not_need_window_information():
    """The design error this split fixed: with the window folded into `evaluate`, a default of
    None made PAYMENT_READY unreachable for an account-level check."""
    import inspect
    assert 'last_inbound_at' not in inspect.signature(pr.evaluate).parameters
    assert _evaluate({'data': [_configuration()]}).state == pr.PAYMENT_READY


def test_an_open_window_needs_no_template():
    verdict = _delivery({'data': [_configuration()]}, last_inbound_at=NOW - 60)
    assert verdict.state == pr.PAYMENT_READY


def test_a_closed_window_with_no_template_configured_blocks():
    verdict = _delivery({'data': [_configuration()]}, last_inbound_at=NOW - (25 * 3600))
    assert verdict.state == pr.PAYMENT_TEMPLATE_MISSING


def test_a_configured_template_that_was_not_verified_blocks():
    """Measured live: this WABA holds only `wecare_otp`. A configured name proves nothing."""
    verdict = _delivery({'data': [_configuration()]},
                        last_inbound_at=NOW - (25 * 3600),
                        payment_template_name='wecare_pay')
    assert verdict.state == pr.CONFIGURATION_UNVERIFIED


def test_a_template_absent_from_meta_blocks():
    verdict = _delivery(
        {'data': [_configuration()]}, last_inbound_at=NOW - (25 * 3600),
        payment_template_name='wecare_pay',
        fetch_templates=lambda _w: {'templates': [
            {'name': 'wecare_otp', 'status': 'APPROVED'}]})
    assert verdict.state == pr.PAYMENT_TEMPLATE_MISSING
    assert 'wecare_otp' in verdict.reason


@pytest.mark.parametrize('status', ['PENDING', 'REJECTED', 'PAUSED', 'DISABLED', 'pending'])
def test_a_non_approved_template_does_not_count(status):
    """A name that exists but cannot be sent is the same class of error as a local constant."""
    verdict = _delivery(
        {'data': [_configuration()]}, last_inbound_at=NOW - (25 * 3600),
        payment_template_name='wecare_pay',
        fetch_templates=lambda _w: {'templates': [
            {'name': 'wecare_pay', 'status': status}]})
    assert verdict.state == pr.PAYMENT_TEMPLATE_MISSING


def test_an_approved_template_outside_the_window_is_ready():
    verdict = _delivery(
        {'data': [_configuration()]}, last_inbound_at=NOW - (25 * 3600),
        payment_template_name='wecare_pay',
        fetch_templates=lambda _w: {'templates': [
            {'name': 'wecare_pay', 'status': 'APPROVED'},
            {'name': 'wecare_otp', 'status': 'APPROVED'}]})
    assert verdict.state == pr.PAYMENT_READY


def test_a_template_read_failure_fails_closed():
    def explode(_waba):
        raise TimeoutError('graph unreachable')

    verdict = _delivery({'data': [_configuration()]},
                        last_inbound_at=NOW - (25 * 3600),
                        payment_template_name='wecare_pay',
                        fetch_templates=explode)
    assert verdict.state == pr.META_UNAVAILABLE


def test_delivery_readiness_never_rescues_a_broken_account():
    """An open window must not paper over a missing configuration."""
    verdict = _delivery({'data': []}, last_inbound_at=NOW - 60)
    assert verdict.state == pr.PAYMENT_CONFIG_MISSING


def test_the_template_readback_accepts_both_graph_shapes():
    for shape in ({'templates': [{'name': 'wecare_pay', 'status': 'APPROVED'}]},
                  {'data': [{'name': 'wecare_pay', 'status': 'APPROVED'}]},
                  [{'name': 'wecare_pay', 'status': 'APPROVED'}]):
        verdict = _delivery({'data': [_configuration()]},
                            last_inbound_at=NOW - (25 * 3600),
                            payment_template_name='wecare_pay',
                            fetch_templates=lambda _w, s=shape: s)
        assert verdict.state == pr.PAYMENT_READY


# ── the REAL live Meta shape (measured 2026-10-08 via a raw probe of the live edge) ──────────
#
# The config lives one level down under `data[].payment_configurations[]`, and the gateway is
# reported as flat `provider_name`/`provider_mid` siblings — NOT the nested
# `payment_gateway: {type, merchant_id}` the fixtures above use. The business-api handler
# flattens the nesting before calling evaluate; evaluate itself must read provider_mid.

def _live_configuration(**overrides):
    """The exact object Meta returns for WECAREDIGITAL (flattened out of its data[] wrapper)."""
    base = {
        'configuration_name': CONFIG,
        'merchant_category_code': {'code': '7392', 'description': 'Management, consulting'},
        'purpose_code': {'code': '03', 'description': 'Travel'},
        'status': 'Active',          # capital A, as Meta sends it
        'provider_mid': MID,
        'provider_name': 'Razorpay',
    }
    base.update(overrides)
    return base


def test_the_real_live_provider_mid_shape_is_accepted():
    """Regression for the false negative that blocked every payment on 2026-10-08: a config
    carrying provider_name/provider_mid (not payment_gateway.merchant_id) must read as READY."""
    verdict = _evaluate({'data': [_live_configuration()]})
    assert verdict.ready is True
    assert verdict.state == pr.PAYMENT_READY


def test_a_live_shape_mid_mismatch_still_fails_closed():
    verdict = _evaluate({'data': [_live_configuration(provider_mid='acc_SOMEONE_ELSE')]})
    assert verdict.ready is False
    assert verdict.state == pr.RAZORPAY_MID_MISMATCH


def test_a_live_shape_inactive_config_still_fails_closed():
    verdict = _evaluate({'data': [_live_configuration(status='Deactivated')]})
    assert verdict.ready is False
    assert verdict.state == pr.PAYMENT_CONFIG_INACTIVE
