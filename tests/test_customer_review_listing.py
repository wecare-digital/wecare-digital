"""Reviews are listed from the one flow-response table, every page, both review codes."""
import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
from lambda_utils import flow_records  # noqa: E402

SERVICE_API = 'amplify/functions/core/service-api/handler.py'


def test_contact_reviews_use_the_flow_code_index_and_all_pages():
    table = MagicMock()
    pages = {
        ('WD_REV', None): {'Items': [{'submissionId': 'other', 'flowCode': 'WD_REV',
                                      'contactId': 'another', 'createdAt': 1}],
                           'LastEvaluatedKey': {'submissionId': 'other'}},
        ('WD_REV', 'other'): {'Items': [{'submissionId': 'mine', 'flowCode': 'WD_REV',
                                         'contactId': 'mine', 'customerPhone': '123',
                                         'createdAt': 2, 'reviewText': 'A useful idea',
                                         'source': 'whatsapp', 'status': 'submitted'}]},
        ('WD_IDEA', None): {'Items': []},
    }

    def query(**kwargs):
        code = kwargs['KeyConditionExpression']._values[1]
        start = (kwargs.get('ExclusiveStartKey') or {}).get('submissionId')
        return pages[(code, start)]

    table.query.side_effect = query
    reviews = flow_records.list_reviews(
        table, {'customerPhone': '+123', 'contactId': 'mine', 'status': 'pending'})

    assert [r['reviewId'] for r in reviews] == ['mine']
    assert reviews[0]['comment'] == 'A useful idea'
    assert reviews[0]['status'] == 'pending'
    assert table.query.call_count == 3
    assert {c.kwargs['IndexName'] for c in table.query.call_args_list} == {'flowCode'}
    table.scan.assert_not_called()


def test_service_api_delegates_to_the_one_review_reader():
    """The canonical service API must use the shared review reader."""
    tree = ast.parse((ROOT / SERVICE_API).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_list_reviews')
    calls = {f'{c.func.value.id}.{c.func.attr}' for c in ast.walk(node)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
             and isinstance(c.func.value, ast.Name)}
    assert 'flow_records.list_reviews' in calls
