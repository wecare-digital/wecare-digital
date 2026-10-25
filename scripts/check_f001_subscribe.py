#!/usr/bin/env python3
"""Purpose-built offline verification for F001 Subscribe (WD-F001-SUBSCRIBE-PROFILE).

WHY THIS EXISTS
---------------
F001 spans the canonical Flow registry (Python and TypeScript twins), the launch policy
(`lambda_utils.flow_launch`), server-issued Flow sessions (`lambda_utils.flow_sessions`), the
data-exchange handler (`flows/subscribe_profile.py`), the business API's registry, send and
status routes, the inbound keyword dispatcher and the Workspace surfaces. A change to any one
of them can quietly break a promise another relies on, so this script exercises the REAL
modules end to end against in-memory tables and states each promise as a named check.

It replaces nothing in the retired test suite and needs no test runner: it is one script in
the same family as `validate_flow_json.py`.

READ-ONLY. No network, no AWS, no writes outside process memory. boto3, botocore and
cryptography are replaced with in-process stubs BEFORE any Lambda module is imported, so it
runs on a machine without the Lambda runtime libraries and can never reach a real table.
Phone numbers are synthetic 555 numbers.

Usage:  python3 scripts/check_f001_subscribe.py [--verbose]
Exit:   0 every check passed, 1 a check failed, 2 the harness could not be set up.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import logging
import re
import sys
import time
import traceback
import types
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
BIZ = ROOT / 'amplify' / 'functions' / 'messaging' / 'whatsapp-business-api'
INBOUND = ROOT / 'amplify' / 'functions' / 'messaging' / 'inbound-whatsapp-handler' / 'handler.py'
FLOW_JSON = BIZ / 'flows' / 'design-drafts' / 'subscribe.json'
TS_CANONICAL = ROOT / 'src' / 'lib' / 'canonicalFlows.ts'
TS_SETTINGS = ROOT / 'src' / 'components' / 'workspace' / 'whatsapp' / 'subscribe-settings.tsx'
TS_FLOW_HUB = ROOT / 'src' / 'components' / 'workspace' / 'whatsapp' / 'flow-hub.tsx'
TS_AUTO_RESPONSE = ROOT / 'src' / 'components' / 'workspace' / 'whatsapp' / 'auto-response.tsx'
TS_INBOX = ROOT / 'src' / 'pages' / 'workspace' / 'engage' / 'inbox' / 'index.tsx'
AI_CONFIG = ROOT / 'amplify' / 'functions' / 'ai' / 'ai-config-management' / 'handler.py'

PHONE_A = '15550100001'
PHONE_B = '15550100002'
PHONE_C = '15550100003'
PHONE_D = '15550100004'
NAME_A = 'Avery Testcustomer'
STREET_A = '742 Evergreen Terrace'


# ── In-process stubs for the Lambda runtime libraries ─────────────────────────────────

class FakeClientError(Exception):
    def __init__(self, error_response: Dict[str, Any], operation_name: str = ''):
        super().__init__(f"{error_response.get('Error', {}).get('Code', 'Error')} ({operation_name})")
        self.response = error_response
        self.operation_name = operation_name


class FakeBotoCoreError(Exception):
    pass


class FakeEndpointConnectionError(FakeBotoCoreError):
    pass


def _conditional_failure(operation: str) -> FakeClientError:
    return FakeClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, operation)


class _KeyCondition:
    def __init__(self, name: str, value: Any = None):
        self.name, self.value = name, value

    def eq(self, value: Any) -> '_KeyCondition':
        return _KeyCondition(self.name, value)

    def __and__(self, other: Any) -> '_KeyCondition':
        return self


_TOKEN = re.compile(r'\s*(attribute_exists\(\s*[#\w]+\s*\)|attribute_not_exists\(\s*[#\w]+\s*\)'
                    r'|\(|\)|AND\b|OR\b|[#\w]+\s*(?:<=|>=|<>|=|<|>)\s*:\w+)')
_COMPARE = {'=': lambda a, b: _same(a, b), '<>': lambda a, b: not _same(a, b),
            '<': lambda a, b: a < b, '<=': lambda a, b: a <= b,
            '>': lambda a, b: a > b, '>=': lambda a, b: a >= b}


def _same(a: Any, b: Any) -> bool:
    numeric = (int, float, Decimal)
    if isinstance(a, numeric) and isinstance(b, numeric) and not isinstance(a, bool) and not isinstance(b, bool):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


def evaluate_condition(expr: str, item: Dict[str, Any], names: Dict[str, str],
                       values: Dict[str, Any]) -> bool:
    """The subset of DynamoDB condition syntax the code under test uses."""
    tokens: List[str] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN.match(expr, pos)
        if not match:
            if not expr[pos:].strip():
                break
            raise ValueError(f'unsupported condition near {expr[pos:pos + 40]!r}')
        tokens.append(match.group(1))
        pos = match.end()
    index = 0

    def resolve(path: str) -> str:
        return names[path] if path.startswith('#') else path

    def atom() -> bool:
        nonlocal index
        token = tokens[index]
        index += 1
        if token == '(':
            value = parse_or()
            if tokens[index] != ')':
                raise ValueError('unbalanced condition')
            index += 1
            return value
        fn = re.fullmatch(r'attribute_(not_)?exists\(\s*([#\w]+)\s*\)', token)
        if fn:
            present = resolve(fn.group(2)) in item
            return not present if fn.group(1) else present
        left, op, right = re.fullmatch(r'([#\w]+)\s*(<=|>=|<>|=|<|>)\s*(:\w+)', token).groups()
        attr = resolve(left)
        return attr in item and _COMPARE[op](item[attr], values[right])

    def parse_and() -> bool:
        nonlocal index
        value = atom()
        while index < len(tokens) and tokens[index] == 'AND':
            index += 1
            rhs = atom()
            value = value and rhs
        return value

    def parse_or() -> bool:
        nonlocal index
        value = parse_and()
        while index < len(tokens) and tokens[index] == 'OR':
            index += 1
            rhs = parse_and()
            value = value or rhs
        return value

    result = parse_or()
    if index != len(tokens):
        raise ValueError(f'trailing condition tokens in {expr!r}')
    return result


def _split_top(body: str) -> List[str]:
    parts, depth, current = [], 0, []
    for ch in body:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    parts.append(''.join(current))
    return parts


def apply_update(item: Dict[str, Any], expr: str, names: Dict[str, str], values: Dict[str, Any]) -> None:
    def resolve(path: str) -> str:
        path = path.strip()
        return names[path] if path.startswith('#') else path
    sections = re.split(r'\b(SET|ADD|REMOVE)\b', expr)
    for i in range(1, len(sections), 2):
        kind, body = sections[i], sections[i + 1]
        for part in _split_top(body):
            part = part.strip()
            if not part:
                continue
            if kind == 'SET':
                lhs, rhs = part.split('=', 1)
                rhs = rhs.strip()
                guarded = re.fullmatch(r'if_not_exists\(\s*([#\w]+)\s*,\s*(:\w+)\s*\)', rhs)
                if guarded:
                    if resolve(guarded.group(1)) not in item:
                        item[resolve(lhs)] = copy.deepcopy(values[guarded.group(2)])
                else:
                    item[resolve(lhs)] = copy.deepcopy(values[rhs])
            elif kind == 'ADD':
                path, value = part.split()
                attr = resolve(path)
                item[attr] = item.get(attr, 0) + values[value]
            else:
                item.pop(resolve(part), None)


class FakeTable:
    """An in-memory DynamoDB table with the operations the code under test calls."""

    def __init__(self, name: str, key: str):
        self.name, self.key = name, key
        self.items: Dict[str, Dict[str, Any]] = {}
        self.calls: List[Tuple[str, Any]] = []
        self.fail_next: Dict[str, Exception] = {}
        self.before_write: Optional[Callable[['FakeTable', str], None]] = None

    def _maybe_fail(self, operation: str) -> None:
        exc = self.fail_next.pop(operation, None)
        if exc:
            raise exc

    def writes(self) -> int:
        return sum(1 for op, _ in self.calls if op in ('put_item', 'update_item', 'delete_item'))

    def get_item(self, Key: Dict[str, Any], ConsistentRead: bool = False, **_: Any) -> Dict[str, Any]:
        self._maybe_fail('get_item')
        self.calls.append(('get_item', Key))
        item = self.items.get(Key[self.key])
        return {'Item': copy.deepcopy(item)} if item is not None else {}

    def put_item(self, Item: Dict[str, Any], ConditionExpression: Optional[str] = None,
                 ExpressionAttributeNames: Optional[Dict[str, str]] = None,
                 ExpressionAttributeValues: Optional[Dict[str, Any]] = None, **_: Any) -> Dict[str, Any]:
        self._maybe_fail('put_item')
        if self.before_write:
            self.before_write(self, 'put_item')
        current = self.items.get(Item[self.key])
        if ConditionExpression and not evaluate_condition(
                ConditionExpression, current or {}, ExpressionAttributeNames or {},
                ExpressionAttributeValues or {}):
            raise _conditional_failure('PutItem')
        self.items[Item[self.key]] = copy.deepcopy(Item)
        self.calls.append(('put_item', copy.deepcopy(Item)))
        return {}

    def update_item(self, Key: Dict[str, Any], UpdateExpression: str,
                    ConditionExpression: Optional[str] = None,
                    ExpressionAttributeNames: Optional[Dict[str, str]] = None,
                    ExpressionAttributeValues: Optional[Dict[str, Any]] = None,
                    ReturnValues: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        self._maybe_fail('update_item')
        if self.before_write:
            self.before_write(self, 'update_item')
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        used = set(re.findall(r'#\w+', UpdateExpression + ' ' + (ConditionExpression or '')))
        unused = set(names) - used
        if unused:
            raise FakeClientError({'Error': {'Code': 'ValidationException',
                                             'Message': f'unused names {sorted(unused)}'}}, 'UpdateItem')
        current = self.items.get(Key[self.key])
        if ConditionExpression and not evaluate_condition(ConditionExpression, current or {}, names, values):
            raise _conditional_failure('UpdateItem')
        old = copy.deepcopy(current) if current is not None else None
        item = copy.deepcopy(current) if current is not None else dict(Key)
        apply_update(item, UpdateExpression, names, values)
        self.items[Key[self.key]] = item
        self.calls.append(('update_item', {'Key': Key, 'UpdateExpression': UpdateExpression}))
        return {'Attributes': old} if ReturnValues == 'ALL_OLD' and old else {}

    def query(self, IndexName: str = '', KeyConditionExpression: Any = None, Limit: int = 0,
              **_: Any) -> Dict[str, Any]:
        self._maybe_fail('query')
        self.calls.append(('query', IndexName))
        cond = KeyConditionExpression
        rows = [copy.deepcopy(i) for i in self.items.values() if i.get(cond.name) == cond.value]
        return {'Items': rows[:Limit] if Limit else rows}

    def scan(self, **_: Any) -> Dict[str, Any]:
        self._maybe_fail('scan')
        self.calls.append(('scan', None))
        return {'Items': [copy.deepcopy(i) for i in self.items.values()]}

    def delete_item(self, Key: Dict[str, Any], **_: Any) -> Dict[str, Any]:
        self.items.pop(Key[self.key], None)
        self.calls.append(('delete_item', Key))
        return {}


_KEYS = (('ContactsTable', 'id'), ('FlowDraftTable', 'draftKey'), ('FlowLogTable', 'logId'),
         ('FlowSubmissionTable', 'submissionId'), ('FlowRegistryTable', 'flowId'),
         ('SystemConfigTable', 'id'), ('IdentityClaimsTable', 'claimKey'), ('MessagesTable', 'messageId'))


class FakeResource:
    def __init__(self) -> None:
        self.tables: Dict[str, FakeTable] = {}

    def Table(self, name: str) -> FakeTable:  # noqa: N802 - boto3 spelling
        if name not in self.tables:
            key = next((k for suffix, k in _KEYS if name.endswith(suffix)), 'id')
            self.tables[name] = FakeTable(name, key)
        return self.tables[name]

    def reset(self) -> None:
        self.tables.clear()


class _AnyClient:
    """A boto3 client whose every call returns an empty response."""

    class exceptions:  # noqa: N801 - boto3 spelling
        NotAuthorizedException = FakeClientError

    def __getattr__(self, name: str) -> Callable[..., Dict[str, Any]]:
        return lambda *args, **kwargs: {}


FAKE_DB = FakeResource()


def install_stubs() -> None:
    boto3 = types.ModuleType('boto3')
    boto3.resource = lambda *a, **k: FAKE_DB
    boto3.client = lambda *a, **k: _AnyClient()
    dynamodb_pkg = types.ModuleType('boto3.dynamodb')
    conditions = types.ModuleType('boto3.dynamodb.conditions')
    conditions.Key = _KeyCondition
    conditions.Attr = _KeyCondition
    boto3.dynamodb = dynamodb_pkg
    dynamodb_pkg.conditions = conditions
    botocore = types.ModuleType('botocore')
    exceptions = types.ModuleType('botocore.exceptions')
    exceptions.ClientError = FakeClientError
    exceptions.BotoCoreError = FakeBotoCoreError
    exceptions.EndpointConnectionError = FakeEndpointConnectionError
    botocore.exceptions = exceptions
    config = types.ModuleType('botocore.config')
    config.Config = lambda *a, **k: None
    botocore.config = config
    modules = {'boto3': boto3, 'boto3.dynamodb': dynamodb_pkg, 'boto3.dynamodb.conditions': conditions,
               'botocore': botocore, 'botocore.exceptions': exceptions, 'botocore.config': config}
    for name in ('cryptography', 'cryptography.hazmat', 'cryptography.hazmat.primitives',
                 'cryptography.hazmat.primitives.asymmetric',
                 'cryptography.hazmat.primitives.asymmetric.padding',
                 'cryptography.hazmat.primitives.ciphers', 'cryptography.hazmat.primitives.serialization'):
        stub = types.ModuleType(name)
        for attr in ('OAEP', 'MGF1', 'hashes', 'Cipher', 'algorithms', 'modes', 'load_pem_private_key'):
            setattr(stub, attr, object())
        modules[name] = stub
    sys.modules.update(modules)
    for path in (SHARED, BIZ, ROOT / 'scripts'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            self.lines.append(str(record.msg))


# ── Check registry ───────────────────────────────────────────────────────────────────

CHECKS: List[Tuple[str, Callable[[], None]]] = []


def check(name: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def register(fn: Callable[[], None]) -> Callable[[], None]:
        CHECKS.append((name, fn))
        return fn
    return register


class CheckFailed(AssertionError):
    pass


def expect(condition: Any, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


# ── Harness state populated by setup() ───────────────────────────────────────────────

M: Dict[str, Any] = {}
LOGS = LogCapture()


def setup() -> None:
    install_stubs()
    root = logging.getLogger()
    root.addHandler(LOGS)
    root.setLevel(logging.DEBUG)
    import importlib
    for name in ('lambda_utils.canonical_flows', 'lambda_utils.flow_launch', 'lambda_utils.flow_sessions',
                 'lambda_utils.flow_funnel', 'lambda_utils.subscribe_messages', 'lambda_utils.contact_store',
                 'lambda_utils.identity_claims', 'lambda_utils.flow_completion', 'lambda_utils.privacy',
                 'lambda_utils.message_store', 'lambda_utils.identity.customer_uuid',
                 'lambda_utils.ecommerce.contact_address', 'lambda_utils.middleware',
                 'lambda_utils.meta_signature',
                 'flows.common', 'flows.subscribe_profile', 'flows.router', 'flows.country_options',
                 'validate_flow_json'):
        M[name.split('.')[-1]] = importlib.import_module(name)
    M['bizapi'] = importlib.import_module('handler')
    # The AI config API is also a module named `handler`, so it is loaded under its own name.
    import importlib.util
    ai_spec = importlib.util.spec_from_file_location('ai_config_handler', AI_CONFIG)
    M['ai_config'] = importlib.util.module_from_spec(ai_spec)
    ai_spec.loader.exec_module(M['ai_config'])
    # The CRM projection is best-effort and outside F001; record it instead of running it.
    M['crm_calls'] = []
    M['flow_completion'].capture_crm_lead = lambda result, **kw: M['crm_calls'].append(kw) or {'outcome': 'recorded'}
    load_inbound()


def table(name: str) -> FakeTable:
    return FAKE_DB.Table(name)


def contacts() -> FakeTable:
    return table(M['common'].CONTACTS_TABLE)


def sessions() -> FakeTable:
    return table(M['flow_sessions'].table_name())


def submissions() -> FakeTable:
    return table(M['common'].FLOW_SUBMISSIONS_TABLE)


def registry() -> FakeTable:
    return table(M['bizapi'].FLOW_REGISTRY_TABLE)


def system_config() -> FakeTable:
    return table(M['subscribe_messages'].system_config_table_name())


def claims() -> FakeTable:
    return table(M['identity_claims'].TABLE_NAME)


def funnel_totals() -> Dict[str, int]:
    return M['flow_funnel'].read(table(M['flow_funnel'].table_name()), F001_CODE(), days=1)['totals']


def F001_CODE() -> str:  # noqa: N802 - reads as a constant at call sites
    return M['canonical_flows'].CANONICAL_CONTRACTS['subscribe']['flowCode']


def F001_ID() -> str:  # noqa: N802
    return M['canonical_flows'].canonical_flow_id('subscribe')


def published_registry_row(**overrides: Any) -> Dict[str, Any]:
    contract = M['canonical_flows'].canonical_contract('subscribe')
    row = {'flowId': F001_ID(), 'flowCode': contract['flowCode'], 'flowName': 'Subscribe',
           'flowType': contract['flowType'], 'wabaId': contract['wabaId'], 'status': 'PUBLISHED',
           'entryMode': 'keyword_interactive', 'entryTemplateName': '', 'requiresPayment': False,
           'submissionPrefix': contract['submissionPrefix'], 'metaStatus': 'PUBLISHED',
           'updatedAt': Decimal('1700000000')}
    row.update(overrides)
    return row


def new_session(phone: str = PHONE_A, *, channel: str = 'keyword', capability: str = 'subscribe',
                waba: str = '1', now: Optional[int] = None) -> str:
    fs = M['flow_sessions']
    token = fs.mint_token('subscribe', phone, waba)
    fs.record_session(sessions(), capability=capability, token=token, launch_channel=channel,
                      initiated_by='customer_keyword' if channel == 'keyword' else 'staff@example.test',
                      now=now)
    return token


def flow_call(action: str, screen: str, data: Dict[str, Any], token: str) -> Dict[str, Any]:
    """POST /flow-data through the real decrypt -> route -> encrypt wrapper (crypto stubbed)."""
    biz = M['bizapi']
    payload = {'version': '3.0', 'action': action, 'screen': screen, 'data': data, 'flow_token': token}
    biz._decrypt_flow_request = lambda *_: (copy.deepcopy(payload), b'k', b'i')
    biz._encrypt_flow_response = lambda response, *_: json.dumps(response)
    out = biz._handle_flow_data({'encrypted_flow_data': 'x', 'encrypted_aes_key': 'y',
                                 'initial_vector': 'z'}, f'req-{uuid.uuid4().hex[:8]}')
    body = out.get('body') or '{}'
    return {'status': out['statusCode'], 'body': json.loads(body)}


def flow_doc() -> Dict[str, Any]:
    return json.loads(FLOW_JSON.read_text(encoding='utf-8'))


def screen_keys(screen_id: str) -> set:
    screen = next(s for s in flow_doc()['screens'] if s['id'] == screen_id)
    return set((screen.get('data') or {}).keys())


def form_from(init_data: Dict[str, Any], **changes: str) -> Dict[str, Any]:
    """What the REVIEW footer posts: every screen field plus the profile_version marker."""
    data = {key: init_data[key] for key in screen_keys('PROFILE')}
    data.update({'full_name': NAME_A, 'username': 'avery.t', 'company_name': 'Example Org',
                 'designation': 'Analyst', 'address_line1': STREET_A, 'address_line2': 'Unit 4',
                 'locality': 'Springfield Heights', 'city': 'Springfield', 'state': 'Oregon',
                 'postal_code': '97477', 'country': 'United States', 'profile_version': '3'})
    data.update(changes)
    return data


def open_flow(token: str) -> Dict[str, Any]:
    response = flow_call('INIT', '', {}, token)
    expect(response['status'] == 200, f'INIT should open, got HTTP {response["status"]}: {response["body"]}')
    return response['body']['data']


# ── A. Canonical registry and contract twins ─────────────────────────────────────────

def _ts_block(source: str, anchor: str) -> str:
    start = source.index(anchor)
    depth, end = 0, start
    for index in range(source.index('{', start), len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                end = index
                break
    return source[start:end + 1]


def _ts_value(block: str, field: str) -> Any:
    match = re.search(rf'\b{field}:\s*(\'[^\']*\'|true|false|null|\[[^\]]*\])', block)
    if not match:
        raise CheckFailed(f'TypeScript field {field} not found')
    raw = match.group(1)
    if raw in ('true', 'false'):
        return raw == 'true'
    if raw == 'null':
        return None
    if raw.startswith('['):
        return tuple(re.findall(r"'([^']*)'", raw))
    return raw[1:-1]


@check('A1 canonical F001 record is PUBLISHED with one Flow ID in both twins')
def _() -> None:
    cf = M['canonical_flows']
    expect(cf.CANONICAL_FLOWS['subscribe'] == ('2413873616105042', 'PUBLISHED', 'WD-F001-SUBSCRIBE-PROFILE'),
           f"python record is {cf.CANONICAL_FLOWS['subscribe']}")
    block = _ts_block(TS_CANONICAL.read_text(encoding='utf-8'), 'subscribe: {')
    expect(_ts_value(block, 'flowId') == '2413873616105042', 'TS flowId differs')
    expect(_ts_value(block, 'status') == 'PUBLISHED', 'TS status differs')
    expect(_ts_value(block, 'metaName') == 'WD-F001-SUBSCRIBE-PROFILE', 'TS metaName differs')


@check('A2 launch contract agrees field for field between Python and TypeScript')
def _() -> None:
    py = M['canonical_flows'].CANONICAL_CONTRACTS['subscribe']
    source = TS_CANONICAL.read_text(encoding='utf-8')
    block = _ts_block(source[source.index('CANONICAL_CONTRACTS'):], 'subscribe: {')
    for field, value in py.items():
        ts_value = _ts_value(block, field)
        expect(ts_value == (tuple(value) if isinstance(value, (list, tuple)) else value),
               f'{field}: python {value!r} vs TypeScript {ts_value!r}')


@check('A3 F001 contract is keyword_interactive, no template, never payment-gated')
def _() -> None:
    contract = M['canonical_flows'].canonical_contract('subscribe')
    expect(contract['entryMode'] == 'keyword_interactive', 'entry mode')
    expect(contract['entryTemplateName'] == '', 'template must be empty')
    expect(contract['requiresPayment'] is False, 'must not require payment')
    expect(M['canonical_flows'].published_flow_token_prefix('subscribe') == contract['tokenPrefix'] == 'subscribe',
           'token prefix must route to the F001 handler')


@check('A4 no retired Subscribe Flow IDs or the old Subscribe template remain wired')
def _() -> None:
    stale = ('1262971692700761', '951987930811295', '1557815099200456', '1386523953464380')
    wired = (INBOUND, BIZ / 'handler.py', BIZ / 'flows' / 'subscribe_profile.py', BIZ / 'flows' / 'router.py',
             SHARED / 'lambda_utils' / 'canonical_flows.py', TS_CANONICAL, TS_SETTINGS, TS_FLOW_HUB)
    for path in wired:
        text = path.read_text(encoding='utf-8')
        for flow_id in stale:
            expect(flow_id not in text, f'{path.name} still names retired Flow {flow_id}')
        expect('feedback_survey_form_1' not in text, f'{path.name} names the old Subscribe template')
    expect(not (BIZ / 'flows' / 'subscribe.py').exists(), 'legacy flows/subscribe.py writers must stay deleted')


# ── B. Flow JSON ─────────────────────────────────────────────────────────────────────

@check('B1 Flow JSON passes the local structural validator and routes PROFILE->ADDRESS->REVIEW->COMPLETE')
def _() -> None:
    doc = flow_doc()
    problems = M['validate_flow_json'].validate_flow(doc)
    expect(not problems, f'validator problems: {problems}')
    expect([s['id'] for s in doc['screens']] == ['PROFILE', 'ADDRESS', 'REVIEW', 'COMPLETE'], 'screen order')
    expect(doc['routing_model'] == {'PROFILE': ['ADDRESS'], 'ADDRESS': ['REVIEW'], 'REVIEW': ['COMPLETE'],
                                    'COMPLETE': []}, 'routing model')
    complete = doc['screens'][-1]
    expect(complete.get('terminal') is True and complete.get('success') is True, 'COMPLETE terminal+success')


@check('B2 handler data keys match each screen schema exactly')
def _() -> None:
    sp = M['subscribe_profile']
    expect(set(sp.SCREEN_KEYS) == screen_keys('PROFILE') == screen_keys('ADDRESS'), 'PROFILE/ADDRESS keys')
    expect(set(sp.REVIEW_KEYS) == screen_keys('REVIEW'), 'REVIEW keys')
    expect(screen_keys('COMPLETE') == {'customer_id', 'message'}, 'COMPLETE keys')


@check('B3 REVIEW save payload carries every field the handler reads; limits match the handler')
def _() -> None:
    sp = M['subscribe_profile']
    doc = flow_doc()
    review = doc['screens'][2]
    footer = next(n for n in _walk(review['layout']) if n.get('type') == 'Footer')
    payload = set(footer['on-click-action']['payload'])
    needed = set(sp.PROFILE_FIELDS) | set(sp.ADDRESS_FIELDS) | {'profile_revision', 'updated_at'}
    expect(needed <= payload, f'missing from REVIEW payload: {sorted(needed - payload)}')
    inputs = {n['name']: n for n in _walk(doc) if n.get('type') == 'TextInput'}
    for key, limit in sp.PROFILE_LIMITS.items():
        expect(inputs[key].get('max-chars') == limit, f'{key} max-chars {inputs[key].get("max-chars")} != {limit}')
    for key, attr in sp.ADDRESS_FIELDS.items():
        if key in inputs:
            expect(inputs[key].get('max-chars') == sp.ADDRESS_LIMITS[attr], f'{key} max-chars differs')
    expect(inputs['full_name'].get('required') is True, 'full name required')
    for key in ('address_line1', 'city', 'state', 'postal_code'):
        expect(inputs[key].get('required') is True, f'{key} required')


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


@check('B4 country dropdown equals the backend country list, India first')
def _() -> None:
    dropdown = next(n for n in _walk(flow_doc()) if n.get('type') == 'Dropdown')
    expect(dropdown['data-source'] == M['country_options'].OPTIONS, 'dropdown options differ from country_options')
    expect(dropdown['data-source'][0]['id'] == 'India', 'India first')


@check('B5 branding is WECARE.DIGITAL everywhere and copy is US English')
def _() -> None:
    sources = {'Flow JSON': FLOW_JSON.read_text(encoding='utf-8'),
               'subscribe_profile': (BIZ / 'flows' / 'subscribe_profile.py').read_text(encoding='utf-8'),
               'subscribe_messages': (SHARED / 'lambda_utils' / 'subscribe_messages.py').read_text(encoding='utf-8'),
               'subscribe-settings': TS_SETTINGS.read_text(encoding='utf-8')}
    for label, text in sources.items():
        bare = re.findall(r'WECARE(?!\.DIGITAL)(?![_A-Z])', text)
        expect(not bare, f'{label} uses bare "WECARE" {len(bare)} time(s)')
        for word in ('Organisation', 'organisation', 'colour', 'neighbourhood', 'catalogue', 'licence',
                     'PIN / postal', 'Profile username'):
            expect(word not in text, f'{label} uses non-US or retired wording {word!r}')
    for text in _visible_strings(flow_doc()):
        expect('WECARE' not in text or 'WECARE.DIGITAL' in text, f'visible text {text!r}')


def _visible_strings(doc: Dict[str, Any]) -> List[str]:
    out = []
    for node in _walk(doc):
        for key in ('text', 'label', 'helper-text', 'alt-text', 'title'):
            if isinstance(node.get(key), str):
                out.append(node[key])
    return out


@check('B6 the Flow collects no consent and offers no opt-in')
def _() -> None:
    text = FLOW_JSON.read_text(encoding='utf-8')
    for marker in ('OptIn', 'opt_in', 'consent', 'marketing'):
        expect(marker not in text, f'Flow JSON contains {marker!r}')


# ── C. Data exchange: sessions, prefill, save, identity, history ─────────────────────

@check('C1 ping answers active; a token with no server session is refused with HTTP 427')
def _() -> None:
    FAKE_DB.reset()
    ping = flow_call('ping', '', {}, '')
    expect(ping['status'] == 200 and ping['body'] == {'data': {'status': 'active'}}, f'ping: {ping}')
    forged = f'subscribe-{uuid.uuid4().hex}-waba-1-ph-{PHONE_A}'
    response = flow_call('INIT', '', {}, forged)
    expect(response['status'] == 427, f'no-session INIT should be 427, got {response["status"]}')
    expect('expired' in response['body'].get('error_msg', ''), 'customer-facing 427 copy')
    expect(contacts().writes() == 0, 'a refused INIT must not write')


@check('C2 an edited phone, a wrong capability, an expired session and a WABA 2 token are all refused')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_A)
    spliced = token.replace(f'-ph-{PHONE_A}', f'-ph-{PHONE_B}')
    expect(flow_call('INIT', '', {}, spliced)['status'] == 427, 'phone-spliced token accepted')
    other = new_session(PHONE_A, capability='leave_review')
    expect(flow_call('INIT', '', {}, other)['status'] == 427, 'other capability accepted')
    old = new_session(PHONE_A, now=int(time.time()) - M['flow_sessions'].SESSION_TTL_SECONDS - 5)
    expect(flow_call('INIT', '', {}, old)['status'] == 427, 'expired session accepted')
    waba2 = new_session(PHONE_A, waba='2')
    expect(flow_call('INIT', '', {}, waba2)['status'] == 427, 'WABA 2 session accepted')


@check('C3 new customer: INIT returns clean defaults and writes nothing')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_A)
    response = flow_call('INIT', '', {}, token)
    expect(response['status'] == 200 and response['body']['screen'] == 'PROFILE', f'INIT: {response}')
    data = response['body']['data']
    expect(set(data) == screen_keys('PROFILE'), f'INIT keys {sorted(set(data) ^ screen_keys("PROFILE"))}')
    expect(data['phone_number'] == f'+{PHONE_A}', 'phone from the session')
    expect(data['customer_id'] == M['subscribe_profile'].CUSTOMER_ID_PENDING, 'pending Customer ID')
    expect((data['country'], data['country_code']) == ('India', 'IN'), 'India default for new profiles')
    expect(data['full_name'] == '' and data['address_line1'] == '', 'clean defaults')
    expect(contacts().writes() == 0, 'INIT must not write the contact')


@check('C4 new customer save creates one canonical contact with server identity and no consent')
def _() -> None:
    FAKE_DB.reset()
    M['crm_calls'].clear()
    token = new_session(PHONE_A)
    data = open_flow(token)
    forged = form_from(data, phone_number=f'+{PHONE_B}', customer_id='C-FORGEDFORGED')
    response = flow_call('data_exchange', 'REVIEW', forged, token)
    expect(response['status'] == 200 and response['body'].get('screen') == 'COMPLETE', f'save: {response}')
    expect(set(response['body']['data']) == screen_keys('COMPLETE'), 'COMPLETE keys')
    rows = list(contacts().items.values())
    expect(len(rows) == 1, f'{len(rows)} contacts created')
    row = rows[0]
    cu = M['customer_uuid']
    expect(row['id'] == row['contactId'] == f'wa{PHONE_A}', 'deterministic canonical id')
    expect(row['phone'] == f'+{PHONE_A}', 'phone comes from the session, never the form')
    expect(cu.is_customer_uuid(row.get('customerUuid')), 'server-minted customerUuid')
    expect(str(row.get('subscriberId', '')).startswith('WD-wecare-digital-'), 'server-minted subscriberId')
    expect(row.get('locked') is True and row.get('lockedReason') == 'created', 'creation retention lock')
    expect(response['body']['data']['customer_id'] == cu.display_code(row), 'COMPLETE shows the real Customer ID')
    expect(response['body']['data']['customer_id'] != 'C-FORGEDFORGED', 'forged Customer ID ignored')
    for key in row:
        expect(not key.startswith(('optIn', 'allowlist', 'consent')), f'consent field {key} written')
    expect(row['name'] == NAME_A and row['profileUsername'] == 'avery.t', 'profile saved')
    address = row['checkoutDeliveryAddress']
    expect(address['countryCode'] == 'US' and address['postalCode'] == '97477', 'international address stored')
    expect(row['fieldSources']['name'] == 'FLOW_SUBMISSION' and row['fieldSources']['phone'] == 'WHATSAPP_INBOUND',
           'provenance recorded')
    claim = claims().items.get(f'PHONE#+{PHONE_A}')
    expect(claim and claim['contactId'] == row['id'], 'phone claimed for the canonical contact')
    expect('username' not in row and 'bsuid' not in row, 'no Meta identity invented')


@check('C5 completion history row is complete, sanitized and filed under the canonical code')
def _() -> None:
    items = list(submissions().items.values())
    expect(len(items) == 1, f'{len(items)} submission rows')
    item = items[0]
    expect(item['flowCode'] == F001_CODE() and item['flowType'] == 'subscribe', 'code and type')
    expect(item['submissionId'].startswith('WD-SUB-') and item['submissionNumber'] == item['submissionId'],
           'reference id')
    expect(item['status'] == 'completed' and item['paymentRequired'] is False and item['paymentStatus'] == 'none',
           'status and payment fields')
    expect(item['channel'] == 'whatsapp' and item['launchChannel'] == 'keyword', 'channel and launch door')
    expect(item.get('requestId') and item.get('completedAt') and item.get('createdAt'), 'correlation and times')
    expect(item['contactId'] == f'wa{PHONE_A}' and M['customer_uuid'].is_customer_uuid(item['customerUuid']),
           'linked to the canonical contact')
    form = json.loads(item['formData'])
    expect('profile_revision' not in form and 'updated_at' not in form and 'country_code' not in form,
           'bookkeeping keys stripped')
    expect(form['phone_number'] == f'+{PHONE_A}', 'stored phone is the session phone, not the forged one')
    inbox = [m for m in table(M['message_store'].MESSAGES_TABLE).items.values()
             if m.get('messageType') == 'flow_response']
    expect(len(inbox) == 1, 'one Inbox projection')
    labels = [answer['question'] for answer in inbox[0]['flowAnswers']]
    expect('WECARE.DIGITAL profile name (customer-entered)' in labels and 'Username' not in labels,
           f'Inbox labels {labels}')


@check('C6 retrying the same save is idempotent: no second mutation, no second history row')
def _() -> None:
    # Sessions store only a digest, so the C4 token is replayed from its history row.
    replay_token = next(iter(submissions().items.values()))['flowToken']
    contact_writes = contacts().writes()
    history_rows = len(submissions().items)
    data = form_from({k: '' for k in screen_keys('PROFILE')},
                     profile_revision='stale', updated_at='stale')
    response = flow_call('data_exchange', 'REVIEW', data, replay_token)
    expect(response['body'].get('screen') == 'COMPLETE', f'retry should complete: {response}')
    expect(response['body']['data']['message'] == 'Your details have been saved.', 'retry keeps new-customer copy')
    expect(contacts().writes() == contact_writes, 'retry repeated the contact mutation')
    expect(len(submissions().items) == history_rows, 'retry created a second history row')


@check('C7 a finished link cannot reopen (427); a changed retry is refused, not silently ignored')
def _() -> None:
    replay_token = next(iter(submissions().items.values()))['flowToken']
    expect(flow_call('INIT', '', {}, replay_token)['status'] == 427, 'consumed session reopened')
    changed = form_from({k: '' for k in screen_keys('PROFILE')}, city='Eugene')
    response = flow_call('data_exchange', 'REVIEW', changed, replay_token)
    expect(response['body'].get('screen') == 'REVIEW', 'changed retry must not COMPLETE')
    expect('already saved' in response['body']['data']['error_message'], 'explains the refusal')


@check('C8 returning customer: prefill from the contact row; protected identity never changes')
def _() -> None:
    row = contacts().items[f'wa{PHONE_A}']
    row.update({'username': 'meta_handle', 'bsuid': 'US.12345678901234567890', 'parentBsuid': 'US.P1',
                'optInWhatsApp': False, 'allowlistWhatsApp': True,
                'consentLedger': [{'channel': 'WHATSAPP', 'state': 'OPTED_OUT'}], 'locked': True,
                'lockedReason': 'paid', 'updatedAt': Decimal('1700000500')})
    protected = {k: copy.deepcopy(row.get(k)) for k in (
        'phone', 'customerUuid', 'subscriberId', 'username', 'bsuid', 'parentBsuid', 'optInWhatsApp',
        'allowlistWhatsApp', 'consentLedger', 'locked', 'lockedReason', 'createdAt', 'workspaceId')}
    token = new_session(PHONE_A)
    data = open_flow(token)
    expect(data['full_name'] == NAME_A and data['address_line1'] == STREET_A, 'prefilled from the contact')
    expect((data['country'], data['country_code']) == ('United States', 'US'), 'saved country wins over India')
    expect(data['customer_id'] == M['customer_uuid'].display_code(row), 'saved Customer ID shown')
    submitted = form_from(data, address_line1='1 Main Street', username='new.profile.name',
                          phone_number=f'+{PHONE_B}', customer_id='C-FORGEDFORGED', country_code='IN')
    response = flow_call('data_exchange', 'REVIEW', submitted, token)
    expect(response['body'].get('screen') == 'COMPLETE', f'returning save: {response}')
    expect(response['body']['data']['message'] == 'Your details have been updated.', 'returning copy')
    saved = contacts().items[f'wa{PHONE_A}']
    for key, value in protected.items():
        expect(saved.get(key) == value, f'protected field {key} changed')
    expect(saved['profileUsername'] == 'new.profile.name' and saved['username'] == 'meta_handle',
           'profile name updated, Meta username untouched')
    expect(saved['checkoutDeliveryAddress']['addressLine1'] == '1 Main Street', 'address updated')
    expect(saved['checkoutDeliveryAddress']['countryCode'] == 'US', 'stale hidden IN code did not win')


@check('C9 stale write: a profile edited elsewhere after INIT is never overwritten')
def _() -> None:
    token = new_session(PHONE_A)
    data = open_flow(token)
    row = contacts().items[f'wa{PHONE_A}']
    row.update({'updatedAt': Decimal(str(int(time.time()) + 50)), 'name': 'Edited On Website'})
    writes = contacts().writes()
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'REVIEW', 'stale save must not COMPLETE')
    expect('profile changed' in response['body']['data']['error_message'], 'stale explanation')
    expect(set(response['body']['data']) == screen_keys('REVIEW'), 'REVIEW error keys match the schema')
    expect(contacts().writes() == writes and contacts().items[f'wa{PHONE_A}']['name'] == 'Edited On Website',
           'newer edit preserved')


@check('C10 validation errors name the field and the screen to correct, on a non-success screen')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_B)
    data = open_flow(token)
    cases = [
        ({'username': 'x' * 51}, 'Please keep your WhatsApp username within 50 characters. Go back to Subscribe to correct it.'),
        ({'full_name': ''}, 'Please enter your full name. Go back to Subscribe to correct it.'),
        ({'full_name': 'Bad\x00Name'}, 'Go back to Subscribe'),
        ({'city': ''}, 'Please enter your city. Go back to Address to correct it.'),
        ({'postal_code': '9' * 101}, 'Go back to Address to correct it.'),
        ({'country': 'Atlantis'}, 'Please select your country from the list. Go back to Address to correct it.'),
        ({'company_name': 'y' * 201}, 'organization within 200 characters'),
    ]
    for change, expected in cases:
        response = flow_call('data_exchange', 'REVIEW', form_from(data, **change), token)
        body = response['body']
        expect(body.get('screen') == 'REVIEW', f'{change} returned {body.get("screen")}')
        expect(expected in body['data']['error_message'], f'{list(change)[0]}: {body["data"]["error_message"]!r}')
        expect(set(body['data']) == screen_keys('REVIEW'), 'error response keys match the REVIEW schema')
    expect(contacts().writes() == 0 and claims().writes() == 0, 'validation failures must not write')


@check('C11 save succeeded but history failed: retry finishes history without a second mutation')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_C)
    data = open_flow(token)
    submissions().fail_next['put_item'] = FakeClientError({'Error': {'Code': 'ProvisionedThroughputExceededException'}}, 'PutItem')
    first = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(first['body'].get('screen') == 'REVIEW' and 'confirmation is pending' in first['body']['data']['error_message'],
           f'history failure must not COMPLETE: {first}')
    expect(f'wa{PHONE_C}' in contacts().items and not submissions().items, 'contact saved, history pending')
    writes = contacts().writes()
    session_row = next(iter(sessions().items.values()))
    expect(not session_row.get('consumedAt'), 'session stays open until history is recorded')
    second = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(second['body'].get('screen') == 'COMPLETE', f'retry should COMPLETE: {second}')
    expect(contacts().writes() == writes, 'retry repeated the contact mutation')
    expect(len(submissions().items) == 1, 'history written once')
    expect(next(iter(sessions().items.values())).get('consumedAt'), 'session consumed after history')


@check('C12 a phone already claimed by another profile is refused; no duplicate contact')
def _() -> None:
    FAKE_DB.reset()
    claims().items[f'PHONE#+{PHONE_D}'] = {'claimKey': f'PHONE#+{PHONE_D}', 'contactId': 'web-other-contact'}
    token = new_session(PHONE_D)
    data = open_flow(token)
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'REVIEW' and 'already linked' in response['body']['data']['error_message'],
           f'conflict: {response}')
    expect(not contacts().items, 'no duplicate contact created')


@check('C12b two live profiles on one phone: the save is refused and explained, never guessed')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_D)
    data = open_flow(token)
    for contact_id in ('web-one', 'web-two'):
        contacts().items[contact_id] = {'id': contact_id, 'contactId': contact_id, 'phone': f'+{PHONE_D}'}
    writes = contacts().writes()
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'REVIEW' and 'already linked' in response['body']['data']['error_message'],
           f'conflict: {response}')
    expect(contacts().writes() == writes, 'a conflicting profile was written')


@check('C13 a soft-deleted contact is never resurrected and the customer is told to contact the team')
def _() -> None:
    FAKE_DB.reset()
    contacts().items[f'wa{PHONE_D}'] = {'id': f'wa{PHONE_D}', 'contactId': f'wa{PHONE_D}', 'phone': f'+{PHONE_D}',
                                        'deletedAt': 1700000000}
    token = new_session(PHONE_D)
    data = open_flow(token)
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'REVIEW' and 'our team can help' in response['body']['data']['error_message'],
           f'deleted contact: {response}')
    expect(contacts().items[f'wa{PHONE_D}'].get('deletedAt') == 1700000000 and 'name' not in contacts().items[f'wa{PHONE_D}'],
           'deleted row untouched')


@check('C14 a malformed stored Customer ID is preserved (never repaired from a Flow) and the save succeeds')
def _() -> None:
    FAKE_DB.reset()
    contacts().items[f'wa{PHONE_D}'] = {'id': f'wa{PHONE_D}', 'contactId': f'wa{PHONE_D}', 'phone': f'+{PHONE_D}',
                                        'customerUuid': 'not-a-uuid', 'updatedAt': Decimal('1700000000')}
    token = new_session(PHONE_D)
    data = open_flow(token)
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'COMPLETE', f'save: {response}')
    expect(contacts().items[f'wa{PHONE_D}']['customerUuid'] == 'not-a-uuid', 'malformed id overwritten')
    expect(response['body']['data']['customer_id'] == M['subscribe_profile'].CUSTOMER_ID_UNAVAILABLE,
           'COMPLETE says the id is being assigned')


@check('C15 a concurrent duplicate save with the same link completes once')
def _() -> None:
    FAKE_DB.reset()
    contacts().items[f'wa{PHONE_C}'] = {'id': f'wa{PHONE_C}', 'contactId': f'wa{PHONE_C}', 'phone': f'+{PHONE_C}',
                                        'updatedAt': Decimal('1700000000')}
    token = new_session(PHONE_C)
    data = open_flow(token)

    def winner_first(tbl: FakeTable, operation: str) -> None:
        if operation == 'update_item' and tbl.before_write:
            tbl.before_write = None
            tbl.items[f'wa{PHONE_C}'].update({'subscribeLastFlowToken': token, 'subscribeProfileWasExisting': False,
                                              'updatedAt': Decimal('1700000999'), 'name': NAME_A})
    contacts().before_write = winner_first
    response = flow_call('data_exchange', 'REVIEW', form_from(data), token)
    expect(response['body'].get('screen') == 'COMPLETE', f'duplicate should complete: {response}')
    expect(len(submissions().items) == 1, 'one history row')


@check('C16 Meta error notifications are acknowledged; unsupported actions never finish the Flow')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_A)
    note = flow_call('data_exchange', 'REVIEW', {'error': 'payload-schema-error', 'error_message': 'x'}, token)
    expect(note['body'] == {'data': {'acknowledged': True}}, f'notification: {note}')
    other = flow_call('data_exchange', 'COMPLETE', {}, token)
    expect(other['body'].get('screen') != 'SUCCESS' and 'error' in other['body'].get('data', {}),
           f'unsupported action must not succeed: {other}')
    expect(contacts().writes() == 0, 'neither may write')


@check('C17 funnel counted every stage exercised, with no customer data in the counter rows')
def _() -> None:
    FAKE_DB.reset()
    token = new_session(PHONE_A)
    data = open_flow(token)
    flow_call('data_exchange', 'REVIEW', form_from(data, city=''), token)
    flow_call('data_exchange', 'REVIEW', form_from(data), token)
    flow_call('INIT', '', {}, token)
    totals = funnel_totals()
    for stage in ('init_received', 'init_success', 'init_rejected', 'validation_failed', 'save_success',
                  'complete_returned'):
        expect(totals.get(stage, 0) >= 1, f'stage {stage} not counted ({totals.get(stage)})')
    for item in table(M['flow_funnel'].table_name()).items.values():
        if item.get('type') == M['flow_funnel'].ROW_TYPE:
            blob = json.dumps(item, default=str)
            expect(PHONE_A not in blob and NAME_A not in blob, 'funnel row carries customer data')


@check('C18 flow-log breadcrumbs store field shapes, not values, and mask the token')
def _() -> None:
    rows = [i for i in table(M['common'].FLOW_LOGS_TABLE).items.values() if i.get('type') == 'flow_log']
    expect(rows, 'router logged interactions')
    for row in rows:
        expect(row['flowToken'].endswith('-ph-***'), 'token masked')
        snapshot = row.get('dataSnapshot', '')
        expect(NAME_A not in snapshot and STREET_A not in snapshot, 'snapshot carries form values')


# ── D. Launch policy ────────────────────────────────────────────────────────────────

@check('D1 registry contract: contradictory entry configuration is rejected')
def _() -> None:
    fl = M['flow_launch']
    expect(fl.registry_errors({'flowId': 'x', 'entryMode': 'payment_template', 'requiresPayment': True}),
           'payment_template without template accepted')
    expect(fl.registry_errors({'flowId': 'x', 'entryMode': 'payment_template', 'entryTemplateName': 't',
                               'requiresPayment': False}), 'payment_template without requiresPayment accepted')
    expect(fl.registry_errors({'flowId': 'x', 'entryMode': 'keyword_interactive', 'entryTemplateName': 't'}),
           'keyword flow with template accepted')
    expect(fl.registry_errors({'flowId': 'x', 'entryMode': 'keyword_interactive', 'requiresPayment': True}),
           'payment-gated keyword flow accepted')
    expect(not fl.registry_errors({'flowId': 'x', 'entryMode': 'keyword_interactive', 'requiresPayment': 'false'}),
           '"false" string must parse as False')
    expect(not fl.registry_errors({'flowId': 'x', 'entryMode': 'payment_template', 'entryTemplateName': 'wd_paid',
                                   'requiresPayment': True}), 'valid payment_template rejected')
    expect(not fl.registry_errors(published_registry_row()), 'valid F001 row rejected')
    for change in ({'entryMode': 'payment_template', 'entryTemplateName': 't', 'requiresPayment': True},
                   {'entryMode': 'internal_event'}, {'requiresPayment': True}, {'submissionPrefix': 'WD'},
                   {'flowCode': 'OTHER'}, {'wabaId': '999'}, {'entryTemplateName': 'feedback_survey_form_1'}):
        expect(fl.registry_errors(published_registry_row(**change)), f'F001 row accepted with {change}')


@check('D2 keyword launch needs canonical, registry, Meta and runtime controls to agree')
def _() -> None:
    fl, cf = M['flow_launch'], M['canonical_flows']
    on = {'enabled': True, 'entryMode': 'keyword_interactive'}

    def reason(row: Any, trigger: Any) -> str:
        return fl.keyword_launch_decision(capability='subscribe', registry_row=row, trigger=trigger).reason
    expect(reason(published_registry_row(), {'enabled': False}) == 'runtime_disabled', 'switch OFF')
    expect(reason(None, on) == 'registry_missing', 'missing registry')
    expect(reason(published_registry_row(status='DRAFT'), on) == 'registry_not_published', 'registry DRAFT')
    expect(reason(published_registry_row(metaStatus='DRAFT'), on) == 'meta_not_published', 'Meta DRAFT')
    expect(reason(published_registry_row(metaStatus='DEPRECATED'), on) == 'meta_not_published', 'Meta DEPRECATED')
    expect(reason(published_registry_row(metaStatus='THROTTLED'), on) == 'allowed', 'THROTTLED still delivers')
    expect(reason(published_registry_row(requiresPayment=True), on) == 'registry_contradiction', 'contradiction')
    expect(reason(published_registry_row(), {'enabled': True, 'entryMode': 'payment_template'}) == 'runtime_entry_mode',
           'runtime entry mode')
    expect(reason(published_registry_row(), on) == 'allowed', 'all controls agree')
    saved = cf.CANONICAL_FLOWS['subscribe']
    try:
        cf.CANONICAL_FLOWS['subscribe'] = (saved[0], 'DRAFT', saved[2])
        expect(reason(published_registry_row(), on) == 'canonical_not_published', 'DRAFT canonical launched')
        expect(fl.registry_errors(published_registry_row()), 'registry PUBLISHED accepted while canonical DRAFT')
    finally:
        cf.CANONICAL_FLOWS['subscribe'] = saved


@check('D3 staff sends need Operator+, ignore the keyword switch, and keep publication gates')
def _() -> None:
    fl = M['flow_launch']

    def reason(row: Any, role: str) -> str:
        return fl.manual_launch_decision(capability='subscribe', registry_row=row, role=role).reason
    expect(reason(published_registry_row(), 'Viewer') == 'role_insufficient', 'Viewer allowed')
    expect(reason(published_registry_row(), '') == 'role_insufficient', 'anonymous allowed')
    expect(reason(published_registry_row(), 'Operator') == 'allowed', 'Operator refused')
    expect(reason(published_registry_row(status='DRAFT'), 'Admin') == 'registry_not_published', 'DRAFT registry')


@check('D4 generic keyword triggers cannot open paid, event, staff-only or other contract Flows')
def _() -> None:
    fl = M['flow_launch']
    expect(fl.generic_keyword_refusal('custom_x', F001_ID(), None) == 'contract_flow_elsewhere', 'F001 via custom key')
    expect(fl.generic_keyword_refusal('custom_x', '111', {'requiresPayment': True}) == 'registry_payment_gated', 'paid')
    for mode in ('payment_template', 'internal_event', 'manual'):
        expect(fl.generic_keyword_refusal('custom_x', '111', {'entryMode': mode}) == 'registry_not_keyword', mode)
    expect(fl.generic_keyword_refusal('order_notes', '111', {'entryMode': 'none'}) == '', 'legacy row kept working')
    expect(fl.generic_keyword_refusal('order_notes', '111', None) == '', 'unregistered flow kept working')


@check('D5 runtime trigger: exact normalized keywords and the canonical Flow ID only')
def _() -> None:
    fl = M['flow_launch']
    trigger = fl.runtime_trigger('subscribe', {'enabled': True, 'keywords': [' Sign  Up ', 'JOIN', 7, 'join'],
                                               'flowId': '999999'})
    expect(trigger['keywords'] == ['sign up', 'join'] and trigger['flowId'] == F001_ID(), f'{trigger}')
    default = fl.runtime_trigger('subscribe', None)
    expect(default['enabled'] is False and tuple(default['keywords']) == tuple(
        M['canonical_flows'].CANONICAL_CONTRACTS['subscribe']['defaultKeywords']), 'defaults OFF with contract keywords')


# ── E. Business API: registry, sync, status, staff send, route authorization ─────────

ADMIN = {'username': 'admin@example.test', 'role': 'Admin'}
OPERATOR = {'username': 'operator@example.test', 'role': 'Operator'}
VIEWER = {'username': 'viewer@example.test', 'role': 'Viewer'}


def _resp(out: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    return out['statusCode'], json.loads(out.get('body') or '{}')


@check('E1 registry upsert validates the merged row, records the editor and refuses lost updates')
def _() -> None:
    FAKE_DB.reset()
    biz = M['bizapi']
    status, _ = _resp(biz._upsert_flow_registry({'flowId': F001_ID()}, auth=None))
    expect(status == 403, 'anonymous registry write allowed')
    contract = M['canonical_flows'].canonical_contract('subscribe')
    status, body = _resp(biz._upsert_flow_registry({
        'flowId': F001_ID(), 'flowCode': contract['flowCode'], 'flowName': 'Subscribe',
        'entryMode': 'keyword_interactive', 'submissionPrefix': contract['submissionPrefix']}, auth=ADMIN))
    expect(status == 200 and body['flow']['status'] == 'DRAFT' and body['flow']['updatedBy'] == ADMIN['username'],
           f'create: {status} {body}')
    status, body = _resp(biz._upsert_flow_registry({'flowId': F001_ID(), 'status': 'PUBLISHED'}, auth=ADMIN))
    expect(status == 200 and body['flow']['entryMode'] == 'keyword_interactive'
           and body['flow']['flowCode'] == contract['flowCode'], f'partial update lost fields: {body}')
    status, body = _resp(biz._upsert_flow_registry({'flowId': F001_ID(), 'requiresPayment': True}, auth=ADMIN))
    expect(status == 400 and any('must not require payment' in e for e in body.get('errors', [])),
           f'payment-gating F001: {status} {body}')
    status, body = _resp(biz._upsert_flow_registry({'flowId': F001_ID(), 'entryMode': 'payment_template',
                                                    'entryTemplateName': 'feedback_survey_form_1',
                                                    'requiresPayment': True}, auth=ADMIN))
    expect(status == 400, 'F001 turned into a template journey')
    status, _ = _resp(biz._upsert_flow_registry({'flowId': 'generic1', 'flowCode': 'G1',
                                                 'entryMode': 'payment_template', 'requiresPayment': True}, auth=ADMIN))
    expect(status == 400, 'payment_template without template accepted')

    def concurrent(tbl: FakeTable, operation: str) -> None:
        tbl.before_write = None
        tbl.items[F001_ID()]['updatedAt'] = Decimal('1')
    registry().before_write = concurrent
    status, _ = _resp(biz._upsert_flow_registry({'flowId': F001_ID(), 'flowName': 'Subscribe v2'}, auth=ADMIN))
    expect(status == 409, f'lost update not detected: {status}')


@check('E2 Meta sync records metaStatus and never changes the registry status')
def _() -> None:
    FAKE_DB.reset()
    biz = M['bizapi']
    biz._graph_api = lambda *a, **k: {'data': [{'id': F001_ID(), 'name': 'WD-F001-SUBSCRIBE-PROFILE',
                                                 'status': 'PUBLISHED', 'json_version': '7.3'}]}
    status, body = _resp(biz._sync_flows({'wabaId': '2094615664435155'}, {}))
    expect(status == 200 and body['synced'] == 1, f'sync: {body}')
    row = registry().items[F001_ID()]
    expect(row['status'] == 'DRAFT' and row['metaStatus'] == 'PUBLISHED', f'new row status {row["status"]}')
    expect(row['entryMode'] == 'keyword_interactive' and row['submissionPrefix'] == 'WD-SUB', 'seeded from contract')
    row['status'] = 'DRAFT'
    biz._graph_api = lambda *a, **k: {'data': [{'id': F001_ID(), 'name': 'WD-F001-SUBSCRIBE-PROFILE',
                                                 'status': 'DEPRECATED'},
                                                {'id': '1557815099200456', 'name': 'WD_Flow_Subscribe_01',
                                                 'status': 'DEPRECATED'}]}
    status, body = _resp(biz._sync_flows({'wabaId': '2094615664435155'}, {}))
    row = registry().items[F001_ID()]
    expect(row['status'] == 'DRAFT' and row['metaStatus'] == 'DEPRECATED', 'sync overwrote registry status')
    expect('1557815099200456' not in registry().items and body['notRegistered'] == 1 and body['synced'] == 1,
           f'a first-seen deprecated Flow was registered: {body}')


@check('E3 launch status explains every control from the server decision')
def _() -> None:
    FAKE_DB.reset()
    biz = M['bizapi']
    status, body = _resp(biz._flow_launch_status({'capability': 'subscribe'}, auth=OPERATOR))
    expect(status == 200 and body['keywordLaunch']['reason'] == 'runtime_disabled', f'{body.get("keywordLaunch")}')
    expect(body['manualLaunch']['reason'] == 'registry_missing', 'manual needs the registry')
    registry().items[F001_ID()] = published_registry_row()
    system_config().items['flow_triggers_config'] = {'id': 'flow_triggers_config', 'configValue': json.dumps(
        {'subscribe': {'enabled': True, 'keywords': ['subscribe'], 'entryMode': 'keyword_interactive'}})}
    status, body = _resp(biz._flow_launch_status({'capability': 'subscribe'}, auth=OPERATOR))
    expect(body['keywordLaunch']['allowed'] and body['manualLaunch']['allowed'], f'{body}')
    expect(_resp(biz._flow_launch_status({'capability': 'nope'}))[0] == 404, 'unknown capability')


@check('E4 staff send: Operator+, server-minted session with initiator, data_exchange, managed copy')
def _() -> None:
    FAKE_DB.reset()
    biz = M['bizapi']
    sent: List[Dict[str, Any]] = []
    biz._send_message = lambda phone_id, message, body=None: (sent.append({'message': message, 'body': body})
                                                              or biz._resp(200, {'success': True, 'messageId': 'wamid.X'}))
    request = {'flowKey': 'subscribe', 'to': f'+{PHONE_A}'}
    expect(_resp(biz._send_flow_msg(dict(request), auth=VIEWER))[0] == 403, 'Viewer could send F001')
    expect(_resp(biz._send_flow_msg(dict(request), auth=OPERATOR))[0] == 409, 'sent with no registry row')
    registry().items[F001_ID()] = published_registry_row()
    expect(_resp(biz._send_flow_msg({**request, 'flowToken': 'subscribe-x-waba-1-ph-1'}, auth=OPERATOR))[0] == 400,
           'client token accepted')
    expect(_resp(biz._send_flow_msg({**request, 'mode': 'draft'}, auth=OPERATOR))[0] == 400, 'draft mode accepted')
    status, body = _resp(biz._send_flow_msg(dict(request), auth=OPERATOR))
    expect(status == 200 and body['flowCode'] == F001_CODE() and body['sessionExpiresAt'] > time.time(), f'{body}')
    params = sent[-1]['message']['interactive']['action']['parameters']
    expect(params['flow_action'] == 'data_exchange' and params['flow_id'] == F001_ID(), 'opens with INIT')
    expect(params['flow_token'].startswith('subscribe-') and params['flow_token'].endswith(f'-waba-1-ph-{PHONE_A}'),
           'session token shape')
    expect(sent[-1]['body'] == {'to': PHONE_A}, 'delivered to the session phone')
    expect(sent[-1]['message']['interactive']['body']['text'] == M['subscribe_messages'].DEFAULTS['newCustomer']['body'],
           'managed new-customer copy')
    session_rows = list(sessions().items.values())
    expect(len(session_rows) == 1 and session_rows[0]['launchChannel'] == 'staff_send'
           and session_rows[0]['initiatedBy'] == OPERATOR['username'], 'initiator recorded on the session')
    expect(flow_call('INIT', '', {}, params['flow_token'])['status'] == 200, 'the staff-sent link opens')


@check('E5 route authorization: Admin for registry/publish, Operator for customer records')
def _() -> None:
    FAKE_DB.reset()
    biz, middleware = M['bizapi'], M['middleware']
    rank = {'Viewer': 1, 'Operator': 2, 'Admin': 3}

    def fake_require_auth(event: Dict[str, Any], required_role: Optional[str] = None) -> Optional[Dict[str, Any]]:
        role = event.get('_test_role', '')
        if not role:
            return {'statusCode': 401, 'body': '{}'}
        if required_role and rank.get(role, 0) < rank[required_role]:
            return {'statusCode': 403, 'body': json.dumps({'error': 'Insufficient permissions'})}
        event['_auth'] = {'username': f'{role.lower()}@example.test', 'role': role}
        return None
    saved = (biz.require_auth, middleware.require_auth)
    biz.require_auth = middleware.require_auth = fake_require_auth
    try:
        def call(method: str, path: str, role: str, body: Optional[Dict[str, Any]] = None) -> int:
            event = {'requestContext': {'http': {'method': method, 'path': path, 'sourceIp': '203.0.113.9'},
                                        'apiId': 'test'}, 'headers': {}, '_test_role': role,
                     'body': json.dumps(body or {}), 'queryStringParameters': {'capability': 'subscribe'}}
            return biz.handler(event, None)['statusCode']
        expect(call('POST', '/wa-business/flow-registry', 'Operator', {'flowId': 'x'}) == 403, 'Operator wrote registry')
        expect(call('POST', '/wa-business/flow-registry', 'Admin', {'flowId': 'zzz', 'flowCode': 'Z'}) == 200, 'Admin refused')
        expect(call('POST', '/wa-business/flows/publish', 'Operator', {'flowId': 'x'}) == 403, 'Operator published')
        expect(call('GET', '/wa-business/flows/publish', 'Admin') == 405, 'GET publishes')
        expect(call('GET', '/wa-business/flow-logs', 'Viewer') == 403, 'Viewer read flow logs')
        expect(call('GET', '/wa-business/flow-customer-journey', 'Viewer') == 403, 'Viewer read journeys')
        expect(call('GET', '/wa-business/flow-launch-status', 'Viewer') == 200, 'status hidden from Viewer')
        expect(call('POST', '/wa-business/messages/send/flow', 'Viewer', {'flowKey': 'subscribe', 'to': PHONE_A}) == 403,
               'Viewer sent F001')
    finally:
        biz.require_auth, middleware.require_auth = saved


def _role_gate(event: Dict[str, Any], required_role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Stand-in for `require_auth` keyed on the test event's `_test_role` (no Cognito)."""
    rank = {'Viewer': 1, 'Operator': 2, 'Admin': 3}
    role = event.get('_test_role', '')
    if not role:
        return {'statusCode': 401, 'body': '{}'}
    if required_role and rank.get(role, 0) < rank[required_role]:
        return {'statusCode': 403, 'body': json.dumps({'error': 'Insufficient permissions'})}
    event['_auth'] = {'username': f'{role.lower()}@example.test', 'role': role}
    return None


def _staff_event(method: str, path: str, role: str, body: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {'requestContext': {'http': {'method': method, 'path': path, 'sourceIp': '203.0.113.9'},
                               'apiId': 'test'}, 'headers': {}, '_test_role': role,
            'body': json.dumps(body or {}), 'queryStringParameters': params or {}}


@check('E6 /flow-data logs whether the Meta signature verifies and never changes the answer')
def _() -> None:
    FAKE_DB.reset()
    biz, signature = M['bizapi'], M['meta_signature']
    token = new_session()
    payload = {'version': '3.0', 'action': 'INIT', 'screen': '', 'data': {}, 'flow_token': token}
    biz._decrypt_flow_request = lambda *_: (copy.deepcopy(payload), b'k', b'i')
    biz._encrypt_flow_response = lambda response, *_: json.dumps(response)
    raw = json.dumps({'encrypted_flow_data': 'x', 'encrypted_aes_key': 'y', 'initial_vector': 'z'})
    saved_secret = biz._get_app_secret

    def post(headers: Dict[str, str]) -> Tuple[int, List[str]]:
        start = len(LOGS.lines)
        # No API Gateway context: the same auth path Meta's callback takes via AUTH_SKIP_PATHS.
        out = biz.handler({'requestContext': {'http': {'method': 'POST', 'path': '/wa-business/flow-data'}},
                           'headers': headers, 'body': raw}, None)
        return out['statusCode'], [line for line in LOGS.lines[start:] if 'flow_endpoint_signature' in line]
    try:
        biz._get_app_secret = lambda *a, **k: 'test-app-secret'
        good = signature.expected_signature('test-app-secret', raw)
        for headers, verified, reason in (({'X-Hub-Signature-256': good}, True, 'ok'),
                                          ({}, False, 'missing_signature'),
                                          ({'x-hub-signature-256': 'sha256=' + '0' * 64}, False, 'signature_mismatch')):
            status, lines = post(headers)
            expect(status == 200, f'{reason}: the answer changed (HTTP {status})')
            expect(len(lines) == 1 and json.loads(lines[0]) == {
                'event': 'flow_endpoint_signature', 'verified': verified, 'reason': reason,
                'requestId': json.loads(lines[0]).get('requestId')}, f'{reason}: logged {lines}')

        def unavailable(*_: Any, **__: Any) -> str:
            raise RuntimeError('secrets unavailable')
        biz._get_app_secret = unavailable
        status, lines = post({'X-Hub-Signature-256': good})
        expect(status == 200 and lines and '"verify_error:RuntimeError"' in lines[0],
               f'a failed observation broke the Flow: HTTP {status} {lines}')
    finally:
        biz._get_app_secret = saved_secret


@check('E7 Flow asset readback is read-only and numeric-only; Flow metadata updates need Admin')
def _() -> None:
    FAKE_DB.reset()
    biz, middleware = M['bizapi'], M['middleware']
    graph_calls: List[Tuple[str, str]] = []

    def fake_graph(endpoint: str, method: str = 'GET', *a: Any, **k: Any) -> Dict[str, Any]:
        graph_calls.append((endpoint, method))
        if endpoint.endswith('/assets'):
            return {'data': [{'name': 'flow.json', 'asset_type': 'FLOW_JSON',
                              'download_url': 'https://example.test/flow.json'}]}
        return {'success': True}
    saved = (biz.require_auth, middleware.require_auth, biz._graph_api)
    biz.require_auth = middleware.require_auth = _role_gate
    biz._graph_api = fake_graph
    try:
        expect(_resp(biz._get_flow_assets('123/../me'))[0] == 400 and not graph_calls, 'non-numeric flowId reached Graph')
        expect(_resp(biz._get_flow_assets('１２３'))[0] == 400, 'non-ASCII digits accepted')
        out = biz.handler(_staff_event('GET', '/wa-business/flows/assets', 'Viewer', params={'flowId': F001_ID()}), None)
        status, body = _resp(out)
        expect(status == 200 and body['assets'] == [{'name': 'flow.json', 'assetType': 'FLOW_JSON',
                                                    'downloadUrl': 'https://example.test/flow.json'}], f'{status} {body}')
        expect(graph_calls == [(f'{F001_ID()}/assets', 'GET')], f'readback was not a single GET: {graph_calls}')
        graph_calls.clear()
        update = {'flowId': F001_ID(), 'endpoint_uri': 'https://example.test/elsewhere'}
        expect(biz.handler(_staff_event('PUT', '/wa-business/flows', 'Operator', update), None)['statusCode'] == 403
               and not graph_calls, 'Operator repointed a Flow endpoint')
        expect(biz.handler(_staff_event('PUT', '/wa-business/flows', 'Admin', update), None)['statusCode'] == 200
               and graph_calls == [(F001_ID(), 'POST')], f'Admin update refused: {graph_calls}')
    finally:
        biz.require_auth, middleware.require_auth, biz._graph_api = saved


@check('E8 keyword triggers and Subscribe copy need Operator to change; other settings keep the staff floor')
def _() -> None:
    FAKE_DB.reset()
    ai, middleware = M['ai_config'], M['middleware']
    config_rows = table(ai.SYSTEM_CONFIG_TABLE).items
    saved = middleware.require_auth
    middleware.require_auth = _role_gate
    try:
        def put(role: str, key: str) -> int:
            body = {'key': key, 'config': {'subscribe': {'enabled': True}}}
            return ai.handler(_staff_event('PUT', '/ai/config', role, body), None)['statusCode']
        for key in ('flow_triggers_config', 'subscribe_messages_config'):
            expect(put('Viewer', key) == 403 and key not in config_rows, f'Viewer changed {key}')
            expect(put('Operator', key) == 200 and key in config_rows, f'Operator could not change {key}')
        expect(put('Viewer', 'welcome_message') == 200 and 'welcome_message' in config_rows,
               'an unrelated setting lost the staff floor')
        reader = _staff_event('GET', '/ai/config', 'Viewer', params={'key': 'flow_triggers_config'})
        expect(ai.handler(reader, None)['statusCode'] == 200, 'Viewer can no longer read keyword triggers')
    finally:
        middleware.require_auth = saved


@check('E9 webhook subscription changes need Admin; Meta sync follows pages, bounded')
def _() -> None:
    FAKE_DB.reset()
    biz, middleware = M['bizapi'], M['middleware']
    graph_calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def fake_graph(endpoint: str, method: str = 'GET', payload: Any = None, params: Any = None,
                   *a: Any, **k: Any) -> Dict[str, Any]:
        graph_calls.append((endpoint, method, dict(params or {})))
        if endpoint.endswith('/flows'):
            page = sum(1 for e, _, _ in graph_calls if e.endswith('/flows'))
            return {'data': [{'id': f'90{page}', 'name': f'Draft {page}', 'status': 'DRAFT'}],
                    'paging': {'cursors': {'after': f'c{page}'}, 'next': 'https://graph.example.test/next'}}
        return {'success': True, 'data': []}
    saved = (biz.require_auth, middleware.require_auth, biz._graph_api)
    biz.require_auth = middleware.require_auth = _role_gate
    biz._graph_api = fake_graph
    try:
        for method in ('POST', 'DELETE'):
            event = _staff_event(method, '/wa-business/webhooks', 'Operator', {'wabaId': '2094615664435155'})
            expect(biz.handler(event, None)['statusCode'] == 403 and not graph_calls, f'Operator {method} on webhooks')
        expect(biz.handler(_staff_event('GET', '/wa-business/webhooks', 'Viewer',
                                        params={'wabaId': '2094615664435155'}), None)['statusCode'] == 200,
               'Viewer can no longer read webhook subscriptions')
        expect(biz.handler(_staff_event('DELETE', '/wa-business/webhooks', 'Admin', {'wabaId': '2094615664435155'}),
                           None)['statusCode'] != 403, 'Admin refused')
        graph_calls.clear()
        status, body = _resp(biz._sync_flows({'wabaId': '2094615664435155'}, {}))
        pages = [c for c in graph_calls if c[0].endswith('/flows')]
        expect(status == 200 and len(pages) == biz._SYNC_MAX_PAGES and body['total'] == biz._SYNC_MAX_PAGES,
               f'pagination unbounded or not followed: {len(pages)} pages, {body}')
        expect(pages[1][2].get('after') == 'c1' and pages[0][2].get('limit') == str(biz._SYNC_PAGE_SIZE),
               f'cursor not passed: {pages[:2]}')
    finally:
        biz.require_auth, middleware.require_auth, biz._graph_api = saved


# ── F. Inbound keyword dispatch (extracted from the real handler source) ────────────

class FakeLambda:
    def __init__(self) -> None:
        self.invocations: List[Dict[str, Any]] = []

    def invoke(self, FunctionName: str, InvocationType: str, Payload: str, **_: Any) -> Dict[str, Any]:
        body = json.loads(json.loads(Payload)['body'])
        token = (body.get('interactiveData') or {}).get('flowToken', '')
        fs = M['flow_sessions']
        session_present = bool(token) and fs.session_key(fs.phone_from_token(token), token) in sessions().items
        self.invocations.append({'body': body, 'session_present': session_present})
        return {'StatusCode': 202}


def load_inbound() -> None:
    tree = ast.parse(INBOUND.read_text(encoding='utf-8'))
    wanted_assign = {'DEFAULT_FLOW_TRIGGERS', 'F001_CONTRACT', 'F001_SESSION_UNAVAILABLE_REPLY',
                     'CUSTOMER_IDEA_KEYWORDS', 'FLOW_LINKS', 'FLOW_LINK_DEFAULT', 'FLOW_LINK_BODIES',
                     'UNREADABLE_MESSAGE_LABELS', 'UNREADABLE_HINT_TEXT',
                     'UNREADABLE_HINT_INTERVAL_SECONDS'}
    wanted_func = {'_get_flow_triggers_config', '_send_generic_flow', '_launch_subscribe_flow',
                   '_send_flow_link', '_send_unreadable_hint'}
    nodes: List[ast.stmt] = [n for n in tree.body if (
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted_assign for t in n.targets)
    ) or (isinstance(n, ast.FunctionDef) and n.name in wanted_func)]
    process = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_process_message')
    loop = next(n for n in ast.walk(process) if isinstance(n, ast.For)
                and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Attribute)
                and isinstance(n.iter.func.value, ast.Name) and n.iter.func.value.id == 'flow_triggers')
    my_id_assign = next(n for n in ast.walk(process) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'MY_ID_KEYWORDS' for t in n.targets))
    my_id_if = next(n for n in ast.walk(process) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                    and isinstance(n.test.comparators[0], ast.Name) and n.test.comparators[0].id == 'MY_ID_KEYWORDS')

    def wrapper(name: str, params: List[str], body: List[ast.stmt]) -> ast.FunctionDef:
        fields: Dict[str, Any] = {'name': name, 'args': ast.arguments(
            posonlyargs=[], args=[ast.arg(arg=p) for p in params], kwonlyargs=[], kw_defaults=[], defaults=[]),
            'body': body + [ast.Return(ast.Constant('fell_through'))], 'decorator_list': [], 'returns': None}
        if 'type_params' in ast.FunctionDef._fields:
            fields['type_params'] = []
        return ast.FunctionDef(**fields)
    common_params = ['content_lower', 'contact_id', 'aws_phone_number_id', 'sender_phone', 'request_id']
    nodes.append(wrapper('dispatch_keyword', common_params + ['flow_triggers'], [loop]))
    nodes.append(wrapper('my_id_command', common_params, [my_id_assign, my_id_if]))
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    privacy = M['privacy']
    M['cta'], M['replies'], M['lambda'] = [], [], FakeLambda()
    import importlib.util
    content_spec = importlib.util.spec_from_file_location('inbound_content', INBOUND.parent / 'modules' / 'content.py')
    M['inbound_content'] = importlib.util.module_from_spec(content_spec)
    content_spec.loader.exec_module(M['inbound_content'])
    ns: Dict[str, Any] = {
        'ClientError': FakeClientError,
        'UNSUPPORTED_UNKNOWN': M['inbound_content'].UNSUPPORTED_UNKNOWN,
        'UNSUPPORTED_DISAPPEARING': M['inbound_content'].UNSUPPORTED_DISAPPEARING,
        'json': json, 'uuid': uuid, 'time': time, 'Decimal': Decimal, 'Dict': Dict, 'Any': Any,
        'Optional': Optional, 'logger': logging.getLogger('inbound-under-test'), 'dynamodb': FAKE_DB,
        'CONTACTS_TABLE': M['common'].CONTACTS_TABLE, 'SYSTEM_CONFIG_TABLE': M['subscribe_messages'].system_config_table_name(),
        'FLOW_SUBMISSIONS_TABLE': M['common'].FLOW_SUBMISSIONS_TABLE, 'PHONE_NUMBER_ID_1': 'phone1',
        'PHONE_NUMBER_ID_2': 'phone2', 'OUTBOUND_WHATSAPP_FUNCTION': 'outbound', 'lambda_client': M['lambda'],
        'mask_contact_id': privacy.mask_contact_id, 'mask_phone': privacy.mask_phone,
        'mask_flow_token': privacy.mask_flow_token, 'contact_store': M['contact_store'],
        'flow_launch': M['flow_launch'], 'flow_sessions': M['flow_sessions'], 'flow_funnel': M['flow_funnel'],
        'subscribe_messages': M['subscribe_messages'], 'customer_uuid': M['customer_uuid'],
        'canonical_flow_id': M['canonical_flows'].canonical_flow_id,
        'canonical_contract': M['canonical_flows'].canonical_contract, '_may_send': lambda purpose: True,
        '_send_cta_button': lambda *a, **k: M['cta'].append({'args': a, 'kwargs': k}),
        '_send_ai_auto_reply': lambda contact_id, content, *a: M['replies'].append(content),
    }
    exec(compile(module, str(INBOUND), 'exec'), ns)  # noqa: S102 - our own handler source
    M['inbound'] = ns


def dispatch(content: str, phone: str = PHONE_A, waba: str = 'phone1') -> str:
    ns = M['inbound']
    return ns['dispatch_keyword'](content, f'wa{phone}', waba, phone, 'req-in', ns['_get_flow_triggers_config']())


def set_triggers(config: Dict[str, Any]) -> None:
    system_config().items['flow_triggers_config'] = {'id': 'flow_triggers_config', 'configValue': json.dumps(config)}


def reset_inbound() -> None:
    FAKE_DB.reset()
    M['cta'].clear()
    M['replies'].clear()
    M['lambda'].invocations.clear()


@check('F1 inbound default: F001 keywords from the contract, switch OFF, no message, no WABA 2 Flow')
def _() -> None:
    default = M['inbound']['DEFAULT_FLOW_TRIGGERS']['subscribe']
    contract = M['canonical_flows'].CANONICAL_CONTRACTS['subscribe']
    expect(tuple(default['keywords']) == tuple(contract['defaultKeywords']), 'keywords')
    expect(default['enabled'] is False and default['entryMode'] == 'keyword_interactive', 'OFF, keyword mode')
    expect(default['flowId'] == F001_ID() and 'message' not in default and 'flowId2' not in default, 'shape')


@check('F2 keyword door stays shut until every control agrees, and says why')
def _() -> None:
    reset_inbound()
    expect(dispatch('subscribe') == 'fell_through' and not M['lambda'].invocations, 'launched while OFF')
    set_triggers({'subscribe': {'enabled': True}})
    expect(dispatch('subscribe') == 'fell_through', 'launched with no registry row')
    registry().items[F001_ID()] = published_registry_row(status='DRAFT')
    expect(dispatch('subscribe') == 'fell_through', 'launched with DRAFT registry')
    registry().items[F001_ID()] = published_registry_row(metaStatus='DRAFT')
    expect(dispatch('subscribe') == 'fell_through', 'launched while Meta DRAFT')
    totals = funnel_totals()
    expect(totals['launch_attempted'] == 4 and totals['launch_blocked'] == 4, f'funnel {totals}')


@check('F3 published + enabled: exact keyword sends the Flow with a session recorded first')
def _() -> None:
    reset_inbound()
    set_triggers({'subscribe': {'enabled': True, 'flowId': '999999999'}})
    registry().items[F001_ID()] = published_registry_row()
    expect(dispatch('sign up') is None, 'exact keyword did not launch')
    call = M['lambda'].invocations[-1]
    data = call['body']['interactiveData']
    expect(data['flowId'] == F001_ID(), 'stored flowId override must not change the Flow')
    expect(data['flowAction'] == 'data_exchange' and data['flowToken'].startswith('subscribe-'), 'opens with INIT')
    expect(data['flowToken'].endswith(f'-waba-1-ph-{PHONE_A}') and call['session_present'], 'session before send')
    expect(data['body'] == M['subscribe_messages'].DEFAULTS['newCustomer']['body'], 'new-customer copy')
    expect(flow_call('INIT', '', {}, data['flowToken'])['status'] == 200, 'the keyword link opens')
    for near_miss in ('subscribe now', 'please subscribe', 'subscribed', 'sub'):
        expect(dispatch(near_miss) == 'fell_through', f'{near_miss!r} launched (not exact)')


@check('F4 returning customers get the returning copy; WABA 2 is sent on to WABA 1, with no session')
def _() -> None:
    reset_inbound()
    set_triggers({'subscribe': {'enabled': True}})
    registry().items[F001_ID()] = published_registry_row()
    contacts().items[f'wa{PHONE_B}'] = {'id': f'wa{PHONE_B}', 'contactId': f'wa{PHONE_B}', 'phone': f'+{PHONE_B}',
                                        'checkoutDeliveryAddress': {'addressLine1': STREET_A, 'city': 'Springfield',
                                                                    'state': 'Oregon', 'postalCode': '97477',
                                                                    'country': 'United States', 'countryCode': 'US'}}
    dispatch('subscribe', PHONE_B)
    expect(M['lambda'].invocations[-1]['body']['interactiveData']['body']
           == M['subscribe_messages'].DEFAULTS['returningCustomer']['body'], 'returning copy')
    before = len(sessions().items)
    dispatch('subscribe', PHONE_A, waba='phone2')
    expect(M['cta'] and M['cta'][-1]['args'][3] == 'https://wa.me/919330994400?text=subscribe',
           f'WABA 2 must continue on WABA 1 with the keyword typed, got {M["cta"][-1]["args"][3] if M["cta"] else None}')
    expect(len(sessions().items) == before, 'no session for the link fallback')


@check('F5 a session-store failure sends no Flow and tells the customer to retry')
def _() -> None:
    reset_inbound()
    set_triggers({'subscribe': {'enabled': True}})
    registry().items[F001_ID()] = published_registry_row()
    sessions().fail_next['put_item'] = FakeClientError({'Error': {'Code': 'InternalServerError'}}, 'PutItem')
    dispatch('subscribe')
    expect(not M['lambda'].invocations, 'Flow sent without a session')
    expect(M['replies'] and 'try again' in M['replies'][-1], 'customer not told')
    expect(funnel_totals()['launch_failed'] == 1, 'failure not counted')


@check('F6 generic triggers: payment or contract Flows never open from a keyword')
def _() -> None:
    reset_inbound()
    set_triggers({'custom_vip': {'enabled': True, 'keywords': ['vipform'], 'flowId': F001_ID()},
                  'custom_paid': {'enabled': True, 'keywords': ['paidform'], 'flowId': '7777'},
                  'custom_ok': {'enabled': True, 'keywords': ['okform'], 'flowId': '8888'}})
    registry().items['7777'] = {'flowId': '7777', 'entryMode': 'payment_template', 'requiresPayment': True,
                                'entryTemplateName': 'wd_paid'}
    registry().items['8888'] = {'flowId': '8888', 'status': 'PUBLISHED', 'metaStatus': 'PUBLISHED'}
    expect(dispatch('vipform') == 'fell_through' and not M['lambda'].invocations, 'F001 opened via a custom key')
    expect(dispatch('paidform') == 'fell_through' and not M['lambda'].invocations, 'paid Flow opened by keyword')
    expect(dispatch('okform') is None and M['lambda'].invocations, 'ordinary keyword Flow stopped working')


def _cta_link() -> Optional[str]:
    return M['cta'][-1]['args'][3] if M['cta'] else None


@check('F8 a keyword Flow not known live on Meta answers with its working link, never a dead Flow')
def _() -> None:
    reset_inbound()
    links = M['inbound']['FLOW_LINKS']
    expect(not any('/r/' in url for url in [*links.values(), M['inbound']['FLOW_LINK_DEFAULT']]),
           'a fallback points at an /r/ short code (six are google.com recovery rows)')
    # track_request has no Flow at all.
    expect(dispatch('track') is None and _cta_link() == links['track_request'] and not M['lambda'].invocations,
           f'no-Flow door: {_cta_link()}')
    # rx_slot names a Flow that FlowRegistry has never seen (it no longer exists on Meta).
    expect(dispatch('pharmacy') is None and _cta_link() == links['rx_slot'] and not M['lambda'].invocations,
           f'unregistered Flow: {_cta_link()}')
    # A generic (non-contract) door: its Flow opens only while FlowRegistry shows it live on Meta.
    # (Not leave_review: F002 made that a canonical door with its own launch policy.)
    set_triggers({'custom_live': {'enabled': True, 'keywords': ['liveform'], 'flowId': '8888'}})
    registry().items['8888'] = {'flowId': '8888', 'status': 'PUBLISHED', 'metaStatus': 'DEPRECATED'}
    expect(dispatch('liveform') is None and _cta_link() == M['inbound']['FLOW_LINK_DEFAULT']
           and not M['lambda'].invocations, 'a deprecated Flow was sent')
    registry().items['8888']['metaStatus'] = 'PUBLISHED'
    expect(dispatch('liveform') is None and M['lambda'].invocations
           and M['lambda'].invocations[-1]['body']['interactiveData']['flowId'] == '8888',
           'a live Flow stopped opening')
    cta_before = len(M['cta'])
    expect(dispatch('pharmacy', waba='phone2') is None and len(M['cta']) == cta_before + 1
           and _cta_link() == links['rx_slot'], 'WABA 2 link path changed')


@check('F9 an unreadable message gets one hint a day; never for an unknown contact or a thread we do not own')
def _() -> None:
    reset_inbound()
    ns, content = M['inbound'], M['inbound_content']
    expect(ns['UNREADABLE_MESSAGE_LABELS'] == {content.UNSUPPORTED_UNKNOWN, content.UNSUPPORTED_DISAPPEARING},
           'labels drifted from modules.content')
    unknown = {'type': 'unsupported', 'unsupported': {'type': 'unknown'},
               'errors': [{'code': 131051, 'title': 'Message type unknown',
                           'error_data': {'details': 'Message type is currently not supported.'}}]}
    otp = {'type': 'unsupported', 'errors': [{'code': 131051, 'error_data': {
        'details': 'OTP authentication message not supported'}}]}
    expect(content.extract_unsupported_content(unknown) in ns['UNREADABLE_MESSAGE_LABELS'], 'measured payload not covered')
    expect(content.extract_unsupported_content(otp) not in ns['UNREADABLE_MESSAGE_LABELS'], 'Meta OTP would be answered')
    contact_id = f'wa{PHONE_A}'
    contacts().items[contact_id] = {'id': contact_id, 'phone': f'+{PHONE_A}'}
    hint, now = ns['_send_unreadable_hint'], 1_800_000_000
    expect(hint(contact_id, 'phone2', now, 'r') and M['replies'][-1] == ns['UNREADABLE_HINT_TEXT'], 'first hint')
    expect(not hint(contact_id, 'phone2', now + 60, 'r') and len(M['replies']) == 1, 'second hint inside a day')
    expect(hint(contact_id, 'phone2', now + ns['UNREADABLE_HINT_INTERVAL_SECONDS'] + 1, 'r')
           and len(M['replies']) == 2, 'no hint the next day')
    expect(not hint('wa15550199999', 'phone2', now, 'r') and 'wa15550199999' not in contacts().items,
           'hint sent to (or row created for) an unknown contact')
    ns['_may_send'] = lambda purpose: False
    try:
        contacts().items[contact_id].pop('unreadableHintAt')
        expect(not hint(contact_id, 'phone2', now, 'r') and len(M['replies']) == 2, 'hint sent on a thread we do not own')
    finally:
        ns['_may_send'] = lambda purpose: True


@check('F10 an unsupported message is not marked read or reacted to, and the hint is wired in')
def _() -> None:
    tree = ast.parse(INBOUND.read_text(encoding='utf-8'))
    process = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_process_message')
    ack = next(n for n in ast.walk(process) if isinstance(n, ast.If) and ast.unparse(n.test) == "msg_type != 'reaction'")
    branch = next(n for n in ack.body if isinstance(n, ast.If))
    expect(ast.unparse(branch.test) == "msg_type == 'unsupported'", 'unsupported is not the first ack branch')
    skipped = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
    expect('_send_direct_api_read_receipt' not in skipped and '_send_direct_api_reaction' not in skipped
           and '_send_read_receipt' not in skipped, 'unsupported branch still acknowledges')
    expect(branch.orelse and '_is_direct_api_phone' in ast.unparse(branch.orelse[0].test), 'other types lost their ack')
    wired = [n for n in ast.walk(process) if isinstance(n, ast.If)
             and ast.unparse(n.test) == "msg_type == 'unsupported' and content in UNREADABLE_MESSAGE_LABELS"]
    expect(wired and '_send_unreadable_hint' in ast.unparse(wired[0]), 'hint not called for unreadable messages')


@check('F7 "my id" answers from the contact row, never from Flow history')
def _() -> None:
    reset_inbound()
    cu = M['customer_uuid'].new_customer_uuid()
    contacts().items[f'wa{PHONE_A}'] = {'id': f'wa{PHONE_A}', 'contactId': f'wa{PHONE_A}', 'phone': f'+{PHONE_A}',
                                        'customerUuid': cu}
    ns = M['inbound']
    expect(ns['my_id_command']('my id', f'wa{PHONE_A}', 'phone1', PHONE_A, 'r') is None, 'command not handled')
    expect(M['customer_uuid'].display_code({'customerUuid': cu}) in M['replies'][-1], f'reply {M["replies"][-1]!r}')
    ns['my_id_command']('my id', f'wa{PHONE_B}', 'phone1', PHONE_B, 'r')
    expect('does not have a WECARE.DIGITAL Customer ID yet' in M['replies'][-1], 'no-ID reply')
    expect(not any(op == 'scan' for op, _ in submissions().calls), 'Flow history scanned')


# ── G. Workspace surfaces (source-level, no browser) ──────────────────────────────────

@check('G1 Workspace copy defaults equal the backend defaults')
def _() -> None:
    source = TS_SETTINGS.read_text(encoding='utf-8')
    for scenario, copy_ in M['subscribe_messages'].DEFAULTS.items():
        for field, value in copy_.items():
            expect(f"'{value}'" in source or f'"{value}"' in source, f'{scenario}.{field} differs in Workspace')


@check('G2 Workspace uses the toast/confirm contexts, never native dialogs')
def _() -> None:
    for path in (TS_SETTINGS, TS_FLOW_HUB, TS_AUTO_RESPONSE):
        text = re.sub(r'//.*|/\*[\s\S]*?\*/', '', path.read_text(encoding='utf-8'))
        # `await confirm(` is the ConfirmContext hook; anything else named alert/confirm/prompt
        # called bare or on `window` is a native dialog.
        text = text.replace('await confirm(', '')
        expect(not re.search(r'(?<![\w.])(window\.)?(alert|confirm|prompt)\s*\(', text),
               f'{path.name} uses a native dialog')


@check('G3 Flow Hub mirrors the entry-mode rules and the F001 contract before saving')
def _() -> None:
    text = TS_FLOW_HUB.read_text(encoding='utf-8')
    for needle in ("entryMode === 'payment_template' && !template", "entryMode === 'payment_template' && !regForm.requiresPayment",
                   "entryMode === 'keyword_interactive' && regForm.requiresPayment", 'contractForFlowId( regForm.flowId )'):
        expect(needle in text, f'Flow Hub lacks {needle!r}')
    expect('preferredGateway' not in text and 'paymentConfigName' not in text, 'dead registry inputs returned')


@check('G4 the generic trigger editor cannot overwrite F001 routing')
def _() -> None:
    text = TS_AUTO_RESPONSE.read_text(encoding='utf-8')
    expect("F001_TRIGGER_KEY = 'subscribe'" in text and 'storedSubscribe' in text, 'F001 entry not preserved on save')
    expect('filter(([k]) => k !== F001_TRIGGER_KEY)' in text, 'F001 still editable in the generic list')


@check('G5 Inbox separates WhatsApp/system identity from customer-entered profile values')
def _() -> None:
    text = TS_INBOX.read_text(encoding='utf-8')
    body = text[text.index('function profileGroups'):text.index('function profileGroups') + 3500]
    identity = body[body.index("'Identity (WhatsApp and system)'"):body.index("'Customer-entered profile'")]
    entered = body[body.index("'Customer-entered profile'"):body.index("title: 'Address'")]
    for label in ('Customer ID', 'Phone', 'Meta WhatsApp username', 'WhatsApp BSUID'):
        expect(f"'{label}'" in identity, f'{label} not in the identity group')
    for label in ('Name', 'WECARE.DIGITAL profile name', 'Organization', 'Job title'):
        expect(f"'{label}'" in entered, f'{label} not in the customer-entered group')
    for label in ('Street address', 'Apartment / suite / unit', 'Landmark / neighborhood', 'City',
                  'State / region', 'Postal code', 'Country'):
        expect(f"'{label}'" in body, f'address row {label} missing')


@check('H1 no captured log line carries a full test phone number, name or street')
def _() -> None:
    leaks = [line for line in LOGS.lines
             if any(secret in line for secret in (PHONE_A, PHONE_B, PHONE_C, PHONE_D, NAME_A, STREET_A))]
    expect(not leaks, f'{len(leaks)} log line(s) leak test PII, first: {leaks[0][:160] if leaks else ""}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--verbose', action='store_true', help='print tracebacks for failures')
    args = parser.parse_args()
    try:
        setup()
    except Exception as exc:  # noqa: BLE001
        print(f'SETUP ERROR: {type(exc).__name__}: {exc}')
        if args.verbose:
            traceback.print_exc()
        return 2
    failures = 0
    for name, fn in CHECKS:
        try:
            fn()
            print(f'[PASS] {name}')
        except Exception as exc:  # noqa: BLE001
            failures += 1
            detail = str(exc) if isinstance(exc, CheckFailed) else f'{type(exc).__name__}: {exc}'
            print(f'[FAIL] {name}: {detail}')
            if args.verbose and not isinstance(exc, CheckFailed):
                traceback.print_exc()
    print(f'\n{len(CHECKS) - failures}/{len(CHECKS)} F001 checks passed '
          '(offline: in-memory tables, stubbed AWS SDK; not a live or handset test)')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
