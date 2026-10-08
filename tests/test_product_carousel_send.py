"""Product carousel send (item 1) -- whatsapp-business-api._send_product_msg.

A product carousel is a CATALOG PRESENTATION. The prohibition that it never carries an
order_details component, a payment-configuration name or an amount is pinned here as a
test rather than left as a comment, because a comment does not fail a build.
"""
import json
import os
import sys
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


def _cards(n):
    return [{'productRetailerId': f'SKU-{i}'} for i in range(n)]


def _logged_events(logger_mock):
    """Every json.dumps'd event dict the handler logged through logger.info."""
    out = []
    for call in logger_mock.info.call_args_list:
        if not call.args:
            continue
        try:
            parsed = json.loads(call.args[0])
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and 'event' in parsed:
            out.append(parsed)
    return out


class TestProductCarouselSend:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.handler = _load_handler()

    def _send(self, body, graph_result=None):
        """Call _send_product_msg with the Graph boundary patched. Returns
        (response, captured_payload_or_None, graph_mock, logger_mock)."""
        captured = {}

        def fake_graph(endpoint, method='GET', payload=None, params=None, waba_id=None, phone_id=None):
            captured['endpoint'] = endpoint
            captured['method'] = method
            captured['payload'] = payload
            return graph_result if graph_result is not None else {
                'messages': [{'id': 'wamid.TEST'}], 'contacts': [{'user_id': 'u1'}]}

        with patch.object(self.handler, '_graph_api', side_effect=fake_graph) as gm, \
                patch.object(self.handler, 'logger', MagicMock()) as lm:
            resp = self.handler._send_product_msg(body)
        return resp, captured.get('payload'), gm, lm

    # 1
    def test_carousel_payload_shape(self):
        body = {'to': '918100640044', 'catalogId': 'CAT1', 'bodyText': 'Pick one',
                'carouselCards': _cards(3)}
        resp, payload, gm, _ = self._send(body)
        assert resp['statusCode'] == 200
        assert gm.call_count == 1
        assert payload['messaging_product'] == 'whatsapp'
        assert payload['recipient_type'] == 'individual'
        assert payload['to'] == '918100640044'
        assert payload['type'] == 'interactive'
        interactive = payload['interactive']
        assert interactive['type'] == 'product_carousel'
        assert interactive['body'] == {'text': 'Pick one'}
        action = interactive['action']
        assert action['catalog_id'] == 'CAT1'
        # Read THROUGH the constant: correcting the unverified key costs one line in the
        # handler and zero edits here.
        items = action[self.handler._PRODUCT_CAROUSEL_ITEMS_KEY]
        assert items == [{'product_retailer_id': 'SKU-0'},
                         {'product_retailer_id': 'SKU-1'},
                         {'product_retailer_id': 'SKU-2'}]

    # 2
    def test_one_card_is_refused(self):
        resp, payload, gm, _ = self._send(
            {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x', 'carouselCards': _cards(1)})
        assert resp['statusCode'] == 400
        assert gm.call_count == 0
        assert payload is None

    def test_eleven_cards_are_refused(self):
        resp, _, gm, _ = self._send(
            {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x', 'carouselCards': _cards(11)})
        assert resp['statusCode'] == 400
        assert gm.call_count == 0

    def test_a_non_list_carousel_cards_is_refused(self):
        resp, _, gm, _ = self._send(
            {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x', 'carouselCards': 'SKU-1,SKU-2'})
        assert resp['statusCode'] == 400
        assert 'list' in json.loads(resp['body'])['error']
        assert gm.call_count == 0

    # 3
    def test_a_card_without_a_retailer_id_is_refused(self):
        cards = [{'productRetailerId': 'SKU-0'}, {'title': 'no id here'}]
        resp, _, gm, _ = self._send(
            {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x', 'carouselCards': cards})
        assert resp['statusCode'] == 400
        assert 'card 1' in json.loads(resp['body'])['error']
        assert gm.call_count == 0

    # 4
    def test_missing_body_text_is_refused(self):
        resp, _, gm, _ = self._send(
            {'to': '91810', 'catalogId': 'CAT1', 'carouselCards': _cards(3)})
        assert resp['statusCode'] == 400
        assert 'bodyText' in json.loads(resp['body'])['error']
        assert gm.call_count == 0

    # 5
    def test_carousel_wins_over_sections(self):
        body = {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x',
                'carouselCards': _cards(2),
                'sections': [{'title': 'S', 'product_items': [{'product_retailer_id': 'A'}]}]}
        resp, payload, _, lm = self._send(body)
        assert resp['statusCode'] == 200
        assert payload['interactive']['type'] == 'product_carousel'
        built = [e for e in _logged_events(lm) if e['event'] == 'product_carousel_built']
        assert len(built) == 1
        assert built[0]['supersededShape'] == 'sections'

    # 5a
    def test_carousel_wins_over_catalog_message(self):
        """catalog_message is the one commerce presentation that survived the 2026-10-02
        withdrawal in both senders, so an accidental override must be readable."""
        body = {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x',
                'carouselCards': _cards(2), 'catalogMessage': True}
        resp, payload, _, lm = self._send(body)
        assert resp['statusCode'] == 200
        assert payload['interactive']['type'] == 'product_carousel'
        assert payload['interactive']['type'] != 'catalog_message'
        built = [e for e in _logged_events(lm) if e['event'] == 'product_carousel_built']
        assert len(built) == 1
        assert built[0]['supersededShape'] == 'catalog_message'

    # 6
    def test_carousel_carries_no_order_details(self):
        """A product carousel is a catalog presentation, never a payment surface."""
        body = {'to': '91810', 'catalogId': 'CAT1', 'bodyText': 'x',
                'headerText': 'Shop', 'footerText': 'Thanks',
                'carouselCards': _cards(3),
                # Even if a caller tries, none of this may reach Meta.
                'order_details': {'total_amount': {'value': 100, 'offset': 100}},
                'paymentConfiguration': 'some-config', 'amount': 100}
        resp, payload, _, _ = self._send(body)
        assert resp['statusCode'] == 200

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    assert 'order_details' not in str(k)
                    assert 'payment' not in str(k).lower()
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            else:
                assert 'payment' not in str(node).lower()

        walk(payload)
        assert 'order_details' not in json.dumps(payload)
        assert 'payment' not in json.dumps(payload).lower()

    # 7
    def test_bsuid_recipient_is_honoured(self):
        """The proven shape is a BARE STRING, not an object (_send_message)."""
        body = {'recipient': 'bsuid_ABCDEF123456', 'catalogId': 'CAT1', 'bodyText': 'x',
                'carouselCards': _cards(2)}
        resp, payload, _, _ = self._send(body)
        assert resp['statusCode'] == 200
        assert payload['recipient'] == 'bsuid_ABCDEF123456'
        assert isinstance(payload['recipient'], str)
        assert 'to' not in payload

    # 8
    def test_the_carousel_inherits_the_unguarded_send_path(self):
        """Inherited and known, not intended.

        `_send_message` has never called `live_smoke.check_recipient`; only
        `_direct_send` does. This carousel is the ninth send type behind that path.
        Adding the guard would change eight shipped types and is outside the nine items
        -- this test exists so a later sweep reads that reasoning before changing it, and
        so the absence is a recorded fact rather than a prose observation.
        """
        body = {'to': '918100640044', 'catalogId': 'CAT1', 'bodyText': 'x',
                'carouselCards': _cards(2)}
        with patch.object(self.handler.live_smoke, 'check_recipient') as guard:
            resp, _, _, _ = self._send(body)
        assert resp['statusCode'] == 200
        assert guard.call_count == 0
