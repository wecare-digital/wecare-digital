"""Live Apollo reads using an explicitly delegated business grant and encrypted custody."""
from __future__ import annotations

import datetime as dt
from email.utils import getaddresses, parseaddr
import re
import time

import boto3

from .apollo_client import ApolloClient, ApolloSessionExpired, ApolloUnavailable
from .apollo_session import MAILBOX, SessionResult, advance_session, invalidate_session
from .gmail_otp import GmailApi, GMAIL_ROOT, MailboxAccessRequired
from .session_store import EncryptedSessionStore

GMAIL_PROVIDER = 'google-gmail-apollo'


class ProviderSetupRequired(RuntimeError):
    pass


def choices(rows, kind):
    if not isinstance(rows, list):
        raise ApolloUnavailable('Provider catalogue response invalid')
    fields = {'hospitals': ('hospitalId', 'HospitalId', 'hospitalName', 'HospitalName'),
        'specialities': ('specialityId', 'SpecialityId', 'specialityName', 'SpecialityName'),
        'healthChecks': ('healthCheckId', 'HealthCheckId', 'healthCheckName', 'HealthCheckName'),
        'appointmentTypes': ('appointmentId', 'AppointmentId', 'appointmentName', 'AppointmentName')}
    id1, id2, name1, name2 = fields.get(kind, ('id', 'Id', 'name', 'Name'))
    result = []
    seen = set()
    for row in rows[:1000]:
        if not isinstance(row, dict):
            continue
        try:
            identifier = int(row.get(id1, row.get(id2, row.get('id', row.get('Id', 0)))))
        except (ValueError, TypeError):
            continue
        label = str(row.get(name1, row.get(name2, row.get('name', row.get('Name', ''))))).strip()
        if identifier < 0 or (identifier == 0 and kind not in {'minutes', 'hours'}) or not label or len(label) > 200 or identifier in seen:
            continue
        if kind == 'doctors' and label.lower() == 'other':
            continue
        item = {'id': identifier, 'label': label}
        if kind == 'hospitals':
            item['city'] = str(row.get('cityName', row.get('CityName', ''))).strip()[:80]
        result.append(item)
        seen.add(identifier)
    return result


def schedule_dates(rows, now):
    if not isinstance(rows, list):
        raise ApolloUnavailable('Provider schedule response invalid')
    today = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    values = set()
    for row in rows[:1000]:
        text = str(row.get('name', row.get('Name', ''))) if isinstance(row, dict) else str(row)
        for candidate in re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', text):
            try:
                if dt.date.fromisoformat(candidate) >= today:
                    values.add(candidate)
            except ValueError:
                continue
    return sorted(values)


def discover_sender(gmail, requested_at, now):
    """Approve only a unique current-challenge sender under Apollo's domain."""
    if str(gmail(GMAIL_ROOT + '/profile', {}).get('emailAddress', '')).lower() != MAILBOX:
        raise MailboxAccessRequired('The Apollo mailbox authorization does not match')
    listed = gmail(GMAIL_ROOT + '/messages', {'q': f'from:(apollohospitals.com) to:{MAILBOX} after:{requested_at}', 'maxResults': 5})
    senders = set()
    for candidate in list(listed.get('messages', []))[:5]:
        identifier = str(candidate.get('id', ''))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier):
            continue
        message = gmail(GMAIL_ROOT + '/messages/' + identifier, {'format': 'metadata'})
        try:
            received = int(message.get('internalDate', 0)) // 1000
        except (ValueError, TypeError):
            continue
        if not requested_at <= received <= now or now - received > 300:
            continue
        headers = {str(h.get('name', '')).lower(): str(h.get('value', '')) for h in message.get('payload', {}).get('headers', [])[:100]}
        sender = parseaddr(headers.get('from', ''))[1].lower()
        recipients = {address.lower() for _, address in getaddresses([headers.get('to', '')])}
        if (MAILBOX in recipients and re.fullmatch(r'[^\s@]+@(?:[a-z0-9-]+\.)*apollohospitals\.com', sender)
                and re.search(r'otp|one.time.password|verification', headers.get('subject', ''), re.I)):
            senders.add(sender)
    return next(iter(senders)) if len(senders) == 1 else ''


class ProviderRuntime:
    def __init__(self, *, table=None, oauth=None, kms=None, clock=time.time):
        import os
        if oauth is None:
            import workspace_tokens
            oauth = workspace_tokens
        self.oauth = oauth
        self.table = table if table is not None else self.oauth.table()
        self.clock = clock
        key = os.environ['TOKEN_KEY']
        self.store = EncryptedSessionStore(self.table, kms or boto3.client('kms', region_name='us-east-1'),
            key_arn=key, record_key='arogya:provider:apollo', clock=clock)

    def connect(self):
        binding = self.table.get_item(Key={'pk': 'arogya:provider:gmail'}, ConsistentRead=True).get('Item', {})
        credential_row = self.table.get_item(Key={'pk': 'arogya:provider:credentials'}, ConsistentRead=True).get('Item', {})
        owner = binding.get('owner', '')
        if (not re.fullmatch(r'[a-f0-9]{64}', owner) or binding.get('provider') != GMAIL_PROVIDER
                or binding.get('expectedMailbox') != MAILBOX or credential_row.get('owner') != owner or not credential_row.get('cipher')
                or not binding.get('revision') or credential_row.get('revision') != binding.get('revision')):
            raise ProviderSetupRequired('Apollo business service setup is required')
        config = self.oauth.decrypt(credential_row['cipher'], owner, GMAIL_PROVIDER)
        if config.get('username') != MAILBOX or not config.get('password') or not config.get('applicationHeader'):
            raise ProviderSetupRequired('Apollo account configuration requires attention')
        provider = ApolloClient(config['applicationHeader'])
        gmail = GmailApi(lambda: self.oauth.token(owner, GMAIL_PROVIDER))
        now = int(self.clock())
        state = self.store.read()
        sender = str(binding.get('apolloOtpSender', ''))
        if (not sender and state.get('stage') == 'awaiting_otp' and type(state.get('requestedAt')) is int
                and 0 <= now - int(state.get('requestedAt', 0)) <= 300):
            if state.get('nextPollAt', 0) > now:
                return provider, SessionResult('renewing', retry_after=3)
            sender = discover_sender(gmail, int(state['requestedAt']), now)
            if not sender:
                return provider, SessionResult('renewing', retry_after=3)
            self.table.update_item(Key={'pk': 'arogya:provider:gmail'},
                UpdateExpression='SET apolloOtpSender = :sender', ConditionExpression='#owner = :owner AND revision = :revision',
                ExpressionAttributeNames={'#owner': 'owner'}, ExpressionAttributeValues={':sender': sender, ':owner': owner, ':revision': binding['revision']})
        result = advance_session(store=self.store, provider=provider, gmail_get=gmail,
            credentials=lambda: config, approved_sender=sender, now=now)
        return provider, result

    def read(self, body):
        provider, session = self.connect()
        if session.status != 'ready':
            return {'status': 'renewing', 'retryAfter': max(2, session.retry_after)}
        kind = body.get('kind')
        try:
            if kind == 'bootstrap':
                data = {name: choices(provider.catalog(name, token=session.token), name)
                    for name in ('hospitals', 'appointmentTypes', 'salutations', 'hours', 'minutes')}
            elif kind in {'specialities', 'healthChecks', 'doctors'}:
                data = {'options': choices(provider.catalog(kind, token=session.token,
                    hospital_id=body.get('hospitalId'), speciality_id=body.get('specialityId')), kind)}
            elif kind == 'dates':
                data = {'dates': schedule_dates(provider.available_dates(body.get('appointmentKind'), token=session.token,
                    hospital_id=body.get('hospitalId'), item_id=body.get('itemId')), int(self.clock()))}
            else:
                raise ValueError('Unknown appointment catalogue resource')
        except ApolloSessionExpired:
            invalidate_session(self.store, session.token, now=int(self.clock()))
            return {'status': 'renewing', 'retryAfter': 3}
        return {'status': 'ready', 'data': data, 'observedAt': int(self.clock())}
