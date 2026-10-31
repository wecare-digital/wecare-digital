"""Automatic Meta->AWS mapping reconciliation, including fail-closed regressions."""
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / (
    'amplify/functions/messaging/whatsapp-business-api/flows/template_flow_sync.py')
spec = importlib.util.spec_from_file_location('template_flow_sync_tested', MODULE)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

WABA = '2094615664435155'
IDS = [
    '2413873616105042', '993862443003108', '39581903361452878',
    '993516553092471', '2408621596338289', '2988393421499259',
    '1804165164183485',
]
NAMES = [
    ('service_details', '2419125382263851', IDS[0]),
    ('wecare_pdf_direct_download', '1428669922724280', IDS[0]),
    ('wecare_leave_review', '1801972550682516', IDS[1]),
    ('wecare_default_invoice_image_template', '1782246473079550', IDS[1]),
    ('_dropdoc_flow', '1041974032198332', IDS[2]),
    ('submit_request_flow', '30181571061431980', IDS[3]),
    ('request_amendment_flow', '4034771700165582', IDS[4]),
    ('pickup_request_flow', '1449099850671553', IDS[5]),
    ('track_ship_flow', '1107523855531222', IDS[6]),
]


def fixture_graph():
    flows = [{'id': fid, 'name': f'Flow {i}', 'status': 'PUBLISHED',
              'validation_errors': [],
              'health_status': {'can_send_message': 'AVAILABLE'}}
             for i, fid in enumerate(IDS)]
    templates = []
    for name, tid, flow_id in NAMES:
        templates.append({'id': tid, 'name': name, 'status': 'APPROVED',
                          'category': 'UTILITY',
                          'components': [{'type': 'BODY', 'text': 'Hello'},
                                         {'type': 'BUTTONS', 'buttons': [
                                             {'type': 'FLOW', 'text': 'Continue',
                                              'flow_id': flow_id,
                                              'flow_action': 'DATA_EXCHANGE'}]}]})
    templates += [{'id': str(100+i), 'name': f'ordinary_{i}', 'status': 'APPROVED',
                   'components': [{'type': 'BODY', 'text': 'No Flow'}]}
                  for i in range(5)]
    return {f'{WABA}/message_templates': templates, f'{WABA}/flows': flows}


class FakeMeta:
    def __init__(self, pages=None, failure=False):
        self.pages = pages if pages is not None else fixture_graph()
        self.failure = failure

    def __call__(self, edge, *, params):
        if self.failure:
            return {'error': {'code': 500}}
        if params.get('after'):
            return {'data': []}
        return {'data': self.pages[edge]}


class FakeTable:
    def __init__(self, rows=None):
        self.rows = rows or []

    def scan(self, **kwargs):
        return {'Items': self.rows}


class FakeResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


class FakeClient:
    def __init__(self):
        self.calls = []

    def transact_write_items(self, **kwargs):
        self.calls.append(kwargs)


def valid_flow(fid):
    return fid in IDS


class AutoSyncTests(unittest.TestCase):
    def test_live_snapshot_has_exactly_nine_links_with_long_ids(self):
        links, totals = sync.snapshot(FakeMeta(), WABA, valid_flow)
        self.assertEqual(len(links), 9)
        self.assertEqual(totals['retainedFlowCount'], 7)
        self.assertEqual(links[(IDS[2], '1041974032198332')]['templateName'], '_dropdoc_flow')
        self.assertEqual(links[(IDS[0], '2419125382263851')]['templateName'], 'service_details')

    def test_one_atomic_write_and_no_meta_mutations(self):
        client = FakeClient()
        result = sync.reconcile(FakeMeta(), FakeResource(FakeTable()), client,
                                WABA, 'mapping-table', valid_flow, 'business', now=123456)
        self.assertEqual(result['mappedTemplates'], 9)
        self.assertEqual(result['mappedFlows'], 7)
        self.assertEqual(len(client.calls), 1)
        items = client.calls[0]['TransactItems']
        self.assertEqual(len(items), 9)
        self.assertTrue(all('Put' in item for item in items))
        self.assertEqual(items[0]['Put']['Item']['flowId']['S'], IDS[0])

    def test_stale_entry_is_removed_in_same_transaction(self):
        old = [{'flowId': IDS[0], 'templateId': '555555',
                'lastVerifiedAt': Decimal(1000)}]
        client = FakeClient()
        result = sync.reconcile(FakeMeta(), FakeResource(FakeTable(old)), client,
                                WABA, 'mapping-table', valid_flow, 'business', now=123456)
        self.assertEqual(result['removedStaleLinks'], 1)
        self.assertEqual(sum('Delete' in item for item in client.calls[0]['TransactItems']), 1)

    def test_failed_provider_read_does_not_write(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            sync.reconcile(FakeMeta(failure=True), FakeResource(FakeTable()), client,
                           WABA, 'mapping-table', valid_flow, 'business')
        self.assertEqual(client.calls, [])

    def test_unregistered_flow_button_aborts_without_writes(self):
        data = fixture_graph()
        data[f'{WABA}/message_templates'][0]['components'][1]['buttons'][0]['flow_id'] = '999999'
        client = FakeClient()
        with self.assertRaises(ValueError):
            sync.reconcile(FakeMeta(data), FakeResource(FakeTable()), client,
                           WABA, 'mapping-table', valid_flow, 'business')
        self.assertEqual(client.calls, [])

    def test_blocked_flow_aborts_without_deleting(self):
        data = fixture_graph()
        data[f'{WABA}/flows'][0]['health_status']['can_send_message'] = 'BLOCKED'
        client = FakeClient()
        with self.assertRaises(ValueError):
            sync.reconcile(FakeMeta(data), FakeResource(FakeTable()), client,
                           WABA, 'mapping-table', valid_flow, 'business')
        self.assertEqual(client.calls, [])

    def test_meta_next_cursor_required(self):
        class BrokenMeta(FakeMeta):
            def __call__(self, edge, *, params):
                result = super().__call__(edge, params=params)
                result['paging'] = {'next': 'https://meta.invalid/next'}
                return result
        with self.assertRaises(ValueError):
            sync.snapshot(BrokenMeta(), WABA, valid_flow)

    def test_empty_provider_inventory_fails_closed(self):
        data = fixture_graph()
        data[f'{WABA}/message_templates'] = []
        with self.assertRaises(ValueError):
            sync.snapshot(FakeMeta(data), WABA, valid_flow)


if __name__ == '__main__':
    unittest.main()
