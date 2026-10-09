"""One fixed Conversions API dataset for BOTH WABAs -- whatsapp-business-api.

Three things are pinned here, because each is easy to lose by accident:

* Both WABAs resolve to dataset `4554612361454941` and NO Graph create call is made. The
  owner consolidated onto one dataset; a stray `POST /{waba_id}/dataset` would hand a
  second, per-WABA dataset back and silently split the reports again.
* A shared dataset must not flatten attribution. `user_data.whatsapp_business_account_id`
  still carries the per-WABA id on every event, which is what Meta attributes on.
* The per-WABA create path is NOT removed, only defaulted past. Clearing
  `CAPI_FIXED_DATASET_ID` must still reach `POST /{waba_id}/dataset` -- and on a table that
  still holds `capi_dataset_<wabaId>` rows, the status read resumes those CACHED retired ids
  rather than creating anything, which is the part of the hatch worth being explicit about.
"""
import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))

FIXED_DATASET = '4554612361454941'
WABA1 = '2094615664435155'
WABA2 = '2513394156072604'


def _load_handler():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'messaging', 'whatsapp-business-api'))
    with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
        with patch('boto3.resource'), patch('boto3.client'):
            import handler
            return handler


class TestCapiFixedDataset:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.handler = _load_handler()
        self.table = MagicMock()
        self.table.get_item.return_value = {}
        self.fake_dynamo = MagicMock()
        self.fake_dynamo.Table.return_value = self.table

    @pytest.mark.parametrize('waba_id', [WABA1, WABA2])
    def test_both_wabas_resolve_the_one_fixed_dataset_without_a_graph_call(self, waba_id):
        graph = MagicMock()
        with patch.object(self.handler, '_graph_api', graph), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo):
            ds = self.handler._capi_get_dataset(waba_id, create=True)
        assert ds['datasetId'] == FIXED_DATASET
        assert ds['wabaId'] == waba_id
        assert ds['fixed'] is True
        graph.assert_not_called()

    @pytest.mark.parametrize('waba_id', [WABA1, WABA2])
    def test_the_event_posts_to_the_shared_dataset_and_keeps_the_per_waba_id(self, waba_id):
        """The dataset is shared; attribution is not. Both must hold in the same call."""
        calls = []

        def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
            calls.append({'endpoint': endpoint, 'method': method, 'payload': payload})
            return {'events_received': 1}

        with patch.object(self.handler, '_graph_api', side_effect=fake_graph), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo), \
                patch.object(self.handler, 'logger', MagicMock()):
            resp = self.handler._capi_log_event({
                'wabaId': waba_id, 'eventName': 'Purchase',
                'ctwaClid': 'ARAbcdefghijklmnop', 'value': 107.02, 'currency': 'INR',
            })

        body = json.loads(resp['body'])
        assert resp['statusCode'] == 200
        assert body['datasetId'] == FIXED_DATASET
        post = next(c for c in calls if c['method'] == 'POST')
        assert post['endpoint'] == f'{FIXED_DATASET}/events'
        event = post['payload']['data'][0]
        assert event['user_data']['whatsapp_business_account_id'] == waba_id
        assert event['action_source'] == 'business_messaging'

    def test_clearing_the_fixed_id_still_reaches_the_per_waba_create_path(self):
        """The escape hatch is the reason nothing had to be deleted - prove it still works."""
        calls = []

        def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
            calls.append({'endpoint': endpoint, 'method': method})
            return {'id': '1111111111111111'}

        with patch.object(self.handler, 'CAPI_FIXED_DATASET_ID', ''), \
                patch.object(self.handler, '_graph_api', side_effect=fake_graph), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo):
            ds = self.handler._capi_get_dataset(WABA1, create=True)

        assert calls == [{'endpoint': f'{WABA1}/dataset', 'method': 'POST'}]
        assert ds == {'datasetId': '1111111111111111', 'wabaId': WABA1, 'cached': False}

    def test_the_cleared_hatch_resumes_the_cached_per_waba_id_on_the_status_read(self):
        """What the hatch actually does on a live table, as opposed to the empty one above.

        The `capi_dataset_<wabaId>` rows from the old path are not deleted, so a status read
        (create=False) hands back the RETIRED per-WABA id from cache without calling Graph.
        Pinned so the escape hatch is not mistaken for 'creates fresh datasets'.
        """
        self.table.get_item.return_value = {'Item': {'configValue': '2222222222222222'}}
        graph = MagicMock()

        with patch.object(self.handler, 'CAPI_FIXED_DATASET_ID', ''), \
                patch.object(self.handler, '_graph_api', graph), \
                patch.object(self.handler, 'dynamodb', self.fake_dynamo):
            ds = self.handler._capi_get_dataset(WABA1, create=False)

        assert ds == {'datasetId': '2222222222222222', 'wabaId': WABA1, 'cached': True}
        graph.assert_not_called()
