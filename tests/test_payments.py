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


class TestInteractivePaymentPayload:
    """Test interactive payment (order_details) message building."""

    @pytest.fixture(autouse=True)
    def setup(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'outbound-whatsapp'))
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1', 'SEND_MODE': 'DRY_RUN'}):
            with patch('boto3.resource'), patch('boto3.client'):
                from handler import _build_message_payload
                self.build = _build_message_payload

    def test_interactive_payment_basic(self):
        order = {
            'reference_id': 'WD-TEST-001',
            'type': 'digital-goods',
            'currency': 'INR',
            'order': {
                'items': [{'name': 'Service Fee', 'amount': {'value': 4900}, 'quantity': 1, 'retailer_id': 'SVC1'}],
                'subtotal': {'value': 4900},
                'discount': {'value': 0},
                'shipping': {'value': 0},
                'tax': {'value': 0},
            },
        }
        # A sender is now REQUIRED. _build_payment_settings used to fall back to
        # DEFAULT_PAYMENT_CONFIG when it could not resolve one, which meant a payment request
        # went out naming a configuration nobody had verified. It now refuses, so these tests
        # pass the phone id a real send always carries.
        payload = self.build('+919330994400', '', None, None, False, None, [],
                             is_interactive_payment=True, order_details=order,
                             phone_number_id=PHONE_1)
        assert payload['type'] == 'interactive'
        assert payload['interactive']['type'] == 'order_details'
        assert payload['interactive']['action']['name'] == 'review_and_pay'
        # reference_id is sanitized by _sanitize_reference_id
        ref_id = payload['interactive']['action']['parameters']['reference_id']
        assert ref_id  # non-empty
        assert 'TEST' in ref_id  # contains original identifier

    def test_interactive_payment_with_gst(self):
        order = {
            'reference_id': 'WD-GST-001',
            'order': {
                'items': [{'name': 'Ticket', 'amount': {'value': 10000}, 'quantity': 2, 'gstRate': 18}],
                'discount': {'value': 0},
                'shipping': {'value': 500},
                'tax': {'value': 0},
            },
        }
        payload = self.build('+919330994400', '', None, None, False, None, [],
                             is_interactive_payment=True, order_details=order,
                             phone_number_id=PHONE_1)
        params = payload['interactive']['action']['parameters']
        # Items: 10000 * 2 = 20000, GST 18% = 3600, Conv fee on 23600
        assert params['total_amount']['value'] > 20000

    def test_an_unresolvable_payment_configuration_refuses_to_build(self):
        """The fallback that was removed. It logged a warning and then sent
        DEFAULT_PAYMENT_CONFIG anyway, so an unverified configuration name reached the
        customer and failed when they tapped Pay — the most expensive place to find out."""
        import handler
        order = {'reference_id': 'WD-TEST-002', 'order': {
            'items': [{'name': 'X', 'amount': {'value': 100}, 'quantity': 1}],
            'subtotal': {'value': 100}, 'discount': {'value': 0},
            'shipping': {'value': 0}, 'tax': {'value': 0}}}

        # No sender resolves to no configuration.
        with pytest.raises(handler.PaymentConfigurationUnresolved):
            self.build('+919330994400', '', None, None, False, None, [],
                       is_interactive_payment=True, order_details=order)

    def test_an_unrecognised_configuration_name_refuses_to_build(self):
        import handler
        order = {'reference_id': 'WD-TEST-003',
                 'payment_configuration': 'WECARE-RAZOR-PAY',  # retired 2026-08-23
                 'order': {
                     'items': [{'name': 'X', 'amount': {'value': 100}, 'quantity': 1}],
                     'subtotal': {'value': 100}, 'discount': {'value': 0},
                     'shipping': {'value': 0}, 'tax': {'value': 0}}}

        with pytest.raises(handler.PaymentConfigurationUnresolved):
            self.build('+919330994400', '', None, None, False, None, [],
                       is_interactive_payment=True, order_details=order,
                       phone_number_id=PHONE_1)

    def test_payment_template_payload(self):
        order = {'reference_id': 'WD-PAY-001', 'total_amount': {'value': 4900, 'offset': 100}, 'currency': 'INR'}
        payload = self.build('+919330994400', '', None, None, True, 'payment_reminder', ['en'],
                             is_payment_template=True, order_details=order)
        assert payload['type'] == 'template'
        assert payload['template']['name'] == 'payment_reminder'
        # Should have button component with order_details
        button_comp = [c for c in payload['template']['components'] if c.get('type') == 'button']
        assert len(button_comp) == 1
        assert button_comp[0]['sub_type'] == 'order_details'


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
    """Test order_status message sending."""

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

    def test_completed_order_status(self):
        details = {'reference_id': 'WD-001', 'order_status': 'completed', 'amount': 49.00}
        with patch.object(self.h, '_send_message', return_value={'messageId': 'wamid.test'}), \
             patch.object(self.h, '_store_message_record'):
            result = self.send_order_status('msg-1', 'contact-1', '+919330994400',
                                             'phone-id-1', details, 'req-1')
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['type'] == 'order_status'
        assert body['orderStatus'] == 'completed'

    def test_failed_order_status(self):
        details = {'reference_id': 'WD-002', 'order_status': 'failed', 'amount': 0}
        with patch.object(self.h, '_send_message', return_value={'messageId': 'wamid.test'}), \
             patch.object(self.h, '_store_message_record'):
            result = self.send_order_status('msg-2', 'contact-2', '+919330994400',
                                             'phone-id-1', details, 'req-2')
        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['orderStatus'] == 'failed'

    def test_completed_order_status_uses_configured_template_outside_window(self):
        details = {'reference_id': 'WD-003', 'order_status': 'completed', 'amountPaise': 4900}
        with patch.object(self.h, '_send_message', return_value={'messageId': 'wamid.template'}) as send, \
             patch.object(self.h, '_store_message_record') as store:
            result = self.send_order_status(
                'msg-3', 'contact-3', '+919330994400', 'phone-id-1',
                details, 'req-3', template_name='wecare_order_status',
            )

        assert result['statusCode'] == 200
        payload = send.call_args.args[1]
        assert payload['type'] == 'template'
        assert payload['template']['name'] == 'wecare_order_status'
        component = payload['template']['components'][0]
        assert component['type'] == 'order_status'
        parameter = component['parameters'][0]
        assert parameter['type'] == 'order_status'
        assert parameter['order_status']['reference_id']
        assert parameter['order_status']['order']['status'] == 'completed'
        assert store.call_args.kwargs['is_template'] is True

    def test_completed_order_status_stays_interactive_inside_window(self):
        details = {'reference_id': 'WD-004', 'order_status': 'completed', 'amountPaise': 4900}
        with patch.object(self.h, '_send_message', return_value={'messageId': 'wamid.interactive'}) as send, \
             patch.object(self.h, '_store_message_record') as store:
            result = self.send_order_status(
                'msg-4', 'contact-4', '+919330994400', 'phone-id-1',
                details, 'req-4',
            )

        assert result['statusCode'] == 200
        payload = send.call_args.args[1]
        assert payload['type'] == 'interactive'
        assert payload['interactive']['type'] == 'order_status'
        assert payload['interactive']['action']['name'] == 'review_order'
        assert store.call_args.kwargs['is_template'] is False

    @pytest.mark.parametrize('changes', [
        {}, {'status':'PAUSED'}, {'language':'hi'}, {'category':'MARKETING'},
        {'sub_category':'OTHER'},
    ])
    def test_status_template_readback_checks_type_language_and_approval(self, changes):
        row={'name':'verified_status','status':'APPROVED','category':'UTILITY',
             'sub_category':'ORDER_STATUS','language':'en',**changes}
        with patch.object(self.h,'WA_ORDER_STATUS_TEMPLATE','verified_status'), \
             patch.object(self.h,'WA_ORDER_STATUS_TEMPLATE_LANGUAGE','en'), \
             patch.object(self.h,'_waba_for_sender',return_value='sender-waba'), \
             patch.object(self.h,'_fetch_approved_templates',return_value={'data':[row]}) as fetch:
            result=self.h._approved_order_status_template('phone-1','req')
        assert result == ('verified_status' if not changes else '')
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
