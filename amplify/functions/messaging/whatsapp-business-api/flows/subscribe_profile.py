"""Subscribe draft: one customer profile/address; never changes channel consent."""
import time
import uuid
from botocore.exceptions import ClientError
from lambda_utils import contact_store
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer_uuid, subscriber_id
from flows import common

PROFILE_FIELDS = {'full_name': 'name', 'email_address': 'email',
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
    return {'phone_number': contact_store.canonical_phone(phone),
            'customer_id': customer_uuid.display_code(row) or 'Assigned when you save',
            **{key: str(row.get(attr) or '') for key, attr in PROFILE_FIELDS.items()},
            **{key: str(address.get(attr) or '') for key, attr in ADDRESS_FIELDS.items()},
            'profile_revision': str(row.get('subscribeProfileRevision') or ''),
            'updated_at': str(row.get('updatedAt') or ''), 'error_message': ''}


def handle_init(data, flow_token, request_id):
    _table, phone, row = _context(flow_token)
    values = _form(row, phone)
    values['country'] = values['country'] or 'India'
    values['country_code'] = values['country_code'] or 'IN'
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
    raw_address = {attr: data.get(key, '') for key, attr in ADDRESS_FIELDS.items()}
    # Country defaults alone do not make an address. Partial addresses fail validation.
    has_address = any(raw_address[k] for k in ('addressLine1', 'addressLine2', 'locality',
                                              'city', 'state', 'postalCode'))
    now = int(time.time())
    if has_address:
        try:
            address = contact_address.normalize_for_storage(raw_address)
        except contact_address.UnusableAddress as exc:
            return _error(data, 'Please complete your address: ' + (exc.field or 'check the address fields') + '.')
        values.update(contact_address.contact_write_fields(address, now=now))
    contact_id = str(row.get('id') or contact_store.deterministic_id(phone))
    if row.get('subscribeLastFlowToken') != flow_token:
        values.update({'updatedAt': now, 'subscribeProfileRevision': str(uuid.uuid4()),
                       'subscribeLastFlowToken': flow_token})
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
                table.put_item(Item=item, ConditionExpression='attribute_not_exists(id)')
        except ClientError as exc:
            if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
                return _error(data, 'Your profile changed. Close and reopen Subscribe before saving again.')
            raise
    saved = table.get_item(Key={'id': contact_id}, ConsistentRead=True).get('Item') or {}
    if not contact_store.is_live(saved):
        return _error(data, 'We could not load your saved profile. Please try again.')
    completion = common.record_completion(
        flow_code='WD_SUBSCRIBE', flow_type='profile_update', phone=phone,
        contact_id=contact_id, sender_name=saved.get('name', ''),
        form_data={k: v for k, v in data.items() if k not in ('profile_revision', 'updated_at', 'error_message')},
        flow_token=flow_token, request_id=request_id, screen='REVIEW',
        reference_prefix='WD-SUB', requires_payment=False, payment_amount=0, status='completed')
    if completion.error:
        # Contact save succeeded; retry can finish the submission without repeating the update.
        return _error(data, 'Your details were saved, but confirmation is pending. Please tap Save details again.')
    return {'screen': 'COMPLETE', 'data': {'customer_id': customer_uuid.display_code(saved),
            'message': 'Your customer details and address are saved. Your subscription preferences have not changed.'}}
