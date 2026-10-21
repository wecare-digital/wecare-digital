"""The canonical WABA 1 Flow map — the ONE Python source of truth for which Meta Flow id
backs each customer-service capability. Python twin of src/lib/canonicalFlows.ts.

WHY THIS MODULE EXISTS. Flow ids used to be hand-copied as literals across the inbound
handler's DEFAULT_FLOW_TRIGGERS and four workspace tables, and they drifted — the same
capability named different ids, several of them unused DRAFT design-duplicates or DEPRECATED
flows, while the real retained flow sat elsewhere. Centralising the ids here (and in the TS
twin) makes a one-sided edit a test failure rather than a silent production mismatch.

SOURCE OF TRUTH. outputs/flow-retirement-2026-10-09.json remains the historical retirement
baseline. Published owner-approved replacements after that snapshot are recorded here with the
date/reason in comments and are exempted explicitly in tests. This module and its TypeScript twin
remain the runtime source of truth, so a newly published Flow is added once here rather than copied
through senders and UI tables.

WABA 1 only (2094615664435155) for the canonical customer-service Flow set.
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
    # Owner-confirmed PUBLISHED 2026-10-21. This supersedes the retired 02.WD_Profile ids
    # 1262971692700761 / 951987930811295 without resurrecting either of them.
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



def published_flow(capability: str):
    """Published canonical Flow metadata, or None when the capability is not publishable yet.

    This is the safe runtime lookup for customer-facing senders: DRAFT/NONE entries stay visible
    in the canonical registry for staff and reconciliation, but cannot accidentally be treated as
    a live customer Flow.
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
