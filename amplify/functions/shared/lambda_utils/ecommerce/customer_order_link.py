"""Attach historical orders only after a verified contact/account binding exists."""
from boto3.dynamodb.conditions import Attr, Key
from lambda_utils import contact_key, customer_auth
from lambda_utils.comms.numbers import to_e164
from lambda_utils.ecommerce import order_keys
from lambda_utils.identity import customer_uuid


def _bound(contact, customer_id):
    return (customer_auth.is_cognito_subject(customer_id)
        and contact.get('checkoutCustomerId') == customer_id
        and contact.get('deletedAt') is None and not contact.get('isDeleted')
        and bool(contact_key.resolve(contact)) and bool(to_e164(contact.get('phone'))))


def _sync_attempt(attempts, row):
    """Best-effort projection repair; the scheduled sweep retries any transient failure."""
    if (attempts is None or not row.get('paymentAttemptId')
            or not row.get('providerPaymentId') or not row.get('orderId')):
        return False
    try:
        attempts.update_item(
            Key={'paymentAttemptId': row['paymentAttemptId']},
            UpdateExpression='SET finalizationStage = :done',
            ConditionExpression=(
                'status = :paid AND orderId = :order AND verifiedProviderPaymentId = :provider '
                'AND (finalizationStage = :waiting OR finalizationStage = :done)'),
            ExpressionAttributeValues={
                ':done': 'ORDER_FINALIZED', ':waiting': 'NEEDS_CUSTOMER_LINK',
                ':paid': 'PAYMENT_PAID', ':order': row['orderId'],
                ':provider': row['providerPaymentId'],
            })
        return True
    except Exception:
        # Never turn a successful contact/order ownership write into a failed profile save.
        # The five-minute reconciler scans finalized orders too and retries this exact repair.
        return False


def _promote(orders, row, contact, customer_id, attempts=None):
    contact_id = contact_key.resolve(contact)
    if (not _bound(contact, customer_id) or row.get('contactId') != contact_id
            or row.get('paymentStatus') != 'PAYMENT_PAID'
            or not row.get('paymentAttemptId') or not row.get('providerPaymentId')):
        return False

    promoted = False
    if row.get('customerId') == contact_id and row.get('finalizationStage') == 'NEEDS_CUSTOMER_LINK':
        values = {':owner': customer_id, ':contact': contact_id,
            ':waiting': 'NEEDS_CUSTOMER_LINK', ':done': 'ORDER_FINALIZED',
            ':paid': 'PAYMENT_PAID', ':attempt': row['paymentAttemptId'], ':provider': row['providerPaymentId']}
        update = 'SET customerId = :owner, finalizationStage = :done'
        public_uuid = customer_uuid.from_contact(contact)
        if public_uuid:
            update += ', customerUuid = :uuid'
            values[':uuid'] = public_uuid
        try:
            orders.update_item(Key={'orderId': row['orderId']}, UpdateExpression=update,
                ConditionExpression=('contactId = :contact AND customerId = :contact '
                    'AND finalizationStage = :waiting AND paymentStatus = :paid '
                    'AND paymentAttemptId = :attempt AND providerPaymentId = :provider'),
                ExpressionAttributeValues=values)
            promoted = True
            row = {**row, 'customerId': customer_id, 'finalizationStage': 'ORDER_FINALIZED'}
            if public_uuid:
                row['customerUuid'] = public_uuid
        except Exception as error:
            if not order_keys.is_conditional_failure(error):
                raise
            return False
    elif not (row.get('customerId') == customer_id
              and row.get('finalizationStage') == 'ORDER_FINALIZED'):
        return False

    _sync_attempt(attempts, row)
    return promoted


def link(*, orders, contact, customer_id, attempts=None):
    """Promote eligible orders and keep their paid-attempt projection stage aligned."""
    if not _bound(contact, customer_id):
        return 0
    count = 0
    kwargs = {'IndexName': 'customerPhone',
        'KeyConditionExpression': Key('customerPhone').eq(to_e164(contact['phone'])), 'Limit': 100}
    while True:
        page = orders.query(**kwargs)
        for row in page.get('Items') or []:
            count += int(_promote(orders, row, contact, customer_id, attempts=attempts))
        last = page.get('LastEvaluatedKey')
        if not last:
            return count
        kwargs['ExclusiveStartKey'] = last


def reconcile(*, orders, contacts, attempts=None):
    """Scheduled repair covers index lag and profile/projection races. No payment or send.

    The profile role cannot scan. Only the existing private webhook worker runs this
    pending-only scan; contact reads are consistent and every ownership write is conditional.
    """
    return reconcile_metrics(orders=orders, contacts=contacts, attempts=attempts)['promoted']


def reconcile_metrics(*, orders, contacts, attempts=None, now=None):
    """`reconcile`, but returning the operational metrics a scheduled sweep should publish.

    A sweep can run green while business work piles up or quietly fails, which is the blind spot
    this closes. Returns:
      - `promoted`:        orders linked to their account THIS run (what `reconcile` returned).
      - `pendingRemaining`: orders still at NEEDS_CUSTOMER_LINK after the run (the backlog).
      - `oldestPendingAgeSeconds`: age of the oldest still-pending order, 0 if none - a backlog
        that is small but OLD is a different problem from one that is large and fresh.
      - `failures`:        rows a promotion attempt RAISED on (not a conditional no-op, which is
        normal) - a genuine error worth an alarm.

    Behaviour of the scan/promote is unchanged; this only also counts what it already walks, so a
    caller can emit the four as CloudWatch metrics without a second pass over the table.
    """
    import time as _time
    now = int(now if now is not None else _time.time())
    promoted = 0
    failures = 0
    pending_remaining = 0
    oldest_created = None
    fields = ['orderId', 'contactId', 'customerId', 'paymentStatus', 'finalizationStage',
              'paymentAttemptId', 'providerPaymentId', 'createdAt']
    # Include finalized rows too so a transient PaymentAttempt sync failure self-heals on the
    # scheduled sweep. Pending/backlog metrics below still count NEEDS_CUSTOMER_LINK rows only.
    kwargs = {'FilterExpression': (Attr('finalizationStage').eq('NEEDS_CUSTOMER_LINK')
                                  | Attr('finalizationStage').eq('ORDER_FINALIZED')),
        'ProjectionExpression': ', '.join(fields), 'Limit': 100, 'ConsistentRead': True}
    while True:
        page = orders.scan(**kwargs)
        for row in page.get('Items') or []:
            cid = row.get('contactId')
            if not cid:
                pending_remaining += 1
                oldest_created = _min_created(oldest_created, row)
                continue
            contact = contacts.get_item(Key={'id': cid}, ConsistentRead=True).get('Item') or {}
            try:
                linked = _promote(orders, row, contact,
                                  str(contact.get('checkoutCustomerId') or ''),
                                  attempts=attempts)
            except Exception:  # noqa: BLE001 - a raised promotion is a failure to COUNT, not swallow silently
                failures += 1
                pending_remaining += 1
                oldest_created = _min_created(oldest_created, row)
                continue
            if linked:
                promoted += 1
            elif row.get('finalizationStage') == 'NEEDS_CUSTOMER_LINK':
                # Still pending: no account linked yet (the common, benign case), or ineligible.
                pending_remaining += 1
                oldest_created = _min_created(oldest_created, row)
        last = page.get('LastEvaluatedKey')
        if not last:
            break
        kwargs['ExclusiveStartKey'] = last
    oldest_age = max(0, now - int(oldest_created)) if oldest_created is not None else 0
    return {'promoted': promoted, 'pendingRemaining': pending_remaining,
            'oldestPendingAgeSeconds': oldest_age, 'failures': failures}


def _min_created(current, row):
    """The smaller (older) createdAt between the running minimum and a row, ignoring junk."""
    try:
        value = int(row.get('createdAt'))
    except (TypeError, ValueError):
        return current
    return value if current is None else min(current, value)
