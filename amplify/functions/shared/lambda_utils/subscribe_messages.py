"""Workspace-editable F001 Subscribe copy: opening message, button text and in-Flow confirmation.

PURPOSE. One copy source for every F001 launch door. The inbound keyword door and the
Workspace staff send both open with the New customer or Returning customer message stored in
SystemConfig `subscribe_messages_config`, and the data-exchange save returns the matching
confirmation. Staff edit it in Communications -> Manage -> WhatsApp -> Auto response ->
Subscribe, so what the customer sees is visible there.

AUTHORITY. Copy only. Editing a message never grants consent, never changes a Customer ID and
never enables a launch door. If the settings read fails or holds malformed values, DEFAULTS
are used, so the customer always sees branded, accurate copy.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Mapping, Optional

from botocore.exceptions import BotoCoreError, ClientError

from lambda_utils.ecommerce import contact_address

CONFIG_KEY = 'subscribe_messages_config'
NEW_CUSTOMER = 'newCustomer'
RETURNING_CUSTOMER = 'returningCustomer'
SCENARIOS = (NEW_CUSTOMER, RETURNING_CUSTOMER)
#: Field -> maximum length. Meta caps an interactive body at 1024 characters and a Flow CTA
#: at 20; the confirmation renders in a TextBody, so it shares the body limit.
LIMITS = (('body', 1024), ('flowCta', 20), ('confirmation', 1024))
FOOTER = 'WECARE.DIGITAL'

DEFAULTS: Dict[str, Dict[str, str]] = {
    NEW_CUSTOMER: {
        'body': 'Welcome to WECARE.DIGITAL. Add your full name, optional WhatsApp username, organization and job title, then your address.',
        'flowCta': 'Subscribe',
        'confirmation': 'Your WECARE.DIGITAL profile and address have been saved.',
    },
    RETURNING_CUSTOMER: {
        'body': 'Welcome back to WECARE.DIGITAL. Review the same profile and address fields, then update anything that has changed.',
        'flowCta': 'Update details',
        'confirmation': 'Your WECARE.DIGITAL profile and address have been updated.',
    },
}

_logger = logging.getLogger(__name__)


def system_config_table_name() -> str:
    """SystemConfigTable for this execution environment."""
    return os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')


def is_returning(row: Optional[Mapping[str, Any]]) -> bool:
    """A returning customer already has a structurally valid saved address."""
    return bool(contact_address.from_contact(dict(row) if isinstance(row, Mapping) else None))


def scenario_for(returning: bool) -> str:
    return RETURNING_CUSTOMER if returning else NEW_CUSTOMER


def copy_for(returning: bool, table: Any) -> Dict[str, str]:
    """The copy for one scenario: stored values that pass LIMITS, else DEFAULTS."""
    scenario = scenario_for(returning)
    selected = dict(DEFAULTS[scenario])
    try:
        item = table.get_item(Key={'id': CONFIG_KEY}, ConsistentRead=True).get('Item') or {}
        config = item.get('configValue') or {}
        if isinstance(config, str):
            config = json.loads(config)
        values = config.get(scenario, {}) if isinstance(config, dict) else {}
        if isinstance(values, dict):
            for key, limit in LIMITS:
                value = values.get(key)
                if isinstance(value, str) and 0 < len(value.strip()) <= limit:
                    selected[key] = value.strip()
    except (BotoCoreError, ClientError, ValueError, TypeError, AttributeError) as exc:
        _logger.warning(json.dumps({'event': 'subscribe_copy_unavailable',
                                    'errorType': type(exc).__name__}))
    return selected
