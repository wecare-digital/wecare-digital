"""Workspace Subscribe wording is bounded and independent of consent/identity."""
import importlib
import json
from unittest.mock import Mock, patch
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

@pytest.fixture
def mod(monkeypatch):
    with patch('boto3.client'), patch('boto3.resource'):
        module=importlib.import_module('flows.subscribe_messages')
    table=Mock()
    table.get_item.return_value={}
    monkeypatch.setattr(module.common.dynamodb,'Table',lambda name:table)
    return module,table


def test_missing_setting_uses_both_defaults(mod):
    module,table=mod
    assert module.copy_for(False)['flowCta']=='Subscribe'
    assert module.copy_for(True)['confirmation']=='Your details have been updated.'
    assert table.get_item.call_args.kwargs=={'Key':{'id':'subscribe_messages_config'},'ConsistentRead':True}


def test_scenarios_are_separate_and_settings_cannot_change_identity_or_consent(mod):
    module,table=mod
    table.get_item.return_value={'Item':{'configValue':json.dumps({
        'newCustomer':{'body':' Welcome new customer ','confirmation':'Saved for you','optInWhatsApp':True},
        'returningCustomer':{'body':'Welcome back','flowCta':'Review details','customerUuid':'forged'},
    })}}
    assert module.copy_for(False)=={'body':'Welcome new customer','flowCta':'Subscribe','confirmation':'Saved for you'}
    assert module.copy_for(True)=={'body':'Welcome back','flowCta':'Review details','confirmation':'Your details have been updated.'}
    table.update_item.assert_not_called()
    table.put_item.assert_not_called()


@pytest.mark.parametrize('stored',['bad json',[],{'newCustomer':{'body':'','flowCta':'x'*21,'confirmation':True}}])
def test_invalid_copy_uses_safe_defaults(mod,stored):
    module,table=mod
    table.get_item.return_value={'Item':{'configValue':stored}}
    assert module.copy_for(False)==module.DEFAULTS['newCustomer']


def test_read_failure_does_not_prevent_profile_confirmation(mod):
    module,table=mod
    table.get_item.side_effect=ClientError({'Error':{'Code':'AccessDeniedException','Message':'denied'}},'GetItem')
    assert module.copy_for(True)==module.DEFAULTS['returningCustomer']


def test_transport_failure_uses_default_confirmation(mod):
    module,table=mod
    table.get_item.side_effect=EndpointConnectionError(endpoint_url='https://dynamodb.us-east-1.amazonaws.com')
    assert module.copy_for(False)==module.DEFAULTS['newCustomer']
