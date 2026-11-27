"""Read-only catalogue adapter for an approved, verified Apollo server session.

An administrator/provider integration must establish the encrypted ready session.
This module never logs in, reads Gmail, exports browser credentials, or writes to
Apollo. Unknown response schemas and expired sessions fail closed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

from .apollo_client import ApolloClient, ApolloUnavailable
from .apollo_session import MAILBOX

RECORD = 'arogya:provider:apollo'
CONTEXT = {'purpose': 'arogya-provider', 'record': RECORD}
FIELDS = {
    'hospitals': (('hospitalid', 'ichospitalid', 'id'), ('hospitalname', 'name')),
    'specialities': (('multispecialityid', 'specialityid', 'specialtyid', 'id'),
                     ('multispecialityname', 'specialityname', 'specialtyname', 'name')),
    'doctors': (('doctorid', 'id'), ('doctorname', 'doctorfullname', 'name')),
    'healthChecks': (('healthcheckid', 'id'), ('healthcheckname', 'name')),
}
WRAPPERS = ('data', 'result', 'items', 'hospitals', 'specialities', 'doctors',
            'healthchecks', 'dates', 'appointmentdates', 'availabledates')


class CatalogueUnavailable(RuntimeError):
    pass


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
            date = _date(value)
            today = dt.datetime.fromtimestamp(now, dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()
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
        option = {'id': identifier, 'label': _label(_first(row, labels))}
        city = _first(row, ('city', 'cityname', 'hospitalcity'))
        if kind == 'hospitals' and city:
            option['city'] = _label(city, 80)
        if identifier in result and result[identifier] != option:
            raise CatalogueUnavailable('Ambiguous Apollo catalogue identifier')
        result[identifier] = option
    return sorted(result.values(), key=lambda item: item['id'] if kind == 'dates' else item['label'].casefold())


def _provider_session(now):
    table_name = os.environ.get('APOLLO_REGISTRY_TABLE')
    key_arn = os.environ.get('APOLLO_TOKEN_KEY_ARN')
    if not table_name or not key_arn:
        raise CatalogueUnavailable('Apollo catalogue authorization required')
    item = boto3.resource('dynamodb').Table(table_name).get_item(
        Key={'pk': RECORD}, ConsistentRead=True).get('Item', {})
    if not item.get('cipher'):
        raise CatalogueUnavailable('Apollo catalogue authorization required')
    state = json.loads(boto3.client('kms').decrypt(
        KeyId=key_arn, CiphertextBlob=bytes(item['cipher']),
        EncryptionContext=CONTEXT)['Plaintext'])
    if (not isinstance(state, dict) or state.get('stage') != 'ready'
            or type(state.get('expiresAt')) is not int or state['expiresAt'] <= now + 30
            or not isinstance(state.get('token'), str) or not state['token']
            or not isinstance(state.get('applicationHeader'), str) or not state['applicationHeader']):
        raise CatalogueUnavailable('Apollo catalogue authorization required')
    client = ApolloClient(state['applicationHeader'])
    profile = client.get_profile(state['token'])
    email = str(profile.get('EmailId', profile.get('emailId', profile.get('userName', '')))).strip().lower() if isinstance(profile, dict) else ''
    if email != MAILBOX:
        raise CatalogueUnavailable('Apollo catalogue account mismatch')
    return client, state['token']


def read_catalog(body, *, now=None, session=None):
    """Request only approved read operations; return normalized public options."""
    if now is None:
        now = int(time.time())
    kind = body.get('kind')
    if kind not in (*FIELDS, 'dates'):
        raise InvalidCatalogueRequest('Invalid catalogue kind')
    allowed = {'action', 'kind'}
    params = {}
    if kind != 'hospitals':
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
    try:
        provider, token = (session or _provider_session)(now)
        raw = provider.available_dates(category, token=token, **params) if kind == 'dates' else provider.catalog(kind, token=token, **params)
        return {'options': normalize(kind, raw, now=now), 'observedAt': now}
    except (ApolloUnavailable, ClientError, KeyError, TypeError, ValueError):
        raise CatalogueUnavailable('Apollo catalogue is temporarily unavailable') from None
