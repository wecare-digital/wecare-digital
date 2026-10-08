"""Official Business Account status read (item 4) -- whatsapp-business-api._get_oba_status.

The rollup is FOUR-valued on purpose. Two WABAs with four numbers between them can
legitimately be half-verified, so a boolean would have to pick a lie; and an empty
phone list is UNKNOWN rather than NOT_OFFICIAL, because "the read did not tell us" is a
different fact from "not official".
"""
import inspect
import json
import os
import re
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))

_WABA_MANAGEMENT = os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging',
    'waba-management', 'handler.py')


def _load_handler():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            import handler
            return handler


def _phone(pid, official):
    return {'id': pid, 'display_phone_number': '+91 80 3183 0030',
            'verified_name': 'WECARE.DIGITAL', 'quality_rating': 'GREEN',
            'code_verification_status': 'VERIFIED', 'name_status': 'APPROVED',
            'is_official_business_account': official}


class TestObaStatus:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.handler = _load_handler()

    def _read(self, graph_result, waba_id='WABA1'):
        calls = []

        def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
            calls.append({'endpoint': endpoint, 'method': method, 'params': params})
            return graph_result

        with patch.object(self.handler, '_graph_api', side_effect=fake_graph) as gm, \
                patch.object(self.handler, 'logger', MagicMock()):
            resp = self.handler._get_oba_status(waba_id)
        return resp, json.loads(resp['body']), calls, gm

    # 1
    def test_all_official_rolls_up_to_official(self):
        resp, body, _, _ = self._read({'data': [_phone('p1', True), _phone('p2', True)]})
        assert resp['statusCode'] == 200
        assert body['obaStatus'] == 'OFFICIAL'
        assert body['wabaId'] == 'WABA1'
        assert len(body['phones']) == 2
        assert body['phones'][0]['phoneId'] == 'p1'
        assert body['phones'][0]['nameStatus'] == 'APPROVED'
        assert 'Meta' in body['note']

    # 2
    def test_mixed_rolls_up_to_partial(self):
        """The case a boolean would get wrong."""
        resp, body, _, _ = self._read({'data': [_phone('p1', True), _phone('p2', False)]})
        assert resp['statusCode'] == 200
        assert body['obaStatus'] == 'PARTIAL'

    # 3
    def test_none_official_rolls_up_to_not_official(self):
        resp, body, _, _ = self._read({'data': [_phone('p1', False), _phone('p2', False)]})
        assert body['obaStatus'] == 'NOT_OFFICIAL'

    def test_a_missing_flag_reads_the_same_as_false(self):
        bare = {'id': 'p1', 'display_phone_number': '+91', 'verified_name': 'X'}
        resp, body, _, _ = self._read({'data': [bare]})
        assert body['obaStatus'] == 'NOT_OFFICIAL'
        assert body['phones'][0]['isOfficialBusinessAccount'] is False
        assert body['phones'][0]['nameStatus'] == ''

    # 4
    def test_empty_phone_list_is_unknown_not_not_official(self):
        resp, body, _, _ = self._read({'data': []})
        assert body['obaStatus'] == 'UNKNOWN'
        assert body['obaStatus'] != 'NOT_OFFICIAL'
        assert body['phones'] == []

    # 5
    def test_graph_error_is_surfaced(self):
        err = {'error': {'message': '(#100) Tried accessing nonexisting field', 'code': 100}}
        resp, body, _, _ = self._read(err)
        assert resp['statusCode'] == 400
        assert body['error']['message'] == '(#100) Tried accessing nonexisting field'

    # 6
    def test_missing_waba_id_is_refused(self):
        event = {'requestContext': {'http': {'method': 'GET', 'path': '/wa-business/oba-status'}},
                 'queryStringParameters': {}, 'body': None}
        with patch.object(self.handler, 'require_auth', return_value=None), \
                patch.object(self.handler, '_graph_api') as gm:
            resp = self.handler.handler(event, None)
        assert resp['statusCode'] == 400
        assert json.loads(resp['body'])['error'] == 'wabaId required'
        assert gm.call_count == 0

    def test_the_dispatcher_reaches_the_read(self):
        event = {'requestContext': {'http': {'method': 'GET', 'path': '/wa-business/oba-status'}},
                 'queryStringParameters': {'wabaId': 'WABA1'}, 'body': None}
        with patch.object(self.handler, 'require_auth', return_value=None), \
                patch.object(self.handler, '_get_oba_status',
                             return_value={'statusCode': 200, 'body': '{}'}) as read:
            resp = self.handler.handler(event, None)
        assert resp['statusCode'] == 200
        read.assert_called_once_with('WABA1')

    # 7
    def test_requested_fields_are_only_proven_ones(self):
        """Every token in _OBA_PHONE_FIELDS must already appear in a field string this
        account is known to resolve. Both reference strings are PARSED FROM SOURCE rather
        than copied here: a copy drifts, and noticing drift is the point of the test.
        """
        _, _, calls, _ = self._read({'data': [_phone('p1', True)]})
        assert len(calls) == 1
        assert calls[0]['params'] == {'fields': self.handler._OBA_PHONE_FIELDS}
        assert calls[0]['endpoint'] == 'WABA1/phone_numbers'

        # Reference 1: _get_phone_settings' own literal in the same module.
        settings_src = inspect.getsource(self.handler._get_phone_settings)
        settings_fields = re.findall(r"'fields':\s*'([^']+)'", settings_src)
        assert settings_fields, 'could not parse _get_phone_settings field literal'

        # Reference 2: waba-management's phone_fields literal.
        with open(os.path.abspath(_WABA_MANAGEMENT), 'r', encoding='utf-8') as fh:
            waba_src = fh.read()
        waba_fields = re.findall(r"phone_fields\s*=\s*'([^']+)'", waba_src)
        assert waba_fields, 'could not parse waba-management phone_fields literal'

        proven = set()
        for literal in settings_fields + waba_fields:
            proven.update(t.strip() for t in literal.split(','))

        for token in self.handler._OBA_PHONE_FIELDS.split(','):
            assert token.strip() in proven, f'{token} is not proven on this account'

    # 8
    def test_the_route_is_read_only(self):
        """POST and DELETE reach no mutating call: _graph_api is only ever invoked with
        method='GET' (its default), so nothing requests or mutates OBA status."""
        for method in ('GET', 'POST', 'DELETE'):
            event = {'requestContext': {'http': {'method': method, 'path': '/wa-business/oba-status'}},
                     'queryStringParameters': {'wabaId': 'WABA1'}, 'body': None}
            calls = []

            def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
                calls.append(method)
                return {'data': [_phone('p1', True)]}

            with patch.object(self.handler, 'require_auth', return_value=None), \
                    patch.object(self.handler, '_graph_api', side_effect=fake_graph), \
                    patch.object(self.handler, 'logger', MagicMock()):
                self.handler.handler(event, None)
            assert calls == ['GET'], f'{method} produced {calls}'
