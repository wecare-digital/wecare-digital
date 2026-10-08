import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(Path(__file__).parent))
from crm_fake_dynamo import FakeDynamo
from lambda_utils import customer_ideas as ideas, flow_completion as fc

REVIEWS = ideas.REVIEWS_TABLE

@pytest.fixture
def db(monkeypatch):
    fake = FakeDynamo({fc.FLOW_SUBMISSIONS_TABLE: 'submissionId', REVIEWS: 'reviewId'},
                     {fc.FLOW_SUBMISSIONS_TABLE: {}, REVIEWS: {}})
    monkeypatch.setattr(fc, '_table', lambda: fake.Table(fc.FLOW_SUBMISSIONS_TABLE))
    return fake

def save(db, data=None, **kwargs):
    return ideas.save_idea(data or {'idea': 'Please add request tracking', 'topic': 'feature_request'},
        contact_id=kwargs.get('contact_id', 'wa-fixture'), phone=kwargs.get('phone', 'fixture-phone'),
        sender_name='Fixture customer', message_id=kwargs.get('message_id', 'fixture-message'),
        dynamodb=db)

def test_save_links_full_idea_and_contact(db):
    result = save(db, {'idea': 'A much better way to track requests', 'follow_up_opt_in': True})
    row = db.tables[fc.FLOW_SUBMISSIONS_TABLE][result.submission_id]
    log = next(iter(db.tables[REVIEWS].values()))
    assert row['contactId'] == log['contactId'] == 'wa-fixture'
    assert row['description'] == log['reviewText'] == 'A much better way to track requests'
    assert 'follow_up_opt_in' not in json.loads(row['formData'])
    assert 'follow_up_opt_in' not in log and 'rating' not in log
    assert log['visibility'] == 'private'
    assert row['status'] == 'open' and row['paymentStatus'] == 'none'

def test_repeat_is_one_submission_and_one_activity(db):
    a = save(db)
    b = save(db, {'idea': 'Changed retry body', 'follow_up_opt_in': True})
    assert a.created and b.duplicate
    assert len(db.tables[fc.FLOW_SUBMISSIONS_TABLE]) == len(db.tables[REVIEWS]) == 1
    log = next(iter(db.tables[REVIEWS].values()))
    assert log['reviewText'] == 'Please add request tracking'
    assert 'follow_up_opt_in' not in log

def test_replay_repairs_tracking_failure(db):
    db.fail_on[(fc.FLOW_SUBMISSIONS_TABLE, 'put_item')] = RuntimeError('temporary failure')
    with pytest.raises(RuntimeError): save(db)
    assert len(db.tables[REVIEWS]) == 1
    assert not db.tables.get(fc.FLOW_SUBMISSIONS_TABLE, {})
    save(db, {'idea': 'Changed retry body'})
    assert len(db.tables[fc.FLOW_SUBMISSIONS_TABLE]) == 1
    assert next(iter(db.tables[fc.FLOW_SUBMISSIONS_TABLE].values()))['description'] == 'Please add request tracking'

def test_review_database_failure_has_no_tracking_success(db):
    db.fail_on[(REVIEWS, 'put_item')] = RuntimeError('unavailable')
    with pytest.raises(RuntimeError): save(db)
    assert not db.tables.get(fc.FLOW_SUBMISSIONS_TABLE, {})

def test_retry_preserves_staff_moderation(db):
    result = save(db)
    db.tables[REVIEWS][result.submission_id]['status'] = 'flagged'
    db.tables[REVIEWS][result.submission_id]['response'] = 'Internal note'
    save(db, {'idea': 'Changed'})
    row = db.tables[REVIEWS][result.submission_id]
    assert row['status'] == 'flagged' and row['response'] == 'Internal note'
    assert row['reviewText'] == 'Please add request tracking'

@pytest.mark.parametrize('text', ['', '   ', None, 123])
def test_blank_or_nontext_is_rejected(db, text):
    with pytest.raises(ValueError): save(db, {'idea': text})
    assert not db.tables.get(fc.FLOW_SUBMISSIONS_TABLE, {})

def test_payload_cannot_change_sender_and_string_true_is_not_consent(db):
    result = save(db, {'idea': 'Wish', 'contactId': 'other', 'phone': 'other', 'follow_up_opt_in': 'true'})
    row = db.tables[fc.FLOW_SUBMISSIONS_TABLE][result.submission_id]
    assert row['contactId'] == 'wa-fixture' and row['phone'] == 'fixture-phone'
    assert 'follow_up_opt_in' not in json.loads(row['formData'])

def test_same_untrusted_token_does_not_merge_customers(db):
    data = {'idea': 'Wish', 'flow_token': 'shared-token'}
    save(db, data)
    save(db, data, contact_id='other-contact', phone='other-phone')
    assert len(db.tables[fc.FLOW_SUBMISSIONS_TABLE]) == 2

def test_long_idea_not_truncated(db):
    text = 'x' * 2000
    result = save(db, {'idea': text})
    assert db.tables[fc.FLOW_SUBMISSIONS_TABLE][result.submission_id]['description'] == text

def test_unrelated_flows_are_untouched():
    def message(payload):
        return {'type': 'interactive', 'interactive': {'type': 'nfm_reply',
            'nfm_reply': {'response_json': json.dumps(payload)}}}
    assert ideas.idea_payload(message({'request_id': 'postpay'})) is None
    assert ideas.idea_payload(message({'flow_key': ideas.FLOW_KEY, 'idea': 'Wish'}))['idea'] == 'Wish'

def test_idea_persistence_precedes_inbox_dedup_and_has_no_send():
    source = (ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py').read_text()
    body = source[source.index('def _process_message('):]
    assert body.index('customer_ideas.save_idea(') < body.index('claim_event(')
    module = ast.parse(Path(ideas.__file__).read_text())
    calls = [node.func.attr for node in ast.walk(module) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert 'invoke' not in calls

def test_real_inbound_route_saves_even_if_inbox_already_has_message(db, monkeypatch):
    import boto3
    import importlib.util
    from unittest.mock import MagicMock
    from lambda_utils import webhook_dedup
    monkeypatch.setattr(boto3, 'resource', lambda *a, **k: db)
    monkeypatch.setattr(boto3, 'client', lambda *a, **k: MagicMock())
    path = ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('ideas_inbound_under_test', path)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    monkeypatch.setattr(handler, '_get_or_create_contact', lambda *a, **k: {'id': 'wa-fixture'})
    monkeypatch.setattr(webhook_dedup, 'claim_event', lambda *a, **k: False)
    message = {'id': 'fixture-message', 'from': 'fixture-phone', 'type': 'interactive',
        'interactive': {'type': 'nfm_reply', 'nfm_reply': {'response_json': json.dumps({
            'flow_key': ideas.FLOW_KEY, 'idea': 'Please add request tracking'})}}}
    def deliver():
        handler._process_message(message, {}, 'fixture-request', '', 'fixture-business-phone', [])
    db.fail_on[(fc.FLOW_SUBMISSIONS_TABLE, 'put_item')] = RuntimeError('temporary failure')
    with pytest.raises(RuntimeError): deliver()
    deliver()
    deliver()
    assert len(db.tables[fc.FLOW_SUBMISSIONS_TABLE]) == len(db.tables[REVIEWS]) == 1


def test_flow_has_no_follow_up_field():
    flow = json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/leave-review-flow-v2.json').read_text())
    assert 'follow_up_opt_in' not in json.dumps(flow)
    assert 'only message you' not in json.dumps(flow)
    form = flow['screens'][0]['layout']['children'][-1]['children']
    assert next(c for c in form if c.get('name') == 'idea')['required'] is True

