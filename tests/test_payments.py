"""Tests for payment-related functionality in outbound WhatsApp handler."""
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))

#: The WABA1 sender. A payment send always carries one; _build_payment_settings no longer
#: substitutes a default when it cannot resolve a configuration.
PHONE_1 = 'phone-number-id-waba1-direct-1016149501586345'


class TestRetiredPaymentPayloads:
    """Legacy WhatsApp payment envelopes must not construct payment messages."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                import handler as h
                self.h = h
                self.build = h._build_message_payload

    def test_interactive_payment_flag_has_no_payment_composer(self):
        payload = self.build(
            '+919330994400', '', None, None, False, None, [],
            is_interactive_payment=True,
            order_details={'reference_id': 'WD-RETIRED-1'},
            phone_number_id=PHONE_1,
        )
        assert payload.get('type') != 'interactive'
        assert 'interactive' not in payload

    def test_payment_template_flag_has_no_order_details_button(self):
        payload = self.build(
            '+919330994400', '', None, None, True, 'retired_payment_template', ['en'],
            is_payment_template=True,
            order_details={'reference_id': 'WD-RETIRED-2'},
            phone_number_id=PHONE_1,
        )
        assert payload['type'] == 'template'
        buttons = [
            component for component in payload['template'].get('components', [])
            if component.get('type') == 'button'
        ]
        assert not any(button.get('sub_type') == 'order_details' for button in buttons)

    def test_only_checkout_template_is_a_payment_request_envelope(self):
        assert self.h._PAYMENT_REQUEST_KEYS == ('isCheckoutTemplate',)
        assert set(self.h._REMOVED_PAYMENT_REQUEST_KEYS) == {
            'isPaymentTemplate', 'isInteractivePayment'
        }


class TestOTPTemplatePayload:
    """Test OTP/Authentication template building."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _build_message_payload
                self.build = _build_message_payload

    def test_otp_copy_code(self):
        payload = self.build('+919330994400', '', None, None, True, 'otp_verify', ['en'],
                             is_otp_template=True, otp_code='123456', otp_button_type='copy_code')
        assert payload['type'] == 'template'
        btn = [c for c in payload['template']['components'] if c.get('type') == 'button']
        assert len(btn) == 1
        assert btn[0]['sub_type'] == 'copy_code'
        assert btn[0]['parameters'][0]['coupon_code'] == '123456'

    def test_otp_url_button(self):
        payload = self.build('+919330994400', '', None, None, True, 'otp_url', ['en'],
                             is_otp_template=True, otp_code='789012', otp_button_type='url')
        btn = [c for c in payload['template']['components'] if c.get('type') == 'button']
        assert btn[0]['sub_type'] == 'url'
        assert btn[0]['parameters'][0]['text'] == '789012'


class TestOrderStatusSend:
    """Order status is template-only; there is no service-window interactive branch."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'LIVE'}):
            with patch('boto3.resource') as mock_res, patch('boto3.client'):
                self.mock_table = MagicMock()
                mock_res.return_value.Table.return_value = self.mock_table
                import handler as h
                self.h = h
                self.send_order_status = h._handle_order_status_send

    def test_completed_order_status_uses_the_single_template(self):
        details = {'reference_id': 'WD-001', 'order_status': 'completed', 'amountPaise': 4900}
        with patch.object(self.h, '_send_message', return_value={'messageId': 'wamid.test'}) as send, \
             patch.object(self.h, '_store_message_record') as store:
            result = self.send_order_status(
                'msg-1', 'contact-1', '+919330994400', 'phone-id-1',
                details, 'req-1', template_name='wecare_order_status_v2')

        assert result['statusCode'] == 200
        payload = send.call_args.args[1]
        assert payload['type'] == 'template'
        assert payload['template']['name'] == 'wecare_order_status_v2'
        component = payload['template']['components'][0]
        assert component['type'] == 'order_status'
        parameter = component['parameters'][0]
        assert parameter['type'] == 'order_status'
        assert parameter['order_status']['order']['status'] == 'completed'
        assert store.call_args.kwargs['is_template'] is True

    def test_missing_template_refuses_instead_of_falling_back_interactive(self):
        details = {'reference_id': 'WD-002', 'order_status': 'shipped', 'amountPaise': 4900}
        with patch.object(self.h, '_send_message') as send, \
             patch.object(self.h, '_store_message_record') as store:
            result = self.send_order_status(
                'msg-2', 'contact-2', '+919330994400', 'phone-id-1',
                details, 'req-2', template_name='')

        assert result['statusCode'] == 409
        body = json.loads(result['body'])
        assert body['error'] == 'ORDER_STATUS_TEMPLATE_NOT_READY'
        send.assert_not_called()
        store.assert_not_called()

    @pytest.mark.parametrize('changes', [
        {}, {'status':'PAUSED'}, {'language':'hi'}, {'category':'MARKETING'},
        {'sub_category':'OTHER'},
    ])
    def test_status_template_readback_checks_type_language_and_approval(self, changes):
        row={'name':'wecare_order_status_v2','status':'APPROVED','category':'UTILITY',
             'sub_category':'ORDER_STATUS','language':'en',**changes}
        with patch.object(self.h,'_waba_for_sender',return_value='sender-waba'), \
             patch.object(self.h,'_fetch_approved_templates',return_value={'data':[row]}) as fetch:
            result=self.h._approved_order_status_template('phone-1','req')
        assert result == ('wecare_order_status_v2' if not changes else '')
        fetch.assert_called_once_with('sender-waba')


class TestPairRateLimit:
    """Test per-recipient pair rate limiting."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource') as mock_res, patch('boto3.client'):
                self.mock_table = MagicMock()
                mock_res.return_value.Table.return_value = self.mock_table
                from handler import _check_pair_rate_limit, _record_pair_rate_violation
                self.check = _check_pair_rate_limit
                self.record_violation = _record_pair_rate_violation

    def test_first_message_allowed(self):
        self.mock_table.get_item.return_value = {}
        allowed, retry = self.check('phone-1', '+919330994400')
        assert allowed is True
        assert retry == 0

    def test_recent_message_blocked(self):
        import time
        now = int(time.time())
        self.mock_table.get_item.return_value = {
            'Item': {'messageCount': Decimal(str(now - 2)), 'violations': Decimal('0')}
        }
        allowed, retry = self.check('phone-1', '+919330994400')
        assert allowed is False
        assert retry > 0

    def test_backoff_increases_with_violations(self):
        import time
        now = int(time.time())
        self.mock_table.get_item.return_value = {
            'Item': {'messageCount': Decimal(str(now - 10)), 'violations': Decimal('2')}
        }
        # With 2 violations, backoff = 6 * 4^2 = 96 seconds
        allowed, retry = self.check('phone-1', '+919330994400')
        assert allowed is False
        assert retry > 80


@pytest.mark.parametrize('payment_state', ['captured', 'paid', 'success'])
def test_verified_payment_words_project_to_processing_order_status(payment_state):
    """Verified payment vocabulary is translated to Meta fulfilment vocabulary before send."""
    import handler
    with patch.object(handler, '_send_message', return_value={'messageId': 'wamid.test'}), \
            patch.object(handler, '_store_message_record'), \
            patch.object(handler, '_emit_delivery_metric'):
        response = handler._handle_order_status_send(
            'message', 'contact', '+919999999999', 'sender',
            {'reference_id': 'OFFLINE', 'order_status': payment_state, 'amountPaise': 10000},
            'request', template_name='wecare_order_status_v2')
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['orderStatus'] == 'processing'
    assert body['type'] == 'order_status'
