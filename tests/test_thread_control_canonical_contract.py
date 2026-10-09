"""Literal current Meta contracts; synthetic inputs and mocked Graph boundary."""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(os.environ.get('WECARE_TEST_REPO_ROOT', Path(__file__).resolve().parents[1]))
FIXES = Path(os.environ.get('WECARE_THREAD_FIXES_DIR', ROOT))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules():
    harness = _load('_canonical_control_harness', ROOT / 'tests/test_thread_control.py')
    agent_path = Path(os.environ.get('WECARE_CONTROL_HANDLER_PATH', ROOT /
        'amplify/functions/messaging/meta-business-agent/handler.py'))
    parser_path = Path(os.environ.get('WECARE_OWNER_PARSER_PATH', ROOT /
        'amplify/functions/shared/lambda_utils/thread_ownership.py'))
    with patch('boto3.resource'), patch('boto3.client'):
        agent = _load('_canonical_control_agent', agent_path)
    parser = _load('_canonical_owner_parser', parser_path)
    return harness, agent, parser


@pytest.mark.parametrize('identifiers,expected', [
    ({'bsuid': 'synthetic-business-scoped-id'}, {'recipient': 'synthetic-business-scoped-id'}),
    ({'to': '15550000002'}, {'to': '15550000002'}),
    ({'recipient': '15550000002'}, {'to': '15550000002'}),
])
def test_release_has_literal_flat_recipient(modules, identifiers, expected):
    harness, agent, _ = modules
    result, cap = harness._call(agent, agent._thread_control,
        {'entityId': 'synthetic-phone-id', 'action': 'release', **identifiers})
    assert result['statusCode'] == 200
    assert cap.count == 1
    assert cap.sent == {'messaging_product': 'whatsapp', 'action': 'release', **expected}


def test_two_identifiers_are_rejected_without_graph_request(modules):
    harness, agent, _ = modules
    result, cap = harness._call(agent, agent._thread_control,
        {'entityId': 'synthetic-phone-id', 'bsuid': 'synthetic-id', 'to': '15550000002'})
    assert result['statusCode'] == 400
    assert cap.count == 0


@pytest.mark.parametrize('event', ['control_passed', 'control_taken'])
def test_official_handover_identifies_business_and_peer(modules, event):
    _, _, parser = modules
    result = parser.parse_handover({
        'messaging_product': 'whatsapp', 'type': event, 'timestamp': '1738796547',
        'sender': {'phone_number': '15550000002'},
        'recipient': {'phone_number_id': 'synthetic-phone-id'},
        event: {'previous_owner_role': 'customer_service', 'new_owner_role': 'escalation'},
    })
    assert result['phone_number_id'] == 'synthetic-phone-id'
    assert result['wa_id'] == '15550000002'
    assert result['control'] == event
    assert result['previous_owner_role'] == 'customer_service'
    assert result['new_owner_role'] == 'escalation'
    assert result['shape'] == parser.SHAPE_DOCUMENTED


def test_legacy_contact_and_role_payload_still_parse(modules):
    _, _, parser = modules
    result = parser.parse_handover({
        'metadata': {'phone_number_id': 'legacy-phone-id'},
        'contacts': [{'wa_id': '15550000003', 'user_id': 'legacy-bsuid'}],
        'control_passed': {'previous_owner_app_role': 'legacy-role',
                           'previous_owner_app_id': 'legacy-app-id'},
    })
    assert (result['phone_number_id'], result['wa_id'], result['bsuid']) == (
        'legacy-phone-id', '15550000003', 'legacy-bsuid')
    assert result['shape'] == parser.SHAPE_LEGACY_APP_ROLE


def test_take_remains_refused_without_graph_request(modules):
    harness, agent, _ = modules
    result, cap = harness._call(agent, agent._thread_control,
        {'entityId': 'synthetic-phone-id', 'bsuid': 'synthetic-id', 'action': 'take'})
    assert result['statusCode'] == 409
    assert cap.count == 0
