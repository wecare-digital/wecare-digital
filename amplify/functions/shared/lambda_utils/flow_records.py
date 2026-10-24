"""Reviews, appointments, Sehat appointments, enterprise cases and amendments are flow responses.

Each used to be stored twice. The WhatsApp Flow that collected it wrote a row to its own
table (ReviewTable, AppointmentTable, SehatAppointment legacy rows, EnterpriseAssistTable) and a second row to
FlowSubmissionTable, while the workspace's staff forms wrote only the domain table (and the
staff amend form only AmendmentHistoryTable). That meant two copies of one answer, two status
vocabularies, and staff-entered records that no flow-response view could see.

They are now ONE row in FlowSubmissionTable, told apart by `flowCode`:

    kind              flowCode(s)        id field        new-id prefix
    ----------------  -----------------  --------------  -------------
    review            WD_REV, WD_IDEA    reviewId        WD-REV-
    appointment       WD_APPT            appointmentId   WD-APT-
    Sehat appointment WD_SEHAT, WD_RX     sehatAppointmentId WD-SEHAT-
    enterprise case   WD_ENT             caseId          WD-ENT-
    amendment         WD_AMEND           amendmentId     WD-AMD-

The row's `submissionId` IS the record id: the WhatsApp Flows already used their derived id
as the submission number. The kind's id field is written as an alias of it, so every API
keeps returning the key it always returned. The kind's own fields (rating, slotDate,
priority, ...) are attributes on the same row, and the row carries `channel`
(whatsapp / website / staff). These rows have no `ttl`, because a review or a booked
appointment is a business record, not a transport log.

Both service-api copies, the WhatsApp Flow modules, the inbound idea path and the SLA engine
read and write through this module, so there is one place the shape is decided.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from boto3.dynamodb.conditions import Key

from lambda_utils import contact_store, flow_completion, shared_tables

#: The GSI on FlowSubmissionTable every kind is listed through.
FLOW_CODE_INDEX = 'flowCode'

#: Bound on pages followed per flowCode query. 50 x 1 MB is far beyond any real volume.
MAX_PAGES = 50

#: Attributes that are transport plumbing, not part of a record's API shape.
_INTERNAL_FIELDS = ('flowToken', 'completionKey', 'completionKeyDegraded', 'ttl')


@dataclass(frozen=True)
class Kind:
    """One kind of flow response kept in FlowSubmissionTable."""

    name: str
    flow_codes: Tuple[str, ...]
    id_field: str
    id_prefix: str
    flow_type: str
    default_status: str

    @property
    def flow_code(self) -> str:
        """The code new rows of this kind are written under."""
        return self.flow_codes[0]


REVIEW = Kind('review', ('WD_REV', 'WD_IDEA'), 'reviewId', 'WD-REV-', 'feedback', 'submitted')
APPOINTMENT = Kind('appointment', ('WD_APPT',), 'appointmentId', 'WD-APT-', 'booking',
                   'scheduled')
SEHAT_APPOINTMENT = Kind('sehat_appointment', ('WD_SEHAT', 'WD_RX'), 'sehatAppointmentId', 'WD-SEHAT-', 'sehat_appointment', 'available')
ENTERPRISE_CASE = Kind('enterprise_case', ('WD_ENT',), 'caseId', 'WD-ENT-', 'enterprise',
                       'open')
AMENDMENT = Kind('amendment', ('WD_AMEND',), 'amendmentId', 'WD-AMD-', 'amendment',
                 'submitted')

KINDS: Tuple[Kind, ...] = (REVIEW, APPOINTMENT, SEHAT_APPOINTMENT, ENTERPRISE_CASE, AMENDMENT)

#: Appointment statuses that are still waiting for the slot to happen. WhatsApp bookings
#: write `booked` and staff bookings `scheduled`; both mean the same state.
APPOINTMENT_PENDING_STATUSES = ('scheduled', 'confirmed', 'booked')


def table_name() -> str:
    return shared_tables.flow_submissions_table_name()


def new_id(kind: Kind) -> str:
    """A fresh staff-record id in the kind's established format (prefix + 8 hex)."""
    return kind.id_prefix + hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:8].upper()


def _clean(fields: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None and v != ''}


def with_id(kind: Kind, row: Mapping[str, Any]) -> Dict[str, Any]:
    """The stored row as the kind's API record: id alias present, plumbing removed."""
    out = {k: v for k, v in dict(row or {}).items() if k not in _INTERNAL_FIELDS}
    out[kind.id_field] = out.get(kind.id_field) or out.get('submissionId', '')
    out['channel'] = flow_completion.channel_of(row)
    return out


def list_rows(table: Any, kind: Kind) -> List[Dict[str, Any]]:
    """Every row of one kind, following pagination, newest first."""
    rows: List[Dict[str, Any]] = []
    for code in kind.flow_codes:
        kwargs: Dict[str, Any] = {
            'IndexName': FLOW_CODE_INDEX,
            'KeyConditionExpression': Key('flowCode').eq(code),
        }
        for _ in range(MAX_PAGES):
            page = table.query(**kwargs)
            rows.extend(page.get('Items') or [])
            last = page.get('LastEvaluatedKey')
            if not last:
                break
            kwargs['ExclusiveStartKey'] = last
    out = [with_id(kind, row) for row in rows]
    out.sort(key=lambda item: _number(item.get('createdAt')), reverse=True)
    return out


def get_row(table: Any, kind: Kind, record_id: str) -> Optional[Dict[str, Any]]:
    """One record by id, or None when it does not exist or belongs to another kind."""
    if not record_id:
        return None
    item = table.get_item(Key={'submissionId': record_id}).get('Item')
    if not item or item.get('flowCode') not in kind.flow_codes:
        return None
    return with_id(kind, item)


def update_row(table: Any, kind: Kind, record_id: str, updates: Mapping[str, Any],
               now: int) -> bool:
    """SET the given fields on one record of this kind. False when there is no such record.

    Conditional on the row existing AND being this kind, so an update can neither create a
    phantom row (UpdateItem upserts) nor rewrite a different kind's record by id.
    """
    if not record_id:
        return False
    fields = dict(updates)
    fields['updatedAt'] = now
    names: Dict[str, str] = {'#code': 'flowCode'}
    values: Dict[str, Any] = {}
    parts: List[str] = []
    for index, (name, value) in enumerate(fields.items()):
        names[f'#f{index}'] = name
        values[f':v{index}'] = value
        parts.append(f'#f{index} = :v{index}')
    codes = []
    for index, code in enumerate(kind.flow_codes):
        values[f':c{index}'] = code
        codes.append(f'#code = :c{index}')
    try:
        table.update_item(
            Key={'submissionId': record_id},
            UpdateExpression='SET ' + ', '.join(parts),
            ConditionExpression=('attribute_exists(submissionId) AND ('
                                 + ' OR '.join(codes) + ')'),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except Exception as error:  # noqa: BLE001 - classified immediately
        if _is_condition_failure(error):
            return False
        raise
    return True


def _is_condition_failure(error: Exception) -> bool:
    code = getattr(error, 'response', {}).get('Error', {}).get('Code')
    return code == 'ConditionalCheckFailedException' or \
        'ConditionalCheckFailedException' in str(error)


def create_staff_row(kind: Kind, *, fields: Mapping[str, Any], phone: str = '',
                     contact_id: str = '', sender_name: str = '',
                     status: Optional[str] = None, form_data: Optional[Mapping[str, Any]] = None,
                     request_id: str = '', attempts: int = 5) -> Dict[str, Any]:
    """Write a staff-entered record through the one idempotent writer. Returns the API record.

    A fresh random id per attempt; a `duplicate` can only mean an id collision, so it is
    retried with a new id rather than overwriting someone else's record. Raises RuntimeError
    when the write fails or no unique id could be allocated.
    """
    last_status = ''
    for _ in range(max(1, attempts)):
        record_id = new_id(kind)
        extra = _clean({**fields, kind.id_field: record_id})
        result = flow_completion.claim_completion(
            flow_token=record_id, screen='STAFF', flow_code=kind.flow_code,
            flow_type=kind.flow_type, phone=contact_store.digits(phone) or phone,
            contact_id=contact_id, sender_name=sender_name, form_data=form_data,
            reference_prefix=kind.id_prefix.rstrip('-'), submission_id=record_id,
            status=status or kind.default_status, extra=extra, ttl_seconds=0,
            request_id=request_id, channel=flow_completion.CHANNEL_STAFF)
        last_status = result.status
        if result.created:
            return with_id(kind, result.item)
        if result.status == 'error':
            raise RuntimeError(f'{kind.name} could not be saved')
    raise RuntimeError(f'could not allocate a unique {kind.name} id ({last_status})')


# ── per-kind API shapes ─────────────────────────────────────────────────────────────

def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _digits_only(value: Any) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def _matches_phone(row: Mapping[str, Any], phone: str, fields: Iterable[str]) -> bool:
    """True when any of `fields` holds the same number, however it was spelled."""
    wanted = _digits_only(phone)
    if not wanted:
        return False
    return any(_digits_only(row.get(field)) == wanted for field in fields)


def review_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    item = with_id(REVIEW, row)
    item['comment'] = item.get('reviewText', item.get('comment', ''))
    item['source'] = item.get('source') or item.get('category') or 'web'
    item['status'] = item.get('status') or 'submitted'
    # The staff page speaks `pending`; storage keeps `submitted`. One translator, here.
    if item['status'] == 'submitted':
        item['status'] = 'pending'
    return item


def list_reviews(table: Any, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    status = params.get('status') or ''
    if status == 'pending':
        status = 'submitted'
    rows = list_rows(table, REVIEW)
    phone = params.get('customerPhone') or ''
    if phone:
        rows = [r for r in rows if _matches_phone(r, phone, ('customerPhone', 'phone'))]
    contact_id = params.get('contactId')
    if contact_id:
        rows = [r for r in rows if r.get('contactId') == contact_id]
    if status:
        rows = [r for r in rows if (r.get('status') or 'submitted') == status]
    source = params.get('source')
    if source:
        rows = [r for r in rows if (r.get('source') or r.get('category') or '') == source]
    min_rating = params.get('minRating')
    if min_rating:
        rows = [r for r in rows if _number(r.get('rating')) >= int(min_rating)]
    return [review_view(r) for r in rows]


def review_fields(body: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        rating = int(body.get('rating', 5))
    except (TypeError, ValueError):
        rating = 0
    return {
        'customerPhone': body.get('customerPhone', ''),
        'customerName': body.get('customerName', ''),
        'orderId': body.get('orderId'),
        'rating': rating if 1 <= rating <= 5 else 0,
        'reviewText': body.get('comment', body.get('reviewText', '')),
        'category': body.get('category', ''),
        'source': body.get('source') or 'web',
    }


def review_updates(body: Mapping[str, Any], now: int) -> Dict[str, Any]:
    updates = {k: body[k] for k in ('status', 'response', 'respondedAt') if k in body}
    if 'response' in body and 'respondedAt' not in body:
        updates['respondedAt'] = now
    if updates.get('status') == 'pending':
        updates['status'] = 'submitted'
    return updates


def _scheduled_at(item: Mapping[str, Any], default_time: str = '00:00') -> Optional[int]:
    if not item.get('slotDate'):
        return None
    text = f"{item['slotDate']} {item.get('slotTime') or default_time}"
    for fmt in ('%Y-%m-%d %I:%M %p', '%Y-%m-%d %H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    return None


def appointment_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    item = with_id(APPOINTMENT, row)
    item['type'] = item.pop('appointmentType', item.get('type', ''))
    if not item.get('scheduledAt'):
        scheduled = _scheduled_at(item)
        if scheduled is not None:
            item['scheduledAt'] = scheduled
    item['provider'] = item.get('assignedTo', item.get('provider', ''))
    item['location'] = item.get('location', '')
    return item


def list_appointments(table: Any, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = list_rows(table, APPOINTMENT)
    status = params.get('status')
    if status:
        rows = [r for r in rows if r.get('status') == status]
    apt_type = params.get('type')
    if apt_type:
        rows = [r for r in rows if r.get('appointmentType') == apt_type]
    return [appointment_view(r) for r in rows]


def appointment_fields(body: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        'customerPhone': body.get('customerPhone', ''),
        'customerName': body.get('customerName', ''),
        'orderId': body.get('orderId'),
        'appointmentType': body.get('type', body.get('appointmentType', 'consultation')),
        'slotDate': body.get('slotDate', body.get('date', '')),
        'slotTime': body.get('slotTime', body.get('time', '')),
        'duration': body.get('duration', ''),
        'location': body.get('location', ''),
        'notes': body.get('notes', ''),
    }


APPOINTMENT_UPDATE_FIELDS = ('status', 'notes', 'adminNotes', 'assignedTo', 'location',
                             'slotDate', 'slotTime')


def sehat_appointment_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    item = with_id(SEHAT_APPOINTMENT, row)
    item['slotId'] = item.get('sehatAppointmentId') or item.get('rxSlotId') or item.get('slotId', '')
    item['date'] = item.get('slotDate', '')
    item['time'] = item.get('slotTime', '')
    item['provider'] = item.get('doctorName', item.get('facilityName', ''))
    item['patientName'] = item.get('customerName', '')
    item['patientPhone'] = item.get('customerPhone', '')
    return item


def list_sehat_appointments(table: Any, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = list_rows(table, SEHAT_APPOINTMENT)
    status = params.get('status')
    if status:
        rows = [r for r in rows if r.get('status') == status]
    date = params.get('date')
    if date:
        rows = [r for r in rows if r.get('slotDate') == date]
    return [sehat_appointment_view(r) for r in rows]


def sehat_appointment_fields(body: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        'customerPhone': body.get('patientPhone', body.get('customerPhone', '')),
        'customerName': body.get('patientName', body.get('customerName', '')),
        'orderId': body.get('orderId'),
        'slotType': body.get('slotType', 'consultation'),
        'slotDate': body.get('date', body.get('slotDate', '')),
        'slotTime': body.get('time', body.get('slotTime', '')),
        'facilityName': body.get('provider', body.get('facilityName', '')),
        'appointmentNotes': body.get('notes', ''),
    }


SEHAT_APPOINTMENT_UPDATE_FIELDS = ('status', 'appointmentNotes', 'adminNotes', 'customerName',
                         'customerPhone')


def enterprise_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    item = with_id(ENTERPRISE_CASE, row)
    item['customerName'] = item.get('contactName', item.get('customerName', ''))
    item['customerPhone'] = item.get('contactPhone', item.get('customerPhone', ''))
    item['category'] = item.get('category', '')
    return item


def list_enterprise_cases(table: Any, params: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = list_rows(table, ENTERPRISE_CASE)
    status = params.get('status')
    if status:
        rows = [r for r in rows if r.get('status') == status]
    priority = params.get('priority')
    if priority:
        rows = [r for r in rows if r.get('priority') == priority]
    return [enterprise_view(r) for r in rows]


def enterprise_fields(body: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        'contactPhone': body.get('customerPhone', body.get('contactPhone', '')),
        'contactName': body.get('customerName', body.get('contactName', '')),
        'contactEmail': body.get('contactEmail', ''),
        'accountName': body.get('accountName', ''),
        'subject': body.get('subject', ''),
        'description': body.get('description', ''),
        'priority': body.get('priority', 'normal'),
        'assignedTo': body.get('assignedTo', ''),
    }


ENTERPRISE_UPDATE_FIELDS = ('status', 'priority', 'assignedTo', 'notes', 'resolution')


def amendment_fields(body: Mapping[str, Any]) -> Dict[str, Any]:
    """An amendment points at the request it amends through `parentSubmissionId`."""
    return {
        'parentSubmissionId': body.get('submissionId', ''),
        'orderId': body.get('orderId', ''),
        'amendmentType': body.get('amendmentType', ''),
        'description': body.get('description', ''),
    }


def pending_appointments(table: Any) -> List[Dict[str, Any]]:
    """Appointments whose slot has not been resolved yet, for the SLA no-show sweep."""
    return [row for row in list_rows(table, APPOINTMENT)
            if row.get('status') in APPOINTMENT_PENDING_STATUSES]


def slot_timestamp(row: Mapping[str, Any], default_time: str = '23:59') -> Optional[int]:
    """The appointment's slot as a unix timestamp, or None when it cannot be parsed.

    A slot with no time is read as the end of its day, so the no-show sweep never fires
    before the day is over.
    """
    return _scheduled_at(row, default_time)
