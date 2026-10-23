"""The canonical WABA 1 Flow map — the ONE Python source of truth for which Meta Flow id
backs each customer-service capability. Python twin of src/lib/canonicalFlows.ts.

WHY THIS MODULE EXISTS. Flow ids used to be hand-copied as literals across the inbound
handler's DEFAULT_FLOW_TRIGGERS and four workspace tables, and they drifted — the same
capability named different ids, several of them unused DRAFT design-duplicates or DEPRECATED
flows, while the real retained flow sat elsewhere. Centralising the ids here (and in the TS
twin) makes a one-sided edit a test failure rather than a silent production mismatch.

SOURCE OF TRUTH. outputs/flow-retirement-2026-10-09.json is a full paginated live-Meta
readback taken after the 9-Oct deprecation run; its keepIds list is the retained plan. Every
id below is one of those keepIds, or None where the capability has no Flow.
tests/test_canonical_flow_ids.py asserts this module against that readback and against the TS
twin, and forbids flow-id literals outside the canonical modules.

WABA 1 only (2094615664435155). WABA 2 has no retained customer-service Flow set and is not
routed from here.
"""

# capability -> (flow_id or None, status, meta_name or None)
CANONICAL_FLOWS = {
    'orders':         ('2167802357142172', 'DRAFT',     'WD_Orders_Design_v1'),
    'submit_request': ('1107164111921876', 'PUBLISHED', 'WD_Submit_Request_Paid_v1'),
    'amend_request':  ('3678132465672138', 'DRAFT',     '03.WD_Amend_Request'),
    'drop_docs':      ('1211063631104445', 'DRAFT',     'WD_Drop_Documents'),
    'shipments':      ('849713848195607',  'DRAFT',     'WD_Shipments_Design_v1'),
    'leave_review':   ('940049388908144',  'PUBLISHED', '01. WECARE REVIEW FLOW'),
    # Vault: website CTA + ₹49 catalog delivery, no Flow.
    'vault':          (None, 'NONE', None),
    # F001 replacement. Published in Meta; runtime activation remains controlled from
    # FlowRegistry/SystemConfig so publication does not by itself enable customer sends.
    'subscribe':      ('2413873616105042', 'PUBLISHED', 'WD-F001-SUBSCRIBE-PROFILE'),
    # Track Request: not in keepIds. Former ids 1486454129852338 (DRAFT) / 973888792200167
    # (DEPRECATED) are not canonical. Tracking is served by
    # GET /wa-business/service/track/{orderId} + the /orders/ page, not a Flow.
    'track_request':  (None, 'NONE', None),
}


def canonical_flow_id(capability: str):
    """The retained flow id for a capability, or None when it has no Flow."""
    row = CANONICAL_FLOWS.get(capability)
    return row[0] if row else None


def canonical_flow_status(capability: str) -> str:
    """The Meta lifecycle status for a capability's canonical flow."""
    row = CANONICAL_FLOWS.get(capability)
    return row[1] if row else 'NONE'


def published_flow(capability: str):
    """Published canonical Flow metadata, or None when the capability is not live.

    DRAFT/NONE entries remain in the canonical registry for staff/reconciliation, but
    customer-facing callers can use this helper without accidentally sending a draft Flow.
    """
    row = CANONICAL_FLOWS.get(capability)
    if not row or not row[0] or row[1] != 'PUBLISHED':
        return None
    return {
        'capability': capability,
        'flowId': row[0],
        'status': row[1],
        'metaName': row[2],
    }


def published_flow_by_id(flow_id: str):
    """Resolve a published Meta Flow id back to its canonical capability."""
    target = str(flow_id or '').strip()
    if not target:
        return None
    for capability, row in CANONICAL_FLOWS.items():
        if row[0] == target and row[1] == 'PUBLISHED':
            return published_flow(capability)
    return None


_TOKEN_PREFIX_OVERRIDES = {
    'submit_request': 'sr',
}


def published_flow_by_name(meta_name: str):
    """Resolve a published Meta Flow name back to canonical metadata."""
    target = str(meta_name or '').strip().casefold()
    if not target:
        return None
    for capability, row in CANONICAL_FLOWS.items():
        if row[1] == 'PUBLISHED' and str(row[2] or '').strip().casefold() == target:
            return published_flow(capability)
    return None


def published_flow_token_prefix(capability: str) -> str:
    """Routing prefix for phone-backed Flow tokens."""
    return _TOKEN_PREFIX_OVERRIDES.get(capability, capability)
