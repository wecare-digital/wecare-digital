"""Approval must use the complete template inventory on the sender's WABA."""
import ast
import time
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / 'amplify/functions/messaging/whatsapp-business-api/handler.py'


def reader(responses):
    tree=ast.parse(HANDLER.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_list_payment_templates')
    graph=Mock(side_effect=responses)
    namespace={'time':time,'Dict':dict,'_graph_api':graph,'_resp':lambda status,body:(status,body)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(HANDLER),'exec'),namespace)
    return namespace['_list_payment_templates'],graph


def test_order_status_on_a_later_page_is_read_with_the_same_waba():
    read,graph=reader([
        {'data':[{'name':'other'}],'paging':{'next':'https://untrusted.invalid/', 'cursors':{'after':'cursor-1'}}},
        {'data':[{'name':'order_status','status':'APPROVED','sub_category':'ORDER_STATUS','language':'en'}]},
    ])
    status,result=read('waba-1')
    assert status==200
    assert len(result['data'])==2
    assert result['data'][1]['sub_category']=='ORDER_STATUS'
    assert all(call.args[0]=='waba-1/message_templates' for call in graph.call_args_list)
    assert graph.call_args.kwargs['params']['after']=='cursor-1'
    assert graph.call_args.kwargs['waba_id']=='waba-1'


def test_incomplete_inventory_never_returns_partial_approval():
    page={'data':[{'name':'status','status':'APPROVED'}],
          'paging':{'next':'more','cursors':{'after':'repeated'}}}
    read,_=reader([page,page])
    status,result=read('waba-1')
    assert status==502
    assert 'data' not in result


def test_inventory_has_a_bounded_page_and_request_budget():
    responses = [{'data': [], 'paging': {'next': 'more', 'cursors': {'after': str(i)}}}
                 for i in range(3)]
    read, graph = reader(responses)
    status, result = read('waba-1')
    assert status == 502
    assert 'data' not in result
    assert graph.call_count == 3
    assert all(0 < call.kwargs['timeout'] <= 3 for call in graph.call_args_list)
