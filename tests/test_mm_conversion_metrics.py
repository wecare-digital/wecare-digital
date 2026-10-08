"""MM API conversion-metrics read (item 7) -- whatsapp-business-api.

Two decisions are pinned here because both are easy to "fix" into something worse:

* A Graph error answers **200 with available:false**, never 400. The edge name is
  unverified on this account, so a panel must be able to render "not available on this
  account" rather than an error toast. That is the honest-refusal contract.
* The rows are returned **unreshaped**. Their shape has never been observed here, so a
  local projection would be as unverified as the edge name while looking settled --
  test_no_local_projection_is_declared stops the withdrawn constant coming back.
"""
import json
import os
import sys
from decimal import Decimal
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))


def _load_handler():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            import handler
            return handler


ROWS = [
    {'event_name': 'Purchase', 'count': 12, 'value': '1480.00'},
    {'event_name': 'AddToCart', 'count': 31},
    {'event_name': 'InitiateCheckout', 'count': 19},
]


class TestMmConversionMetrics:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.handler = _load_handler()
        self.table = MagicMock()
        self.table.get_item.return_value = {}
        self.fake_dynamo = MagicMock()
        self.fake_dynamo.Table.return_value = self.table

    def _read(self, graph_result, waba_id='WABA1', params=None):
        calls = []

        def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
            calls.append({'endpoint': endpoint, 'method': method, 'params': params})
            return graph_result

        with patch.object(self.handler, '_graph_api', side_effect=fake_graph), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo), \
                patch.object(self.handler, 'logger', MagicMock()):
            resp = self.handler._get_mm_conversion_metrics(waba_id, params or {})
        return resp, json.loads(resp['body']), calls

    # 1
    def test_successful_read_returns_rows_unreshaped_and_caches(self):
        resp, body, _ = self._read({'data': ROWS})
        assert resp['statusCode'] == 200
        assert body['available'] is True
        assert body['edge'] == self.handler.MM_METRICS_EDGE
        # Byte-identical and in order: no projection, no regrouping, no reordering.
        assert body['metrics'] == ROWS
        assert json.dumps(body['metrics']) == json.dumps(ROWS)
        assert isinstance(body['readAt'], int)

        assert self.table.put_item.call_count == 1
        item = self.table.put_item.call_args.kwargs['Item']
        assert item['id'] == self.handler.MM_METRICS_CACHE_PREFIX + 'WABA1'
        assert isinstance(item['configValue'], str)
        assert json.loads(item['configValue']) == ROWS
        assert isinstance(item['updatedAt'], (int, Decimal))
        assert not isinstance(item['updatedAt'], float)

    # 2
    def test_unavailable_edge_returns_200_not_400(self):
        """The load-bearing test: a capability Meta may simply not offer this account
        must not render as a failure."""
        resp, body, _ = self._read({'error': {'message': 'Unsupported get request'}})
        assert resp['statusCode'] == 200
        assert resp['statusCode'] != 400
        assert body['available'] is False
        assert body['edge'] == self.handler.MM_METRICS_EDGE
        assert 'note' in body and body['note']
        assert body['reason'] == 'Unsupported get request'
        assert self.table.put_item.call_count == 0

    # 3
    def test_unavailable_read_returns_the_cached_answer(self):
        self.table.get_item.return_value = {
            'Item': {'id': self.handler.MM_METRICS_CACHE_PREFIX + 'WABA1',
                     'configValue': json.dumps(ROWS),
                     'updatedAt': Decimal('1760000000')}}
        resp, body, _ = self._read({'error': {'message': 'Unsupported get request'}})
        assert resp['statusCode'] == 200
        assert body['available'] is False
        assert body['cached']['metrics'] == ROWS
        assert body['cached']['readAt'] == 1760000000

    # 4
    def test_the_edge_name_comes_from_the_constant(self):
        _, _, calls = self._read({'data': ROWS})
        assert len(calls) == 1
        assert calls[0]['endpoint'].endswith(self.handler.MM_METRICS_EDGE)
        assert calls[0]['endpoint'] == 'WABA1/' + self.handler.MM_METRICS_EDGE
        # No `fields` is sent: the edge's own field names are unverified.
        assert calls[0]['params'] is None

    def test_since_and_until_are_forwarded_unparsed(self):
        _, _, calls = self._read({'data': ROWS},
                                 params={'since': 'nonsense', 'until': '2026-10-01'})
        assert calls[0]['params'] == {'since': 'nonsense', 'until': '2026-10-01'}

    # 5
    def test_an_object_response_is_wrapped(self):
        obj = {'spend': '12.00', 'data': {'not': 'a list'}}
        resp, body, _ = self._read(obj)
        assert resp['statusCode'] == 200
        assert body['available'] is True
        assert body['metrics'] == [obj]

    # 6
    def test_cache_failure_does_not_break_the_read(self):
        self.table.put_item.side_effect = RuntimeError('throttled')
        resp, body, _ = self._read({'data': ROWS})
        assert resp['statusCode'] == 200
        assert body['available'] is True
        assert body['metrics'] == ROWS

    def test_cache_read_failure_fails_open(self):
        self.table.get_item.side_effect = RuntimeError('throttled')
        resp, body, _ = self._read({'error': {'message': 'Unsupported get request'}})
        assert resp['statusCode'] == 200
        assert body['cached'] == {}

    def test_a_missing_cache_row_is_an_empty_answer_and_hasCached_says_so(self):
        """`hasCached` is the only field the one unavailable-read log line carries that
        could distinguish two runs, so it has to be able to say False. An earlier shape
        returned {'metrics': [], 'readAt': 0} for a row that does not exist -- truthy --
        and reported True on every unavailable read."""
        self.table.get_item.return_value = {}          # no 'Item': the row is absent
        logged = self._unavailable_log_line()
        assert logged['hasCached'] is False
        with patch.object(self.handler, 'dynamodb', self.fake_dynamo):
            assert self.handler._mm_metrics_cached('WABA1') == {}

    def test_hasCached_is_true_when_a_row_exists(self):
        self.table.get_item.return_value = {
            'Item': {'id': self.handler.MM_METRICS_CACHE_PREFIX + 'WABA1',
                     'configValue': json.dumps(ROWS), 'updatedAt': Decimal('1760000000')}}
        assert self._unavailable_log_line()['hasCached'] is True

    def _unavailable_log_line(self):
        """The mm_conversion_metrics_unavailable line, read at the logger boundary."""
        fake_logger = MagicMock()
        with patch.object(self.handler, '_graph_api',
                          return_value={'error': {'message': 'Unsupported get request'}}), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo), \
                patch.object(self.handler, 'logger', fake_logger):
            self.handler._get_mm_conversion_metrics('WABA1', {})
        for call in fake_logger.info.call_args_list:
            payload = json.loads(call.args[0])
            if payload.get('event') == 'mm_conversion_metrics_unavailable':
                return payload
        raise AssertionError('no mm_conversion_metrics_unavailable line was logged')

    # 7
    def test_missing_waba_id_is_refused(self):
        event = {'requestContext': {'http': {'method': 'GET',
                                             'path': '/wa-business/mm-conversion-metrics'}},
                 'queryStringParameters': {}, 'body': None}
        with patch.object(self.handler, 'require_auth', return_value=None), \
                patch.object(self.handler, '_graph_api') as gm:
            resp = self.handler.handler(event, None)
        assert resp['statusCode'] == 400
        assert json.loads(resp['body'])['error'] == 'wabaId required'
        assert gm.call_count == 0

    def test_the_dispatcher_does_not_shadow_mm_onboarding_status(self):
        """The two MM path fragments are disjoint, so neither branch swallows the other."""
        for path, target in (('/wa-business/mm-onboarding-status', '_get_mm_onboarding_status'),
                             ('/wa-business/mm-conversion-metrics', '_get_mm_conversion_metrics')):
            event = {'requestContext': {'http': {'method': 'GET', 'path': path}},
                     'queryStringParameters': {'wabaId': 'WABA1'}, 'body': None}
            with patch.object(self.handler, 'require_auth', return_value=None), \
                    patch.object(self.handler, target,
                                 return_value={'statusCode': 200, 'body': '{}'}) as fn:
                self.handler.handler(event, None)
            assert fn.call_count == 1, f'{path} did not reach {target}'

    # 8
    def test_no_local_projection_is_declared(self):
        """Withdrawn decision 4: a constant describing a projection that no code performs
        is the "looks like coverage and decides nothing" failure. It stays deleted."""
        assert not hasattr(self.handler, 'MM_CONVERSION_EVENTS')
