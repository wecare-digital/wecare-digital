"""Workspace-editable Subscribe copy; editing messages never grants consent."""
import json
import logging
import os
from botocore.exceptions import BotoCoreError, ClientError
from lambda_utils.ecommerce import contact_address
from lambda_utils.canonical_flows import published_flow
from flows import common

CONFIG_KEY = 'subscribe_messages_config'
_SUBSCRIBE_FLOW = published_flow('subscribe') or {}
FLOW_ID = str(_SUBSCRIBE_FLOW.get('flowId') or '')
FLOW_NAME = str(_SUBSCRIBE_FLOW.get('metaName') or '')
DEFAULTS = {
    'newCustomer': {
        'body': 'Welcome to WECARE.DIGITAL. Add your name, username and address to complete your customer profile.',
        'flowCta': 'Subscribe',
        'confirmation': 'Your details have been saved.',
    },
    'returningCustomer': {
        'body': 'Welcome back to WECARE.DIGITAL. Review your saved details and update your username or address whenever needed.',
        'flowCta': 'Update details',
        'confirmation': 'Your details have been updated.',
    },
}


def is_returning(row):
    return bool(contact_address.from_contact(row))


def copy_for(returning):
    scenario = 'returningCustomer' if returning else 'newCustomer'
    selected = dict(DEFAULTS[scenario])
    try:
        table = common.dynamodb.Table(os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable'))
        item = table.get_item(Key={'id': CONFIG_KEY}, ConsistentRead=True).get('Item') or {}
        config = item.get('configValue') or {}
        if isinstance(config, str):
            config = json.loads(config)
        values = config.get(scenario, {}) if isinstance(config, dict) else {}
        if isinstance(values, dict):
            for key, limit in (('body', 1024), ('flowCta', 20), ('confirmation', 1024)):
                value = values.get(key)
                if isinstance(value, str) and 0 < len(value.strip()) <= limit:
                    selected[key] = value.strip()
    except (BotoCoreError, ClientError, ValueError, TypeError):
        logging.getLogger(__name__).warning('Subscribe message settings unavailable; using default copy')
    return selected
