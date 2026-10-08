"""Exercise the deployed review-list function with paginated records."""
import ast
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from boto3.dynamodb.conditions import Key

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('path', [
 'amplify/functions/core/service-api/handler.py',
 'amplify/functions/messaging/whatsapp-business-api/service_api.py'])
def test_contact_reviews_use_index_and_all_pages(path):
    source = (ROOT/path).read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_list_reviews')
    table = MagicMock()
    table.query.side_effect = [
      {'Items':[{'reviewId':'other','contactId':'another','createdAt':1}], 'LastEvaluatedKey':{'reviewId':'other'}},
      {'Items':[{'reviewId':'mine','contactId':'mine','customerPhone':'123','createdAt':2,
                 'reviewText':'A useful idea','source':'whatsapp','status':'submitted'}]}]
    dynamo = MagicMock();dynamo.Table.return_value = table
    scope = {'Dict':dict,'dynamodb':dynamo,'REVIEWS_TABLE':'reviews','Key':Key,
             '_resp':lambda status,body:(status,body)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),path,'exec'),scope)
    status, body = scope['_list_reviews']({'customerPhone':'+123','contactId':'mine','status':'pending'})
    assert status == 200 and body['count'] == 1
    assert body['reviews'][0]['comment'] == 'A useful idea'
    assert body['reviews'][0]['status'] == 'pending'
    assert table.query.call_count == 2
    assert table.query.call_args_list[0].kwargs['IndexName'] == 'customerPhone'
    assert table.query.call_args_list[1].kwargs['ExclusiveStartKey'] == {'reviewId':'other'}
    table.scan.assert_not_called()
