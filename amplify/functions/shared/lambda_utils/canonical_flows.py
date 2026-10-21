"""The canonical WABA 1 Flow map — the ONE Python source of truth for which Meta Flow id
backs each customer-service capability. Python twin of src/lib/canonicalFlows.ts.

WHY THIS MODULE EXISTS. Flow ids used to be hand-copied as literals across the inbound
handler's DEFAULT_FLOW_TRIGGERS and four workspace tables, and they drifted — the same
capability named different ids, several of them unused DRAFT design-duplicates or DEPRECATED
flows, while the real retained flow sat elsewhere. Centralising the ids here (and in the TS
twin) makes a one-sided edit a test failure rather than a silent production mismatch.

SOURCE OF TRUTH. This table is the current WABA 1 registry. The
outputs/flow-retirement-2026-10-09.json readback is a historical retirement baseline, not a
ceiling: later owner-verified publications may legitimately introduce ids that were not present
on 9-Oct. tests/test_canonical_flow_ids.py asserts the Python/TypeScript twins agree, checks that
new ids are published rather than silently introduced as drafts, and forbids stale ids from
resurfacing.

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
    # Owner-verified published on 2026-10-20.
    'leave_review':   ('940049388908144',  'PUBLISHED', '01. WECARE REVIEW FLOW'),
    # Vault: website CTA + ₹49 catalog delivery, no Flow.
    'vault':          (None, 'NONE', None),
    # Owner-verified published on 2026-10-21. The historical 02.WD_Profile ids
    # 1262971692700761 / 951987930811295 remain deprecated and must not be resurrected.
    'subscribe':      ('1386523953464380', 'PUBLISHED', 'WD_Subscribe_Design_v1'),
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


_TOKEN_PREFIX_OVERRIDES = {
    'submit_request': 'sr',
}


def canonical_flow_name(capability: str):
    """The current Meta Flow name for a capability, or None."""
    row = CANONICAL_FLOWS.get(capability)
    return row[2] if row else None


def canonical_flow_token_prefix(capability: str) -> str:
    """Prefix embedded in {prefix}-{uuid}-waba-{n}-ph-{phone} Flow tokens."""
    return _TOKEN_PREFIX_OVERRIDES.get(capability, capability)


def canonical_flow_record(capability: str):
    """Customer-safe registry record for a capability, or None when unknown."""
    row = CANONICAL_FLOWS.get(capability)
    if not row:
        return None
    return {
        'capability': capability,
        'flowId': row[0],
        'status': row[1],
        'metaName': row[2],
        'tokenPrefix': canonical_flow_token_prefix(capability),
    }


def published_flow(capability: str):
    """Return the canonical record only when it is currently published and sendable."""
    record = canonical_flow_record(capability)
    if not record or record['status'] != 'PUBLISHED' or not record['flowId']:
        return None
    return record


def capability_for_flow(flow_id: str = '', meta_name: str = ''):
    """Resolve a canonical capability from a Meta id or name."""
    fid = str(flow_id or '').strip()
    name = str(meta_name or '').strip().casefold()
    for capability, row in CANONICAL_FLOWS.items():
        if fid and str(row[0] or '') == fid:
            return capability
        if name and str(row[2] or '').strip().casefold() == name:
            return capability
    return None
