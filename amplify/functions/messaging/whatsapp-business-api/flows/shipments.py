"""F006 Track Shipping Flow data-exchange endpoint.

Only the INIT request is dynamic.  The published Flow keeps its cloned
SELECT_TARGET -> NOTE -> CONFIRMATION navigation client-side; INIT supplies choices that
belong to the server-issued session's customer.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from flows.common import dynamodb
from flows.orders import fetch_orders_for_flow, get_order
from lambda_utils import contact_store, customer_auth, flow_sessions, shared_tables
from lambda_utils.ecommerce import service_request_store

logger = logging.getLogger(__name__)

CAPABILITY = 'shipments'
REJECTED = 'This Track Shipping form session is no longer valid. Open Track Shipping again.'


def _verify(flow_token: str):
    return flow_sessions.verify_session(
        dynamodb.Table(shared_tables.flow_drafts_table_name()),
        capability=CAPABILITY,
        token=flow_token,
        rejected_message=REJECTED,
    )


def _contact(phone: str) -> Dict[str, Any]:
    try:
        return contact_store.lookup(
            dynamodb.Table(shared_tables.contacts_table_name()), phone
        ) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning('Track Shipping contact lookup failed: %s', type(exc).__name__)
        return {}


def _customer_identity(contact: Dict[str, Any], phone: str) -> Optional[customer_auth.CustomerIdentity]:
    """Return a pre-existing verified commerce identity; never mint one for a Flow."""
    owner = str(contact.get('checkoutCustomerId') or '').strip()
    if not customer_auth.is_cognito_subject(owner):
        return None
    canonical = contact_store.canonical_phone(phone)
    if not canonical:
        return None
    return customer_auth.CustomerIdentity(
        customer_id=owner,
        subject=owner,
        phone=canonical,
        phone_verified=True,
    )


def _order_targets(phone: str) -> List[Dict[str, str]]:
    targets: List[Dict[str, str]] = []
    try:
        for order in fetch_orders_for_flow(phone, '')[:20]:
            order_id = str(order.get('id') or '').strip()
            title = str(order.get('title') or order_id).strip()
            if not order_id:
                continue
            detail = get_order(order_id) or {}
            purpose = str(detail.get('itemsSummary') or '').strip()
            label = f'Order · {title}'
            if purpose:
                label += f' · {purpose[:28]}'
            targets.append({'id': 'order:' + order_id, 'title': label[:72]})
    except Exception as exc:  # noqa: BLE001
        logger.warning('Track Shipping order lookup failed: %s', type(exc).__name__)
    return targets


def _request_targets(identity: Optional[customer_auth.CustomerIdentity]) -> List[Dict[str, str]]:
    if identity is None:
        return []
    try:
        rows, _cursor = service_request_store.list_for_customer(
            dynamodb.Table(service_request_store.DEFAULT_TABLE_NAME), identity, limit=20
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Track Shipping request lookup failed: %s', type(exc).__name__)
        return []

    out: List[Dict[str, str]] = []
    for row in rows:
        public_id = str(row.get('requestId') or '').strip()
        if not public_id:
            continue
        kind = str(row.get('kind') or 'request').replace('_', ' ').title()
        out.append({
            'id': 'request:' + public_id,
            'title': (f'Request · {public_id} · {kind}')[:72],
        })
    return out


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT -> SELECT_TARGET using only targets owned by the session customer."""
    try:
        session = _verify(flow_token)
    except flow_sessions.FlowSessionRejected as exc:
        return {
            'screen': 'SELECT_TARGET',
            'data': {
                'error': str(exc),
                'targets': [{'id': 'unavailable', 'title': REJECTED[:72]}],
            },
        }
    except flow_sessions.FlowSessionUnavailable:
        return {
            'screen': 'SELECT_TARGET',
            'data': {
                'error': 'Please try again.',
                'targets': [{'id': 'unavailable', 'title': 'Please try again'}],
            },
        }

    if session.consumed_at:
        return {
            'screen': 'SELECT_TARGET',
            'data': {
                'error': REJECTED,
                'targets': [{'id': 'unavailable', 'title': REJECTED[:72]}],
            },
        }

    contact = _contact(session.phone)
    identity = _customer_identity(contact, session.phone)
    targets = _order_targets(session.phone) + _request_targets(identity)
    if not targets:
        targets = [{'id': 'unavailable', 'title': 'No matching orders or requests found'}]

    return {'screen': 'SELECT_TARGET', 'data': {'targets': targets}}
