"""Read-only catalogue adapter with explicitly enabled, fenced provider renewal.

An administrator must bind a verified business Gmail grant and configure provider-
approved credentials. No credentials, mail, tokens, patient lookup or booking writes
are exposed to customers. Unknown response schemas fail closed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

from .apollo_client import ApolloClient, ApolloUnavailable, ApolloSessionExpired
from .apollo_session import MAILBOX, ApolloAuthorizationRequired, advance_session, invalidate_session
from .gmail_otp import MailboxAccessRequired, GmailReadUnavailable
from .provider_grant import VerifiedGmailGrant
from .session_store import EncryptedSessionStore, RenewalLeaseLost

RECORD = 'arogya:provider:apollo'
CONTEXT = {'purpose': 'arogya-provider', 'record': RECORD}
FIELDS = {
    'hospitals': (('hospitalid', 'ichospitalid', 'id'), ('hospitalname', 'name')),
    'specialities': (('multispecialityid', 'specialityid', 'specialtyid', 'id'),
                     ('multispecialityname', 'specialityname', 'specialtyname', 'name')),
    'doctors': (('doctorid', 'id'), ('doctorname', 'doctorfullname', 'name')),
    'healthChecks': (('healthcheckid', 'id'), ('healthcheckname', 'name')),
    'appointmentTypes': (('appointmentid', 'appointmenttypeid', 'id'),
                         ('appointmentname', 'appointmenttypename', 'appointmenttype', 'name')),
    'salutations': (('salutationid', 'id'), ('salutationname', 'salutation', 'name')),
}
WRAPPERS = ('data', 'result', 'items', 'hospitals', 'specialities', 'doctors',
            'healthchecks', 'dates', 'appointmentdates', 'availabledates', 'appointmenttypes', 'salutations', 'hours', 'minutes')


class CatalogueUnavailable(RuntimeError):
    pass


class CatalogueRenewing(CatalogueUnavailable):
    def __init__(self, retry_after):
        super().__init__('Apollo catalogue session is being renewed')
        self.retry_after = min(60, max(2, int(retry_after)))


class InvalidCatalogueRequest(ValueError):
    pass


def _rows(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        candidates = [child for key, child in value.items()
                      if key.lower() in WRAPPERS and isinstance(child, (list, dict))]
        if len(candidates) == 1:
            return _rows(candidates[0])
    raise CatalogueUnavailable('Unrecognized Apollo catalogue response')


def _first(row, names):
    return next((row[name] for name in names if name in row), None)


def _identifier(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', value):
        raise InvalidCatalogueRequest('Invalid provider selection')
    return int(value)


def _label(value, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise CatalogueUnavailable('Invalid Apollo catalogue label')
    if any(ord(char) < 32 for char in value):
        raise CatalogueUnavailable('Invalid Apollo catalogue label')
    return value.strip()


def _date(value):
    if isinstance(value, dict):
        value = _first({k.lower(): v for k, v in value.items()},
                       ('appointmentdate', 'availabledate', 'date'))
    if not isinstance(value, str):
        raise CatalogueUnavailable('Invalid Apollo availability date')
    # Date-only values or an exact midnight without an offset (provider-local).
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?', value):
        value = value[:10]
    for pattern in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            parsed = dt.datetime.strptime(value, pattern).date()
            if parsed.strftime(pattern) == value:
                return parsed.isoformat()
        except ValueError:
            continue
    raise CatalogueUnavailable('Unrecognized Apollo availability date')


def normalize(kind, raw, *, now):
    result = {}
    for value in _rows(raw):
        if kind == 'dates':
            today = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()
            # The IC portal reads schedule rows as {id, name}, where name can
            # contain comma-separated ISO dates. Preserve the other accepted
            # date schemas and refuse malformed tokens rather than invent dates.
            candidate = value
            if isinstance(value, dict):
                row = {key.lower(): item for key, item in value.items()}
                if not any(key in row for key in ('appointmentdate', 'availabledate', 'date')) and 'name' in row:
                    candidate = row['name']
                    if candidate in ('', None):
                        continue
            dates = candidate.split(',') if isinstance(candidate, str) else [candidate]
            if len(dates) > 1000:
                raise CatalogueUnavailable('Apollo schedule exceeded limit')
            for item in dates:
                date = _date(item.strip() if isinstance(item, str) else item)
                if date >= today:
                    result[date] = {'id': date, 'label': date}
            continue
        if not isinstance(value, dict):
            raise CatalogueUnavailable('Invalid Apollo catalogue row')
        row = {key.lower(): item for key, item in value.items()}
        ids, labels = FIELDS[kind]
        try:
            identifier = str(_identifier(_first(row, ids)))
        except InvalidCatalogueRequest:
            raise CatalogueUnavailable('Invalid Apollo catalogue identifier') from None
        label = _label(_first(row, labels))
        if kind == 'appointmentTypes':
            canonical = {'consultation': 'Consultation', 'health checks': 'Health Checks',
                         'health check': 'Health Checks', 'admission': 'Admission'}
            label = canonical.get(label.casefold())
            if label is None:
                continue  # only the supported draft workflows are enabled
        if kind == 'salutations':
            canonical = {'master': 'Master', 'mr': 'Mr.', 'mrs': 'Mrs.', 'ms': 'Ms.', 'dr': 'Dr'}
            label = canonical.get(label.casefold().rstrip('.'))
            if label is None:
                continue
        option = {'id': identifier, 'label': label}
        city = _first(row, ('city', 'cityname', 'hospitalcity'))
        if kind == 'hospitals' and city:
            option['city'] = _label(city, 80)
        if identifier in result and result[identifier] != option:
            raise CatalogueUnavailable('Ambiguous Apollo catalogue identifier')
        result[identifier] = option
    return sorted(result.values(), key=lambda item: item['id'] if kind == 'dates' else item['label'].casefold())


def _time_parts(raw, *, hour):
    """Read the provider's time-component choices, not appointment slot inventory."""
    names = ('hour', 'hours', 'hourname', 'ichour', 'ichours', 'value', 'name', 'id') if hour else (
        'minute', 'minutes', 'minutename', 'icminute', 'icminutes', 'value', 'name', 'id')
    options = set()
    for row in _rows(raw):
        value = _first({k.lower(): v for k, v in row.items()}, names) if isinstance(row, dict) else row
        if type(value) is int:
            value = str(value)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,2}', value.strip()):
            raise CatalogueUnavailable('Unrecognized Apollo time choices')
        number = int(value)
        if (hour and 1 <= number <= 23) or (not hour and 0 <= number <= 55 and number % 5 == 0):
            options.add(number)
    return sorted(options)


def _preferred_times(provider, token):
    hours = _time_parts(provider.catalog('hours', token=token), hour=True)
    minutes = _time_parts(provider.catalog('minutes', token=token), hour=False)
    return [{'id': f'{h:02}:{m:02}', 'label': f'{h:02}:{m:02}'}
            for h in hours for m in minutes]


def _secret(arn):
    # The exact ARN is deployment-pinned and separately scoped by IAM.
    if not arn.startswith('arn:aws:secretsmanager:'):
        raise CatalogueUnavailable('Apollo runtime credential is not configured')
    value = boto3.client('secretsmanager').get_secret_value(SecretId=arn, VersionStage='AWSCURRENT')
    raw = value.get('SecretString')
    if not isinstance(raw, str) or len(raw) > 8192:
        raise CatalogueUnavailable('Apollo runtime credential is invalid')
    config = json.loads(raw)
    if not isinstance(config, dict):
        raise CatalogueUnavailable('Apollo runtime credential is invalid')
    return config


def _provider_config():
    # Provider credentials have one authoritative home: the exact deployment-
    # pinned Secrets Manager secret. Never copy a password into a session row.
    arn = os.environ.get('APOLLO_SERVICE_SECRET_ARN', '')
    if not re.fullmatch(r'arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/arogya/apollo-[A-Za-z0-9]+', arn):
        raise CatalogueUnavailable('Apollo runtime requires administrator configuration')
    return validate_provider_config(_secret(arn), os.environ.get('APOLLO_GMAIL_GRANT_OWNER', ''))


def validate_provider_config(config, owner):
    if not isinstance(config, dict) or not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
        raise CatalogueUnavailable('Apollo runtime requires administrator configuration')
    sender = config.get('approvedSender', '')
    header = config.get('applicationHeader')
    password = config.get('password')
    if (config.get('providerAutomationApproved') is not True
            or config.get('grantOwner') != owner
            or config.get('username') != MAILBOX
            or config.get('websiteAddress') != 'https://aauser-ic.apollohospitals.com/'
            or not isinstance(sender, str) or not re.fullmatch(r'[^\s@]+@(?:[a-z0-9-]+\.)*apollohospitals\.com', sender)
            or not isinstance(header, str) or not header or len(header) > 2048
            or not header.strip() or any(ord(char) < 32 or ord(char) == 127 for char in header)
            or not isinstance(password, str) or not password or len(password) > 1024):
        raise CatalogueUnavailable('Apollo runtime requires administrator configuration')
    return config


def _runtime_store():
    table_name = os.environ.get('APOLLO_REGISTRY_TABLE')
    key_arn = os.environ.get('APOLLO_TOKEN_KEY_ARN')
    if (os.environ.get('APOLLO_AUTOMATION_ENABLED') != 'true'
            or table_name != 'wecare-workspace-mcp' or not key_arn
            or not os.environ.get('APOLLO_SERVICE_SECRET_ARN')):
        raise CatalogueUnavailable('Apollo catalogue authorization required')
    table = boto3.resource('dynamodb').Table(table_name)
    kms = boto3.client('kms')
    return table, kms, EncryptedSessionStore(table, kms, key_arn=key_arn, record_key=RECORD)


def _provider_session(now):
    table, kms, store = _runtime_store()
    grant = VerifiedGmailGrant(table, kms, key_arn=os.environ['APOLLO_TOKEN_KEY_ARN'],
        owner=os.environ.get('APOLLO_GMAIL_GRANT_OWNER', ''),
        oauth_config=lambda: _secret(os.environ['APOLLO_GOOGLE_OAUTH_SECRET_ARN']))
    # The administrator's verified binding must exist on every catalogue read.
    # Verify metadata before reading credentials or contacting Apollo.
    grant.verified_row()
    config = _provider_config()
    client = ApolloClient(config['applicationHeader'])
    gmail = None

    def gmail_get(path, params):
        nonlocal gmail
        if gmail is None:
            gmail = grant.transport()
        return gmail(path, params)

    def credentials():
        # Validate the authorized mailbox before starting a new login challenge.
        grant.verify_mailbox()
        return {'username': config['username'], 'password': config['password']}

    result = advance_session(store=store, provider=client, gmail_get=gmail_get,
        credentials=credentials, approved_sender=config['approvedSender'], now=now)
    if result.status != 'ready' or not result.token:
        raise CatalogueRenewing(result.retry_after or 3)
    return client, result.token

def read_catalog(body, *, now=None, session=None):
    """Request only approved read operations; return normalized public options."""
    if now is None:
        now = int(time.time())
    kind = body.get('kind')
    if kind not in (*FIELDS, 'dates', 'times'):
        raise InvalidCatalogueRequest('Invalid catalogue kind')
    allowed = {'action', 'kind'}
    params = {}
    if kind in ('specialities', 'doctors', 'healthChecks', 'dates'):
        allowed.add('hospitalId')
        params['hospital_id'] = _identifier(body.get('hospitalId'))
    if kind == 'doctors':
        allowed.add('specialityId')
        params['speciality_id'] = _identifier(body.get('specialityId'))
    if kind == 'dates':
        allowed.update(('doctorId', 'healthCheckId'))
        keys = [name for name in ('doctorId', 'healthCheckId') if body.get(name)]
        if len(keys) != 1:
            raise InvalidCatalogueRequest('Select a doctor or health check')
        params['item_id'] = _identifier(body[keys[0]])
        category = 'consultation' if keys[0] == 'doctorId' else 'healthCheck'
    if set(body) - allowed:
        raise InvalidCatalogueRequest('Unexpected catalogue parameters')
    token = ''
    try:
        provider, token = (session or _provider_session)(now)
        if kind == 'times':
            return {'options': _preferred_times(provider, token), 'observedAt': now, 'preferredOnly': True}
        raw = provider.available_dates(category, token=token, **params) if kind == 'dates' else provider.catalog(kind, token=token, **params)
        return {'options': normalize(kind, raw, now=now), 'observedAt': now}
    except ApolloSessionExpired:
        # Do not expose a provider 401 as customer authentication failure. Invalidate
        # only the rejected token, then let a later bounded request renew it.
        if token and session is None:
            try:
                _, _, store = _runtime_store()
                invalidate_session(store, token, now=int(time.time()))
            except (ClientError, RenewalLeaseLost, CatalogueUnavailable):
                raise CatalogueUnavailable('Apollo catalogue temporarily unavailable') from None
            raise CatalogueRenewing(3) from None
        raise CatalogueUnavailable('Apollo catalogue temporarily unavailable') from None
    except (ApolloUnavailable, ApolloAuthorizationRequired, MailboxAccessRequired, GmailReadUnavailable,
            RenewalLeaseLost, ClientError, KeyError, TypeError, ValueError):
        raise CatalogueUnavailable('Apollo catalogue is temporarily unavailable') from None
