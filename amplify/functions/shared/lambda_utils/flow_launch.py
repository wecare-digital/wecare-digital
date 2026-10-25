"""One entry-policy contract for WhatsApp Flows: how a Flow may be launched, and by whom.

PURPOSE. A Flow's launch policy used to be stated in three places that did not agree. The
FlowRegistry upsert validated only the fields in a request body, so a partial update could
silently un-publish a row or strip its entry configuration. The keyword dispatcher read entry
mode from SystemConfig instead of the registry. The staff send API checked neither. This
module is the single validator every side uses.

AUTHORITY.
* `registry_errors(record)` runs on the MERGED registry row (existing row + patch) before
  any FlowRegistry write. It rejects the contradictory combinations of the entry-mode
  contract and any disagreement with a canonical capability contract
  (`canonical_flows.CANONICAL_CONTRACTS`).
* `keyword_launch_decision` and `manual_launch_decision` run in each launch door wired to
  them (today: F001 Subscribe). Every control must agree - the canonical code record, the
  FlowRegistry row, Meta's last-synced status and, for a keyword door, the runtime switch -
  so publishing a Flow in Meta never activates it by itself.
* Default deny: a missing or contradictory registry row or an unknown role refuses. Callers
  treat a registry read error as a refusal too.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

from lambda_utils import canonical_flows

ENTRY_MODES = ('keyword_interactive', 'payment_template', 'internal_event', 'manual', 'none')
REGISTRY_STATUSES = ('DRAFT', 'PUBLISHED', 'DEPRECATED')
SENDABLE_META_STATUSES = frozenset({'PUBLISHED', 'THROTTLED'})
#: Staff roles ranked as lambda_utils.middleware.ROLE_HIERARCHY ranks them.
_ROLE_RANK = {'Viewer': 1, 'Operator': 2, 'Admin': 3}
MANUAL_SEND_MIN_ROLE = 'Operator'

#: Staff-readable explanation for every refusal reason a decision can return.
REASONS = {
    'allowed': 'All launch controls agree.',
    'not_a_keyword_flow': 'This Flow is not a keyword Flow, so typed keywords cannot open it.',
    'not_a_manual_door': 'Paid and event-launched Flows have no staff send shortcut.',
    'no_contract': 'This Flow has no canonical launch contract.',
    'runtime_disabled': 'Keyword launch is switched off in Workspace.',
    'runtime_entry_mode': 'The keyword trigger is not configured as a native keyword Flow.',
    'canonical_not_published': 'The canonical Flow record is not PUBLISHED.',
    'registry_missing': 'FlowRegistry has no row for this Flow. Register it in Workspace.',
    'registry_flow_mismatch': 'The FlowRegistry row names a different Flow ID.',
    'registry_not_published': 'The FlowRegistry status is not PUBLISHED.',
    'meta_not_published': "Meta's last-synced status for this Flow is not PUBLISHED.",
    'registry_contradiction': 'The FlowRegistry row contradicts the Flow launch contract.',
    'registry_entry_mode': 'The FlowRegistry entry mode is not keyword_interactive.',
    'registry_unreadable': 'FlowRegistry could not be read, so launch is refused.',
    'role_insufficient': 'Sending this Flow requires the Operator or Admin role.',
    'contract_flow_elsewhere': 'This Flow can only be opened through its own launch door.',
    'registry_payment_gated': 'FlowRegistry marks this Flow as paid; paid Flows never open from a keyword.',
    'registry_not_keyword': 'FlowRegistry launches this Flow from a template, an event or staff only.',
}


@dataclass(frozen=True)
class LaunchDecision:
    allowed: bool
    reason: str


def explain(reason: str) -> str:
    """Human explanation for a decision reason; never empty."""
    return REASONS.get(reason, 'This Flow cannot be launched.')


def registry_table_name() -> str:
    """FlowRegistryTable, named the way the business API already names it."""
    return os.environ.get('FLOW_REGISTRY_TABLE', 'stack-wecare-digital-FlowRegistryTable')


def parse_bool(value: Any) -> bool:
    """Strict boolean. `bool("false")` is True, which is how a string became payment-gated."""
    if isinstance(value, bool):
        return value
    return str(value if value is not None else '').strip().lower() in ('true', '1', 'yes')


def entry_policy_errors(record: Mapping[str, Any]) -> List[str]:
    """The entry-mode contract every registry row obeys."""
    mode = str(record.get('entryMode') or 'none')
    if mode not in ENTRY_MODES:
        return [f'Invalid entryMode: {mode}. Must be one of {ENTRY_MODES}']
    template = str(record.get('entryTemplateName') or '').strip()
    requires_payment = parse_bool(record.get('requiresPayment'))
    errors: List[str] = []
    if mode == 'payment_template':
        if not template:
            errors.append('entryTemplateName is required for payment_template entryMode')
        if not requires_payment:
            errors.append('payment_template flows must set requiresPayment=true')
    if mode == 'keyword_interactive':
        if template:
            errors.append('keyword_interactive flows must not declare an entryTemplateName')
        if requires_payment:
            errors.append('keyword_interactive flows must not be payment-gated; '
                          'use payment_template or internal_event')
    return errors


def contract_errors(record: Mapping[str, Any]) -> List[str]:
    """Disagreements between a registry row and its canonical capability contract."""
    match = canonical_flows.contract_for_flow_id(record.get('flowId'))
    if not match:
        return []
    capability, contract = match
    label = f"{contract['flowNumber']} {contract['label']}"
    errors: List[str] = []
    if str(record.get('entryMode') or 'none') != contract['entryMode']:
        errors.append(f"{label} must use entryMode {contract['entryMode']}")
    if str(record.get('entryTemplateName') or '').strip() != contract['entryTemplateName']:
        errors.append(f'{label} must not declare an entry template'
                      if not contract['entryTemplateName']
                      else f"{label} must use entry template {contract['entryTemplateName']}")
    if parse_bool(record.get('requiresPayment')) != contract['requiresPayment']:
        errors.append(f'{label} must not require payment' if not contract['requiresPayment']
                      else f'{label} must require payment')
    # The code and prefix are how history is filed; a blank one would hide submissions.
    for field in ('flowCode', 'submissionPrefix'):
        if str(record.get(field) or '').strip() != contract[field]:
            errors.append(f'{label} must use {field} {contract[field]}')
    waba_id = str(record.get('wabaId') or '').strip()
    if waba_id and waba_id != contract['wabaId']:
        errors.append(f"{label} exists on WABA {contract['wabaId']} only")
    if (str(record.get('status') or '') == 'PUBLISHED'
            and canonical_flows.canonical_flow_status(capability) != 'PUBLISHED'):
        errors.append(f'{label} cannot be PUBLISHED in FlowRegistry while its canonical Flow '
                      'is not published')
    return errors


def registry_errors(record: Mapping[str, Any]) -> List[str]:
    """Every reason a merged registry row must not be stored. Empty means valid."""
    errors: List[str] = []
    status = str(record.get('status') or 'DRAFT')
    if status not in REGISTRY_STATUSES:
        errors.append(f'Invalid status: {status}. Must be one of {REGISTRY_STATUSES}')
    errors.extend(entry_policy_errors(record))
    errors.extend(contract_errors(record))
    return errors


#: Longest keyword the dispatcher will store or match.
MAX_KEYWORD_CHARS = 60


def normalize_keywords(raw: Any) -> List[str]:
    """Lowercase, whitespace-collapsed, de-duplicated keywords; non-strings are dropped."""
    out: List[str] = []
    for value in raw if isinstance(raw, (list, tuple)) else []:
        if not isinstance(value, str):
            continue
        keyword = ' '.join(value.split()).lower()
        if keyword and len(keyword) <= MAX_KEYWORD_CHARS and keyword not in out:
            out.append(keyword)
    return out


def runtime_trigger(capability: str, stored: Any) -> dict:
    """A capability's keyword trigger as the inbound dispatcher sees it: the stored
    SystemConfig `flow_triggers_config` entry merged over the contract's defaults.

    The Flow id always comes from the canonical record, whatever the stored entry says, so
    a keyword can only ever open the capability's own Flow.
    """
    contract = canonical_flows.canonical_contract(capability) or {}
    entry = dict(stored) if isinstance(stored, Mapping) else {}
    keywords = normalize_keywords(entry['keywords']) if 'keywords' in entry else \
        normalize_keywords(list(contract.get('defaultKeywords') or ()))
    return {
        'enabled': parse_bool(entry.get('enabled', False)),
        'keywords': keywords,
        'entryMode': str(entry.get('entryMode') or contract.get('entryMode') or 'none'),
        'flowId': canonical_flows.canonical_flow_id(capability) or '',
        'configured': bool(entry),
    }


def read_registry_row(table: Any, flow_id: str) -> Optional[dict]:
    """The registry row for a Flow id. Read errors propagate; callers must refuse on them."""
    target = str(flow_id or '').strip()
    if not target:
        return None
    return table.get_item(Key={'flowId': target}, ConsistentRead=True).get('Item') or None


def _publication_reason(capability: str, registry_row: Optional[Mapping[str, Any]]) -> str:
    published = canonical_flows.published_flow(capability)
    if not published:
        return 'canonical_not_published'
    if not registry_row:
        return 'registry_missing'
    if str(registry_row.get('flowId') or '') != published['flowId']:
        return 'registry_flow_mismatch'
    if str(registry_row.get('status') or '') != 'PUBLISHED':
        return 'registry_not_published'
    meta_status = str(registry_row.get('metaStatus') or '').strip().upper()
    # Absent until the first sync from Meta. THROTTLED still delivers (Meta caps the rate);
    # DRAFT, DEPRECATED and BLOCKED cannot be sent to customers.
    if meta_status and meta_status not in SENDABLE_META_STATUSES:
        return 'meta_not_published'
    if registry_errors(registry_row):
        return 'registry_contradiction'
    return ''


def generic_keyword_refusal(trigger_key: str, flow_id: str,
                            registry_row: Optional[Mapping[str, Any]]) -> str:
    """Why a generic (non-contract) keyword trigger must not open `flow_id`; '' when it may.

    SystemConfig triggers are editable in Workspace, so a trigger's own `entryMode` cannot be
    the authority. The FlowRegistry row is: a Flow registered as paid, template-launched,
    event-launched or staff-only never opens from a keyword, and a canonical contract Flow
    opens only through its own door. A missing row or a legacy `none` row keeps the
    trigger's existing behavior.
    """
    match = canonical_flows.contract_for_flow_id(flow_id)
    if match and match[0] != trigger_key:
        return 'contract_flow_elsewhere'
    if not registry_row:
        return ''
    if parse_bool(registry_row.get('requiresPayment')):
        return 'registry_payment_gated'
    if str(registry_row.get('entryMode') or 'none') in ('payment_template', 'internal_event', 'manual'):
        return 'registry_not_keyword'
    return ''


def keyword_launch_decision(*, capability: str, registry_row: Optional[Mapping[str, Any]],
                            trigger: Optional[Mapping[str, Any]]) -> LaunchDecision:
    """Whether a customer's exact keyword may open this Flow right now."""
    contract = canonical_flows.canonical_contract(capability)
    if not contract or contract['entryMode'] != 'keyword_interactive':
        return LaunchDecision(False, 'not_a_keyword_flow')
    if not isinstance(trigger, Mapping) or not parse_bool(trigger.get('enabled')):
        return LaunchDecision(False, 'runtime_disabled')
    if str(trigger.get('entryMode') or 'keyword_interactive') != 'keyword_interactive':
        return LaunchDecision(False, 'runtime_entry_mode')
    reason = _publication_reason(capability, registry_row)
    if reason:
        return LaunchDecision(False, reason)
    if str((registry_row or {}).get('entryMode') or '') != 'keyword_interactive':
        return LaunchDecision(False, 'registry_entry_mode')
    return LaunchDecision(True, 'allowed')


def manual_launch_decision(*, capability: str, registry_row: Optional[Mapping[str, Any]],
                           role: str) -> LaunchDecision:
    """Whether a staff member with `role` may send this Flow to one customer right now.

    The keyword runtime switch is deliberately not consulted: a staff send is the controlled
    QA door that runs before keyword launch is enabled. Publication controls still apply.
    """
    if _ROLE_RANK.get(str(role or ''), 0) < _ROLE_RANK[MANUAL_SEND_MIN_ROLE]:
        return LaunchDecision(False, 'role_insufficient')
    contract = canonical_flows.canonical_contract(capability)
    if not contract:
        return LaunchDecision(False, 'no_contract')
    if contract['requiresPayment'] or contract['entryMode'] in ('payment_template', 'internal_event'):
        return LaunchDecision(False, 'not_a_manual_door')
    reason = _publication_reason(capability, registry_row)
    if reason:
        return LaunchDecision(False, reason)
    return LaunchDecision(True, 'allowed')
