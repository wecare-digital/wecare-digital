"""Subscribe draft: one customer profile/address; never changes channel consent."""
import time
import uuid
from botocore.exceptions import ClientError
from lambda_utils import contact_store, identity_claims
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer_uuid, subscriber_id
from flows import common, country_options, subscribe_messages

PROFILE_FIELDS = {'full_name': 'name', 'username': 'profileUsername',
                  'company_name': 'companyName', 'designation': 'designation'}
ADDRESS_FIELDS = {'address_line1': 'addressLine1', 'address_line2': 'addressLine2',
                  'locality': 'locality', 'city': 'city', 'state': 'state',
                  'postal_code': 'postalCode', 'country': 'country', 'country_code': 'countryCode'}


def _context(token):
    phone = common.get_phone_from_token(token)
    if not contact_store.digits(phone) or '-waba-1-ph-' not in token:
        raise ValueError('A WABA1 customer session is required')
    table = common.dynamodb.Table(common.CONTACTS_TABLE)
    return table, phone, contact_store.lookup(table, phone) or {}


def _form(row, phone):
    address = contact_address.from_contact(row) or {}
    address_values = {key: str(address.get(attr) or '') for key, attr in ADDRESS_FIELDS.items()}
    if address:
        # Prefer the stored ISO code as the canonical prefill authority. Some older rows can
        # carry a legacy/default country label that disagrees with their real countryCode.
        country_name, country_code = country_options.canonical_country(
            '', address_values.get('country_code'))
        if not country_name:
            country_name, country_code = country_options.canonical_country(
                address_values.get('country'), address_values.get('country_code'))
        address_values['country'] = country_name
        address_values['country_code'] = country_code
    return {'phone_number': contact_store.canonical_phone(phone),
            'customer_id': customer_uuid.display_code(row) or 'Assigned when you save',
            **{key: str(row.get(attr) or '') for key, attr in PROFILE_FIELDS.items()},
            **address_values,
            'profile_revision': str(row.get('subscribeProfileRevision') or ''),
            'updated_at': str(row.get('updatedAt') or ''), 'error_message': ''}


def handle_init(data, flow_token, request_id):
    _table, phone, row = _context(flow_token)
    values = _form(row, phone)
    # India is only the editable UI default when the canonical customer has no saved country.
    # A saved country always wins, and handle_review derives ISO code from the customer's
    # explicit dropdown choice so changing this default never locks the profile to India.
    if not values.get('country'):
        values['country'] = 'India'
        values['country_code'] = 'IN'
    return {'screen': 'PROFILE', 'data': values}


def _error(data, message):
    # Reuse the review screen so validation never displays a success screen.
    return {'screen': 'REVIEW', 'data': {**data, 'error_message': message}}


def handle_review(data, flow_token, request_id):
    table, phone, row = _context(flow_token)
    values = {}
    for key, attr in PROFILE_FIELDS.items():
        raw = data.get(key, '')
        if not isinstance(raw, str) or len(raw.strip()) > 200:
            return _error(data, 'Please check your profile fields (maximum 200 characters).')
        values[attr] = raw.strip()
    if not values['name']:
        return _error(data, 'Please enter your name.')
    if not values['companyName']:
        return _error(data, 'Please enter your organisation.')
    if not values['designation']:
        return _error(data, 'Please enter your role / designation.')
    raw_address = {attr: data.get(key, '') for key, attr in ADDRESS_FIELDS.items()}
    for attr, label in (('addressLine2', 'address line 2'), ('locality', 'landmark / locality')):
        raw = raw_address.get(attr, '')
        if not isinstance(raw, str) or not raw.strip():
            return _error(data, 'Please enter your ' + label + '.')
    country_name, country_code = country_options.canonical_country(
        raw_address.get('country'), raw_address.get('countryCode'))
    if not country_name or not country_code:
        return _error(data, 'Please select your country.')
    raw_address['country'] = country_name
    raw_address['countryCode'] = country_code
    # Any validation error after this point echoes `data` back to the Flow. Keep its visible
    # country and hidden ISO code canonical so a retry cannot resurrect a stale pair.
    data['country'] = country_name
    data['country_code'] = country_code
    # A profile username is customer-entered; never overwrite Meta's username,
    # BSUID, ownership or permanent customer identity with it.
    if len(values['profileUsername']) > 50:
        return _error(data, 'Please keep your username within 50 characters.')
    now = int(time.time())
    try:
        address = contact_address.normalize_for_storage(raw_address)
    except contact_address.UnusableAddress as exc:
        labels = {'addressLine1': 'address line 1', 'city': 'city', 'state': 'state',
                  'postalCode': 'PIN / postal code'}
        return _error(data, 'Please check your ' + labels.get(exc.field, 'address') + '.')
    values.update(contact_address.contact_write_fields(address, now=now))
    contact_id = str(row.get('id') or contact_store.deterministic_id(phone))
    is_retry = row.get('subscribeLastFlowToken') == flow_token
    if is_retry and 'subscribeProfileWasExisting' not in row:
        return _error(data, 'Your saved Subscribe session is incomplete. Close and reopen Subscribe before saving again.')
    returning = (bool(row['subscribeProfileWasExisting'])
                 if is_retry else subscribe_messages.is_returning(row))
    if not is_retry:
        values.update({'updatedAt': now, 'subscribeProfileRevision': str(uuid.uuid4()),
                       'subscribeLastFlowToken': flow_token,
                       'subscribeProfileWasExisting': returning})
        try:
            if row:
                # A stale screen cannot overwrite details edited on the website or another Flow.
                if (str(row.get('updatedAt') or '') != str(data.get('updated_at') or '')
                        or str(row.get('subscribeProfileRevision') or '') != str(data.get('profile_revision') or '')):
                    return _error(data, 'Your profile changed. Close and reopen Subscribe to load your latest details.')
                names = {f'#f{i}': key for i, key in enumerate(values)}
                attrs = {f':v{i}': value for i, value in enumerate(values.values())}
                names.update({'#ua': 'updatedAt', '#rev': 'subscribeProfileRevision'})
                condition = 'attribute_exists(id) AND attribute_not_exists(deletedAt) AND (attribute_not_exists(isDeleted) OR isDeleted=:notdeleted)'
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
                if not customer_uuid.from_contact(row):
                    condition += ' AND attribute_not_exists(customerUuid)'
                    values[customer_uuid.ATTRIBUTE] = customer_uuid.new_customer_uuid()
                    i = len(names)
                    names[f'#f{i}'] = customer_uuid.ATTRIBUTE
                    attrs[f':v{i}'] = values[customer_uuid.ATTRIBUTE]
                assignments = [f'{name}=:v{name[2:]}' for name in names if name.startswith('#f')]
                table.update_item(Key={'id': contact_id}, UpdateExpression='SET ' + ', '.join(assignments),
                                  ConditionExpression=condition, ExpressionAttributeNames=names,
                                  ExpressionAttributeValues=attrs)
            else:
                # Do not resurrect a deleted deterministic WhatsApp row.
                item = {'id': contact_id, 'contactId': contact_id, 'phone': contact_store.canonical_phone(phone),
                        **subscriber_id.new_contact_fields(now=now), 'createdAt': now, **values}
                try:
                    identity_claims.claim_identities(
                        common.dynamodb.Table(identity_claims.TABLE_NAME),
                        contact_id=contact_id, phone=item['phone'], now=now)
                except identity_claims.IdentityClaimConflict:
                    return _error(
                        data,
                        'Your phone is already linked to another customer profile. '
                        'Close and reopen Subscribe to load the canonical profile.')
                table.put_item(Item=item, ConditionExpression='attribute_not_exists(id)')
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return _error(data, 'Your profile changed. Close and reopen Subscribe before saving again.')
            raise
    saved = table.get_item(Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
    if not contact_store.is_live(saved):
        return _error(data, 'We could not load your saved profile. Please try again.')
    completion = common.record_completion(
        flow_code='WD_SUBSCRIBE', flow_type='subscribe', phone=phone,
        contact_id=contact_id, sender_name=saved.get('name', ''),
        form_data={k: v for k, v in _form(saved, phone).items()
                   if k not in ('profile_revision', 'updated_at', 'error_message', 'country_code')},
        flow_token=flow_token, request_id=request_id, screen='REVIEW',
        reference_prefix='WD-SUB', requires_payment=False, payment_amount=0, status='completed')
    if completion.error:
        # Contact save succeeded; retry can finish the submission without repeating the update.
        return _error(data, 'Your details were saved, but confirmation is pending. Please tap Save details again.')
    return {'screen': 'COMPLETE', 'data': {'customer_id': customer_uuid.display_code(saved),
            'message': subscribe_messages.copy_for(returning)['confirmation']}}
