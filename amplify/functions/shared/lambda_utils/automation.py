"""
Automation evaluator — shared helper so any inbound handler can apply automation rules.

Reads AutomationRulesTable (managed by the automation-rules Lambda) and returns the
auto-reply text for the first matching enabled rule, or None. Pure + guarded: any
failure returns None so it can never break inbound message processing.

Usage (in an inbound handler, after the message is stored):
    from lambda_utils.automation import evaluate_rules
    reply = evaluate_rules(text=content, channel='whatsapp')
    if reply:
        ...send reply via the channel's send path...
"""
import os
import time
import logging
from typing import Optional

import boto3

logger = logging.getLogger(__name__)
_dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
RULES_TABLE = os.environ.get('AUTOMATION_RULES_TABLE', 'stack-wecare-digital-AutomationRulesTable')

# Tiny in-process cache (warm-start) to avoid scanning on every message.
_cache = {'rules': None, 'at': 0}
_CACHE_TTL = 30  # seconds


def _usable_rules(items):
    """Rules in priority order. A rule whose priority is not a number is skipped, not fatal."""
    ranked = []
    for rule in items:
        try:
            ranked.append((int(rule.get('priority', 100)), rule))
        except (AttributeError, TypeError, ValueError, OverflowError):
            logger.warning('automation rule skipped: invalid priority (id=%s)'
                           % str((rule.get('id') if isinstance(rule, dict) else '') or '')[:64])
    return [rule for _, rule in sorted(ranked, key=lambda pair: pair[0])]


def _load_rules():
    now = time.time()
    if _cache['rules'] is not None and ( now - _cache['at'] ) < _CACHE_TTL:
        return _cache['rules']
    try:
        resp = _dynamodb.Table(RULES_TABLE).scan()
        rules = _usable_rules(resp.get('Items', []))
    except Exception as e:  # noqa: BLE001
        logger.warning('automation rules load failed: %s' % e)
        rules = []
    _cache['rules'] = rules
    _cache['at'] = now
    return rules


def evaluate_rules(text: str, channel: str) -> Optional[str]:
    """Return the auto-reply text for the first matching enabled rule, else None.
    Only actionType 'reply' is supported; it returns the literal text."""
    try:
        ch = (channel or '').lower()
        body = (text or '').lower().strip()
        for r in _load_rules():
            if not r.get('enabled', True):
                continue
            rule_ch = str(r.get('channel', 'any')).lower()
            if rule_ch != 'any' and rule_ch != ch:
                continue
            trig = str(r.get('triggerType', 'keyword'))
            val = str(r.get('triggerValue', '')).lower().strip()
            matched = ( trig == 'any' ) or ( trig == 'keyword' and val and val in body )
            if not matched:
                continue
            if str(r.get('actionType', 'reply')) == 'reply':
                action = r.get('actionValue', '')
                if action:
                    return str(action)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning('automation evaluate failed: %s' % e)
        return None
