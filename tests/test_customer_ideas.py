"""Customer ideas: ONE row in the shared flow-response table, written once.

ReviewTable was folded into FlowSubmissionTable (see `lambda_utils.flow_records`), so an idea
is a single conditional claim. These tests pin what that buys: a retry or a replayed webhook
can neither duplicate the idea nor overwrite the customer's text or a staff moderation
decision, and the row still carries the review fields the staff page and contact timeline read.
"""
import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify/functions/shared'))
sys.path.insert(0, str(Path(__file__).parent))
from crm_fake_dynamo import FakeDynamo
from lambda_utils import customer_ideas as ideas, flow_completion as fc, flow_records

SUBMISSIONS = fc.FLOW_SUBMISSIONS_TABLE


@pytest.fixture
def db(monkeypatch):
    fake = FakeDynamo({SUBMISSIONS: 'submissionId'},
                      {SUBMISSIONS: {flow_records.FLOW_CODE_INDEX: ('flowCode', None)}})
    monkeypatch.setattr(fc, '_table', lambda: fake.Table(SUBMISSIONS))
    return fake


def save(db, data=None, **kwargs):
    return ideas.save_idea(data or {'idea': 'Please add request tracking', 'topic': 'feature_request'},
        contact_id=kwargs.get('contact_id', 'wa-fixture'), phone=kwargs.get('phone', 'fixture-phone'),
        sender_name='Fixture customer', message_id=kwargs.get('message_id', 'fixture-message'),
        dynamodb=db)


def test_save_links_full_idea_and_contact(db):
    result = save(db, {'idea': 'A much better way to track requests', 'follow_up_opt_in': True})
    row = db.tables[SUBMISSIONS][result.submission_id]
    assert row['contactId'] == 'wa-fixture'
    assert row['description'] == row['reviewText'] == 'A much better way to track requests'
    assert 'follow_up_opt_in' not in json.loads(row['formData'])
    assert 'follow_up_opt_in' not in row and 'rating' not in row
    assert row['visibility'] == 'private' and row['reviewType'] == 'customer_idea'
    assert row['reviewId'] == result.submission_id
    assert row['status'] == 'submitted' and row['paymentStatus'] == 'none'
    assert row['channel'] == 'whatsapp'


def test_an_idea_never_expires(db):
    """A business record, not a transport log: no `ttl` attribute at all."""
    result = save(db)
    assert 'ttl' not in db.tables[SUBMISSIONS][result.submission_id]


def test_repeat_is_one_submission(db):
    a = save(db)
    b = save(db, {'idea': 'Changed retry body', 'follow_up_opt_in': True})
    assert a.created and b.duplicate
    assert len(db.tables[SUBMISSIONS]) == 1
    row = next(iter(db.tables[SUBMISSIONS].values()))
    assert row['reviewText'] == 'Please add request tracking'
    assert 'follow_up_opt_in' not in row


def test_a_failed_write_raises_so_the_webhook_retries(db):
    db.arm_failure(SUBMISSIONS, 'put_item', RuntimeError('temporary failure'))
    with pytest.raises(RuntimeError):
        save(db)
    assert not db.tables.get(SUBMISSIONS, {})
    # The failure is one-shot; the redelivery stores the idea it carries.
    save(db, {'idea': 'Changed retry body'})
    assert len(db.tables[SUBMISSIONS]) == 1
    assert next(iter(db.tables[SUBMISSIONS].values()))['description'] == 'Changed retry body'


def test_retry_preserves_staff_moderation(db):
    result = save(db)
    db.tables[SUBMISSIONS][result.submission_id]['status'] = 'flagged'
    db.tables[SUBMISSIONS][result.submission_id]['response'] = 'Internal note'
    save(db, {'idea': 'Changed'})
    row = db.tables[SUBMISSIONS][result.submission_id]
    assert row['status'] == 'flagged' and row['response'] == 'Internal note'
    assert row['reviewText'] == 'Please add request tracking'


def test_the_staff_reviews_list_reads_the_idea(db):
    """The reviews page and the contact timeline read the same row, as a customer idea."""
    result = save(db)
    reviews = flow_records.list_reviews(db.Table(SUBMISSIONS), {'contactId': 'wa-fixture'})
    assert [r['reviewId'] for r in reviews] == [result.submission_id]
    assert reviews[0]['reviewType'] == 'customer_idea'
    assert reviews[0]['comment'] == 'Please add request tracking'
    assert reviews[0]['status'] == 'pending'


@pytest.mark.parametrize('text', ['', '   ', None, 123])
def test_blank_or_nontext_is_rejected(db, text):
    with pytest.raises(ValueError): save(db, {'idea': text})
    assert not db.tables.get(SUBMISSIONS, {})


def test_payload_cannot_change_sender_and_string_true_is_not_consent(db):
    result = save(db, {'idea': 'Wish', 'contactId': 'other', 'phone': 'other', 'follow_up_opt_in': 'true'})
    row = db.tables[SUBMISSIONS][result.submission_id]
    assert row['contactId'] == 'wa-fixture' and row['phone'] == 'fixture-phone'
    assert 'follow_up_opt_in' not in json.loads(row['formData'])


def test_same_untrusted_token_does_not_merge_customers(db):
    data = {'idea': 'Wish', 'flow_token': 'shared-token'}
    save(db, data)
    save(db, data, contact_id='other-contact', phone='other-phone')
    assert len(db.tables[SUBMISSIONS]) == 2


def test_long_idea_not_truncated(db):
    text = 'x' * 2000
    result = save(db, {'idea': text})
    assert db.tables[SUBMISSIONS][result.submission_id]['description'] == text


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
    db.arm_failure(SUBMISSIONS, 'put_item', RuntimeError('temporary failure'))
    with pytest.raises(RuntimeError): deliver()
    deliver()
    deliver()
    assert len(db.tables[SUBMISSIONS]) == 1


def test_flow_has_no_follow_up_field():
    flow = json.loads((ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/leave-review-flow-v2.json').read_text())
    assert 'follow_up_opt_in' not in json.dumps(flow)
    assert 'only message you' not in json.dumps(flow)
    form = flow['screens'][0]['layout']['children'][-1]['children']
    assert next(c for c in form if c.get('name') == 'idea')['required'] is True
