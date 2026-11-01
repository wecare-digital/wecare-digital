"""F001 Subscribe (WD-F001-SUBSCRIBE-PROFILE): the WhatsApp Flow data-exchange handler.

PURPOSE. Opens and saves one customer's WECARE.DIGITAL profile - name, WECARE.DIGITAL profile
name ("WhatsApp username" on screen), organization, job title and one structured address - on
the canonical ContactsTable row, and records the completion once in the unified Flow
submission history.

AUTHORITY.
* Identity comes only from the server-issued Flow session (`lambda_utils.flow_sessions`). The
  phone number and Customer ID inside a submission are display values, never identity.
* An update writes only PROFILE_FIELDS, the address, provenance for those fields and this
  Flow's own bookkeeping. Phone, Meta username, BSUID, customerUuid, subscriberId, retention
  lock, merge state and consent are never written by an update. A new contact receives
  server-minted identity in its creating PutItem, after the phone is claimed.
* A retention lock (`locked`) protects the row from deletion and merging, not from edits:
  locked and paid customers still keep their own name and address current here.
* Never writes consent (optIn*, allowlist*, consentLedger). Consent is an evidence workflow.
* ContactsTable is current truth. The FlowSubmission row is history, never prefill authority.
* COMPLETE is returned only after the contact write is confirmed by a consistent read and the
  completion is recorded. Every refusal returns REVIEW with copy naming the screen to fix.
"""
from __future__ import annotations

import json
import logging
import time
import unicodedata
import uuid
from typing import Any, Dict, Mapping, Optional, Tuple

from botocore.exceptions import ClientError

from lambda_utils import (canonical_flows, contact_key, contact_store, flow_funnel,
                          flow_sessions, identity_claims, subscribe_messages)
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer_uuid, provenance, subscriber_id
from flows import common, country_options

logger = logging.getLogger(__name__)

CAPABILITY = 'subscribe'
CONTRACT = canonical_flows.canonical_contract(CAPABILITY)
FLOW_CODE = CONTRACT['flowCode']
REFERENCE_PREFIX = CONTRACT['submissionPrefix']
#: FlowSubmission.flowType for this Flow's rows; kept from the first F001 rows so history
#: stays filterable as one series.
SUBMISSION_TYPE = 'subscribe'
#: fieldSources value for every field the customer declares in this Flow.
DECLARED_SOURCE = 'FLOW_SUBMISSION'

#: Flow field -> ContactsTable attribute. The only customer fields an update may write.
PROFILE_FIELDS = {'full_name': 'name', 'username': 'profileUsername',
                  'company_name': 'companyName', 'designation': 'designation'}
PROFILE_LABELS = {'full_name': 'full name', 'username': 'WhatsApp username',
                  'company_name': 'organization', 'designation': 'job title'}
#: Matches the Flow JSON max-chars; the Flow enforces them first, the handler enforces them always.
PROFILE_LIMITS = {'full_name': 200, 'username': 50, 'company_name': 200, 'designation': 200}
ADDRESS_FIELDS = {'address_line1': 'addressLine1', 'address_line2': 'addressLine2',
                  'locality': 'locality', 'city': 'city', 'state': 'state',
                  'postal_code': 'postalCode', 'country': 'country', 'country_code': 'countryCode'}
ADDRESS_LABELS = {'addressLine1': 'street address', 'addressLine2': 'apartment / suite / unit',
                  'locality': 'landmark / neighborhood', 'city': 'city',
                  'state': 'state / region', 'postalCode': 'postal code',
                  'country': 'country', 'countryCode': 'country'}
ADDRESS_LIMITS = {'addressLine1': 200, 'addressLine2': 200, 'locality': 100, 'city': 100,
                  'state': 100, 'postalCode': 100}
#: Exactly the `data` keys the PROFILE and ADDRESS screens declare. INIT returns these and
#: nothing else, so a response can never fail the screen's data schema.
SCREEN_KEYS = ('phone_number', 'customer_id', 'full_name', 'username', 'company_name',
               'designation', 'address_line1', 'address_line2', 'locality', 'city', 'state',
               'postal_code', 'country', 'country_code', 'profile_revision', 'updated_at')
#: The REVIEW screen declares the same keys plus `error_message`.
REVIEW_KEYS = SCREEN_KEYS + ('error_message',)
CUSTOMER_ID_PENDING = 'Assigned when you save'
#: After a save, for the rare row whose stored Customer ID is malformed (never repaired here).
CUSTOMER_ID_UNAVAILABLE = 'Being assigned by WECARE.DIGITAL'
DEFAULT_COUNTRY = ('India', 'IN')

SESSION_EXPIRED = ('This Subscribe link has expired. Message WECARE.DIGITAL in this chat '
                   'to get a new one.')
SESSION_FINISHED = ('Your details from this Subscribe link are already saved. Message '
                    'WECARE.DIGITAL in this chat to update them again.')
STALE = 'Your profile changed. Close and reopen Subscribe to load your latest details.'
PHONE_LINKED = ('Your phone number is already linked to another customer profile. Close '
                'Subscribe and message WECARE.DIGITAL so our team can help.')
CONTACT_UNAVAILABLE = ('We could not update this profile on WhatsApp. Close Subscribe and '
                       'message WECARE.DIGITAL so our team can help.')
SESSION_INCOMPLETE = ('Your saved Subscribe session is incomplete. Close and reopen Subscribe '
                      'before saving again.')
ALREADY_SAVED = ('These details were already saved from this Subscribe link. Close it and '
                 'message WECARE.DIGITAL in this chat to make more changes.')
NOT_CONFIRMED = 'We could not confirm your saved details. Please tap Save details again.'
CONFIRMATION_PENDING = ('Your details were saved, but confirmation is pending. '
                        'Please tap Save details again.')


class _Refusal(Exception):
    """A validation or save refusal: funnel stage, safe reason and customer copy."""

    def __init__(self, stage: str, reason: str, message: str):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason
        self.message = message


def _contacts():
    return common.dynamodb.Table(common.CONTACTS_TABLE)


def _count(stage: str, request_id: str, **fields: Any) -> None:
    flow_funnel.record(common.dynamodb.Table(flow_funnel.table_name()), FLOW_CODE, stage,
                       logger=logger, requestId=request_id, **fields)


def _count_init_outcome(stage: str, request_id: str, **fields: Any) -> None:
    """One counted 'received' and one outcome, in a single DynamoDB update.

    These are best-effort observability records, not permission checks: a failed
    counter update must not delay or reject a valid customer Flow.
    """
    flow_funnel.record_stages(
        common.dynamodb.Table(flow_funnel.table_name()), FLOW_CODE,
        ('init_received', stage), logger=logger, requestId=request_id, **fields)


def _session(flow_token: str, *, allow_consumed: bool) -> flow_sessions.FlowSession:
    table = common.dynamodb.Table(flow_sessions.table_name())
    session = flow_sessions.verify_session(table, capability=CAPABILITY, token=flow_token,
                                           rejected_message=SESSION_EXPIRED)
    # F001 exists on WABA 1 only; a WABA 2 token can never address this Flow.
    if session.waba != '1' or '-waba-1-ph-' not in flow_token:
        raise flow_sessions.FlowSessionRejected('session_wrong_waba', SESSION_EXPIRED)
    if session.consumed_at and not allow_consumed:
        raise flow_sessions.FlowSessionRejected('session_consumed', SESSION_FINISHED)
    return session


def _display_customer_id(row: Optional[Mapping[str, Any]], missing: str = CUSTOMER_ID_PENDING) -> str:
    return customer_uuid.display_code(dict(row) if row else None) or missing


def _screen_values(row: Mapping[str, Any], phone: str) -> Dict[str, str]:
    """PROFILE/ADDRESS screen data from the canonical row. Never from submission history."""
    address = contact_address.from_contact(dict(row)) or {}
    values = {key: str(address.get(attr) or '') for key, attr in ADDRESS_FIELDS.items()}
    if address:
        # The stored ISO code is the prefill authority; some older rows carry a legacy
        # country label that disagrees with their real countryCode.
        name, code = country_options.canonical_country('', values['country_code'])
        if not name:
            name, code = country_options.canonical_country(values['country'], '')
        values['country'], values['country_code'] = name, code
    if not values['country']:
        # Editable UI default only. REVIEW derives the code from the customer's choice.
        values['country'], values['country_code'] = DEFAULT_COUNTRY
    for key, attr in PROFILE_FIELDS.items():
        # Truncated to the input's max-chars so the screen always renders; a longer value
        # can only have come from another writer.
        values[key] = str(row.get(attr) or '')[:PROFILE_LIMITS[key]]
    values['phone_number'] = contact_store.canonical_phone(phone)
    values['customer_id'] = _display_customer_id(row)
    values['profile_revision'] = str(row.get('subscribeProfileRevision') or '')
    values['updated_at'] = str(row.get('updatedAt') or '')
    return {key: values[key] for key in SCREEN_KEYS}


def _review_error(data: Mapping[str, Any], row: Mapping[str, Any], phone: str,
                  message: str) -> Dict[str, Any]:
    """REVIEW again, never a success screen, with the customer's entries kept.

    Display identity comes from the server row. The revision pair is echoed from the
    submission on purpose: after a stale-write refusal, saving again must keep failing
    until the customer reopens Subscribe and loads the newer details.
    """
    out: Dict[str, str] = {}
    for key in REVIEW_KEYS:
        value = data.get(key) if isinstance(data, Mapping) else ''
        out[key] = value if isinstance(value, str) else ''
    out['phone_number'] = contact_store.canonical_phone(phone)
    out['customer_id'] = _display_customer_id(row)
    out['error_message'] = message
    return {'screen': 'REVIEW', 'data': out}


def _clean_text(raw: Any, label: str, limit: int, screen: str, *, required: bool) -> str:
    if raw is None:
        raw = ''
    if not isinstance(raw, str):
        raise _Refusal('validation_failed', 'field_type',
                       f'Please check your {label}. Go back to {screen} to correct it.')
    value = ' '.join(raw.split())
    if any(unicodedata.category(ch) == 'Cc' for ch in value):
        raise _Refusal('validation_failed', 'control_characters',
                       f'Please remove unsupported characters from your {label}. '
                       f'Go back to {screen} to correct it.')
    if required and not value:
        raise _Refusal('validation_failed', 'field_required',
                       f'Please enter your {label}. Go back to {screen} to correct it.')
    if len(value) > limit:
        raise _Refusal('validation_failed', 'field_too_long',
                       f'Please keep your {label} within {limit} characters. '
                       f'Go back to {screen} to correct it.')
    return value


def _validated_profile(data: Mapping[str, Any]) -> Dict[str, str]:
    """Customer-editable profile values, normalized. PROFILE is titled "Subscribe"."""
    return {attr: _clean_text(data.get(key), PROFILE_LABELS[key], PROFILE_LIMITS[key],
                              'Subscribe', required=(key == 'full_name'))
            for key, attr in PROFILE_FIELDS.items()}


def _validated_address(data: Mapping[str, Any]) -> Dict[str, Any]:
    """The normalized address for storage. ADDRESS is titled "Address"."""
    raw: Dict[str, Any] = {}
    for key, attr in ADDRESS_FIELDS.items():
        if attr in ('country', 'countryCode'):
            continue
        raw[attr] = _clean_text(data.get(key), ADDRESS_LABELS[attr], ADDRESS_LIMITS[attr],
                                'Address', required=False)
    chosen = data.get('country')
    chosen = ' '.join(chosen.split()) if isinstance(chosen, str) else ''
    if chosen:
        # The customer's dropdown choice is the authority; a stale hidden code never wins.
        name, code = country_options.canonical_country(chosen, '')
    else:
        hidden = data.get('country_code')
        name, code = country_options.canonical_country('', hidden if isinstance(hidden, str) else '')
    if not name or not code:
        raise _Refusal('validation_failed', 'country_unrecognized',
                       'Please select your country from the list. Go back to Address to correct it.')
    raw['country'], raw['countryCode'] = name, code
    try:
        return contact_address.normalize_for_storage(raw)
    except contact_address.UnusableAddress as exc:
        label = ADDRESS_LABELS.get(exc.field, 'address')
        if exc.code == 'FIELD_TOO_LONG':
            message = f'Please shorten your {label}. Go back to Address to correct it.'
        elif exc.code == 'FIELD_REQUIRED':
            message = f'Please enter your {label}. Go back to Address to correct it.'
        else:
            message = 'Please check your address. Go back to Address to correct it.'
        raise _Refusal('validation_failed', f'address_{exc.code.lower()}', message) from None


def _matches_saved(row: Mapping[str, Any], values: Mapping[str, str],
                   address: Mapping[str, Any]) -> bool:
    """True when a retried submission carries exactly what this session already saved."""
    if any(str(row.get(attr) or '') != value for attr, value in values.items()):
        return False
    saved = contact_address.from_contact(dict(row)) or {}
    return all(str(saved.get(field) or '') == str(address.get(field) or '')
               for field in ADDRESS_FIELDS.values())


def _is_conditional(exc: ClientError) -> bool:
    return exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException'


def _after_condition_failure(table: Any, contact_id: str, flow_token: str) -> str:
    """Why a conditional write lost: 'retry' (this session already saved), 'gone' or 'stale'."""
    current = table.get_item(Key=contact_key.key(contact_id), ConsistentRead=True).get('Item') or {}
    if current and current.get('subscribeLastFlowToken') == flow_token:
        return 'retry'
    if current and not contact_store.is_live(current):
        return 'gone'
    return 'stale'


def _write_contact(table: Any, row: Mapping[str, Any], contact_id: str, phone: str,
                   session: flow_sessions.FlowSession, values: Mapping[str, str],
                   address: Dict[str, Any], data: Mapping[str, Any], flow_token: str,
                   returning: bool, now: int, request_id: str) -> None:
    """The one primary customer mutation. Raises `_Refusal` instead of writing stale data."""
    fields: Dict[str, Any] = dict(values)
    fields.update(contact_address.contact_write_fields(address, now=now))
    fields.update({'updatedAt': now, 'subscribeProfileRevision': str(uuid.uuid4()),
                   'subscribeLastFlowToken': flow_token, 'subscribeProfileWasExisting': returning})
    declared = {attr: DECLARED_SOURCE for attr in values}
    declared[contact_address.ATTRIBUTE] = DECLARED_SOURCE

    if row:
        # A stale screen cannot overwrite details edited on the website, by staff or by
        # another Subscribe session since this one opened.
        if (str(row.get('updatedAt') or '') != str(data.get('updated_at') or '')
                or str(row.get('subscribeProfileRevision') or '') != str(data.get('profile_revision') or '')):
            raise _Refusal('stale_write_refused', 'revision_changed', STALE)
        fields[provenance.PROVENANCE_ATTRIBUTE] = provenance.merged_provenance(row, declared)
        names = {f'#f{i}': attr for i, attr in enumerate(fields)}
        attrs: Dict[str, Any] = {f':v{i}': value for i, value in enumerate(fields.values())}
        names.update({'#ua': 'updatedAt', '#rev': 'subscribeProfileRevision'})
        condition = ('attribute_exists(id) AND attribute_not_exists(deletedAt) AND '
                     '(attribute_not_exists(isDeleted) OR isDeleted=:notdeleted)')
        attrs[':notdeleted'] = False
        if 'updatedAt' in row:
            condition += ' AND #ua=:previous'
            attrs[':previous'] = row['updatedAt']
        else:
            condition += ' AND attribute_not_exists(#ua)'
        if row.get('subscribeProfileRevision'):
            condition += ' AND #rev=:revision'
            attrs[':revision'] = row['subscribeProfileRevision']
        else:
            condition += ' AND attribute_not_exists(#rev)'
        assignments = [f'{name}=:v{name[2:]}' for name in names if name.startswith('#f')]
        if customer_uuid.ATTRIBUTE not in row:
            # Mint the permanent Customer ID only where none exists, and only once.
            # `#cu` is added only here: DynamoDB rejects an unused attribute name.
            names['#cu'] = customer_uuid.ATTRIBUTE
            condition += ' AND attribute_not_exists(#cu)'
            attrs[':newcu'] = customer_uuid.new_customer_uuid()
            assignments.append('#cu=:newcu')
        elif not customer_uuid.from_contact(dict(row)):
            # A malformed stored Customer ID is protected identity: never repaired from a
            # Flow. The profile still saves; staff see the gap in Workspace.
            logger.warning(json.dumps({'event': 'subscribe_customer_uuid_invalid',
                                       'requestId': request_id}))
        try:
            table.update_item(Key=contact_key.key(contact_id),
                              UpdateExpression='SET ' + ', '.join(assignments),
                              ConditionExpression=condition, ExpressionAttributeNames=names,
                              ExpressionAttributeValues=attrs)
        except ClientError as exc:
            if not _is_conditional(exc):
                raise
            outcome = _after_condition_failure(table, contact_id, flow_token)
            if outcome == 'retry':
                return
            if outcome == 'gone':
                raise _Refusal('save_refused', 'contact_not_live', CONTACT_UNAVAILABLE) from None
            raise _Refusal('stale_write_refused', 'condition_failed', STALE) from None
        return

    created_sources = dict(declared)
    created_sources['phone'] = ('WHATSAPP_INBOUND' if session.launch_channel == flow_sessions.LAUNCH_KEYWORD
                                else 'OPERATOR')
    item = {**contact_key.contact_item_keys(contact_id),
            'phone': contact_store.canonical_phone(phone),
            **subscriber_id.new_contact_fields(now=now), 'createdAt': now, **fields,
            provenance.PROVENANCE_ATTRIBUTE: created_sources}
    try:
        identity_claims.claim_identities(common.dynamodb.Table(identity_claims.TABLE_NAME),
                                         contact_id=contact_id, phone=item['phone'], now=now)
    except identity_claims.IdentityClaimConflict:
        raise _Refusal('save_refused', 'identity_conflict', PHONE_LINKED) from None
    try:
        # Never resurrects a deleted deterministic WhatsApp row and never creates a second one.
        table.put_item(Item=item, ConditionExpression='attribute_not_exists(id)')
    except ClientError as exc:
        if not _is_conditional(exc):
            raise
        outcome = _after_condition_failure(table, contact_id, flow_token)
        if outcome == 'retry':
            return
        if outcome == 'gone':
            raise _Refusal('save_refused', 'contact_not_live', CONTACT_UNAVAILABLE) from None
        raise _Refusal('stale_write_refused', 'created_concurrently', STALE) from None


def _answers(saved: Mapping[str, Any]) -> list:
    """Inbox answers with explicit labels, so a customer-entered profile name can never be
    read as the Meta WhatsApp username."""
    address = contact_address.from_contact(dict(saved)) or {}
    rows = [('Customer ID', _display_customer_id(saved, CUSTOMER_ID_UNAVAILABLE)),
            ('Name', saved.get('name')),
            ('WECARE.DIGITAL profile name (customer-entered)', saved.get('profileUsername')),
            ('Organization', saved.get('companyName')),
            ('Job title', saved.get('designation')),
            ('Address', address.get('fullAddress'))]
    return [{'question': question, 'answer': str(answer)[:2000]}
            for question, answer in rows if answer]


def route(action: str, screen: str, data: Any, flow_token: str, request_id: str) -> Dict[str, Any]:
    """Every F001 data-exchange request. Only INIT and the REVIEW save reach the endpoint;
    PROFILE -> ADDRESS -> REVIEW navigate on the handset and COMPLETE ends client-side."""
    payload = data if isinstance(data, dict) else {}
    if payload.get('error'):
        # Meta's error notification for an earlier response: acknowledge, never save.
        _count('error_notification', request_id, reason=str(payload.get('error'))[:80])
        return {'data': {'acknowledged': True}}
    if action == 'INIT':
        return handle_init(payload, flow_token, request_id)
    if action == 'data_exchange' and screen == 'REVIEW':
        return handle_review(payload, flow_token, request_id)
    _count('review_rejected', request_id, reason='unsupported_action')
    return {'data': {'error': 'This Subscribe step is not available. Close and reopen Subscribe.',
                     'error_code': 'F001_UNSUPPORTED_ACTION'}}


def handle_init(data: Mapping[str, Any], flow_token: str, request_id: str) -> Dict[str, Any]:
    """Open PROFILE prefilled from the canonical row; clean defaults for a new customer."""
    # Keep the issued-session check and canonical contact lookup authoritative.
    # INIT's two best-effort funnel counters are recorded together only AFTER
    # the outcome is known, avoiding a separate DynamoDB write before identity
    # verification. No cached customer profile or client-supplied identity.
    try:
        session = _session(flow_token, allow_consumed=False)
    except flow_sessions.FlowSessionRejected as rejected:
        _count_init_outcome('init_rejected', request_id, reason=rejected.reason)
        raise
    except Exception as exc:
        _count_init_outcome('init_failed', request_id, reason=type(exc).__name__)
        raise
    try:
        row = contact_store.lookup(_contacts(), session.phone) or {}
        values = _screen_values(row, session.phone)
    except Exception as exc:
        _count_init_outcome('init_failed', request_id, reason=type(exc).__name__)
        raise
    _count_init_outcome('init_success', request_id,
                        launchChannel=session.launch_channel, created=not row)
    return {'screen': 'PROFILE', 'data': values}


def handle_review(data: Mapping[str, Any], flow_token: str, request_id: str) -> Dict[str, Any]:
    """Validate, save once, record history once, then COMPLETE."""
    try:
        session = _session(flow_token, allow_consumed=True)
    except flow_sessions.FlowSessionRejected as rejected:
        _count('review_rejected', request_id, reason=rejected.reason)
        raise
    phone = session.phone
    table = _contacts()
    try:
        row = contact_store.lookup(table, phone) or {}
    except contact_store.IdentityConflict:
        # Two live profiles claim this phone: never pick one. Staff resolve it in Customers.
        _count('save_refused', request_id, reason='identity_conflict')
        return _review_error(data, {}, phone, PHONE_LINKED)
    try:
        values = _validated_profile(data)
        address = _validated_address(data)
    except _Refusal as refusal:
        _count(refusal.stage, request_id, reason=refusal.reason)
        return _review_error(data, row, phone, refusal.message)

    contact_id = contact_key.resolve(row) or contact_store.deterministic_id(phone)
    is_retry = bool(row) and row.get('subscribeLastFlowToken') == flow_token
    if session.consumed_at and not is_retry:
        _count('review_rejected', request_id, reason='session_finished')
        raise flow_sessions.FlowSessionRejected('session_finished', SESSION_FINISHED)
    try:
        if is_retry:
            # The primary mutation already happened for this token: never repeat it.
            if 'subscribeProfileWasExisting' not in row:
                raise _Refusal('save_refused', 'retry_incomplete', SESSION_INCOMPLETE)
            if not _matches_saved(row, values, address):
                raise _Refusal('save_refused', 'retry_changed', ALREADY_SAVED)
            returning = bool(row['subscribeProfileWasExisting'])
        else:
            returning = subscribe_messages.is_returning(row)
            _write_contact(table, row, contact_id, phone, session, values, address, data,
                           flow_token, returning, int(time.time()), request_id)
    except _Refusal as refusal:
        _count(refusal.stage, request_id, reason=refusal.reason)
        return _review_error(data, row, phone, refusal.message)

    saved = table.get_item(Key=contact_key.key(contact_id), ConsistentRead=True).get('Item') or {}
    if not contact_store.is_live(saved) or saved.get('subscribeLastFlowToken') != flow_token:
        _count('save_refused', request_id, reason='not_confirmed')
        return _review_error(data, saved or row, phone, NOT_CONFIRMED)
    if not is_retry:
        returning = bool(saved.get('subscribeProfileWasExisting', returning))
    _count('save_success', request_id, retry=is_retry, created=not row,
           launchChannel=session.launch_channel)

    form = _screen_values(saved, phone)
    completed_at = int(time.time())
    completion = common.record_completion(
        flow_code=FLOW_CODE, flow_type=SUBMISSION_TYPE, phone=phone, contact_id=contact_id,
        sender_name=str(saved.get('name') or ''),
        form_data={key: value for key, value in form.items()
                   if key not in ('profile_revision', 'updated_at', 'country_code')},
        flow_token=flow_token, request_id=request_id, screen='REVIEW',
        reference_prefix=REFERENCE_PREFIX, requires_payment=False, payment_amount=0,
        status='completed', answers=_answers(saved),
        extra={'launchChannel': session.launch_channel, 'requestId': request_id,
               'completedAt': completed_at})
    if completion.error:
        # Saved, history not yet written: a retry finishes it without repeating the update.
        _count('completion_history_failed', request_id, reason='claim_error')
        return _review_error(data, saved, phone, CONFIRMATION_PENDING)
    flow_sessions.mark_consumed(common.dynamodb.Table(flow_sessions.table_name()), token=flow_token)
    copy = subscribe_messages.copy_for(
        returning, common.dynamodb.Table(subscribe_messages.system_config_table_name()))
    _count('complete_returned', request_id, retry=is_retry)
    return {'screen': 'COMPLETE', 'data': {
        'customer_id': _display_customer_id(saved, CUSTOMER_ID_UNAVAILABLE),
        'message': copy['confirmation']}}


def launch_session_token(phone: Any, *, launch_channel: str, initiated_by: str,
                         now: Optional[int] = None) -> Tuple[str, flow_sessions.FlowSession]:
    """Mint and record a WABA 1 F001 session before a Flow message is sent. Raises on failure."""
    token = flow_sessions.mint_token(CONTRACT['tokenPrefix'], phone, '1')
    session = flow_sessions.record_session(
        common.dynamodb.Table(flow_sessions.table_name()), capability=CAPABILITY, token=token,
        launch_channel=launch_channel, initiated_by=initiated_by, now=now)
    return token, session
