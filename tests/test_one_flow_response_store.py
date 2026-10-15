"""One flow-response table for every channel, and the records that were folded into it.

Reviews, appointments, Rx slots, enterprise cases and amendments used to be written twice (a
domain table plus FlowSubmissionTable) by the WhatsApp Flows and only to the domain table by
the staff forms. They are one row each now, carrying `channel` (whatsapp / website / staff).
Flow logs are one store too: FlowLogTable, which the journey view already read.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
WBA = ROOT / 'amplify' / 'functions' / 'messaging' / 'whatsapp-business-api'
for _path in (str(SHARED), str(WBA), str(Path(__file__).resolve().parent),
              str(ROOT / 'scripts')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from crm_fake_dynamo import FakeDynamo  # noqa: E402
from lambda_utils import flow_completion as fc, flow_records, shared_tables  # noqa: E402

SUBMISSIONS = shared_tables.FLOW_SUBMISSIONS.default_name
LOGS = shared_tables.FLOW_LOGS.default_name
DRAFTS = shared_tables.FLOW_DRAFTS.default_name
HISTORY = shared_tables.STATUS_HISTORY.default_name
ORDERS = shared_tables.ORDERS.default_name
CONTACTS = shared_tables.CONTACTS.default_name
QA_PHONE = '918100640044'


def make_db():
    return FakeDynamo(
        {SUBMISSIONS: 'submissionId', LOGS: 'logId', DRAFTS: 'draftKey', HISTORY: 'historyId',
         ORDERS: 'orderId', CONTACTS: 'id'},
        {SUBMISSIONS: {flow_records.FLOW_CODE_INDEX: ('flowCode', None)}})


@pytest.fixture()
def db(monkeypatch):
    fake = make_db()
    monkeypatch.setattr(fc, '_table', lambda: fake.Table(SUBMISSIONS))
    return fake


# ── the one writer ─────────────────────────────────────────────────────────────────

def test_every_claim_records_its_channel(db):
    result = fc.claim_completion(flow_token='tok-1', screen='S', flow_code='WD_X', phone='1')
    assert db.tables[SUBMISSIONS][result.submission_id]['channel'] == 'whatsapp'
    staff = fc.claim_completion(flow_token='tok-2', screen='S', flow_code='WD_X',
                                channel=fc.CHANNEL_STAFF)
    assert db.tables[SUBMISSIONS][staff.submission_id]['channel'] == 'staff'


def test_an_unknown_channel_is_refused_before_anything_is_written(db):
    with pytest.raises(ValueError):
        fc.claim_completion(flow_token='tok', flow_code='WD_X', channel='WhatsApp ')
    assert not db.tables.get(SUBMISSIONS)


def test_a_business_record_is_written_with_no_ttl(db):
    kept = fc.claim_completion(flow_token='a', flow_code='WD_X', ttl_seconds=0)
    transport = fc.claim_completion(flow_token='b', flow_code='WD_X')
    assert 'ttl' not in db.tables[SUBMISSIONS][kept.submission_id]
    assert db.tables[SUBMISSIONS][transport.submission_id]['ttl'] > time.time()


@pytest.mark.parametrize('row,expected', [
    ({}, 'whatsapp'),
    ({'channel': 'website'}, 'website'),
    ({'flowId': 'web-submit'}, 'staff'),
    ({'channel': 'nonsense'}, 'whatsapp'),
    (None, 'whatsapp'),
])
def test_legacy_rows_have_a_channel_too(row, expected):
    assert fc.channel_of(row) == expected


# ── the folded kinds ───────────────────────────────────────────────────────────────

def test_a_staff_record_is_one_flow_response(db):
    record = flow_records.create_staff_row(
        flow_records.APPOINTMENT, fields=flow_records.appointment_fields(
            {'customerPhone': '+91 81006 40044', 'type': 'consultation',
             'slotDate': '2026-10-20', 'slotTime': '10:30'}),
        phone='+91 81006 40044', status='scheduled')
    row = db.tables[SUBMISSIONS][record['appointmentId']]
    assert row['submissionId'] == row['appointmentId']
    assert row['flowCode'] == 'WD_APPT' and row['channel'] == 'staff'
    assert row['phone'] == QA_PHONE, 'the phone GSI must line up with WhatsApp-written rows'
    assert 'ttl' not in row and row['status'] == 'scheduled'


def test_update_cannot_create_or_cross_kinds(db):
    review = flow_records.create_staff_row(flow_records.REVIEW,
                                           fields=flow_records.review_fields({'rating': 4}))
    table = db.Table(SUBMISSIONS)
    assert flow_records.update_row(table, flow_records.REVIEW, review['reviewId'],
                                   {'status': 'approved'}, 1)
    assert not flow_records.update_row(table, flow_records.APPOINTMENT, review['reviewId'],
                                       {'status': 'no_show'}, 1)
    assert not flow_records.update_row(table, flow_records.REVIEW, 'WD-REV-MISSING',
                                       {'status': 'approved'}, 1)
    assert db.tables[SUBMISSIONS][review['reviewId']]['status'] == 'approved'
    assert 'WD-REV-MISSING' not in db.tables[SUBMISSIONS]


def test_the_reviews_list_reads_ratings_and_ideas_from_every_channel(db):
    flow_records.create_staff_row(flow_records.REVIEW, fields=flow_records.review_fields(
        {'rating': 5, 'comment': 'Great', 'source': 'google'}))
    from lambda_utils import customer_ideas
    customer_ideas.save_idea({'idea': 'Add tracking', 'topic': 'feature_request'},
                             contact_id='wa1', phone=QA_PHONE, sender_name='QA',
                             message_id='m1')
    reviews = flow_records.list_reviews(db.Table(SUBMISSIONS), {})
    assert {(r['flowCode'], r['channel']) for r in reviews} == {('WD_REV', 'staff'),
                                                               ('WD_IDEA', 'whatsapp')}
    assert all(r['status'] == 'pending' for r in reviews)
    google = flow_records.list_reviews(db.Table(SUBMISSIONS), {'source': 'google'})
    assert [r['comment'] for r in google] == ['Great']


# ── the WhatsApp Flows write one row each ──────────────────────────────────────────

@pytest.fixture()
def flows_env(db, monkeypatch):
    from flows import common as flows_common
    monkeypatch.setattr(flows_common, 'dynamodb', db)
    monkeypatch.setattr(flows_common, 'send_simple_confirmation', lambda *a, **k: None)
    return db


@pytest.mark.parametrize('module_name,handler,data,kind,fields', [
    ('flows.appointment', 'handle_review',
     {'appointment_type': 'consultation', 'slot_date': '2026-10-20', 'slot_time': '10:30'},
     flow_records.APPOINTMENT, {'appointmentType': 'consultation', 'slotDate': '2026-10-20'}),
    ('flows.rx_slot', 'handle_review',
     {'slot_type': 'lab_test', 'slot_date': '2026-10-21', 'slot_time': '09:00'},
     flow_records.RX_SLOT, {'slotType': 'lab_test', 'slotDate': '2026-10-21'}),
    ('flows.enterprise_assist', 'handle_intake_form',
     {'account_name': 'Acme', 'subject': 'Bulk order', 'priority': 'high'},
     flow_records.ENTERPRISE_CASE, {'accountName': 'Acme', 'priority': 'high'}),
])
def test_each_flow_writes_one_row_in_the_shared_table(flows_env, monkeypatch, module_name,
                                                      handler, data, kind, fields):
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, 'find_contact_by_phone', lambda phone: 'wa' + QA_PHONE)
    monkeypatch.setattr(module, 'get_contact_name', lambda cid: 'QA Tester')
    token = f'x-3f2a91c4-0000-4aaa-bbbb-000000000001-waba-1-ph-{QA_PHONE}'
    getattr(module, handler)(dict(data), token, 'req-1')
    getattr(module, handler)(dict(data), token, 'req-retry')
    rows = flows_env.all_rows(SUBMISSIONS)
    assert len(rows) == 1, 'one completion, one row - and no second domain table'
    row = rows[0]
    assert row['flowCode'] == kind.flow_code and row['channel'] == 'whatsapp'
    assert row[kind.id_field] == row['submissionId']
    assert row['contactId'] == 'wa' + QA_PHONE
    assert 'ttl' not in row
    for key, value in fields.items():
        assert row[key] == value


def test_flow_logs_land_in_the_flow_log_table(flows_env):
    from flows import common as flows_common
    flows_common.log_flow_event('tok', QA_PHONE, 'data_exchange', 'FORM', {'a': 1}, 'req')
    rows = flows_env.all_rows(LOGS)
    assert len(rows) == 1 and rows[0]['logId'].startswith('flog-')
    assert rows[0]['ttl'] > time.time() and json.loads(rows[0]['dataSnapshot']) == {'a': 1}


# ── the staff service API ──────────────────────────────────────────────────────────

@pytest.fixture()
def service_api(db, monkeypatch):
    module = importlib.import_module('service_api')
    monkeypatch.setattr(module, 'dynamodb', db)
    return module, db


def _body(response):
    return response['statusCode'], json.loads(response['body'])


def test_a_staff_request_is_a_staff_flow_response_linked_to_the_order(service_api):
    module, db = service_api
    db.Table(ORDERS).put_item(Item={'orderId': 'WD-ORD-ABCD1234', 'contactId': 'wa1',
                                    'customerPhone': '+918100640044'})
    status, body = _body(module._submit_request({'orderId': 'WD-ORD-ABCD1234',
                                                 'subject': 'Change', 'description': 'x'}))
    assert status == 201 and body['submissionId'] == body['submissionNumber']
    row = db.tables[SUBMISSIONS][body['submissionId']]
    assert row['channel'] == 'staff' and row['flowId'] == 'web-submit'
    assert row['contactId'] == 'wa1' and row['phone'] == QA_PHONE
    assert row['flowCode'] == '01.WD_SR' and 'ttl' not in row


def test_an_amendment_is_a_flow_response_pointing_at_its_request(service_api):
    module, db = service_api
    db.Table(SUBMISSIONS).put_item(Item={'submissionId': 'WD-SR-PARENT01', 'contactId': 'wa1',
                                         'phone': QA_PHONE, 'flowCode': '01.WD_SR'})
    status, body = _body(module._amend_request({'submissionId': 'WD-SR-PARENT01',
                                                'orderId': 'WD-ORD-ABCD1234',
                                                'amendmentType': 'address'}))
    assert status == 201 and body['success']
    row = db.tables[SUBMISSIONS][body['amendmentId']]
    assert row['flowCode'] == 'WD_AMEND' and row['parentSubmissionId'] == 'WD-SR-PARENT01'
    assert row['contactId'] == 'wa1' and row['channel'] == 'staff'


def test_staff_creates_and_lists_round_trip_through_the_one_table(service_api):
    module, db = service_api
    _, case = _body(module._create_enterprise_case({'customerPhone': '+918100640044',
                                                    'accountName': 'Acme'}))
    _, slot = _body(module._create_rx_slot({'patientPhone': '+918100640044',
                                            'date': '2026-10-22', 'time': '11:00'}))
    _, cases = _body(module._list_enterprise_cases({'status': 'open'}))
    _, slots = _body(module._list_rx_slots({'date': '2026-10-22'}))
    assert [c['caseId'] for c in cases['cases']] == [case['caseId']]
    assert cases['cases'][0]['customerPhone'] == '+918100640044'
    assert [s['slotId'] for s in slots['slots']] == [slot['rxSlotId']]
    status, _ = _body(module._update_rx_slot('WD-RX-MISSING0', {'status': 'booked'}))
    assert status == 404


# ── the SLA engine sweeps the folded appointments ──────────────────────────────────

def test_a_missed_whatsapp_booking_is_marked_no_show(db, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'sla_engine_under_test', ROOT / 'amplify/functions/operations/sla-engine/handler.py')
    sla = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sla)
    monkeypatch.setattr(sla, 'dynamodb', db)
    db.Table(SUBMISSIONS).put_item(Item={
        'submissionId': 'WD-APT-1', 'appointmentId': 'WD-APT-1', 'flowCode': 'WD_APPT',
        'status': 'booked', 'slotDate': '2026-01-01', 'slotTime': '09:00'})
    db.Table(SUBMISSIONS).put_item(Item={
        'submissionId': 'WD-SR-1', 'flowCode': '01.WD_SR', 'status': 'booked',
        'slotDate': '2026-01-01'})
    assert sla._mark_no_show_appointments(int(time.time())) == 1
    assert db.tables[SUBMISSIONS]['WD-APT-1']['status'] == 'no_show'
    assert db.tables[SUBMISSIONS]['WD-SR-1']['status'] == 'booked', 'only appointments'


# ── the one-off migration ──────────────────────────────────────────────────────────

def test_the_migration_plans_an_idea_onto_its_existing_tracking_row():
    import consolidate_shared_tables as migrate
    target = migrate.plan_domain_row('ReviewTable', {
        'reviewId': 'WD-IDEA-1', 'reviewType': 'customer_idea', 'source': 'whatsapp',
        'customerPhone': '+918100640044', 'status': 'flagged', 'reviewText': 'Hi'})
    assert target['submissionId'] == 'WD-IDEA-1' and target['flowCode'] == 'WD_IDEA'
    assert target['channel'] == 'whatsapp' and target['phone'] == QA_PHONE


def test_the_migration_merges_without_overwriting_and_never_deletes():
    import consolidate_shared_tables as migrate
    db = make_db()
    review_table = 'stack-wecare-digital-ReviewTable'
    db.keys[review_table] = 'reviewId'
    db.Table(review_table).put_item(Item={'reviewId': 'WD-IDEA-1', 'reviewType': 'customer_idea',
                                          'source': 'whatsapp', 'status': 'flagged',
                                          'reviewText': 'From the review table'})
    db.Table(SUBMISSIONS).put_item(Item={'submissionId': 'WD-IDEA-1', 'flowCode': 'WD_IDEA',
                                         'status': 'open', 'description': 'Tracking copy',
                                         'reviewText': 'Tracking text', 'ttl': 1})

    def table_exists(name):
        return name in db.keys

    def run(apply):
        tables = {n: db.Table(n) for n in db.keys}

        class Resource:
            def Table(self, name):  # noqa: N802
                if name not in tables:
                    raise AssertionError(name)
                return _Scannable(tables[name], db, name)

        return migrate.run(Resource(), apply=apply, now=int(time.time()), exists=table_exists)

    dry = run(apply=False)
    assert dry['steps']['ReviewTable']['planned'] == 1
    assert db.tables[SUBMISSIONS]['WD-IDEA-1']['status'] == 'open', 'a dry run writes nothing'

    run(apply=True)
    merged = db.tables[SUBMISSIONS]['WD-IDEA-1']
    assert merged['status'] == 'flagged', 'the moderation status the review table owned wins'
    assert merged['reviewText'] == 'Tracking text', 'existing fields are never overwritten'
    assert merged['channel'] == 'whatsapp' and 'ttl' not in merged
    assert db.tables[review_table], 'the source rows stay; deletion is a separate step'


class _Scannable:
    """The crm fake has no `scan`; the migration only needs a full-table read."""

    def __init__(self, table, db, name):
        self._table, self._db, self.name = table, db, name

    def scan(self, **_):
        return {'Items': self._db.all_rows(self.name)}

    def __getattr__(self, attr):
        return getattr(self._table, attr)
