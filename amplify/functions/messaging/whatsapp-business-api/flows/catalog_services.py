"""Vault purchase over WhatsApp: document list, ₹49 payment request, paid-file refresh.

Internal invocation only; rollout defaults off (WHATSAPP_CATALOG_SERVICES_ENABLED).

Entry points
------------
* ``start``  - the inbound worker, for a cart that is exactly one Vault line or for the "vault"
  keyword. Both are signed inbound messages, so commerce's identity bridge can prove the
  customer from them. Lists the customer's documents.
* ``select`` - the customer's pick from that list. A paid file with access left gets the Access
  Vault link again at no charge; an unpaid file, or a paid one whose every window has been used,
  gets ONE priced Review and Pay.
* ``sendOffer`` - secure-files, when staff press "Send ₹49 Vault message" for one file. Sends the
  approved offer `wecare_vault_request_ready` ("📄 Your requested <document> is available in your Vault. Amount due for this request: ₹49.") whose "Unlock
  Vault" quick reply carries an opaque offer token. It charges nothing and needs no linked
  contact: the customer is proven from the tap.
* ``unlock`` - the inbound worker, for a tap on "Unlock Vault". The tap is a signed inbound
  message, so commerce's bridge proves the customer from it exactly as for a cart. The offer's
  file gets ONE Review and Pay (or the Access Vault link if already paid). An unknown, expired or
  someone else's offer falls back to ``start``: the customer's own document list.

It never prices, reserves or sends a payment itself: it hands ONE session to `wecare-commerce`
`prepareNativeCatalogService`. See `catalog_service_checkout.ALLOWED` for why only Vault is sold
here.
"""
import json
import os
import re
import secrets
import time
import boto3
from lambda_utils import contact_key, contact_store, customer_auth, shared_tables, whatsapp_templates
from lambda_utils.identity import customer as customer_identity
from lambda_utils.ecommerce import (catalog_service_checkout as catalog, service_request_store as store,
                                    service_requests, vault_access as vault, vault_window)

REQUESTS_TABLE = 'stack-wecare-digital-ServiceRequestsTable'
_FILE_ID = re.compile(r'[A-Za-z0-9_-]{1,120}')

#: Refusals commerce returns BEFORE its one-shot `nativePrepareClaim`: nothing was reserved or
#: sent, so the session can be closed and the customer may simply try again.
_NOT_PREPARED = frozenset({
    'WHATSAPP_IDENTITY_REQUIRED', 'PAYMENT_SENDER_NOT_PERMITTED',
    'CATALOG_SERVICE_INTENT_UNAVAILABLE', 'CATALOG_SERVICE_UNAVAILABLE',
    'NATIVE_SERVICE_ROLLOUT_DISABLED', 'NATIVE_SERVICE_META_NOT_READY',
    'NATIVE_SERVICE_WRITEBACK_NOT_READY',
})
#: `_create` answers that leave no payable message on the customer's phone.
_NOT_SENT = _NOT_PREPARED | {'PAYMENT_REQUEST_NOT_SENT', 'PAYMENT_REQUEST_REFUSED',
                             'PAYMENT_INITIATION_DISABLED'}

_TITLE_PREFIX = {'OPEN': 'Paid · ', 'READY': 'Paid · ', 'EXPIRED': 'Renew · ', 'UNPAID': ''}

#: One Vault offer per row, keyed by its token. The token is what the quick reply returns; the
#: row binds it to one file, its owner and the number it was sent to.
OFFER_PREFIX = 'VAULTOFFER#'
#: Per-file guard row, so a double click does not send the same customer two offers in a row.
OFFER_FILE_PREFIX = 'VAULTOFFERFILE#'
#: An offer older than this is answered with the document list instead, which is still a path to
#: the same Review and Pay.
OFFER_TTL_SECONDS = 7 * 24 * 3600
OFFER_RESEND_GUARD_SECONDS = 60
OFFER_FILE_GONE = ('This document is no longer available. Nothing has been charged. '
                   'Send "Vault" to see your documents.')


def _invoke(client, function, payload):
    result = client.invoke(FunctionName=function, InvocationType='RequestResponse',
                           Payload=json.dumps(payload).encode())
    answer = json.loads(result['Payload'].read())
    if result.get('FunctionError'):
        raise RuntimeError('downstream invocation failed')
    return answer


def _send(client, row, **body):
    return _invoke(client, 'wecare-outbound-whatsapp:live', {'body': json.dumps({
        'contactId': row['contactId'], 'recipientPhone': row['phone'],
        'phoneNumberId': row['phoneNumberId'], **body})})


def _send_access(client, row, file_id):
    """The Access Vault template again. Never a charge; the window opens on the next download."""
    response = _send(client, row, **whatsapp_templates.download_send_fields(file_id))
    code = int(response.get('statusCode', 500)) if isinstance(response, dict) else 500
    return {'outcome': 'VAULT_ACCESS_REFRESH_SENT' if 200 <= code < 300 else 'VAULT_ACCESS_REFRESH_PENDING',
            'fileId': file_id}


def readiness(graph):
    """Live Meta readback of the two templates a Vault purchase needs. Reads only."""
    templates = {}
    for name, ident in {'wecare_whatapp_native_pay_template': '2714938845570815',
                        'wecare_default_download': '1410998911012572'}.items():
        info = graph(ident, params={'fields': 'id,name,status,language,components'})
        templates[name] = {k: info.get(k) for k in ('id', 'name', 'status', 'language', 'components', 'error')}
    return {'templates': templates}


IDENTITY_NOT_READY = (
    'We could not verify this WhatsApp checkout safely. Nothing has been charged. '
    'Please send the catalog item again or contact support.'
)
NOT_REQUESTED = ('This document cannot be paid for right now. No payment has been requested. '
                 'Please try again later.')


def _entitlement(db, file, customer_id):
    """The file's durable VAULT_ENTITLEMENT for this customer, or None."""
    eid = 'vault-entitlement#' + str(customer_id) + '#' + str(file.get('fileId') or '')
    row = db.Table(vault.GRANTS_TABLE).get_item(Key={'grantId': eid}, ConsistentRead=True).get('Item') or {}
    if (row.get('recordType') == 'VAULT_ENTITLEMENT' and row.get('entitlementState') == 'ACTIVE'
            and row.get('customerId') == customer_id and row.get('fileId') == file.get('fileId')):
        return row
    return None


def _file_state(db, file, customer_id, now):
    """`vault_window.access_state` for one owned file, or '' when it can be neither sold nor sent.

    ``UNPAID`` and ``EXPIRED`` may be sold; ``OPEN`` and ``READY`` get the link again for free.
    A paid file whose entitlement row is missing is a legacy grant the Vault page migrates on
    open, so it is ``READY`` rather than sold twice. A grant pointer with no payment is
    inconsistent state that staff reconcile, so it is offered as neither.
    """
    access_id = str(file.get('vaultEntitlementId') or file.get('vaultAccessGrantId') or '')
    paid = file.get('vaultPaymentStatus') == 'PAID'
    if not access_id and not paid:
        return 'UNPAID'
    if not (access_id and paid):
        return ''
    entitlement = _entitlement(db, file, customer_id)
    return vault_window.access_state(entitlement, now) if entitlement else 'READY'


def _payment_outcome(result):
    """One word for what commerce's prepare did, from its two answer shapes."""
    if not isinstance(result, dict):
        return 'PAYMENT_REQUEST_UNCONFIRMED'
    if result.get('outcome'):
        return str(result['outcome'])
    code = int(result.get('statusCode') or 0)
    try:
        body = json.loads(result.get('body') or '{}')
    except (TypeError, ValueError):
        body = {}
    if code == 200:
        return str(body.get('status') or 'PAYMENT_REQUEST_SENT')
    if code == 502:
        return 'PAYMENT_REQUEST_UNCONFIRMED' if body.get('sendUnconfirmed') else 'PAYMENT_REQUEST_NOT_SENT'
    return 'PAYMENT_REQUEST_REFUSED'


def _close(keys, row, customer_id):
    """Release the customer's purchase lock and retire the session. Best effort, never raises.

    Called only when nothing payable can have reached the customer, so a retry starts clean
    instead of being told for an hour that a payment is "already in progress".
    """
    try:
        keys.update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + customer_id},
            UpdateExpression='SET #s=:closed', ConditionExpression='sessionKey=:session',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':closed': 'CLOSED', ':session': row['orderId']})
    except Exception:  # noqa: BLE001 - a lock someone else now holds is not ours to close
        pass
    try:
        keys.update_item(Key={'orderId': row['orderId']},
            UpdateExpression='SET #s=:closed',
            ConditionExpression='attribute_not_exists(paymentAttemptId)',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':closed': 'CLOSED_UNPAID'})
    except Exception:  # noqa: BLE001
        pass


def handle(event, client):
    if any(event.get(k) for k in ('requestContext', 'rawPath', 'path', 'httpMethod')):
        return {'statusCode': 403, 'error': 'Internal invocation required'}
    if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true':
        return {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}
    db = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    keys = db.Table('stack-wecare-digital-CommerceKeys')
    contacts = db.Table(shared_tables.contacts_table_name())
    now = int(time.time())
    action = event.get('action', 'start')

    if action == 'sendOffer':
        return _send_offer(event, client, db, keys, contacts, now)
    # Answered before any read: an unknown action (such as the retired `requestPayment`) or a
    # customer action without its contact used to reach `get_item` with an empty key and crash.
    if action not in ('start', 'select', 'unlock'):
        return {'outcome': 'CATALOG_ACTION_UNAVAILABLE'}
    if not event.get('contactId'):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}

    contact = contacts.get_item(Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
    # Outbound resolves only our Direct-API sender ids; the bare Meta phone id is refused.
    sender = {'contactId': contact.get('id', ''), 'phone': event.get('senderPhone', ''),
              'phoneNumberId': event.get('phoneNumberId') or os.environ.get(
                  'WHATSAPP_PHONE_NUMBER_ID_1', 'phone-number-id-waba1-direct-1016149501586345')}

    if action == 'select':
        # Selection is authorized by the already-created, high-entropy session token. Identity
        # provisioning happened only on the signed cart message that created this session.
        token = str(event.get('token') or '')
        session = keys.get_item(
            Key={'orderId': catalog.SESSION_PREFIX + token}, ConsistentRead=True
        ).get('Item') or {}
        owner = str(session.get('customerId') or '')
        number = str(session.get('phone') or '')
        try:
            # senderPhone is Meta's bare wa_id (country code, no `+`); see
            # checkout._native_whatsapp_identity for why canonicalising it guesses nothing.
            event_phone = customer_identity.normalize_phone_preserving_country(
                contact_store.canonical_phone(event.get('senderPhone')))
            session_phone = customer_identity.normalize_phone_preserving_country(
                contact_store.canonical_phone(number))
        except customer_identity.InvalidPhoneNumber:
            event_phone = session_phone = ''
        if (not customer_auth.is_cognito_subject(owner)
                or not event_phone or event_phone != session_phone
                or str(session.get('contactId') or '') != str(contact.get('id') or '')
                or str(contact.get('checkoutCustomerId') or '') != owner):
            _send(client, sender, content=IDENTITY_NOT_READY)
            return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
        identity = customer_auth.CustomerIdentity(
            customer_id=owner, subject=owner, phone=session_phone, phone_verified=True)
    else:
        # Native WhatsApp payment identity is established from the signed cart message, not a
        # browser session. Commerce owns the bridge to the dedicated registration function, so
        # this shared business-api role never gains customer-pool provisioning rights.
        try:
            resolved = _invoke(client, 'wecare-commerce:live', {
                'internalAction': 'ensureNativeWhatsAppIdentity',
                'contactId': contact.get('id', ''),
                'senderPhone': event.get('senderPhone', ''),
                'sourceMessageId': event.get('sourceMessageId', ''),
                'phoneNumberId': sender['phoneNumberId'],
            })
        except Exception:
            resolved = {}
        if resolved.get('outcome') != 'WHATSAPP_IDENTITY_READY':
            _send(client, sender, content=IDENTITY_NOT_READY)
            return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
        owner = str(resolved.get('customerId') or '')
        number = str(resolved.get('phone') or '')
        if not customer_auth.is_cognito_subject(owner) or not number:
            _send(client, sender, content=IDENTITY_NOT_READY)
            return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}
        identity = customer_auth.CustomerIdentity(
            customer_id=owner, subject=owner, phone=number, phone_verified=True)
        # Re-read because the bridge may have attached checkoutCustomerId to this row.
        contact = contacts.get_item(
            Key={'id': event.get('contactId', '')}, ConsistentRead=True).get('Item') or {}
        if str(contact.get('checkoutCustomerId') or '') != owner:
            _send(client, sender, content=IDENTITY_NOT_READY)
            return {'outcome': 'WHATSAPP_IDENTITY_REQUIRED'}

    if action == 'unlock':
        offer = _live_offer(keys, event.get('offerToken'), identity, now)
        if offer:
            return _unlock(event, client, db, keys, contact, identity, offer, now)
        # An unknown, expired or someone else's offer: this customer's own document list, exactly
        # as the "Vault" keyword gives. Nothing is charged either way.
        action = 'start'

    if action == 'start':
        choice = catalog.service_from_lines(event.get('lines') or [])
        if not choice or not event.get('sourceMessageId'):
            return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
        # Source message owns exactly one session. Replay never creates another payment.
        index_key = 'CATALOGSERVICEMSG#' + event['sourceMessageId']
        token = secrets.token_urlsafe(24)
        try:
            keys.put_item(Item={'orderId': index_key, 'token': token},
                          ConditionExpression='attribute_not_exists(orderId)')
        except Exception as error:
            if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                return {'outcome': 'CATALOG_SERVICE_REPLAY'}
            raise
        row = {'orderId': catalog.SESSION_PREFIX + token, 'token': token, **choice,
               'contactId': contact['id'], 'phone': identity.phone, 'customerId': identity.customer_id,
               'phoneNumberId': event['phoneNumberId'], 'sourceMessageId': event['sourceMessageId'],
               'createdAt': now, 'expiresAt': now + 3600, 'status': 'SELECTING'}
        files = db.Table(vault.FILES_TABLE)
        projected = files.query(IndexName='owner-created-index',
            KeyConditionExpression='ownerPhone=:p', ExpressionAttributeValues={':p': identity.phone.lstrip('+')},
            Limit=100, ScanIndexForward=False).get('Items') or []
        choices = []
        for item in projected:
            file = files.get_item(Key={'fileId': item['fileId']}, ConsistentRead=True).get('Item') or {}
            # Only files already bound to this customer. `vault.bind_file` refuses an ownerless
            # legacy file (a reassigned phone must not inherit it), so listing one offered a
            # choice that could only fail after the customer picked it.
            if (file.get('status') != 'active' or file.get('ownerPhone') != identity.phone.lstrip('+')
                    or file.get('ownerCustomerId') != identity.customer_id):
                continue
            state = _file_state(db, file, identity.customer_id, now)
            if state:
                choices.append((file, state))
        if not choices:
            row['status'] = 'AWAITING_FILE'
            keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
            _send(client, row, content='No Vault documents are currently available for this verified account. No payment has been requested.')
            return {'outcome': 'VAULT_FILE_NOT_READY'}
        # At most ten choices per native list. Paid rows remain visible as refresh actions and
        # used-up rows as renewals.
        row['fileChoices'] = [file['fileId'] for file, _state in choices[:10]]
        row['fileChoiceStates'] = [state for _file, state in choices[:10]]
        keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
        hours = vault_window.window_hours()
        _send(client, row, isInteractive=True, interactiveType='list', interactiveData={
            'body': ('Choose a document. Paid documents download again at no charge. '
                     f'Renew opens a new {hours}-hour access window.'),
            'button': 'Choose document', 'sections': [{'title': 'Your documents', 'rows': [
                {'id': 'vaultpick:' + token + ':' + str(i),
                 'title': (_TITLE_PREFIX.get(state, '') + str(file.get('displayName') or file.get('originalFilename') or 'Document'))[:24]}
                for i, (file, state) in enumerate(choices[:10])]}]})
        return {'outcome': 'VAULT_FILE_SELECTION_SENT'}
    if action != 'select':
        return {'outcome': 'CATALOG_ACTION_UNAVAILABLE'}

    try:
        row = catalog.selected_session(keys, event.get('token', ''), contact['id'], identity.phone, now)
    except customer_auth.CustomerNotAuthorized:
        # A tap on a list whose session expired (one hour) or belongs to someone else.
        _send(client, {**sender, 'phone': identity.phone},
              content='This document list has expired. Nothing has been charged. Please send the Vault item from the catalog again.')
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    index = event.get('fileIndex')
    if (row.get('customerId') != identity.customer_id or row['kind'] != 'VAULT' or row.get('status') != 'SELECTING' or type(index) is not int
            or not 0 <= index < len(row.get('fileChoices') or [])):
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    try:
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['fileChoices'][index])
    except customer_auth.CustomerNotAuthorized:
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    # Decided now, not from the list: a window may have closed (or been paid) since it was sent.
    state = _file_state(db, file, identity.customer_id, now)
    if state in ('OPEN', 'READY'):
        return _send_access(client, row, file['fileId'])
    if state not in ('UNPAID', 'EXPIRED'):
        _send(client, row, content=NOT_REQUESTED)
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    row['vaultFileId'] = file['fileId']
    return _prepare_payment(client, db, keys, row, identity, state, notify=True)


def _conditional_failed(error):
    return getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException'


def _vault_session(event, identity, contact, file_id, now):
    """A one-file SELECTING session for the tapped offer, in the shape `_prepare_payment` and
    commerce's prepare read. `sourceMessageId` is the tap, so commerce re-proves the customer
    from the same signed message."""
    variant = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
    token = secrets.token_urlsafe(24)
    return {'orderId': catalog.SESSION_PREFIX + token, 'token': token, 'kind': service_requests.VAULT,
            'variantId': variant, 'productId': service_requests.SERVICE_PRODUCT_BY_VARIANT[variant],
            'contactId': contact['id'], 'phone': identity.phone, 'customerId': identity.customer_id,
            'phoneNumberId': event['phoneNumberId'], 'sourceMessageId': event['sourceMessageId'],
            'createdAt': now, 'expiresAt': now + 3600, 'status': 'SELECTING',
            'fileChoices': [file_id], 'origin': 'VAULT_OFFER'}


def _live_offer(keys, token, identity, now):
    """The offer this tap names, or None when it is unknown, expired or not this customer's."""
    token = str(token or '')
    if not catalog.OFFER_TOKEN_RE.fullmatch(token):
        return None
    offer = keys.get_item(Key={'orderId': OFFER_PREFIX + token}, ConsistentRead=True).get('Item') or {}
    if (offer.get('kind') != 'VAULT_OFFER' or int(offer.get('expiresAt') or 0) <= now
            or offer.get('ownerCustomerId') != identity.customer_id
            or offer.get('phone') != identity.phone):
        return None
    return offer


def _unlock(event, client, db, keys, contact, identity, offer, now):
    """"Unlock Vault" on one offer: Review and Pay for its file, or the link if already paid."""
    if not event.get('sourceMessageId') or not event.get('phoneNumberId'):
        return {'outcome': 'CATALOG_SERVICE_UNAVAILABLE'}
    # The tap owns exactly one session. A replayed webhook never creates a second payment.
    try:
        keys.put_item(Item={'orderId': 'CATALOGSERVICEMSG#' + event['sourceMessageId'],
                            'offerKey': offer['orderId']},
                      ConditionExpression='attribute_not_exists(orderId)')
    except Exception as error:
        if _conditional_failed(error):
            return {'outcome': 'CATALOG_SERVICE_REPLAY'}
        raise
    row = _vault_session(event, identity, contact, offer['fileId'], now)
    row['offerKey'] = offer['orderId']
    try:
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, offer['fileId'])
    except customer_auth.CustomerNotAuthorized:
        # Revoked or reassigned since the offer went out.
        row['status'] = 'FILE_UNAVAILABLE'
        keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
        _send(client, row, content=OFFER_FILE_GONE)
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    # Decided now, not when the offer was sent: it may have been paid (or a window may have
    # closed) in between.
    state = _file_state(db, file, identity.customer_id, now)
    row['fileChoiceStates'] = [state]
    keys.put_item(Item=row, ConditionExpression='attribute_not_exists(orderId)')
    if state in ('OPEN', 'READY'):
        return _send_access(client, row, file['fileId'])
    if state not in ('UNPAID', 'EXPIRED'):
        _send(client, row, content=NOT_REQUESTED)
        return {'outcome': 'VAULT_FILE_SELECTION_UNAVAILABLE'}
    row['vaultFileId'] = file['fileId']
    return _prepare_payment(client, db, keys, row, identity, state, notify=True)


def _offer_send_outcome(response):
    """``(outcome, detail)`` for one offer send. ``detail`` carries no customer data."""
    if not isinstance(response, dict):
        return 'VAULT_OFFER_UNCONFIRMED', 'no answer from the sender'
    code = int(response.get('statusCode') or 0)
    try:
        body = json.loads(response.get('body') or '{}')
    except (TypeError, ValueError):
        body = {}
    body = body if isinstance(body, dict) else {}
    if 200 <= code < 300:
        if body.get('status') == 'dry_run' or body.get('mode') == 'DRY_RUN':
            return 'VAULT_OFFER_NOT_SENT', 'the sender is in dry-run mode'
        return 'VAULT_OFFER_SENT', 'sent'
    reason = str(body.get('error') or body.get('message') or '')[:120]
    if 400 <= code < 500:
        # Refused before or by Meta: nothing reached the customer.
        return 'VAULT_OFFER_NOT_SENT', ('HTTP %d %s' % (code, reason)).strip()
    # A 5xx or a timeout can follow an accepted send, so it is never reported as "not sent".
    return 'VAULT_OFFER_UNCONFIRMED', 'HTTP %d' % code


def _send_offer(event, client, db, keys, contacts, now):
    """Staff asked for ₹49 for one file: send the Vault offer (wecare_vault_request_ready). Never charges.

    The offer names the document and carries an opaque token in its "Unlock Vault" quick reply.
    The tap, a signed inbound message, is what proves the customer and opens Review and Pay
    (`unlock`), so no linked contact is needed here. Answers an outcome and never messages the
    customer a refusal.
    """
    file_id = str(event.get('fileId') or '')
    owner = str(event.get('ownerCustomerId') or '')
    owner_phone = ''.join(c for c in str(event.get('ownerPhone') or '') if c in '0123456789')
    if not _FILE_ID.fullmatch(file_id) or not customer_auth.is_cognito_subject(owner) or not owner_phone:
        return {'outcome': 'VAULT_FILE_UNAVAILABLE'}
    file = db.Table(vault.FILES_TABLE).get_item(Key={'fileId': file_id}, ConsistentRead=True).get('Item') or {}
    if (file.get('status') != 'active' or file.get('ownerCustomerId') != owner
            or file.get('ownerPhone') != owner_phone):
        return {'outcome': 'VAULT_FILE_UNAVAILABLE'}
    state = _file_state(db, file, owner, now)
    if state in ('OPEN', 'READY'):
        return {'outcome': 'VAULT_ACCESS_ACTIVE'}
    if state not in ('UNPAID', 'EXPIRED'):
        return {'outcome': 'VAULT_FILE_UNAVAILABLE'}
    phone = '+' + owner_phone
    try:
        contact = contact_store.find_by_phone(contacts, phone)
    except contact_store.IdentityConflict:
        # The tap would fail closed on the same ambiguity, so the offer would be a dead end.
        return {'outcome': 'CONTACT_AMBIGUOUS'}
    try:
        keys.update_item(Key={'orderId': OFFER_FILE_PREFIX + file_id},
                         UpdateExpression='SET lastOfferAt=:now',
                         ConditionExpression='attribute_not_exists(lastOfferAt) OR lastOfferAt < :recent',
                         ExpressionAttributeValues={':now': now,
                                                    ':recent': now - OFFER_RESEND_GUARD_SECONDS})
    except Exception as error:
        if _conditional_failed(error):
            return {'outcome': 'VAULT_OFFER_RECENT'}
        raise
    from lambda_utils.ecommerce import wa_payment_request
    token = secrets.token_urlsafe(24)
    contact_id = contact_key.resolve(contact) if contact else ''
    offer = {'orderId': OFFER_PREFIX + token, 'kind': 'VAULT_OFFER', 'fileId': file_id,
             'ownerCustomerId': owner, 'phone': phone, 'contactId': contact_id,
             'createdAt': now, 'expiresAt': now + OFFER_TTL_SECONDS, 'fileState': state,
             'status': 'SENDING', 'requestedBy': str(event.get('requestedBy') or 'staff')[:64]}
    keys.put_item(Item=offer, ConditionExpression='attribute_not_exists(orderId)')
    # No contact id is fine: outbound resolves or creates the contact from the number.
    recipient = {'contactId': contact_id, 'phone': phone,
                 'phoneNumberId': wa_payment_request.PHONE_NUMBER_ID_1}
    try:
        response = _send(client, recipient, **whatsapp_templates.vault_offer_send_fields(
            file.get('displayName') or file.get('originalFilename'), token))
    except Exception:  # noqa: BLE001 - an invoke failure may follow an accepted send
        response = None
    outcome, detail = _offer_send_outcome(response)
    keys.update_item(Key={'orderId': offer['orderId']}, UpdateExpression='SET #s=:s, sendDetail=:d',
                     ExpressionAttributeNames={'#s': 'status'},
                     ExpressionAttributeValues={':s': outcome, ':d': detail})
    if outcome == 'VAULT_OFFER_NOT_SENT':
        # Nothing reached the customer, so staff may try again straight away.
        try:
            keys.update_item(Key={'orderId': OFFER_FILE_PREFIX + file_id},
                             UpdateExpression='REMOVE lastOfferAt',
                             ConditionExpression='lastOfferAt = :now',
                             ExpressionAttributeValues={':now': now})
        except Exception:  # noqa: BLE001 - a newer offer owns the guard now
            pass
    return {'outcome': outcome, 'fileId': file_id, 'renewal': state == 'EXPIRED', 'detail': detail}


def _prepare_payment(client, db, keys, row, identity, state, *, notify):
    """Lock, freeze the file into a priced intent, and ask commerce for ONE Review and Pay.

    ``notify`` is True when the customer started this in WhatsApp and is waiting for an answer;
    a staff request reports its outcome to staff instead of messaging the customer a refusal.
    """
    now = int(time.time())
    # One outstanding native purchase per permanent customer, even across catalog messages.
    # The lock lives exactly as long as the session it names (its `expiresAt`, one hour after the
    # cart) and no longer: it used to close only on a paid finalisation, so a customer who let
    # one payment request expire unpaid was refused every later service purchase, permanently. A
    # lock with no `activeUntil` predates the expiry and is treated as expired. Checkout refuses
    # an expired session, the ORDER_DETAILS request itself expires after 15 minutes, and
    # `finalizeNativeCatalogService` closes by `sessionKey`, so a late payment cannot release a
    # newer session's lock.
    try:
        keys.update_item(Key={'orderId': 'NATIVESERVICEACTIVE#' + identity.customer_id},
            UpdateExpression='SET #s=:active, sessionKey=:session, activeUntil=:until',
            ConditionExpression=('attribute_not_exists(orderId) OR #s=:closed '
                                 'OR attribute_not_exists(activeUntil) OR activeUntil < :now'),
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':active': 'ACTIVE', ':closed': 'CLOSED',
                                       ':session': row['orderId'],
                                       ':until': int(row.get('expiresAt') or now + 3600),
                                       ':now': now})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            if notify:
                _send(client, row, content='You already have a service payment in progress. Please complete that payment before starting another purchase.')
            return {'outcome': 'NATIVE_SERVICE_PAYMENT_ALREADY_IN_PROGRESS'}
        raise
    # Freeze the intent and selected file before native checkout can reserve any money reference.
    try:
        keys.update_item(Key={'orderId': row['orderId']},
            UpdateExpression='SET #s=:preparing, vaultFileId=:file',
            ConditionExpression='#s=:selecting AND customerId=:owner',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':preparing': 'PREPARING_PAYMENT', ':selecting': 'SELECTING',
                ':owner': identity.customer_id, ':file': row.get('vaultFileId', '')})
    except Exception as error:
        if getattr(error, 'response', {}).get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
            # A second tap on the same list: the first one holds this session and its lock.
            return {'outcome': 'CATALOG_SERVICE_ALREADY_PREPARING'}
        raise
    try:
        file = vault.bind_file(db.Table(vault.FILES_TABLE), identity, row['vaultFileId'])
        # A renewal is sold only against the durable entitlement proving every paid window used.
        entitlement = _entitlement(db, file, identity.customer_id) if state == 'EXPIRED' else None
        intent = store.request_intent(db.Table(REQUESTS_TABLE), identity, row['kind'],
                                      vault_file=file, vault_entitlement=entitlement)
        keys.update_item(Key={'orderId': row['orderId']}, UpdateExpression='SET serviceIntentId=:intent',
                         ExpressionAttributeValues={':intent': intent['intentId']})
    except (service_requests.ServiceRejected, customer_auth.CustomerNotAuthorized,
            store.ServiceIdentityUnavailable) as refused:
        # Nothing priced or reserved yet: close cleanly instead of holding the lock for an hour.
        _close(keys, row, identity.customer_id)
        code = getattr(refused, 'code', '') or type(refused).__name__
        if code in (service_requests.VAULT_ACCESS_ACTIVE, 'VAULT_ALREADY_PAID'):
            # Paid in the meantime: the right answer is the link, never a second charge.
            if notify:
                return {**_send_access(client, row, row['vaultFileId']), 'reason': code}
            return {'outcome': 'VAULT_ACCESS_ACTIVE', 'reason': code}
        if notify:
            _send(client, row, content=NOT_REQUESTED)
        return {'outcome': 'VAULT_PAYMENT_NOT_PREPARED', 'reason': code}
    try:
        result = _invoke(client, 'wecare-commerce:live', {
            'internalAction': 'prepareNativeCatalogService', 'catalogToken': row['token']})
    except Exception:
        # Ambiguous: commerce may already have sent the request. No automatic second attempt
        # after an ambiguous provider send; the lock expires with the session.
        result = {'outcome': 'PAYMENT_REQUEST_UNCONFIRMED'}
    keys.update_item(Key={'orderId': row['orderId']}, UpdateExpression='SET paymentResult=:result',
                     ExpressionAttributeValues={':result': result})
    outcome = _payment_outcome(result)
    if outcome in _NOT_SENT:
        _close(keys, row, identity.customer_id)
        if notify:
            _send(client, row, content=NOT_REQUESTED)
    return {'outcome': outcome, 'fileId': row['vaultFileId'], 'renewal': state == 'EXPIRED'}
