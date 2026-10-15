#!/usr/bin/env python3
"""Copy existing rows from the folded tables into the shared stores. Dry-run by default.

The code now writes every flow response to FlowSubmissionTable and every flow log to
FlowLogTable (see `amplify/functions/shared/lambda_utils/shared_tables.py`). This script moves
the rows that were written to the old tables before that change, so readers that only look at
the shared stores see the full history:

    ReviewTable            -> FlowSubmissionTable  (WD_REV, or WD_IDEA for customer ideas)
    AppointmentTable       -> FlowSubmissionTable  (WD_APPT)
    RxSlotTable            -> FlowSubmissionTable  (WD_RX)
    EnterpriseAssistTable  -> FlowSubmissionTable  (WD_ENT)
    AmendmentHistoryTable  -> FlowSubmissionTable  (WD_AMEND)
    SubmitRequestsTable    -> FlowLogTable (flow_log rows) / FlowSubmissionTable (requests)

It also backfills the attribution fields new writers stamp:

    FlowSubmissionTable.channel   (whatsapp / website / staff, via flow_completion.channel_of)
    OrderTable.channel, shortId   (via order_record.view)

Safety
------
* Default is a dry run: it reads, plans and prints a JSON report, and writes nothing.
* `--apply` writes with conditions only. A missing row is created with
  `attribute_not_exists`; an existing row only gains attributes it does not have
  (`if_not_exists`), so nothing already in a shared store is overwritten.
* It never deletes. Retiring the old tables is a separate, owner-approved step.

Run it AFTER the Lambdas that write the shared stores are deployed, so nothing is still
landing in the old tables once the copy has run. Re-running is safe.

Usage:
    python3 scripts/consolidate_shared_tables.py            # dry run against live tables
    python3 scripts/consolidate_shared_tables.py --apply    # write
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))

from lambda_utils import contact_store, flow_completion, shared_tables  # noqa: E402
from lambda_utils.ecommerce import order_record  # noqa: E402

PREFIX = shared_tables.DEFAULT_PREFIX
FLOW_LOG_TTL_SECONDS = 90 * 86400

#: Folded table -> (key attribute, flowCode for its rows, flowType).
DOMAIN_SOURCES: Dict[str, Tuple[str, str, str]] = {
    'ReviewTable': ('reviewId', 'WD_REV', 'feedback'),
    'AppointmentTable': ('appointmentId', 'WD_APPT', 'booking'),
    'RxSlotTable': ('rxSlotId', 'WD_RX', 'rx_booking'),
    'EnterpriseAssistTable': ('caseId', 'WD_ENT', 'enterprise'),
    'AmendmentHistoryTable': ('amendmentId', 'WD_AMEND', 'amendment'),
}

#: Attributes never copied from a source row: they are the source table's own key or are
#: re-derived for the target.
_SKIP = {'ttl'}


def _phone_of(row: Mapping[str, Any]) -> str:
    for field in ('customerPhone', 'contactPhone', 'phone'):
        digits = contact_store.digits(row.get(field))
        if digits:
            return digits
    return ''


def plan_domain_row(table: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    """The FlowSubmission row a folded domain row becomes. Pure."""
    key, flow_code, flow_type = DOMAIN_SOURCES[table]
    record_id = str(row.get(key) or '')
    if not record_id:
        raise ValueError(f'{table} row without {key}')
    if table == 'ReviewTable' and row.get('reviewType') == 'customer_idea':
        flow_code, flow_type = 'WD_IDEA', 'customer_idea'
    target: Dict[str, Any] = {k: v for k, v in row.items() if k not in _SKIP}
    if table == 'AmendmentHistoryTable':
        # The amendment's `submissionId` pointed at the request it amends; in the shared table
        # `submissionId` is the row's own key, so the pointer moves to `parentSubmissionId`.
        target['parentSubmissionId'] = target.pop('submissionId', '')
    target.update({
        'submissionId': record_id,
        'submissionNumber': record_id,
        key: record_id,
        'flowCode': str(row.get('flowCode') or flow_code),
        'flowType': flow_type,
        'paymentStatus': row.get('paymentStatus') or 'none',
    })
    phone = _phone_of(row)
    if phone:
        target['phone'] = phone
    # WhatsApp Flow writers stamped `source=whatsapp`, a `flowCode` or the sender's `contactId`;
    # the staff forms stamped none of the three.
    source = str(row.get('source') or '').lower()
    from_whatsapp = source == 'whatsapp' or bool(row.get('flowCode')) or bool(row.get('contactId'))
    target['channel'] = (flow_completion.CHANNEL_WHATSAPP if from_whatsapp
                         else flow_completion.CHANNEL_STAFF)
    return {k: v for k, v in target.items() if v is not None and v != ''}


def plan_submit_request_row(row: Mapping[str, Any], now: int) -> Tuple[str, Optional[Dict[str, Any]]]:
    """`('log' | 'submission' | 'expired', target)` for one SubmitRequestsTable row. Pure."""
    if row.get('type') == 'flow_log':
        created = int(row.get('createdAt') or now)
        expires = created + FLOW_LOG_TTL_SECONDS
        if expires <= now:
            return 'expired', None
        log = {k: v for k, v in row.items() if k not in ('id', 'flowData')}
        log['logId'] = str(row.get('id') or '')
        if row.get('flowData'):
            log['dataSnapshot'] = str(row['flowData'])[:4000]
        log['ttl'] = expires
        return 'log', {k: v for k, v in log.items() if v is not None and v != ''}
    record_id = str(row.get('requestNumber') or row.get('id') or '')
    target = {k: v for k, v in row.items() if k not in ('id', 'paymentReferenceId')}
    target.update({
        'submissionId': record_id,
        'submissionNumber': record_id,
        'flowCode': '01.WD_SR',
        'flowType': 'form_submit',
        'paymentRefId': row.get('paymentReferenceId') or '',
        'channel': flow_completion.CHANNEL_WHATSAPP,
    })
    return 'submission', {k: v for k, v in target.items() if v is not None and v != ''}


def plan_order_backfill(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Attributes an order row is missing that every writer now stamps. Pure."""
    view = order_record.view(row)
    missing: Dict[str, Any] = {}
    if not row.get('channel'):
        missing['channel'] = view['channel']
    if not row.get('shortId') and view.get('shortId'):
        missing['shortId'] = view['shortId']
    return missing


# ── I/O ─────────────────────────────────────────────────────────────────────────────

def scan_all(table: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get('Items') or [])
        last = page.get('LastEvaluatedKey')
        if not last:
            return rows
        kwargs['ExclusiveStartKey'] = last


def _is_conditional(error: Exception) -> bool:
    return (getattr(error, 'response', {}).get('Error', {}).get('Code')
            == 'ConditionalCheckFailedException'
            or 'ConditionalCheckFailedException' in str(error))


def merge_into(table: Any, key: Dict[str, Any], item: Mapping[str, Any], *,
               authoritative: Iterable[str] = (), remove: Iterable[str] = ()) -> str:
    """Create the row, or add only the attributes it lacks. Returns 'created' / 'merged'.

    `authoritative` names fields the source owns outright (a review's moderation `status`),
    which overwrite the target's copy; every other field is `if_not_exists`. `remove` drops
    attributes the merged row must not keep (a business record's transport `ttl`).
    """
    try:
        table.put_item(Item=dict(item),
                       ConditionExpression=f'attribute_not_exists({next(iter(key))})')
        return 'created'
    except Exception as error:  # noqa: BLE001 - classified immediately
        if not _is_conditional(error):
            raise
    owned = set(authoritative)
    fields = {k: v for k, v in item.items() if k not in key}
    names, values, parts = {}, {}, []
    for index, (name, value) in enumerate(fields.items()):
        names[f'#f{index}'] = name
        values[f':v{index}'] = value
        parts.append(f'#f{index} = :v{index}' if name in owned
                     else f'#f{index} = if_not_exists(#f{index}, :v{index})')
    removals = []
    for index, name in enumerate(remove):
        names[f'#r{index}'] = name
        removals.append(f'#r{index}')
    if not parts and not removals:
        return 'merged'
    expression = ('SET ' + ', '.join(parts) if parts else '') + \
        ((' REMOVE ' if parts else 'REMOVE ') + ', '.join(removals) if removals else '')
    kwargs: Dict[str, Any] = {'Key': key, 'UpdateExpression': expression,
                              'ExpressionAttributeNames': names}
    if values:
        kwargs['ExpressionAttributeValues'] = values
    table.update_item(**kwargs)
    return 'merged'


def run(dynamodb: Any, *, apply: bool, now: int,
        exists: Callable[[str], bool]) -> Dict[str, Any]:
    """Plan (and with `apply`, write) every step. Returns the report."""
    submissions = dynamodb.Table(shared_tables.FLOW_SUBMISSIONS.default_name)
    logs = dynamodb.Table(shared_tables.FLOW_LOGS.default_name)
    orders = dynamodb.Table(shared_tables.ORDERS.default_name)
    report: Dict[str, Any] = {'mode': 'apply' if apply else 'dry-run', 'steps': {}}

    for source, (key, _code, _type) in DOMAIN_SOURCES.items():
        name = f'{PREFIX}-{source}'
        step = {'table': name, 'rows': 0, 'planned': 0, 'written': {}}
        if not exists(name):
            step['skipped'] = 'table not found'
            report['steps'][source] = step
            continue
        for row in scan_all(dynamodb.Table(name)):
            step['rows'] += 1
            target = plan_domain_row(source, row)
            step['planned'] += 1
            if apply:
                # The domain table owned the record's lifecycle (a review's moderation status,
                # an appointment's no-show), so its `status` wins over the tracking copy, and
                # the merged business record keeps no transport `ttl`.
                outcome = merge_into(submissions, {'submissionId': target['submissionId']},
                                     target, authoritative=('status',), remove=('ttl',))
                step['written'][outcome] = step['written'].get(outcome, 0) + 1
        report['steps'][source] = step

    name = f'{PREFIX}-SubmitRequestsTable'
    step = {'table': name, 'rows': 0, 'logs': 0, 'submissions': 0, 'expired': 0, 'written': {}}
    if exists(name):
        for row in scan_all(dynamodb.Table(name)):
            step['rows'] += 1
            kind, target = plan_submit_request_row(row, now)
            step[{'log': 'logs', 'submission': 'submissions', 'expired': 'expired'}[kind]] += 1
            if apply and target:
                table, key = ((logs, {'logId': target['logId']}) if kind == 'log'
                              else (submissions, {'submissionId': target['submissionId']}))
                outcome = merge_into(table, key, target)
                step['written'][outcome] = step['written'].get(outcome, 0) + 1
    else:
        step['skipped'] = 'table not found'
    report['steps']['SubmitRequestsTable'] = step

    step = {'table': submissions.name if hasattr(submissions, 'name') else
            shared_tables.FLOW_SUBMISSIONS.default_name, 'rows': 0, 'missingChannel': 0}
    for row in scan_all(submissions):
        step['rows'] += 1
        if not row.get('channel'):
            step['missingChannel'] += 1
            if apply:
                merge_into(submissions, {'submissionId': row['submissionId']},
                           {'submissionId': row['submissionId'],
                            'channel': flow_completion.channel_of(row)})
    report['steps']['FlowSubmissionChannel'] = step

    step = {'table': shared_tables.ORDERS.default_name, 'rows': 0, 'backfilled': 0}
    for row in scan_all(orders):
        step['rows'] += 1
        missing = plan_order_backfill(row)
        if missing:
            step['backfilled'] += 1
            if apply:
                merge_into(orders, {'orderId': row['orderId']}, {'orderId': row['orderId'], **missing})
    report['steps']['OrderAttribution'] = step
    return report


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--apply', action='store_true', help='write (default: dry run)')
    parser.add_argument('--region', default='us-east-1')
    args = parser.parse_args(list(argv) if argv is not None else None)

    import time

    import boto3

    dynamodb = boto3.resource('dynamodb', region_name=args.region)
    client = boto3.client('dynamodb', region_name=args.region)

    def exists(name: str) -> bool:
        try:
            client.describe_table(TableName=name)
            return True
        except client.exceptions.ResourceNotFoundException:
            return False

    report = run(dynamodb, apply=args.apply, now=int(time.time()), exists=exists)
    print(json.dumps(report, indent=2, default=_default))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
