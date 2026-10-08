"""Customer entry must open the published private Flow without changing order reviews."""
import ast
import io
import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'


def load_entry(source=None):
    tree = ast.parse(source or HANDLER.read_text())
    names = {'CUSTOMER_IDEA_KEYWORDS', 'DEFAULT_FLOW_TRIGGERS'}
    functions = {'_is_deterministic_trigger', '_send_generic_flow'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))
             or (isinstance(n, ast.FunctionDef) and n.name in functions)]
    calls = []
    def invoke(**kwargs):
        calls.append(json.loads(kwargs['Payload']))
        return {'Payload': io.BytesIO(b'{"statusCode":200}')}
    ns = {'Dict': dict, 'json': json, 'uuid': uuid, 'logger': logging.getLogger('test'),
          'PHONE_NUMBER_ID_1': 'phone1', 'PHONE_NUMBER_ID_2': 'phone2',
          'OUTBOUND_WHATSAPP_FUNCTION': 'fixture-outbound',
          'lambda_client': SimpleNamespace(invoke=invoke),
          'mask_contact_id': lambda x: x, 'mask_phone': lambda x: x,
          'mask_flow_token': lambda x: x,
          'strip_decorative_edges': lambda x: x,
          '_get_routing_config': lambda: {'enabled': True, 'keywords': [], 'contains': []}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(HANDLER), 'exec'), ns)
    return ns, calls


def test_exact_entry_with_dashboard_keyword_config_and_kill_switch():
    ns, _ = load_entry()
    for text in ['Share an idea', ' share idea ', '/idea', 'Leave Review', 'LEAVE A REVIEW', 'feedback', '/review', 'feature request']:
        assert ns['_is_deterministic_trigger']({'type': 'text', 'text': {'body': text}})
    assert not ns['_is_deterministic_trigger']({'type': 'text', 'text': {'body': 'I might share an idea later'}})
    ns['_get_routing_config'] = lambda: {'enabled': False}
    assert not ns['_is_deterministic_trigger']({'type': 'text', 'text': {'body': 'Share an idea'}})


def test_new_flow_opens_static_screen_and_preserves_order_review():
    ns, calls = load_entry()
    trigger = ns['DEFAULT_FLOW_TRIGGERS']['customer_idea']
    assert ns['DEFAULT_FLOW_TRIGGERS']['leave_review']['flowId'] == '4423166114671543'
    ns['_send_generic_flow']('fixture-contact', 'phone1', 'fixture-phone', 'fixture-request',
                             flow_config=trigger, flow_key='customer_idea')
    assert len(calls) == 1
    body = json.loads(calls[0]['body'])
    data = body['interactiveData']
    assert body['contactId'] == 'fixture-contact'
    assert data['flowId'] == '1578178897413815'
    assert data['flowAction'] == 'navigate' and data['screenId'] == 'FEEDBACK'
    assert data['flowCta'] == 'Leave Review'


def test_second_account_links_to_correct_customer_entry():
    ns, calls = load_entry()
    ctas = []
    ns['_send_cta_button'] = lambda *args, **kwargs: ctas.append(args)
    ns['_send_generic_flow']('fixture-contact', 'phone2', 'fixture-phone', 'fixture-request',
                             flow_config=ns['DEFAULT_FLOW_TRIGGERS']['customer_idea'], flow_key='customer_idea')
    assert not calls
    assert ctas[0][3] == 'https://wa.me/message/ZM74K2H2BIFOA1'


def test_general_review_aliases_take_precedence_over_legacy_order_review():
    ns, _ = load_entry()
    for text in ['leave review', 'review', 'feedback', 'feature request']:
        match = next((key for key, trigger in ns['DEFAULT_FLOW_TRIGGERS'].items()
                      if text in trigger['keywords'] and trigger.get('enabled', True)), None)
        assert match == 'customer_idea'
    assert 'review wd-ord-1234abcd' not in ns['CUSTOMER_IDEA_KEYWORDS']
